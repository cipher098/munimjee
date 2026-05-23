"""Anthropic Claude API client — business logic decisions + fallback reply generation."""
import json
import logging

import anthropic

from app.bot import agent_spec
from app.config import settings
from app.prompts import (
    CATALOG_MATCH_PROMPT,
    DECISION_PROMPT,
    IMAGE_DESCRIBE_PROMPT,
    REPLY_PROMPT,
)

logger = logging.getLogger(__name__)

# Backward-compat aliases — model selection now lives in agents.yaml.
# `MODEL` is still re-exported because training.py and tests import it.
MODEL = agent_spec.get("decide").model
FALLBACK_MODEL = agent_spec.get("decide").fallback_model or "claude-3-5-sonnet-20241022"


def _to_anthropic_role(raw_role: str) -> str | None:
    """Map sellerbot conversation roles to Anthropic API roles."""
    if raw_role == "customer":
        return "user"
    if raw_role == "bot":
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


def _parse_json(text: str) -> dict:
    """Parse JSON from Claude's response, handling code fences and prose wrappers."""
    text = text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0].strip()
    # If Claude wrapped JSON in prose, extract the first {...} block
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


class ClaudeClient:
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def _create(self, *, fallback_model: str | None = None, **kwargs):
        """messages.create with one retry on transient API errors and a
        model fallback when the primary model emits a content-policy refusal.
        `fallback_model` lets callers override the global FALLBACK_MODEL on a
        per-method basis (driven by agents.yaml). Logs cache hits."""
        model_name = kwargs.get("model", MODEL)
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

        usage = getattr(resp, "usage", None)
        if usage is not None:
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
            if cache_read or cache_create:
                logger.info(
                    "Claude cache: read=%d write=%d input=%d output=%d model=%s",
                    cache_read, cache_create,
                    getattr(usage, "input_tokens", 0) or 0,
                    getattr(usage, "output_tokens", 0) or 0,
                    model_name,
                )
        return resp

    async def decide(self, context: dict) -> dict:
        last_counter = context.get("last_counter_price")
        last_counter_str = f"{last_counter} paise (₹{last_counter // 100})" if last_counter else "none yet"

        # Pass empty customer_message/message_history so .format() still works if
        # the training dashboard re-introduces those placeholders. The actual
        # latest customer message and history are sent as native Anthropic
        # messages below for prefix caching.
        prompt = DECISION_PROMPT.format(
            state=context.get("state", ""),
            customer_message="",
            listed_price=context.get("listed_price", "unknown"),
            floor_price=context.get("floor_price", "unknown"),
            last_counter_price=last_counter_str,
            round_number=context.get("negotiation_round", 0),
            message_history="",
            available_products=json.dumps(context.get("available_products", []), ensure_ascii=False),
            other_inquiry_products=json.dumps(context.get("other_inquiry_products", []), ensure_ascii=False),
            bundle_pitched=context.get("bundle_pitched", False),
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
        if context_block:
            messages = _build_decision_messages(history_for_cache, current_user_text, context_block)
            request_kwargs = dict(
                model=spec.model,
                max_tokens=spec.max_tokens,
                system=[
                    {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
                ],
                messages=messages,
            )
        else:
            # Marker missing (training dashboard rewrote prompt structure) — degraded path.
            logger.warning("DECISION_PROMPT missing CONTEXT/STRATEGY markers — skipping cache")
            request_kwargs = dict(
                model=spec.model,
                max_tokens=spec.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

        try:
            response = await self._create(fallback_model=spec.fallback_model, **request_kwargs)
        except Exception as exc:
            logger.exception("Claude decide() failed unrecoverably: %s — returning clarify", exc)
            return {"action": "clarify", "price": None, "reason": "api error"}

        text = response.content[0].text.strip()
        try:
            return _parse_json(text)
        except json.JSONDecodeError:
            logger.error("Claude returned non-JSON decision: %r", text)
            return {"action": "clarify", "price": None, "reason": "parse error"}

    async def generate_reply(self, context: dict) -> str:
        decision = context.get("decision", {})
        price = decision.get("price")
        price_context = f"YOUR COUNTER OFFER IS ₹{price // 100} — quote this exact number" if price else "No price change"
        last_counter = context.get("last_counter_price")
        last_counter_reply_str = f"₹{last_counter // 100}" if last_counter else "none"

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
        other_inquiry_str = (
            ", ".join(
                f"{p['name']} listed=₹{p['listed_price_rupees']} floor=₹{p['floor_price_rupees']}"
                for p in other_inquiry
            )
            if other_inquiry else "none"
        )

        # customer_message/message_history are no longer rendered into REPLY_PROMPT —
        # they're sent as native Anthropic messages below for prefix caching.
        # Pass empty strings to .format() in case the training dashboard re-introduces
        # the placeholders later.
        prompt = REPLY_PROMPT.format(
            persona_json=json.dumps(context.get("persona", {}), ensure_ascii=False),
            product_name=context.get("product_name", "the product"),
            product_description=product_description,
            product_tag_values=tag_values_str,
            listed_price_rupees=context.get("listed_price_rupees", "N/A"),
            floor_price_rupees=context.get("floor_price_rupees", "N/A"),
            warranty_info=warranty_str,
            stock_info=stock_str,
            policy_info=policy_str,
            action=decision.get("action", "clarify"),
            price_context=price_context,
            last_counter_price=last_counter_reply_str,
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
        if context_block:
            current_user_text = context.get("customer_message", "")
            if history and history[-1].get("role") == "customer":
                history_for_cache = history[:-1]
            else:
                history_for_cache = history
            messages = _build_decision_messages(history_for_cache, current_user_text, context_block)
            request_kwargs = dict(
                model=spec.model,
                max_tokens=spec.max_tokens,
                system=[
                    {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
                ],
                messages=messages,
            )
        else:
            logger.warning("REPLY_PROMPT missing DYNAMIC CONTEXT marker — skipping cache")
            request_kwargs = dict(
                model=spec.model,
                max_tokens=spec.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

        try:
            response = await self._create(fallback_model=spec.fallback_model, **request_kwargs)
        except Exception as exc:
            logger.exception("Claude generate_reply() failed unrecoverably: %s", exc)
            # Soft fallback — return a safe acknowledgment rather than crashing the conversation.
            return ""
        return response.content[0].text.strip()

    async def generate_product_description(self, image_url: str, product_name: str) -> str:
        """Generate a seller-facing product description from an image for catalog use."""
        spec = agent_spec.get("generate_product_description")
        response = await self._create(
            fallback_model=spec.fallback_model,
            model=spec.model,
            max_tokens=spec.max_tokens,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"You are helping an Indian small business seller list a product called '{product_name}'.\n"
                            "Write a short product description (2-3 sentences) based on this image.\n"
                            "Mention: material, colour, key features, typical use.\n"
                            "Write in simple English. No marketing fluff. Return ONLY the description text."
                        ),
                    },
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
        response = await self._create(
            fallback_model=spec.fallback_model,
            model=spec.model,
            max_tokens=spec.max_tokens,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": IMAGE_DESCRIBE_PROMPT},
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

        prompt = CATALOG_MATCH_PROMPT.format(
            description=description,
            catalog_json=json.dumps(catalog, ensure_ascii=False),
        )

        spec = agent_spec.get("match_product_by_description")
        response = await self._create(
            fallback_model=spec.fallback_model,
            model=spec.model,
            max_tokens=spec.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        try:
            return _parse_json(text)
        except json.JSONDecodeError:
            logger.error("Claude returned non-JSON catalog match: %r", text)
            return {"product_id": None, "confidence": "low", "reason": "parse error"}

    async def suggest_category(self, product_name: str, product_description: str = "") -> dict:
        """Suggest a category name and relevant tag definitions for a product.
        Returns: {category_name, tags: [{name, display_name, value_type, allowed_values}]}
        """
        prompt = (
            f"A seller is listing a product called '{product_name}'.\n"
            + (f"Description: {product_description}\n" if product_description else "")
            + "Suggest a product category name and 3-6 useful specification tags a buyer might ask about.\n"
            "Return ONLY valid JSON, no other text:\n"
            '{"category_name": "e.g. Wall Clock", "tags": ['
            '{"name": "power_source", "display_name": "Power Source", "value_type": "enum", "allowed_values": ["AC Power", "Battery", "USB"]}'
            "]}\n"
            "Rules:\n"
            "- category_name: short, generic product type (2-3 words max)\n"
            "- tag name: lowercase_snake_case slug\n"
            "- value_type: 'enum' if there are fixed choices, 'text' for free text, 'number' for measurements\n"
            "- For enum tags, always include allowed_values. For text/number, set allowed_values to null.\n"
        )
        spec = agent_spec.get("suggest_category")
        response = await self._create(
            fallback_model=spec.fallback_model,
            model=spec.model,
            max_tokens=spec.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        try:
            return _parse_json(text)
        except json.JSONDecodeError:
            logger.error("Claude returned non-JSON category suggestion: %r", text)
            return {"category_name": None, "tags": []}

    async def suggest_tags_for_category(self, category_name: str) -> list[dict]:
        """Suggest tag definitions for a given product category.
        Returns: [{name, display_name, value_type, allowed_values, suggested_value}]
        suggested_value is a typical default value the seller can confirm or change.
        """
        prompt = (
            f"A seller has a product category called '{category_name}'.\n"
            "Suggest 4-8 specification tags that customers commonly ask about for this product type.\n"
            "For each tag, also suggest a typical/common value as 'suggested_value'.\n"
            "Return ONLY a valid JSON array, no other text:\n"
            "[\n"
            '  {"name": "power_source", "display_name": "Power Source", "value_type": "enum", '
            '"allowed_values": ["AC Power", "Battery", "USB Chargeable"], "suggested_value": "AC Power"},\n'
            '  {"name": "dial_size", "display_name": "Dial Size", "value_type": "text", '
            '"allowed_values": null, "suggested_value": "30 cm"}\n'
            "]\n"
            "Rules:\n"
            "- name: lowercase_snake_case slug\n"
            "- value_type: 'enum' if fixed choices exist, 'text' for free input, 'number' for measurements\n"
            "- For enum: include allowed_values list. For text/number: set allowed_values to null.\n"
            "- suggested_value: the most common/default value for this category — can be null if unknown.\n"
        )
        spec = agent_spec.get("suggest_tags_for_category")
        response = await self._create(
            fallback_model=spec.fallback_model,
            model=spec.model,
            max_tokens=spec.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        try:
            result = _parse_json(text)
            return result if isinstance(result, list) else []
        except json.JSONDecodeError:
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
        prompt = (
            f"Customer message: \"{customer_message}\"\n\n"
            f"Known product tags: {tags_json}\n\n"
            "Is this message asking about a specific specification or feature of the CURRENT product being discussed?\n"
            "Examples of feature questions: charging method, power source, size, material, colour, weight, display type, connectivity, whether a feature exists on THIS product\n"
            "NOT feature questions:\n"
            "- price, warranty, delivery, return policy, 'le lunga', 'order karna hai'\n"
            "- Requests to see OTHER products or designs ('koi aur design hai?', 'aur kuch dikhao', 'different model hai?', 'or sample', 'aur kya hai')\n"
            "- General browsing or switching ('ye nahi, kuch aur', 'koi doosra', 'aur options')\n"
            "- Compliments or reactions ('accha hai', 'sundar hai', 'theek hai')\n"
            "- Expressing DISLIKE or REJECTION of a feature value — even if a tag word appears ('yeh colour nhi chahie', 'ye size nahi chalega', 'is design mein nahi chahiye', 'aur colour hai?'). These mean the customer does not want THIS product, NOT that they are asking what the feature is.\n"
            "- Asking if a product EXISTS in a different variant/colour/style ('koi blue green colour type hai?', 'X mein kuch hai?', 'koi aur colour hai?', 'X colour available hai?'). These are availability/browse questions — the customer wants to see a different product, not know about THIS product's specs.\n"
            "Key test: is the customer asking WHAT THIS specific product IS or HAS? Only that is a feature question. 'Do you have X colour?' or 'Is X available?' is browsing, not a feature question.\n\n"
            "If it IS a feature question, check if it maps to one of the known tags above.\n"
            "If it does NOT map to a known tag, suggest a new tag. For the new tag:\n"
            "- Choose a clear, meaningful display name (e.g. 'Second Hand' for a clock seconds hand question)\n"
            "- Decide value_type: 'enum' if the answer has fixed options, 'text' for free text, 'number' for measurements\n"
            "- For enum: provide the most likely allowed_values list (e.g. Yes/No questions → [\"Yes\", \"No\"])\n"
            "- For text/number: set allowed_values to null\n\n"
            "Return ONLY valid JSON, no other text:\n"
            '{"is_feature_question": true/false, '
            '"matched_tag_name": "<existing tag slug or null>", '
            '"new_tag_name": "<snake_case slug if no match, else null>", '
            '"new_tag_display_name": "<human label if no match, else null>", '
            '"new_tag_value_type": "<enum|text|number if new tag, else null>", '
            '"new_tag_allowed_values": ["option1", "option2"] or null}'
        )
        spec = agent_spec.get("extract_feature_query")
        response = await self._create(
            fallback_model=spec.fallback_model,
            model=spec.model,
            max_tokens=spec.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        try:
            return _parse_json(text)
        except json.JSONDecodeError:
            logger.error("Claude returned non-JSON feature query: %r", text)
            return {"is_feature_question": False, "matched_tag_name": None,
                    "new_tag_name": None, "new_tag_display_name": None,
                    "new_tag_value_type": None, "new_tag_allowed_values": None}

    async def extract_persona(self, conversation_history: str) -> dict:
        prompt = f"""Analyze these Instagram DM conversations from an Indian seller.
Return ONLY valid JSON, no other text:
{{
  "greeting_style": "exact phrase they use e.g. 'Haan bolo' or 'Ji kya chahiye'",
  "negotiation_firmness": "soft | medium | firm",
  "closing_phrases": ["phrases used when deal closes"],
  "common_expressions": ["frequent words/phrases they use"],
  "hindi_english_ratio": "e.g. 70% Hindi 30% English",
  "emoji_usage": "none | light | moderate | heavy",
  "response_length": "short | medium | long",
  "tone": "formal | casual | very_casual",
  "sample_responses": {{
    "greeting": "in their exact style",
    "price_rejection": "how they say no to low offers",
    "deal_accepted": "how they confirm a deal",
    "payment_request": "how they ask for payment",
    "dispatched": "how they say order is shipped"
  }}
}}
Conversation history: {conversation_history}
"""
        spec = agent_spec.get("extract_persona")
        response = await self._create(
            fallback_model=spec.fallback_model,
            model=spec.model,
            max_tokens=spec.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        try:
            return _parse_json(text)
        except json.JSONDecodeError:
            logger.error("Claude returned non-JSON persona: %r", text)
            return {}
