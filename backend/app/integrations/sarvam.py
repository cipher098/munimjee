"""Sarvam AI client — Hinglish-tuned chat model used as an alternative
provider for both the bot's thinking call (decide → JSON) and the
customer-facing reply.

Driven by the multi-provider factory in `llm_provider.py`: every call
arrives with an explicit `model` and `max_tokens` chosen by the factory
based on the app default in `agents.yaml` and the seller's
`llm_preferences` override (if any). Nothing about model selection lives
in this file.

Errors propagate — the factory catches them and falls back to the
provider/model in the agent spec's `fallback_provider` / `fallback_model`.
"""
import json
import logging

import httpx

from app.bot import prompt_store
from app.config import settings
from app.integrations._json_utils import LLMOutputParseError, parse_json_relaxed

logger = logging.getLogger(__name__)

# Sarvam's current chat models (sarvam-30b / sarvam-105b) are reasoning
# models: they spend tokens on an internal `reasoning_content` stream
# before emitting the user-visible `content`. That reasoning is billed
# against `max_tokens`, so if we forward the caller's answer-budget
# verbatim the reasoning can eat the whole allowance and `content` comes
# back null. We (a) request the lightest reasoning tier and (b) add a
# fixed headroom on top of the caller's budget so `max_tokens` keeps
# meaning "answer length" from the factory's point of view.
# Measured: even on "low", our full decide/reply system prompts drive
# ~1300-1500 reasoning tokens before the answer, so the headroom must be
# generous or `content` truncates to null (finish_reason=length).
_REASONING_EFFORT = "low"
_REASONING_HEADROOM_TOKENS = 1800


