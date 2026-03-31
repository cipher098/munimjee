"""Anthropic Claude API client — business logic decisions + fallback reply generation."""
import json
import logging

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"


def _parse_json(text: str) -> dict:
    """Parse JSON from Claude's response, stripping markdown code fences if present."""
    text = text.strip()
    if text.startswith("```"):
        # Strip ```json ... ``` or ``` ... ```
        text = text.split("\n", 1)[-1]  # remove opening fence line
        text = text.rsplit("```", 1)[0]  # remove closing fence
    return json.loads(text.strip())

IMAGE_DESCRIBE_PROMPT = """Look at this product image sent by a customer who wants to buy it.
Describe the product in detail so it can be matched against a catalog.
Focus on: product type, colour, material, size/shape, style, brand if visible, any text/labels.
Return ONLY a plain text description, 1-2 sentences, no JSON.
"""

CATALOG_MATCH_PROMPT = """You are matching a product description to a seller's catalog.

CUSTOMER WANTS: {description}

CATALOG:
{catalog_json}

Find the best matching product. Return ONLY valid JSON, no other text:
{{
  "product_id": "<uuid of best match, or null if nothing matches reasonably>",
  "confidence": "high|medium|low",
  "reason": "<brief — what matched>"
}}
"""

DECISION_PROMPT = """You are the negotiation engine for an Indian Instagram seller bot.
Your goal is to MAXIMISE the sale price. Sell as close to listed_price as possible.
Never reveal floor_price or any internal pricing to the customer.

Return ONLY valid JSON, no other text:
{{
  "action": "greet|show_product|counter|accept|hold_firm|bulk_discount|request_payment|clarify|escalate",
  "price": <int in paise, only for counter/accept/bulk_discount, else null>,
  "product_id": "<uuid if you identified which product the customer wants, else null>",
  "customer_intent": "hot|warm|cold|bulk",
  "bulk_quantity": <int if customer mentioned a quantity > 1, else null>,
  "reason": "<brief>"
}}

--- CONTEXT ---
State: {state}
Negotiation round: {round_number}
Listed price: {listed_price} paise
Floor price: {floor_price} paise
Customer message: {customer_message}
Last messages: {message_history}
Available products: {available_products}

--- NEGOTIATION STRATEGY (follow strictly) ---

STEP 1 — Read customer intent from their tone:
  hot  = eager, asking details, "fix karo", "le lunga", "confirm", "pakka"
  warm = interested but bargaining casually, asking for small discount
  cold = walk-away threat or strong price refusal:
         "aur se le lunga", "kahi aur se lunga", "rehne do", "chhod do",
         "nahi chahiye", "bahut zyada hai", "itna nahi dunga"
  bulk = customer mentions quantity > 1: "2 chahiye", "5 piece", "10 lunga",
         "bulk order", "zyada quantity" — this is a HOT signal, treat them well

STEP 2 — Choose the correct action:

  clarify = ONLY when the customer's message is genuinely ambiguous and you cannot
            understand what they want at all. NEVER use clarify for price objections,
            walk-away threats, bulk orders, or any negotiation message.

  bulk_discount = use this action ONLY when customer has mentioned a quantity > 1.
                  Extract the quantity from their message and set it in the reason field.
                  Offer a small per-piece discount: 5-10% off listed_price per piece.
                  Price in the response = discounted per-piece price in paise.
                  Still must be >= floor_price.

  hold_firm = customer pushed back on price but you are not moving yet.
              Use a retention message: remind them of quality, uniqueness, value.
              For walk-away threats ("aur se le lunga"): call the bluff confidently —
              "Bhai milega nahi itni quality mein, ye last price hai"

  counter = you are willing to reduce price slightly this round.

  accept = customer has offered >= floor_price.

STEP 3 — Round-based pricing strategy:

  Round 0 (first price ask):
    → Always hold_firm at listed_price. Never discount on round 0.

  Round 1 (first pushback):
    → hot/warm: hold_firm — emphasise quality/value.
    → cold (walk-away): hold_firm — call the bluff, retention message.
    → Never counter on round 1.

  Round 2 (second pushback):
    → hot: hold_firm.
    → warm: counter at listed_price minus at most 5% of (listed - floor).
    → cold: counter at listed_price minus at most 10% of (listed - floor).

  Round 3+ (persistent):
    → Each round reduce by at most 10% of (listed - floor) from previous counter.
    → Never drop more than 30% of (listed - floor) total across all rounds.
    → At floor_price: hold_firm permanently.

STEP 4 — Hard constraints (non-negotiable):
  - counter/accept price must ALWAYS be >= floor_price
  - If listed_price == floor_price: always hold_firm, never counter
  - Never accept below floor_price
  - Do not counter twice in a row without a new customer offer
"""

REPLY_PROMPT = """You are a sales assistant for an Indian Instagram seller.
Reply in the seller's personal style below. Never break character. Never reveal you are AI.
If no style info is provided, default to casual Hinglish like a typical Indian small business seller.

SELLER STYLE:
{persona_json}

PRODUCT: {product_name}
LISTED PRICE: ₹{listed_price_rupees}
ACTION TO TAKE: {action}
PRICE CONTEXT: {price_context}
CUSTOMER INTENT: {customer_intent}

CRITICAL — Price transparency rule:
If the customer is asking for the price ("kya price", "kitne ka", "price batao", "price?", "kitna"),
you MUST state the price clearly (₹{listed_price_rupees}) in your reply. Never dodge a direct price question.

Tone guidance based on customer intent:
- hot: confident and brief — just close the deal, don't over-explain
- warm: friendly but firm — highlight quality/value to justify price
- cold: if walk-away threat ("aur se le lunga") — call the bluff confidently, don't panic,
        remind them why your product is worth it. Never ask unrelated questions.
- bulk: customer wants multiple pieces — be warm and appreciative, mention the quantity,
        offer the per-piece bulk price clearly e.g. "10 piece ke liye ₹X/piece kar deta hoon"

Rules:
- Write in natural Hinglish (mix of Hindi and English)
- Keep messages short like real Instagram DMs (1-3 lines max)
- Emojis: use sparingly and only when they add meaning. Do NOT use the same emoji twice
  in a conversation. Pick emojis relevant to the context:
  price talk → 💰🤝, quality → ✨👌, urgency → ⚡, walk-away → 🙏, shipped → 🚀📦
  Many messages should have NO emoji at all — that feels more natural and human
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
