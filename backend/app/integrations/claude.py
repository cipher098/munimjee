"""Anthropic Claude API client — business logic decisions + fallback reply generation."""
import json
import logging

import anthropic

from app.bot import agent_spec
from app.bot import prompt_store
from app.config import settings
# Direct imports kept as in-process fallbacks; prompt_store also reaches into
# these modules when the DB lookup misses.
from app.prompts import (  # noqa: F401  (re-exported for training.py and tests)
    CATALOG_MATCH_PROMPT,
    DECISION_PROMPT,
    IMAGE_DESCRIBE_PROMPT,
    REPLY_PROMPT,
)
from app.subagent_prompts import (  # noqa: F401
    EXTRACT_FEATURE_QUERY_PROMPT,
    EXTRACT_PERSONA_PROMPT,
    GENERATE_PRODUCT_DESCRIPTION_PROMPT,
    SUGGEST_CATEGORY_PROMPT,
    SUGGEST_TAGS_FOR_CATEGORY_PROMPT,
)

logger = logging.getLogger(__name__)

# Backward-compat aliases — model selection now lives in agents.yaml.
# `MODEL` is still re-exported because training.py and tests import it.
MODEL = agent_spec.get("decide").model
FALLBACK_MODEL = agent_spec.get("decide").fallback_model or "claude-3-5-sonnet-20241022"


def _to_anthropic_role(raw_role: str) -> str | None:
    """Map sellerbot conversation roles to Anthropic API roles.

    `seller_manual` is a message the seller typed themselves from the IG inbox
    during a takeover — functionally a brand-side outbound, same as `bot`.
    Mapping it to `assistant` keeps prompt history coherent when the bot resumes.
    """
    if raw_role == "customer":
        return "user"
    if raw_role in ("bot", "seller_manual"):
        return "assistant"
    return None


def _build_decision_messages(
    history: list[dict],
    current_user_text: str,
    context_block: str,
) -> list[dict]:
    """Build an Anthropic messages array with cache_control on the last
    historical message so prior turns become a stable cached prefix.

    `history` is conversation.messages EXCLUDING the current turn.
    `current_user_text` is the latest customer message (will go in final user msg).
    `context_block` is the dynamic CONTEXT string (state/round/prices) — appended
    to the final user message so it doesn't pollute the cached prefix.

    Guarantees:
      - Coalesces consecutive same-role messages (Anthropic requires alternation).
      - Drops leading assistant messages (first must be user).
      - If the last historical message is user (no bot reply yet), folds it into
        the current user message instead of placing a cache breakpoint there.
      - Adds cache_control: ephemeral on the final historical message only when
        that message is an assistant turn (stable boundary).
    """
    coalesced: list[dict] = []
    last_role: str | None = None
    for entry in history:
        role = _to_anthropic_role(entry.get("role", ""))
        if role is None:
            continue
        content = (entry.get("content") or "").strip()
        if not content:
            continue
        if role == last_role and coalesced:
            coalesced[-1]["content"] += "\n" + content
        else:
            coalesced.append({"role": role, "content": content})
            last_role = role

    # First message must be user.
    while coalesced and coalesced[0]["role"] != "user":
        coalesced.pop(0)

    # If trailing historical message is user (bot didn't reply yet), fold it
    # into the new user turn so we don't end up with two consecutive user msgs.
    trailing_user_text = ""
    if coalesced and coalesced[-1]["role"] == "user":
        trailing_user_text = coalesced.pop()["content"] + "\n\n"

    # Place cache breakpoint on the last historical (assistant) message.
    if coalesced:
        last_msg = coalesced[-1]
        last_msg["content"] = [
            {
                "type": "text",
                "text": last_msg["content"],
                "cache_control": {"type": "ephemeral"},
            }
        ]

    final_user_text = f"{trailing_user_text}{current_user_text}\n\n{context_block}"
    coalesced.append({"role": "user", "content": final_user_text})
    return coalesced


