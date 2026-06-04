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


def _split_reply_prompt(formatted_prompt: str) -> tuple[str, str]:
    """Split a fully-formatted REPLY_PROMPT into (static_system, dynamic_context).

    Splits at the `--- DYNAMIC CONTEXT ---` marker which sits BEFORE the
    data section. Static rules (cacheable) go above, dynamic per-call data
    (persona, product, prices, etc.) goes below.

    Returns (whole_prompt, "") if the marker is missing — caller falls back
    to sending the whole prompt as the user message uncached.
    """
    marker = "--- DYNAMIC CONTEXT ---"
    if marker not in formatted_prompt:
        return formatted_prompt, ""
    before, _, after = formatted_prompt.partition(marker)
    return before.rstrip(), marker + after.rstrip()


def _split_decision_prompt(formatted_prompt: str) -> tuple[str, str]:
    """Split a fully-formatted DECISION_PROMPT into (static_system, dynamic_user).

    The training dashboard rewrites DECISION_PROMPT freely, so we split at
    runtime on stable markers rather than maintaining two prompt constants.
    Returns (system_prompt, user_prompt) where system holds the rules
    (cacheable across calls) and user holds the per-call context.

    Falls back to (whole_prompt, "") if markers are missing — caller can
    detect empty user and skip caching.
    """
    ctx_marker = "--- CONTEXT ---"
    strategy_marker = "--- NEGOTIATION STRATEGY"
    if ctx_marker not in formatted_prompt or strategy_marker not in formatted_prompt:
        return formatted_prompt, ""
    before_ctx, _, after_ctx = formatted_prompt.partition(ctx_marker)
    if strategy_marker not in after_ctx:
        return formatted_prompt, ""
    context_block, _, strategy_block = after_ctx.partition(strategy_marker)
    static_system = (
        before_ctx.rstrip()
        + "\n\n"
        + strategy_marker
        + strategy_block.rstrip()
    )
    dynamic_user = ctx_marker + context_block.rstrip()
    return static_system, dynamic_user


