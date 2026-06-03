"""Prompts for one-shot Claude utility calls ("sub-agents").

DECISION_PROMPT and REPLY_PROMPT live in prompts.py because the training
dashboard rewrites that file based on seller feedback. The prompts here are
internal utility calls (catalog matching, image description, persona
extraction, intent classification, etc.) that should NOT be hand-tuned via
the customer-facing feedback loop — they're shaped by what the calling code
expects to parse.

Pulling them out of inline f-strings in claude.py:
  - makes them grep-able / diff-able
  - sets up the migration path to a DB-backed prompt store (each one keyed
    by sub-agent name)
  - lets the YAML spec in agents.yaml drive both model AND prompt selection
    per method in a future change

Format conventions match prompts.py: Python str.format() placeholders are
single-braced, JSON literals are double-braced.
"""

# ─── Catalog onboarding helpers ──────────────────────────────────────────

GENERATE_PRODUCT_DESCRIPTION_PROMPT = (
    "You are helping an Indian small business seller list a product called '{product_name}'.\n"
    "Write a short product description (2-3 sentences) based on this image.\n"
    "Mention: material, colour, key features, typical use.\n"
    "Write in simple English. No marketing fluff. Return ONLY the description text."
)

SUGGEST_CATEGORY_PROMPT = (
    "A seller is listing a product called '{product_name}'.\n"
    "{description_line}"
    "Suggest a product category name and 3-6 useful specification tags a buyer might ask about.\n"
    "Return ONLY valid JSON, no other text:\n"
    '{{"category_name": "e.g. Wall Clock", "tags": ['
    '{{"name": "power_source", "display_name": "Power Source", "value_type": "enum", "allowed_values": ["AC Power", "Battery", "USB"]}}'
    "]}}\n"
    "Rules:\n"
    "- category_name: short, generic product type (2-3 words max)\n"
    "- tag name: lowercase_snake_case slug\n"
    "- value_type: 'enum' if there are fixed choices, 'text' for free text, 'number' for measurements\n"
    "- For enum tags, always include allowed_values. For text/number, set allowed_values to null.\n"
)

SUGGEST_TAGS_FOR_CATEGORY_PROMPT = (
    "A seller has a product category called '{category_name}'.\n"
    "Suggest 4-8 specification tags that customers commonly ask about for this product type.\n"
    "For each tag, also suggest a typical/common value as 'suggested_value'.\n"
    "Return ONLY a valid JSON array, no other text:\n"
    "[\n"
    '  {{"name": "power_source", "display_name": "Power Source", "value_type": "enum", '
    '"allowed_values": ["AC Power", "Battery", "USB Chargeable"], "suggested_value": "AC Power"}},\n'
    '  {{"name": "dial_size", "display_name": "Dial Size", "value_type": "text", '
    '"allowed_values": null, "suggested_value": "30 cm"}}\n'
    "]\n"
    "Rules:\n"
    "- name: lowercase_snake_case slug\n"
    "- value_type: 'enum' if fixed choices exist, 'text' for free input, 'number' for measurements\n"
    "- For enum: include allowed_values list. For text/number: set allowed_values to null.\n"
    "- suggested_value: the most common/default value for this category — can be null if unknown.\n"
)

# ─── Runtime customer-message analyzers ──────────────────────────────────

EXTRACT_FEATURE_QUERY_PROMPT = (
    'Customer message: "{customer_message}"\n\n'
    "Known product tags: {tags_json}\n\n"
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
    '{{"is_feature_question": true/false, '
    '"matched_tag_name": "<existing tag slug or null>", '
    '"new_tag_name": "<snake_case slug if no match, else null>", '
    '"new_tag_display_name": "<human label if no match, else null>", '
    '"new_tag_value_type": "<enum|text|number if new tag, else null>", '
    '"new_tag_allowed_values": ["option1", "option2"] or null}}'
)

# ─── Persona extraction (seller onboarding) ─────────────────────────────

EXTRACT_PERSONA_PROMPT = """Analyze these Instagram DM conversations from an Indian seller.
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

# ─── Intent classifier (lives alongside the others for grepability) ─────
# This template is consumed by .replace() (NOT .format()), so the schema
# braces below stay single — there is no Python format-placeholder collision.

INTENT_CLASSIFIER_PROMPT = """Classify this customer's latest message in an ongoing Instagram seller conversation.

Return ONLY a valid JSON object, no other text. Use this exact schema:
{
  "sentiment": "positive|neutral|negative|very_negative",
  "intent_label": "greeting|feature_question|price_negotiation|walkaway|bulk_inquiry|policy_question|complaint|closing|channel_switch_request|other",
  "is_repeated_dissatisfaction": true|false,
  "confidence": 0.0-1.0
}

Definitions:
- sentiment: emotional tone of THIS message. "very_negative" = clearly angry/frustrated.
- intent_label:
  - greeting: hello, kya chahiye, hi etc.
  - feature_question: asking what the product is/has/does (size, material, charging...)
  - price_negotiation: discussing or pushing on price (counter, discount, kam karo)
  - walkaway: signalling they will leave or buy elsewhere ("aur se le lunga", "rehne do", "chodo")
  - bulk_inquiry: asking about multiple pieces / wholesale
  - policy_question: asking about return, refund, COD, exchange, delivery
  - complaint: dissatisfaction about product quality, response time, behavior
  - closing: agreeing to buy / asking payment details ("le lunga", "fix karo", "UPI?")
  - channel_switch_request: customer wants to move off Instagram —
    "WhatsApp pe baat", "call kar lo", "Instagram delete kar diya",
    "phone number do", "DM nahi karna", "email pe", "kahin aur baat"
  - other: anything else
- is_repeated_dissatisfaction: TRUE if the message reads like the customer is repeating a
  complaint or rejection they already expressed. Look at RECENT HISTORY for context.
- confidence: how confident you are (0.0-1.0).

RECENT HISTORY (oldest first):
{history}

LATEST CUSTOMER MESSAGE:
{message}
"""