from app.integrations._json_utils import (  # noqa: F401  (re-export for test compatibility)
    LLMOutputParseError,
    parse_json_relaxed as _parse_json,
)
from app.integrations import llm_logging
from app.integrations import llm_provider as _llm_provider
# Prompt construction is shared with the Sarvam provider so the two never drift.
from app.bot.prompt_builders import (
    build_decide_prompt,
    build_reply_prompt,
    evaluate_interventions,
    split_decide_prompt as _split_decision_prompt,
    split_reply_prompt as _split_reply_prompt,
)


def _response_text(resp) -> str:
    """Concatenate the text blocks of an Anthropic response for the cost log."""
    try:
        parts = [getattr(b, "text", "") for b in (resp.content or [])]
        return "".join(p for p in parts if p)
    except Exception:  # pragma: no cover - defensive
        return ""


class ClaudeClient:
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def _create(self, *, fallback_model: str | None = None, log_method: str | None = None, **kwargs):
        """messages.create with one retry on transient API errors and a
        model fallback when the primary model emits a content-policy refusal.
        `fallback_model` lets callers override the global FALLBACK_MODEL on a
        per-method basis (driven by agents.yaml). `log_method` names the
        logical call (decide / generate_reply / subagent) for the cost
        ledger. Logs cache hits and records the call via llm_logging."""
        model_name = kwargs.get("model", MODEL)
        try:
            try:
                resp = await self._client.messages.create(**kwargs)
            except (anthropic.APIConnectionError, anthropic.APITimeoutError, anthropic.RateLimitError) as exc:
                logger.warning("Anthropic transient error (%s) on model %s — retrying once", type(exc).__name__, model_name)
                resp = await self._client.messages.create(**kwargs)

            if getattr(resp, "stop_reason", None) == "refusal":
                target = fallback_model or FALLBACK_MODEL
                logger.warning("Model %s refused — retrying with fallback %s", model_name, target)
                kwargs["model"] = target
                resp = await self._client.messages.create(**kwargs)
        except Exception as exc:
            llm_logging.record(
                "anthropic", kwargs.get("model", model_name), log_method,
                status="error", request=kwargs, error=f"{type(exc).__name__}: {exc}",
            )
            raise

        used_model = kwargs.get("model", model_name)
        usage = getattr(resp, "usage", None)
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0 if usage else 0
        cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0 if usage else 0
        if usage is not None and (cache_read or cache_create):
            logger.info(
                "Claude cache: read=%d write=%d input=%d output=%d model=%s",
                cache_read, cache_create,
                getattr(usage, "input_tokens", 0) or 0,
                getattr(usage, "output_tokens", 0) or 0,
                used_model,
            )
        llm_logging.record(
            "anthropic", used_model, log_method,
            input_tokens=(getattr(usage, "input_tokens", None) if usage else None),
            output_tokens=(getattr(usage, "output_tokens", None) if usage else None),
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_create,
            request=kwargs,
            response=_response_text(resp),
        )
        return resp

    async def decide(self, context: dict, *, model: str | None = None, max_tokens: int | None = None) -> dict:
        # Shared builder — same prompt Sarvam uses. customer_message/history are
        # sent below as native Anthropic messages for prefix caching.
        prompt = await build_decide_prompt(context)
        system_text, context_block = _split_decision_prompt(prompt)

        # Fired intervention reminders go INTO the user-side context so they stay
        # dynamic (don't pollute the cached system prompt). Shared with Sarvam.
        reminder_block = evaluate_interventions(context)
        if reminder_block and context_block:
            context_block = f"{reminder_block}\n\n{context_block}"

        history = context.get("message_history") or []
        current_user_text = context.get("customer_message", "")
        if history and history[-1].get("role") == "customer":
            # Standard flow: latest history entry IS the current customer turn.
            history_for_cache = history[:-1]
        else:
            # No history or last entry is bot reply — use entire history as cached prefix.
            history_for_cache = history

        spec = agent_spec.get("decide")
        effective_model = model or spec.model
        effective_max_tokens = max_tokens or spec.max_tokens
        if context_block:
            messages = _build_decision_messages(history_for_cache, current_user_text, context_block)
            request_kwargs = dict(
                model=effective_model,
                max_tokens=effective_max_tokens,
                system=[
                    {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
                ],
                messages=messages,
            )
        else:
            # Marker missing (training dashboard rewrote prompt structure) — degraded path.
            logger.warning("DECISION_PROMPT missing CONTEXT/STRATEGY markers — skipping cache")
            request_kwargs = dict(
                model=effective_model,
                max_tokens=effective_max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

        # NB: errors propagate to the LLM-provider factory so it can fall back
        # to the configured fallback_provider/fallback_model. The old
        # "return clarify on error" path swallowed failures and prevented
        # the factory from ever firing the fallback.
        response = await self._create(fallback_model=spec.fallback_model, log_method="decide", **request_kwargs)
        text = response.content[0].text.strip()
        return _parse_json(text)  # raises LLMOutputParseError on bad JSON

    async def generate_reply(self, context: dict, *, model: str | None = None, max_tokens: int | None = None) -> str:
        history = context.get("message_history") or []

        # Shared builder — identical prompt + context to the Sarvam provider.
        prompt = await build_reply_prompt(context)
        system_text, context_block = _split_reply_prompt(prompt)

        spec = agent_spec.get("generate_reply")
        effective_model = model or spec.model
        effective_max_tokens = max_tokens or spec.max_tokens
        if context_block:
            current_user_text = context.get("customer_message", "")
            if history and history[-1].get("role") == "customer":
                history_for_cache = history[:-1]
            else:
                history_for_cache = history
            messages = _build_decision_messages(history_for_cache, current_user_text, context_block)
            request_kwargs = dict(
                model=effective_model,
                max_tokens=effective_max_tokens,
                system=[
                    {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
                ],
                messages=messages,
            )
        else:
            logger.warning("REPLY_PROMPT missing DYNAMIC CONTEXT marker — skipping cache")
            request_kwargs = dict(
                model=effective_model,
                max_tokens=effective_max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

        # Propagate errors to the LLM-provider factory for fallback. Old
        # `return ""` swallow path is gone — factory routes to fallback
        # provider/model on exception, which is more useful than a silent ""
        # reply that prints "BOT REPLY :" with nothing.
        response = await self._create(fallback_model=spec.fallback_model, log_method="generate_reply", **request_kwargs)
        return response.content[0].text.strip()

    async def generate_product_description(self, image_url: str, product_name: str) -> str:
        """Generate a seller-facing product description from an image for catalog use.
        Routed to the agents.yaml-configured provider (vision) with fallback."""
        template = await prompt_store.get("generate_product_description")
        return await _llm_provider.complete_vision(
            "generate_product_description",
            prompt=template.format(product_name=product_name),
            image={"kind": "url", "url": image_url},
        )

    async def describe_product_image(self, image_b64: str, media_type: str = "image/jpeg") -> str:
        """Stage 1 — Vision only: describe what product is in the customer's image.
        Accepts base64-encoded image bytes (Instagram blocks direct URL fetching).
        Routed to the configured provider (vision) with fallback."""
        template = await prompt_store.get("image_describe")
        return await _llm_provider.complete_vision(
            "describe_product_image",
            prompt=template,
            image={"kind": "base64", "media_type": media_type, "data": image_b64},
        )

    async def match_product_by_description(
        self, description: str, products: list[dict]
    ) -> dict:
        """Stage 2 — Text only: match description against catalog, return best product."""
        catalog = [
            {
                "id": p["id"],
                "name": p["name"],
                "description": p.get("description") or "",
                "listed_price_rupees": p["listed_price_paise"] // 100,
            }
            for p in products
        ]

        template = await prompt_store.get("catalog_match")
        prompt = template.format(
            description=description,
            catalog_json=json.dumps(catalog, ensure_ascii=False),
        )

        text = await _llm_provider.complete_text("match_product_by_description", user=prompt)
        try:
            return _parse_json(text)
        except LLMOutputParseError:
            logger.error("LLM returned non-JSON catalog match: %r", text)
            return {"product_id": None, "confidence": "low", "reason": "parse error"}

    async def suggest_category(self, product_name: str, product_description: str = "") -> dict:
        """Suggest a category name and relevant tag definitions for a product.
        Returns: {category_name, tags: [{name, display_name, value_type, allowed_values}]}
        """
        description_line = f"Description: {product_description}\n" if product_description else ""
        template = await prompt_store.get("suggest_category")
        prompt = template.format(
            product_name=product_name,
            description_line=description_line,
        )
        text = await _llm_provider.complete_text("suggest_category", user=prompt)
        try:
            return _parse_json(text)
        except LLMOutputParseError:
            logger.error("LLM returned non-JSON category suggestion: %r", text)
            return {"category_name": None, "tags": []}

    async def suggest_tags_for_category(self, category_name: str) -> list[dict]:
        """Suggest tag definitions for a given product category.
        Returns: [{name, display_name, value_type, allowed_values, suggested_value}]
        suggested_value is a typical default value the seller can confirm or change.
        """
        template = await prompt_store.get("suggest_tags_for_category")
        prompt = template.format(category_name=category_name)
        text = await _llm_provider.complete_text("suggest_tags_for_category", user=prompt)
        try:
            result = _parse_json(text)
            return result if isinstance(result, list) else []
        except LLMOutputParseError:
            logger.error("LLM returned non-JSON tag suggestions: %r", text)
            return []

    async def extract_feature_query(
        self, customer_message: str, tags: list[dict]
    ) -> dict:
        """Determine if customer is asking about a product feature and which tag it maps to.
        tags: [{name, display_name, value_type, allowed_values}]
        Returns: {
            is_feature_question: bool,
            matched_tag_name: str | null,
            new_tag_name: str | null,
            new_tag_display_name: str | null,
            new_tag_value_type: "enum" | "text" | "number" | null,
            new_tag_allowed_values: list[str] | null,
        }
        """
        tags_json = json.dumps(tags, ensure_ascii=False)
        template = await prompt_store.get("extract_feature_query")
        prompt = template.format(
            customer_message=customer_message,
            tags_json=tags_json,
        )
        text = await _llm_provider.complete_text("extract_feature_query", user=prompt)
        try:
            return _parse_json(text)
        except LLMOutputParseError:
            logger.error("LLM returned non-JSON feature query: %r", text)
            return {"is_feature_question": False, "matched_tag_name": None,
                    "new_tag_name": None, "new_tag_display_name": None,
                    "new_tag_value_type": None, "new_tag_allowed_values": None}

    async def extract_persona(self, conversation_history: str) -> dict:
        template = await prompt_store.get("extract_persona")
        prompt = template.format(conversation_history=conversation_history)
        text = await _llm_provider.complete_text("extract_persona", user=prompt)
        try:
            return _parse_json(text)
        except LLMOutputParseError:
            logger.error("LLM returned non-JSON persona: %r", text)
            return {}


# ---------------------------------------------------------------------------
# LLMProvider wrapper — exposed via app.integrations.llm_provider for the
# factory. Subagent methods (vision, catalog, etc.) stay on ClaudeClient
# directly; only the customer-facing decide / generate_reply go through here.
# ---------------------------------------------------------------------------

from app.integrations.llm_provider import LLMProvider as _LLMProvider  # noqa: E402


class ClaudeProvider(_LLMProvider):
    name = "anthropic"

    def __init__(self) -> None:
        self._client = ClaudeClient()

    async def decide(self, context: dict, *, model: str, max_tokens: int) -> dict:
        return await self._client.decide(context, model=model, max_tokens=max_tokens)

    async def generate_reply(self, context: dict, *, model: str, max_tokens: int) -> str:
        return await self._client.generate_reply(context, model=model, max_tokens=max_tokens)

    async def complete_text(self, *, system: str, user: str, model: str,
                            max_tokens: int, log_method: str | None = None) -> str:
        kwargs = dict(model=model, max_tokens=max_tokens,
                      messages=[{"role": "user", "content": user}])
        if system:
            kwargs["system"] = system
        resp = await self._client._create(log_method=log_method, **kwargs)
        return resp.content[0].text.strip()

    async def complete_vision(self, *, prompt: str, image: dict, model: str,
                              max_tokens: int, log_method: str | None = None) -> str:
        if image.get("kind") == "base64":
            source = {"type": "base64", "media_type": image["media_type"], "data": image["data"]}
        else:
            source = {"type": "url", "url": image["url"]}
        resp = await self._client._create(
            log_method=log_method, model=model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image", "source": source},
            ]}],
        )
        return resp.content[0].text.strip()
