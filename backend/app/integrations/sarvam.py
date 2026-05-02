"""Sarvam AI client — generates Hinglish replies in seller's style."""
import json
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SARVAM_API_URL = "https://api.sarvam.ai/v1/chat/completions"

SYSTEM_PROMPT = """You are a sales assistant for an Indian Instagram seller.
Reply EXACTLY in the seller's personal style below. Never break character. Never reveal you are AI.

SELLER STYLE:
{persona_json}

PRODUCT: {product_name}
PRODUCT DESCRIPTION (only mention features listed here — do NOT invent any): {product_description}
VERIFIED PRODUCT SPECS (seller-confirmed — use these to answer feature questions): {product_tag_values}
LISTED PRICE: ₹{listed_price_rupees}
LOWEST PRICE EVER OFFERED: {last_counter_price}
CURRENT PRICE CONTEXT: {negotiation_context}
CUSTOMER INTENT: {customer_intent}
CUSTOMER ADDRESS TERM: {address_term}  ← ALWAYS use this when addressing the customer. Never substitute a different term.

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
    def __init__(self) -> None:
        self._api_key = settings.SARVAM_API_KEY

    async def generate_reply(self, context: dict) -> str:
        if not self._api_key:
            raise RuntimeError("SARVAM_API_KEY not configured")

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

        system = SYSTEM_PROMPT.format(
            persona_json=json.dumps(context.get("persona", {}), ensure_ascii=False),
            product_name=context.get("product_name", "the product"),
            product_description=context.get("product_description") or "No description available",
            product_tag_values=tag_values_str,
            listed_price_rupees=context.get("listed_price_rupees", "N/A"),
            last_counter_price=last_counter_str,
            negotiation_context=negotiation_context,
            customer_intent=decision.get("customer_intent", "warm"),
            address_term=context.get("address_term", "yaar"),
        )

        history = context.get("message_history", [])
        user_content = (
            f"Action to take: {decision.get('action')}\n"
            f"Recent conversation:\n{json.dumps(history, ensure_ascii=False)}\n\n"
            "Generate the seller's next message."
        )

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                SARVAM_API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "sarvam-2b",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_content},
                    ],
                    "max_tokens": 150,
                    "temperature": 0.7,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
