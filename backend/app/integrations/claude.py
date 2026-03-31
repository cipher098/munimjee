"""Anthropic Claude API client — business logic decisions + fallback reply generation."""
import json
import logging

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"

DECISION_PROMPT = """You are the business logic engine for an Instagram seller bot.
Return ONLY valid JSON, no other text:
{{
  "action": "greet|show_product|counter|accept|hold_firm|request_payment|clarify|escalate",
  "price": <int in paise, only for counter/accept, else null>,
  "reason": "<brief>"
}}

State: {state}
Customer message: {customer_message}
Listed price: {listed_price} paise
Floor price: {floor_price} paise
Negotiation round: {round_number}
Last messages: {message_history}
"""

REPLY_PROMPT = """You are a sales assistant for an Indian Instagram seller.
Reply EXACTLY in the seller's personal style below. Never break character. Never reveal you are AI.

SELLER STYLE:
{persona_json}

PRODUCT: {product_name}
ACTION TO TAKE: {action}
PRICE CONTEXT: {price_context}

Rules:
- Write in the seller's natural Hinglish style
- Keep messages short like real Instagram DMs (1-3 lines max)
- Use emojis only if seller's style includes them
- Never mention floor price or internal pricing
- Return ONLY the message text, nothing else
"""


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
        )

        response = await self._client.messages.create(
            model=MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        try:
            return json.loads(text)
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
            action=decision.get("action", "clarify"),
            price_context=price_context,
        )

        response = await self._client.messages.create(
            model=MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

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
            return json.loads(text)
        except json.JSONDecodeError:
            logger.error("Claude returned non-JSON persona: %r", text)
            return {}
