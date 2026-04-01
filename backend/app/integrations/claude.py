"""Anthropic Claude API client — business logic decisions + fallback reply generation."""
import json
import logging

import anthropic

from app.config import settings
from app.prompts import (
    CATALOG_MATCH_PROMPT,
    DECISION_PROMPT,
    IMAGE_DESCRIBE_PROMPT,
    REPLY_PROMPT,
)

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"


def _parse_json(text: str) -> dict:
    """Parse JSON from Claude's response, stripping markdown code fences if present."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    return json.loads(text.strip())


class ClaudeClient:
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    async def decide(self, context: dict) -> dict:
        prompt = DECISION_PROMPT.format(
            state=context.get("state", ""),
            customer_message=context.get("customer_message", ""),
            listed_price=context.get("listed_price", "unknown"),
            floor_price=context.get("floor_price", "unknown"),
            round_number=context.get("negotiation_round", 0),
            message_history=json.dumps(context.get("message_history", []), ensure_ascii=False),
            available_products=json.dumps(context.get("available_products", []), ensure_ascii=False),
        )

        response = await self._client.messages.create(
            model=MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        try:
            return _parse_json(text)
        except json.JSONDecodeError:
            logger.error("Claude returned non-JSON decision: %r", text)
            return {"action": "clarify", "price": None, "reason": "parse error"}

    async def generate_reply(self, context: dict) -> str:
        decision = context.get("decision", {})
        price = decision.get("price")
        price_context = f"Counter price: ₹{price // 100}" if price else "No price change"

        prompt = REPLY_PROMPT.format(
            persona_json=json.dumps(context.get("persona", {}), ensure_ascii=False),
            product_name=context.get("product_name", "the product"),
            listed_price_rupees=context.get("listed_price_rupees", "N/A"),
            action=decision.get("action", "clarify"),
            price_context=price_context,
            customer_intent=decision.get("customer_intent", "warm"),
        )

        response = await self._client.messages.create(
            model=MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    async def generate_product_description(self, image_url: str, product_name: str) -> str:
        """Generate a seller-facing product description from an image for catalog use."""
        response = await self._client.messages.create(
            model=MODEL,
            max_tokens=200,
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
        response = await self._client.messages.create(
            model=MODEL,
            max_tokens=150,
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

        response = await self._client.messages.create(
            model=MODEL,
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        try:
            return _parse_json(text)
        except json.JSONDecodeError:
            logger.error("Claude returned non-JSON catalog match: %r", text)
            return {"product_id": None, "confidence": "low", "reason": "parse error"}

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
        response = await self._client.messages.create(
            model=MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        try:
            return _parse_json(text)
        except json.JSONDecodeError:
            logger.error("Claude returned non-JSON persona: %r", text)
            return {}
