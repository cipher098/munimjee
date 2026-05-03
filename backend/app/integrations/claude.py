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

    async def decide(self, context: dict) -> dict:
        last_counter = context.get("last_counter_price")
        last_counter_str = f"{last_counter} paise (₹{last_counter // 100})" if last_counter else "none yet"

        prompt = DECISION_PROMPT.format(
            state=context.get("state", ""),
            customer_message=context.get("customer_message", ""),
            listed_price=context.get("listed_price", "unknown"),
            floor_price=context.get("floor_price", "unknown"),
            last_counter_price=last_counter_str,
            round_number=context.get("negotiation_round", 0),
            message_history=json.dumps(context.get("message_history", []), ensure_ascii=False),
            available_products=json.dumps(context.get("available_products", []), ensure_ascii=False),
            other_inquiry_products=json.dumps(context.get("other_inquiry_products", []), ensure_ascii=False),
            bundle_pitched=context.get("bundle_pitched", False),
        )

        response = await self._client.messages.create(
            model=MODEL,
            max_tokens=350,
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

        history = context.get("message_history", [])
        history_str = json.dumps(history[-6:], ensure_ascii=False) if history else "[]"

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
            customer_message=context.get("customer_message", ""),
            has_more_photos=has_more_photos,
            message_history=history_str,
            address_term=context.get("address_term", "yaar"),
            other_active_products=other_active_str,
            other_inquiry_products_str=other_inquiry_str,
            multi_price_breakdown=context.get("multi_price_breakdown") or "N/A",
            bundle_breakdown=context.get("bundle_breakdown") or "N/A",
            inquiry_floor_total_rupees=context.get("inquiry_floor_total_rupees") or 0,
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
        response = await self._client.messages.create(
            model=MODEL,
            max_tokens=400,
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
        response = await self._client.messages.create(
            model=MODEL,
            max_tokens=600,
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
        response = await self._client.messages.create(
            model=MODEL,
            max_tokens=200,
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