from app.integrations._json_utils import (  # noqa: F401  (re-export for test compatibility)
    LLMOutputParseError,
    parse_json_relaxed as _parse_json,
)
from app.integrations import llm_logging


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
        last_counter = context.get("last_counter_price")
        last_counter_str = f"{last_counter} paise (₹{last_counter // 100})" if last_counter else "none yet"
        last_shown = context.get("last_shown_price")
        last_shown_str = f"{last_shown} paise (₹{last_shown // 100})" if last_shown else "none yet"

        # Pass empty customer_message/message_history so .format() still works if
        # the training dashboard re-introduces those placeholders. The actual
        # latest customer message and history are sent as native Anthropic
        # messages below for prefix caching.
        decision_template = await prompt_store.get("decide")
        prompt = decision_template.format(
            state=context.get("state", ""),
            customer_message="",
            listed_price=context.get("listed_price", "unknown"),
            floor_price=context.get("floor_price", "unknown"),
            last_counter_price=last_counter_str,
            last_shown_price=last_shown_str,
            round_number=context.get("negotiation_round", 0),
            message_history="",
            available_products=json.dumps(context.get("available_products", []), ensure_ascii=False),
            other_inquiry_products=json.dumps(context.get("other_inquiry_products", []), ensure_ascii=False),
            bundle_pitched=context.get("bundle_pitched", False),
            seller_channels=json.dumps(context.get("seller_channels", []), ensure_ascii=False),
            product_variants=json.dumps(context.get("product_variants", []), ensure_ascii=False),
            active_variant_label=context.get("active_variant_label") or "none",
        )

        system_text, context_block = _split_decision_prompt(prompt)

        # Evaluate intervention rules. Fired reminders go INTO the user-side context
        # so they remain dynamic (don't pollute the cached system prompt) and give
        # the model fresh, situation-specific guidance for high-leverage turns.
        from app.bot import interventions as _interventions

        fired = _interventions.evaluate(context)
        if fired:
            logger.info(
                "Interventions fired: %s",
                ", ".join(f"{r.id}(p={r.priority})" for r in fired),
            )
        # Test hook — scenario harness asserts on which rules fired this turn.
        from app.bot.test_hooks import record as _record_turn
        _record_turn(fired_interventions=[r.id for r in fired])
        reminder_block = _interventions.render_reminders(fired)
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
        decision = context.get("decision", {})
        price = decision.get("price")
        price_context = f"YOUR COUNTER OFFER IS ₹{price // 100} — quote this exact number" if price else "No price change"
        last_counter = context.get("last_counter_price")
        last_counter_reply_str = f"₹{last_counter // 100}" if last_counter else "none"
        last_shown = context.get("last_shown_price")
        last_shown_reply_str = f"₹{last_shown // 100}" if last_shown else "none"
        display_price_rupees = context.get("display_price_rupees")
        display_price_str = f"₹{display_price_rupees}" if display_price_rupees is not None else "N/A"

        warranty = context.get("warranty_months")
        warranty_str = f"{warranty} months" if warranty else "No warranty"

        stock = context.get("stock_quantity")
        if stock is None:
            stock_str = "Not tracked"
        elif stock == 0:
            stock_str = "Out of stock"
        elif stock <= 3:
            stock_str = f"Only {stock} left"
        else:
            stock_str = f"{stock} in stock"

        policies = context.get("policies") or {}
        cod = policies.get("cod")
        cod_charges = policies.get("cod_charges", 0)
        return_days = policies.get("return_days")
        exchange_days = policies.get("exchange_days")
        delivery_days = policies.get("delivery_days")
        payment_modes = policies.get("payment_modes") or []

        _mode_labels = {"upi": "UPI", "bank_transfer": "Bank Transfer/NEFT", "card": "Card"}
        mode_str = " / ".join(_mode_labels.get(m, m) for m in payment_modes) if payment_modes else None

        policy_lines = []
        if mode_str:
            policy_lines.append(f"Accepted payment: {mode_str}")
        if cod is True:
            if cod_charges:
                policy_lines.append(f"COD available with ₹{cod_charges} extra charge")
            else:
                policy_lines.append("COD available, no extra charge")
        elif cod is False:
            policy_lines.append("No COD — prepaid only")
        if return_days:
            policy_lines.append(f"{return_days}-day returns accepted")
        elif return_days == 0 and "return_days" in policies:
            policy_lines.append("No returns")
        if exchange_days:
            policy_lines.append(f"{exchange_days}-day exchange accepted")
        elif exchange_days == 0 and "exchange_days" in policies:
            policy_lines.append("No exchange")
        if delivery_days:
            policy_lines.append(f"Delivery in {delivery_days}")
        policy_str = ", ".join(policy_lines) if policy_lines else "Not configured — do not mention or invent any policy; say you'll check and confirm"

        total_photos = context.get("total_photos", 1)
        has_more_photos = total_photos > 1

        history = context.get("message_history") or []

        product_description = context.get("product_description") or "No description available"
        logger.warning("generate_reply: product=%r description=%r", context.get("product_name"), product_description)

        tag_values = context.get("product_tag_values") or {}
        tag_values_str = (
            ", ".join(f"{k}: {v}" for k, v in tag_values.items()) if tag_values else "None available"
        )

        other_active = context.get("other_active_products") or []
        other_active_str = (
            ", ".join(p["name"] for p in other_active) if other_active else "none"
        )

        other_inquiry = context.get("other_inquiry_products") or []

        def _fmt_inquiry(p: dict) -> str:
            base = f"{p['name']} listed=₹{p['listed_price_rupees']} floor=₹{p['floor_price_rupees']}"
            if p.get("last_shown_price_rupees"):
                base += f" last_shown=₹{p['last_shown_price_rupees']} (NEVER quote higher than this)"
            return base

        other_inquiry_str = (
            ", ".join(_fmt_inquiry(p) for p in other_inquiry) if other_inquiry else "none"
        )

        # customer_message/message_history are no longer rendered into REPLY_PROMPT —
        # they're sent as native Anthropic messages below for prefix caching.
        # Pass empty strings to .format() in case the training dashboard re-introduces
        # the placeholders later.
        reply_template = await prompt_store.get("generate_reply")
        prompt = reply_template.format(
            persona_json=json.dumps(context.get("persona", {}), ensure_ascii=False),
            product_name=context.get("product_name", "the product"),
            product_description=product_description,
            product_tag_values=tag_values_str,
            listed_price_rupees=context.get("listed_price_rupees", "N/A"),
            display_price_rupees=display_price_str,
            floor_price_rupees=context.get("floor_price_rupees", "N/A"),
            warranty_info=warranty_str,
            stock_info=stock_str,
            policy_info=policy_str,
            action=decision.get("action", "clarify"),
            price_context=price_context,
            last_counter_price=last_counter_reply_str,
            last_shown_price=last_shown_reply_str,
            customer_intent=decision.get("customer_intent", "warm"),
            customer_message="",
            has_more_photos=has_more_photos,
            message_history="",
            address_term=context.get("address_term", "yaar"),
            other_active_products=other_active_str,
            other_inquiry_products_str=other_inquiry_str,
            multi_price_breakdown=context.get("multi_price_breakdown") or "N/A",
            bundle_breakdown=context.get("bundle_breakdown") or "N/A",
            inquiry_floor_total_rupees=context.get("inquiry_floor_total_rupees") or 0,
        )

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
        """Generate a seller-facing product description from an image for catalog use."""
        spec = agent_spec.get("generate_product_description")
        template = await prompt_store.get("generate_product_description")
        response = await self._create(
            fallback_model=spec.fallback_model,
            log_method=spec.name,
            model=spec.model,
            max_tokens=spec.max_tokens,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": template.format(product_name=product_name)},
                    {"type": "image", "source": {"type": "url", "url": image_url}},
                ],
            }],
        )
        return response.content[0].text.strip()

    async def describe_product_image(self, image_b64: str, media_type: str = "image/jpeg") -> str:
        """Stage 1 — Vision only: describe what product is in the customer's image.
        Accepts base64-encoded image bytes (Instagram blocks direct URL fetching).
        """
        spec = agent_spec.get("describe_product_image")
        template = await prompt_store.get("image_describe")
        response = await self._create(
            fallback_model=spec.fallback_model,
            log_method=spec.name,
            model=spec.model,
            max_tokens=spec.max_tokens,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": template},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                ],
            }],
        )
        return response.content[0].text.strip()

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

        spec = agent_spec.get("match_product_by_description")
        response = await self._create(
            fallback_model=spec.fallback_model,
            log_method=spec.name,
            model=spec.model,
            max_tokens=spec.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        try:
            return _parse_json(text)
        except LLMOutputParseError:
            logger.error("Claude returned non-JSON catalog match: %r", text)
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
        spec = agent_spec.get("suggest_category")
        response = await self._create(
            fallback_model=spec.fallback_model,
            log_method=spec.name,
            model=spec.model,
            max_tokens=spec.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        try:
            return _parse_json(text)
        except LLMOutputParseError:
            logger.error("Claude returned non-JSON category suggestion: %r", text)
            return {"category_name": None, "tags": []}

    async def suggest_tags_for_category(self, category_name: str) -> list[dict]:
        """Suggest tag definitions for a given product category.
        Returns: [{name, display_name, value_type, allowed_values, suggested_value}]
        suggested_value is a typical default value the seller can confirm or change.
        """
        template = await prompt_store.get("suggest_tags_for_category")
        prompt = template.format(category_name=category_name)
        spec = agent_spec.get("suggest_tags_for_category")
        response = await self._create(
            fallback_model=spec.fallback_model,
            log_method=spec.name,
            model=spec.model,
            max_tokens=spec.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        try:
            result = _parse_json(text)
            return result if isinstance(result, list) else []
        except LLMOutputParseError:
            logger.error("Claude returned non-JSON tag suggestions: %r", text)
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
        spec = agent_spec.get("extract_feature_query")
        response = await self._create(
            fallback_model=spec.fallback_model,
            log_method=spec.name,
            model=spec.model,
            max_tokens=spec.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        try:
            return _parse_json(text)
        except LLMOutputParseError:
            logger.error("Claude returned non-JSON feature query: %r", text)
            return {"is_feature_question": False, "matched_tag_name": None,
                    "new_tag_name": None, "new_tag_display_name": None,
                    "new_tag_value_type": None, "new_tag_allowed_values": None}

    async def extract_persona(self, conversation_history: str) -> dict:
        template = await prompt_store.get("extract_persona")
        prompt = template.format(conversation_history=conversation_history)
        spec = agent_spec.get("extract_persona")
        response = await self._create(
            fallback_model=spec.fallback_model,
            log_method=spec.name,
            model=spec.model,
            max_tokens=spec.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        try:
            return _parse_json(text)
        except LLMOutputParseError:
            logger.error("Claude returned non-JSON persona: %r", text)
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
