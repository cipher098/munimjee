"""Unit tests for the intent classifier — focuses on parse robustness.

We don't make live API calls here. The classifier is also exercised via VCR
elsewhere; these tests guard the failure modes that matter:
  - empty / whitespace input returns a neutral classification (not a crash)
  - garbage model output returns a neutral classification
  - well-formed JSON parses into the correct dataclass shape
  - out-of-range / unknown enum values fall back to safe defaults
"""
import pytest

from app.bot.intent_classifier import (
    _NEUTRAL_FALLBACK,
    Classification,
    _parse,
    classify,
)


@pytest.mark.asyncio
async def test_classify_empty_input_returns_neutral():
    """Empty / whitespace input must NOT trigger an API call, just return neutral."""
    result = await classify("")
    assert result == _NEUTRAL_FALLBACK
    result = await classify("   \n   ")
    assert result == _NEUTRAL_FALLBACK


def test_parse_valid_json_with_all_fields():
    text = '{"sentiment": "very_negative", "intent_label": "complaint", "is_repeated_dissatisfaction": true, "confidence": 0.92}'
    c = _parse(text)
    assert c.sentiment == "very_negative"
    assert c.intent_label == "complaint"
    assert c.is_repeated_dissatisfaction is True
    assert c.confidence == pytest.approx(0.92)


def test_parse_strips_markdown_fences():
    text = "```json\n{\"sentiment\": \"positive\", \"intent_label\": \"greeting\", \"is_repeated_dissatisfaction\": false, \"confidence\": 0.8}\n```"
    c = _parse(text)
    assert c.intent_label == "greeting"
    assert c.sentiment == "positive"


def test_parse_extracts_json_from_prose():
    text = "Sure, here's the classification: {\"sentiment\": \"neutral\", \"intent_label\": \"feature_question\", \"is_repeated_dissatisfaction\": false, \"confidence\": 0.7} hope that helps"
    c = _parse(text)
    assert c.intent_label == "feature_question"


def test_parse_unknown_enum_falls_back_to_default():
    """Defense against future model drift returning labels we don't know about."""
    text = '{"sentiment": "ecstatic", "intent_label": "mystery_label", "is_repeated_dissatisfaction": false, "confidence": 0.5}'
    c = _parse(text)
    assert c.sentiment == "neutral"  # unknown sentiment → neutral
    assert c.intent_label == "other"  # unknown label → other


def test_parse_clamps_confidence_to_range():
    text = '{"sentiment": "neutral", "intent_label": "other", "is_repeated_dissatisfaction": false, "confidence": 5.0}'
    c = _parse(text)
    assert c.confidence == 1.0
    text = '{"sentiment": "neutral", "intent_label": "other", "is_repeated_dissatisfaction": false, "confidence": -0.5}'
    c = _parse(text)
    assert c.confidence == 0.0


def test_parse_garbage_returns_neutral():
    assert _parse("not json at all") == _NEUTRAL_FALLBACK
    assert _parse("") == _NEUTRAL_FALLBACK
    assert _parse("{broken json") == _NEUTRAL_FALLBACK


def test_classification_as_dict_round_trips():
    """as_dict() output is what we pass through to interventions context;
    its shape must match what `intent_label_in`/`sentiment_in` operators expect."""
    c = Classification(
        sentiment="negative",
        intent_label="complaint",
        is_repeated_dissatisfaction=True,
        confidence=0.85,
    )
    d = c.as_dict()
    assert d["sentiment"] == "negative"
    assert d["intent_label"] == "complaint"
    assert d["is_repeated_dissatisfaction"] is True
    assert d["confidence"] == 0.85