REPLY_SYSTEM_PROMPT = """You are a sales assistant for an Indian Instagram seller.
Reply EXACTLY in the seller's personal style below. Never break character. Never reveal you are AI.

SELLER STYLE:
{persona_json}

PRODUCT: {product_name}
PRODUCT DESCRIPTION (only mention features listed here — do NOT invent any): {product_description}
VERIFIED PRODUCT SPECS (seller-confirmed — use these to answer feature questions): {product_tag_values}
LISTED PRICE: ₹{listed_price_rupees}
FLOOR PRICE: ₹{floor_price_rupees} (absolute minimum for {product_name} — never quote this product below this)
LOWEST PRICE EVER OFFERED: {last_counter_price}
CURRENT PRICE CONTEXT: {negotiation_context}
CUSTOMER INTENT: {customer_intent}
CUSTOMER ADDRESS TERM: {address_term}  ← ALWAYS use this when addressing the customer. Never substitute a different term.
OTHER ACTIVE PRODUCTS (customer is already discussing these — not rejected, not purchased): {other_active_products}
OTHER INQUIRY PRODUCTS WITH PRICES: {other_inquiry_products_str}
SHOW MULTI PRICE DATA — CODE-COMPUTED (use verbatim if ACTION is show_multi_price): {multi_price_breakdown}
BUNDLE BREAKDOWN — CODE-COMPUTED (use verbatim ONLY if customer explicitly asks for per-product breakdown): {bundle_breakdown}
BUNDLE MINIMUM TOTAL: ₹{inquiry_floor_total_rupees} (sum of inquiry product floors — total must never go below this)

CRITICAL — Not interested rule:
If ACTION is "not_interested":
- If OTHER ACTIVE PRODUCTS is not "none": pivot directly to one of those products by name.
  Example: "Koi baat nahi {address_term}! Waise {{other_product_name}} toh dekha? Uske baare mein baat karte hain 😊"
  Do NOT say generic "kuch aur chahiye toh batana" — the customer is mid-discussion on those products.
- If OTHER ACTIVE PRODUCTS is "none": gracefully acknowledge and offer generic help.
  Example: "Ok {address_term}, koi baat nahi! Kuch aur chahiye toh batana 😊"
Keep it warm. Do NOT mention the rejected product. Do NOT pitch price.

CRITICAL — Bundle pitch rule:
If ACTION is "bundle_pitch": mention all products in OTHER INQUIRY PRODUCTS WITH PRICES plus the current product, with their prices.
Example: "Waise {address_term}, aapne Wooden Clock (₹1800), Silver Watch (₹1200) aur Blue Frame (₹900) — teeno le lo toh ek sath ship kar deta hoon, easy hoga na? 😊"
Keep it casual, one line. No hard sell. Customer can say yes/no freely.

CRITICAL — Multi-product / bundle price rule (NO EXCEPTIONS, overrides everything):
- If ACTION is "show_multi_price": use ONLY the prices in SHOW MULTI PRICE DATA above — verbatim. Do NOT use any other numbers. These are code-computed and floor-enforced.
- If ACTION is "counter" or "accept" AND OTHER INQUIRY PRODUCTS WITH PRICES is non-empty:
  → DEFAULT: quote ONLY the TOTAL price from PRICE CONTEXT as one number (e.g. "total ₹2100" or "dono ka ₹2100").
  → EXCEPTION: if customer explicitly asks for breakdown ("har ek ka kitna", "alag alag batao", "breakdown", "kis ka kitna"), use BUNDLE BREAKDOWN above verbatim — do NOT compute your own numbers.
  → If PRICE CONTEXT total is less than BUNDLE MINIMUM TOTAL, use BUNDLE MINIMUM TOTAL instead.
- NEVER write any individual product price below its floor=₹X.
- Example violation: black rose gold floor=₹1000 → you CANNOT write ₹900 for it, ever.

⚠️ HARD PRICE RULE — read first:
If LOWEST PRICE EVER OFFERED is set, NEVER quote any price higher than that in your reply.
Not the listed price, not any other number. The customer already saw the lower price — going back up makes you look dishonest.
When customer asks "final price" / "kitna final" and LOWEST PRICE EVER OFFERED is set: quote that lower price, not the listed price.

CRITICAL — Price transparency rule:
If the customer asks for price ("kya price", "kitne ka", "price batao", "kitna") and NO lower price was offered yet,
state ₹{listed_price_rupees} clearly. If a lower price was already offered, state that lower price instead.

CRITICAL — Repetition rule:
The recent conversation is shown below. Before writing, scan the last bot messages.
If a point (quality pitch, gift suitability, urgency, value argument) was already made recently,
do NOT repeat it. Say something fresh, or keep the reply very short.
A bot that repeats itself sounds scripted and irritates the customer.

CRITICAL — Engage/conversational rule:
If ACTION is "engage" and CUSTOMER INTENT is NOT hot or warm, just respond naturally to what
the customer said — NO sales close, NO "order kar do", NO price. Sound like a friend.
Only add a soft close if the customer has shown clear buying interest.

Tone guidance based on customer intent:
- hot: confident, brief, close the deal — don't over-explain
- warm: friendly but firm, highlight value to justify price
- cold: empathetic but don't cave — acknowledge their concern, stand your ground

Rules:
- Write in the seller's natural Hinglish style
- Keep messages short like real Instagram DMs (1-3 lines max)
- Emojis: use sparingly, only when relevant, never repeat the same emoji. Many messages
  should have no emoji — that feels more natural. Pick contextually: 💰🤝 for price,
  ✨👌 for quality, 🙏 for walk-away, 🚀📦 for dispatch
- Never mention floor price or internal pricing
- Return ONLY the message text, nothing else
"""


