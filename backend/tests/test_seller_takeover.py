"""Tests for the seller manual takeover feature.

When the seller replies to a customer from Instagram's own inbox, the bot
should detect it via the echo webhook event, append the message to
conversation history as `seller_manual`, stamp `last_seller_manual_reply_at`,
and pause itself until the auto-resume window elapses.

These tests target the pure helpers extracted for that decision logic. The
end-to-end webhook path (signature → DB write) is exercised manually per the
plan's verification section.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.api.webhooks.instagram import (
    build_seller_manual_entry,
    is_known_outbound_mid,
)
from app.integrations.claude import _to_anthropic_role
from app.workers.message_batch import (
    extract_customer_text_entries,
    is_bot_paused_for_manual_takeover,
    unanswered_customer_messages,
)


# ---------------------------------------------------------------------------
# is_known_outbound_mid — distinguishes bot's own echo from seller manual reply
# ---------------------------------------------------------------------------

def test_known_mid_in_history_is_classified_as_bot_echo():
    messages = [
        {"role": "customer", "content": "kya price?"},
        {"role": "bot", "content": "1200 rupees", "mid": "MID_BOT_1"},
    ]
    assert is_known_outbound_mid(messages, "MID_BOT_1") is True


def test_novel_mid_is_classified_as_seller_manual():
    messages = [
        {"role": "bot", "content": "1200 rupees", "mid": "MID_BOT_1"},
    ]
    assert is_known_outbound_mid(messages, "MID_NEVER_SEEN") is False


def test_missing_mid_is_treated_as_seller_manual():
    """If the echo arrives without a mid, we can't match — err on seller side
    so the bot doesn't silently swallow a real manual reply."""
    messages = [{"role": "bot", "content": "1200 rupees", "mid": "MID_BOT_1"}]
    assert is_known_outbound_mid(messages, None) is False
    assert is_known_outbound_mid(messages, "") is False


def test_empty_history_with_any_mid_is_seller_manual():
    assert is_known_outbound_mid([], "MID_BOT_1") is False
    assert is_known_outbound_mid(None, "MID_BOT_1") is False


# ---------------------------------------------------------------------------
# build_seller_manual_entry — shape of the JSONB entry appended to messages
# ---------------------------------------------------------------------------

def test_build_seller_manual_entry_has_required_shape():
    fixed_now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    entry = build_seller_manual_entry("hi ji discount mil jayega", "MID_42", now=fixed_now)
    assert entry["role"] == "seller_manual"
    assert entry["content"] == "hi ji discount mil jayega"
    assert entry["mid"] == "MID_42"
    assert entry["timestamp"] == fixed_now.isoformat()


def test_build_seller_manual_entry_omits_mid_when_missing():
    entry = build_seller_manual_entry("hi", None)
    assert "mid" not in entry
    assert entry["role"] == "seller_manual"
    assert entry["content"] == "hi"


def test_build_seller_manual_entry_handles_empty_text():
    """Echo for an image-only manual reply has no text — we still want to
    record something so the timestamp+role provide a takeover signal."""
    entry = build_seller_manual_entry("", "MID_99")
    assert entry["content"] == ""
    assert entry["role"] == "seller_manual"


# ---------------------------------------------------------------------------
# is_bot_paused_for_manual_takeover — auto-resume window math (minutes)
# ---------------------------------------------------------------------------

def test_never_paused_when_no_manual_reply_recorded():
    assert is_bot_paused_for_manual_takeover(None, window_minutes=360) is False


def test_paused_within_window():
    now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    five_minutes_ago = now - timedelta(minutes=5)
    assert is_bot_paused_for_manual_takeover(five_minutes_ago, 360, now=now) is True


def test_resumed_after_window():
    now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    seven_hours_ago = now - timedelta(hours=7)
    assert is_bot_paused_for_manual_takeover(seven_hours_ago, 360, now=now) is False


def test_resumed_exactly_at_window_boundary():
    """Right at the boundary the bot is NOT paused — strict `<` window."""
    now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    exactly_360_min_ago = now - timedelta(minutes=360)
    assert is_bot_paused_for_manual_takeover(exactly_360_min_ago, 360, now=now) is False


def test_zero_window_means_never_paused():
    """Useful as an operational kill-switch: setting BOT_AUTO_RESUME_AFTER_MINUTES=0
    instantly resumes every paused conversation on the next customer message."""
    now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    just_now = now - timedelta(seconds=1)
    assert is_bot_paused_for_manual_takeover(just_now, window_minutes=0, now=now) is False


def test_minute_granularity_supports_short_windows():
    """The whole point of the minutes rename: short windows (e.g. 2m) work."""
    now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    one_minute_ago = now - timedelta(minutes=1)
    three_minutes_ago = now - timedelta(minutes=3)
    assert is_bot_paused_for_manual_takeover(one_minute_ago, window_minutes=2, now=now) is True
    assert is_bot_paused_for_manual_takeover(three_minutes_ago, window_minutes=2, now=now) is False


