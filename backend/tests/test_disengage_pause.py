"""Tests for the customer-disengagement pause + re-engagement escape.

When the bot acks a "bye"/"ok" the conversation enters a quiet window
(default 2h). A re-engagement signal in any customer message during the
window lifts the pause immediately so the bot doesn't miss a hot lead.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.workers.message_batch import (
    is_bot_paused_for_disengage,
    is_reengagement_signal,
)


NOW = datetime(2026, 6, 4, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# is_bot_paused_for_disengage — window math
# ---------------------------------------------------------------------------

def test_no_pause_when_column_is_null():
    assert is_bot_paused_for_disengage(None, now=NOW) is False


def test_pause_active_when_future_timestamp():
    future = NOW + timedelta(minutes=30)
    assert is_bot_paused_for_disengage(future, now=NOW) is True


def test_pause_expired_when_past_timestamp():
    past = NOW - timedelta(minutes=1)
    assert is_bot_paused_for_disengage(past, now=NOW) is False


def test_pause_boundary_strict_less_than():
    """At exactly the boundary the pause is no longer active (strict <)."""
    assert is_bot_paused_for_disengage(NOW, now=NOW) is False


# ---------------------------------------------------------------------------
# is_reengagement_signal — what lifts the disengage pause
# ---------------------------------------------------------------------------

# Negative cases — these stay muted
@pytest.mark.parametrize("text", [
    "",
    "ok",
    "bye",
    "ok bye",
    "nahi chahiye",
    "thik hai",
    "rehne do",
    "hmm",
    "kal dekhte hai",
])
def test_passive_drop_off_stays_muted(text):
    assert is_reengagement_signal(text) is False


def test_none_text_stays_muted():
    assert is_reengagement_signal(None) is False


# Positive cases — these wake the bot
@pytest.mark.parametrize("text", [
    "kya price?",
    "kitne ka hai",
    "rate batao",
    "dam kya hai",
    "le lunga yaar",
    "lelo confirm",
    "dedo na",
    "fix karo",
    "confirm",
    "yes",
    "haan dedo",
    "accept",
    "order kar do",
    "buy karna hai",
    "purchase",
    "ek lunga",
    "leta hoon",
])
def test_buying_keywords_lift_pause(text):
    assert is_reengagement_signal(text) is True


def test_numeric_token_lifts_pause():
    """Any digit token signals price negotiation or quantity."""
    assert is_reengagement_signal("1000 dedo") is True
    assert is_reengagement_signal("2 piece") is True
    assert is_reengagement_signal("yaar 850 last") is True


def test_question_mark_lifts_pause():
    """Customer is actively asking — wake up even without a keyword."""
    assert is_reengagement_signal("?") is True
    assert is_reengagement_signal("hmm?") is True


def test_keywords_are_case_insensitive():
    assert is_reengagement_signal("PRICE?") is True
    assert is_reengagement_signal("LeLo") is True


# Negation gate — words like "chahiye" / "milega" that flip on "nahi"
# must stay muted when the negation is present.
@pytest.mark.parametrize("text", [
    "nahi chahiye",
    "nahi lena bhai",
    "nahin lunga",
    "no thanks",
    "not interested",
    "mat bhejo",
    "abhi nahi 100 wala",          # even with a digit, "nahi" wins
    "kya price nahi chahiye",      # keyword + negation → still muted
])
def test_negation_keeps_pause(text):
    assert is_reengagement_signal(text) is False
