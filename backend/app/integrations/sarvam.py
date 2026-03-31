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
CURRENT PRICE CONTEXT: {negotiation_context}

Rules:
- Write in the seller's natural Hinglish style
- Keep messages short like real Instagram DMs (1-3 lines max)
- Use emojis only if seller's style includes them
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

        system = SYSTEM_PROMPT.format(
            persona_json=json.dumps(context.get("persona", {}), ensure_ascii=False),
            product_name=context.get("product_name", "the product"),
            negotiation_context=negotiation_context,
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