# ---------------------------------------------------------------------------
# extract_customer_text_entries — what we preserve in history during pause
# ---------------------------------------------------------------------------

def test_extract_customer_text_preserves_each_text_event_with_mid():
    fixed_now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)
    events = [
        {"type": "text", "text": "200 wali dedo", "mid": "MID_C1"},
        {"type": "text", "text": "Nhi sasti chaiye", "mid": "MID_C2"},
    ]
    out = extract_customer_text_entries(events, now=fixed_now)
    assert len(out) == 2
    assert out[0] == {
        "role": "customer", "content": "200 wali dedo",
        "timestamp": fixed_now.isoformat(), "mid": "MID_C1",
    }
    assert out[1]["content"] == "Nhi sasti chaiye"
    assert out[1]["mid"] == "MID_C2"


def test_extract_customer_text_skips_non_text_events():
    """Image/reel events aren't preserved during pause — seller will see them in IG anyway."""
    events = [
        {"type": "image", "image_url": "https://example.com/x.jpg"},
        {"type": "reel", "reel_url": "https://instagram.com/p/abc"},
        {"type": "text", "text": "still here"},
    ]
    out = extract_customer_text_entries(events)
    assert len(out) == 1
    assert out[0]["content"] == "still here"


def test_extract_customer_text_skips_empty_text():
    events = [{"type": "text", "text": ""}, {"type": "text", "text": "  hi  "}]
    out = extract_customer_text_entries(events)
    assert len(out) == 1
    assert out[0]["content"] == "  hi  "


def test_extract_customer_text_omits_mid_when_missing():
    out = extract_customer_text_entries([{"type": "text", "text": "no mid"}])
    assert "mid" not in out[0]


# ---------------------------------------------------------------------------
# unanswered_customer_messages — drives proactive wake-up decision
# ---------------------------------------------------------------------------

def test_unanswered_empty_history_returns_empty():
    assert unanswered_customer_messages([]) == []
    assert unanswered_customer_messages(None) == []


def test_unanswered_returns_all_trailing_customer_turns():
    messages = [
        {"role": "customer", "content": "kya price?"},
        {"role": "bot", "content": "1200 rupees"},
        {"role": "customer", "content": "warranty?"},
        {"role": "customer", "content": "color options?"},
    ]
    out = unanswered_customer_messages(messages)
    assert len(out) == 2
    assert [e["content"] for e in out] == ["warranty?", "color options?"]


def test_unanswered_stops_at_seller_manual():
    """Seller manual reply means the customer's prior turns were addressed —
    only count customer messages that came AFTER it."""
    messages = [
        {"role": "customer", "content": "old question"},
        {"role": "seller_manual", "content": "I handled this manually"},
        {"role": "customer", "content": "new question"},
    ]
    out = unanswered_customer_messages(messages)
    assert len(out) == 1
    assert out[0]["content"] == "new question"


def test_unanswered_empty_when_ending_in_bot():
    """Bot just replied — nothing unanswered, wake-up should no-op."""
    messages = [
        {"role": "customer", "content": "kya price?"},
        {"role": "bot", "content": "1200"},
    ]
    assert unanswered_customer_messages(messages) == []


def test_unanswered_empty_when_ending_in_seller_manual():
    """Seller just answered — nothing unanswered, wake-up should no-op."""
    messages = [
        {"role": "customer", "content": "kya price?"},
        {"role": "seller_manual", "content": "1200 hai"},
    ]
    assert unanswered_customer_messages(messages) == []


def test_unanswered_preserves_mid_for_last_customer_msg():
    """Wake-up needs the last customer mid to pass to advance_conversation."""
    messages = [
        {"role": "bot", "content": "hi"},
        {"role": "customer", "content": "A", "mid": "MID_A"},
        {"role": "customer", "content": "B", "mid": "MID_B"},
    ]
    out = unanswered_customer_messages(messages)
    assert out[-1]["mid"] == "MID_B"


def test_unanswered_only_customer_msgs_returns_them_all():
    """Brand-new conversation: customer talked first, no brand response yet."""
    messages = [
        {"role": "customer", "content": "hi"},
        {"role": "customer", "content": "anyone there?"},
    ]
    out = unanswered_customer_messages(messages)
    assert len(out) == 2


# ---------------------------------------------------------------------------
# _to_anthropic_role — seller_manual must map to assistant so resumed bot
# sees the seller's manual turn in Claude's prompt history.
# ---------------------------------------------------------------------------

def test_seller_manual_role_maps_to_assistant():
    assert _to_anthropic_role("seller_manual") == "assistant"


def test_bot_role_still_maps_to_assistant():
    assert _to_anthropic_role("bot") == "assistant"


def test_customer_role_still_maps_to_user():
    assert _to_anthropic_role("customer") == "user"


def test_unknown_role_returns_none():
    assert _to_anthropic_role("admin") is None
