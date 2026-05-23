"""Intent classifier — runs alongside decide() to surface emotional signals.

The existing decide() prompt already classifies negotiation intent
(hot/warm/cold/bulk) as part of its JSON output. This classifier focuses on
the orthogonal signals decide() does NOT capture well:

  - sentiment: customer's emotional state (positive / neutral / negative /
    very_negative). Drives intervention rules around acknowledging frustration.
  - intent_label: high-level message category beyond pure negotiation
    (complaint, policy_question, closing, etc.).
  - is_repeated_dissatisfaction: customer has expressed the same complaint
    or rejection multiple times → escalate, don't repeat the same retort.

Uses claude-haiku for speed and cost (~$0.0001 per call). Designed to run
in parallel with extract_feature_query so it adds minimal latency to the
critical path.

Modeled on cortex/emergent's `IntentClassifier`. Falls back to a "neutral"
classification on any error so the bot never blocks on this signal.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Literal

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)

CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"

Sentiment = Literal["positive", "neutral", "negative", "very_negative"]
IntentLabel = Literal[
    "greeting",
    "feature_question",
    "price_negotiation",
    "walkaway",
    "bulk_inquiry",
    "policy_question",
    "complaint",
    "closing",
    "other",
]


@dataclass
class Classification:
    sentiment: Sentiment
    intent_label: IntentLabel
    is_repeated_dissatisfaction: bool
    confidence: float  # 0.0 - 1.0

    def as_dict(self) -> dict:
        return asdict(self)


_NEUTRAL_FALLBACK = Classification(
    sentiment="neutral",
    intent_label="other",
    is_repeated_dissatisfaction=False,
    confidence=0.0,
)

_PROMPT = """Classify this customer's latest message in an ongoing Instagram seller conversation.

Return ONLY a valid JSON object, no other text. Use this exact schema:
{
  "sentiment": "positive|neutral|negative|very_negative",
  "intent_label": "greeting|feature_question|price_negotiation|walkaway|bulk_inquiry|policy_question|complaint|closing|other",
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
  - other: anything else
- is_repeated_dissatisfaction: TRUE if the message reads like the customer is repeating a
  complaint or rejection they already expressed. Look at RECENT HISTORY for context.
- confidence: how confident you are (0.0-1.0).

RECENT HISTORY (oldest first):
{history}

LATEST CUSTOMER MESSAGE:
{message}
"""


async def classify(customer_message: str, recent_history: list[dict] | None = None) -> Classification:
    """Classify the latest customer message. Returns _NEUTRAL_FALLBACK on any error.

    `recent_history` is the conversation.messages list (last few entries used).
    Failures here MUST NOT block the bot — the rest of the pipeline still works
    without this signal.
    """
    if not customer_message or not customer_message.strip():
        return _NEUTRAL_FALLBACK

    history_str = _format_history(recent_history or [])
    prompt = _PROMPT.replace("{history}", history_str).replace("{message}", customer_message)

    try:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        resp = await client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        logger.warning("Intent classifier API failed (%s) — using neutral fallback", exc)
        return _NEUTRAL_FALLBACK

    text = resp.content[0].text.strip() if resp.content else ""
    return _parse(text)


def _format_history(history: list[dict], limit: int = 6) -> str:
    if not history:
        return "(no prior messages)"
    recent = history[-limit:]
    lines = []
    for entry in recent:
        role = entry.get("role", "unknown")
        content = (entry.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "(no prior messages)"


def _parse(text: str) -> Classification:
    if not text:
        return _NEUTRAL_FALLBACK
    # Strip code fences / prose wrappers.
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Intent classifier returned non-JSON: %r", text[:200])
        return _NEUTRAL_FALLBACK

    try:
        return Classification(
            sentiment=_safe_enum(data.get("sentiment"), {"positive", "neutral", "negative", "very_negative"}, "neutral"),
            intent_label=_safe_enum(
                data.get("intent_label"),
                {
                    "greeting", "feature_question", "price_negotiation", "walkaway",
                    "bulk_inquiry", "policy_question", "complaint", "closing", "other",
                },
                "other",
            ),
            is_repeated_dissatisfaction=bool(data.get("is_repeated_dissatisfaction", False)),
            confidence=max(0.0, min(1.0, float(data.get("confidence", 0.0)))),
        )
    except (TypeError, ValueError) as exc:
        logger.warning("Intent classifier parse error %s — using fallback", exc)
        return _NEUTRAL_FALLBACK


def _safe_enum(value, allowed: set[str], default: str) -> str:
    if isinstance(value, str) and value in allowed:
        return value
    return default