class SarvamClient:
    """Thin httpx wrapper around Sarvam's OpenAI-compatible chat
    completions endpoint. Model + max_tokens are passed in from the
    factory; no agents.yaml lookup here."""

    def __init__(self) -> None:
        self._api_key = settings.SARVAM_API_KEY
        self._url = settings.SARVAM_API_URL

    async def _chat(self, *, model: str, max_tokens: int, system: str, user: str, temperature: float = 0.7) -> str:
        if not self._api_key:
            raise RuntimeError("SARVAM_API_KEY not configured")
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # Reasoning models burn the budget thinking before they answer —
            # add headroom so the caller's max_tokens still bounds the answer.
            "max_tokens": max_tokens + _REASONING_HEADROOM_TOKENS,
            "temperature": temperature,
            "reasoning_effort": _REASONING_EFFORT,
        }
        last_exc: Exception | None = None
        for attempt in (1, 2):
            try:
                async with httpx.AsyncClient(timeout=45) as client:
                    response = await client.post(
                        self._url,
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    response.raise_for_status()
                    data = response.json()
                    content = (data["choices"][0]["message"]["content"] or "").strip()
                    if not content:
                        # Reasoning consumed the whole budget and never emitted
                        # an answer. Treat as a failure so the factory falls back.
                        raise LLMOutputParseError(
                            f"Sarvam returned empty content "
                            f"(finish_reason={data['choices'][0].get('finish_reason')})"
                        )
                    return content
            except (httpx.HTTPError, KeyError, IndexError) as exc:
                last_exc = exc
                logger.warning("Sarvam call attempt %d failed (%s)", attempt, exc)
        assert last_exc is not None
        raise last_exc

    async def decide(self, context: dict, *, model: str, max_tokens: int) -> dict:
        """Run the decide prompt on Sarvam and parse JSON. Raises
        LLMOutputParseError on malformed output so the factory falls back."""
        decision_template = await prompt_store.get("decide")
        last_counter = context.get("last_counter_price")
        last_counter_str = f"{last_counter} paise (₹{last_counter // 100})" if last_counter else "none yet"
        last_shown = context.get("last_shown_price")
        last_shown_str = f"{last_shown} paise (₹{last_shown // 100})" if last_shown else "none yet"

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

        # Sarvam doesn't have prompt caching — send the whole prompt as
        # the system message, with the customer turn + recent history as
        # the user message. The DECISION_PROMPT already instructs
        # "Return ONLY valid JSON" so no extra wrapper is needed.
        history = context.get("message_history") or []
        history_str = json.dumps(history[-10:], ensure_ascii=False) if history else "(empty)"
        customer_msg = context.get("customer_message") or ""
        user_block = (
            f"Recent conversation (oldest first):\n{history_str}\n\n"
            f"Latest customer message: {customer_msg!r}\n\n"
            "Choose the next action and return ONLY a JSON object — no prose, no code fences."
        )

        text = await self._chat(
            model=model, max_tokens=max_tokens,
            system=prompt, user=user_block, temperature=0.2,
        )
        return parse_json_relaxed(text)

    async def generate_reply(self, context: dict, *, model: str, max_tokens: int) -> str:
        decision = context.get("decision", {})
        price = decision.get("price")
        negotiation_context = (
            f"Counter price: ₹{price // 100}" if price else f"Action: {decision.get('action', '')}"
        )
        last_counter = context.get("last_counter_price")
        last_counter_str = f"₹{last_counter // 100}" if last_counter else "none"

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

        system = REPLY_SYSTEM_PROMPT.format(
            persona_json=json.dumps(context.get("persona", {}), ensure_ascii=False),
            product_name=context.get("product_name", "the product"),
            product_description=context.get("product_description") or "No description available",
            product_tag_values=tag_values_str,
            listed_price_rupees=context.get("listed_price_rupees", "N/A"),
            floor_price_rupees=context.get("floor_price_rupees", "N/A"),
            last_counter_price=last_counter_str,
            negotiation_context=negotiation_context,
            customer_intent=decision.get("customer_intent", "warm"),
            address_term=context.get("address_term", "yaar"),
            other_active_products=other_active_str,
            other_inquiry_products_str=other_inquiry_str,
            multi_price_breakdown=context.get("multi_price_breakdown") or "N/A",
            bundle_breakdown=context.get("bundle_breakdown") or "N/A",
            inquiry_floor_total_rupees=context.get("inquiry_floor_total_rupees") or 0,
        )

        history = context.get("message_history", [])
        user_content = (
            f"Action to take: {decision.get('action')}\n"
            f"Recent conversation:\n{json.dumps(history, ensure_ascii=False)}\n\n"
            "Generate the seller's next message."
        )

        return await self._chat(
            model=model, max_tokens=max_tokens,
            system=system, user=user_content, temperature=0.7,
        )


# ---------------------------------------------------------------------------
# LLMProvider wrapper used by the factory
# ---------------------------------------------------------------------------

from app.integrations.llm_provider import LLMProvider as _LLMProvider  # noqa: E402


class SarvamProvider(_LLMProvider):
    name = "sarvam"

    def __init__(self) -> None:
        self._client = SarvamClient()

    async def decide(self, context: dict, *, model: str, max_tokens: int) -> dict:
        return await self._client.decide(context, model=model, max_tokens=max_tokens)

    async def generate_reply(self, context: dict, *, model: str, max_tokens: int) -> str:
        return await self._client.generate_reply(context, model=model, max_tokens=max_tokens)
