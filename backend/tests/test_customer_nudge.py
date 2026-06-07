"""Tests for the customer-nudge follow-up.

Pure helpers in app.workers.nudge — eligibility logic that scan + send_nudge
re-check, separated for unit testing.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.workers.nudge import (
    last_customer_message_at,
    last_message_role,
    should_nudge_now,
)


# ---------------------------------------------------------------------------
# last_customer_message_at — walks history backwards for most-recent customer turn
# ---------------------------------------------------------------------------

def test_last_customer_at_returns_none_when_empty():
    assert last_customer_message_at([]) is None
    assert last_customer_message_at(None) is None


def test_last_customer_at_returns_none_when_only_bot_turns():
    assert last_customer_message_at([{"role": "bot", "content": "hi"}]) is None


def test_last_customer_at_returns_latest_customer_timestamp():
    ts1 = "2026-06-03T08:00:00+00:00"
    ts2 = "2026-06-03T09:00:00+00:00"
    out = last_customer_message_at([
        {"role": "customer", "content": "old", "timestamp": ts1},
        {"role": "bot", "content": "reply", "timestamp": ts1},
        {"role": "customer", "content": "new", "timestamp": ts2},
    ])
    assert out == datetime(2026, 6, 3, 9, 0, 0, tzinfo=timezone.utc)


def test_last_customer_at_assumes_utc_when_timestamp_naive():
    out = last_customer_message_at([
        {"role": "customer", "content": "x", "timestamp": "2026-06-03T08:00:00"},
    ])
    assert out is not None
    assert out.tzinfo is timezone.utc


def test_last_customer_at_skips_entries_without_timestamp():
    ts = "2026-06-03T08:00:00+00:00"
    out = last_customer_message_at([
        {"role": "customer", "content": "no ts"},
        {"role": "customer", "content": "has ts", "timestamp": ts},
    ])
    assert out == datetime(2026, 6, 3, 8, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# last_message_role
# ---------------------------------------------------------------------------

def test_last_message_role_returns_role_string():
    assert last_message_role([{"role": "customer", "content": "hi"}]) == "customer"
    assert last_message_role([
        {"role": "customer", "content": "hi"},
        {"role": "bot", "content": "ji"},
    ]) == "bot"


def test_last_message_role_none_when_empty():
    assert last_message_role([]) is None
    assert last_message_role(None) is None


# ---------------------------------------------------------------------------
# should_nudge_now — eligibility math driving the beat scan + send_nudge
# ---------------------------------------------------------------------------

NOW = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)


def _customer_msg(hours_ago: float) -> dict:
    ts = (NOW - timedelta(hours=hours_ago)).isoformat()
    return {"role": "customer", "content": "kya price?", "timestamp": ts}


def test_no_nudge_when_no_customer_messages():
    assert should_nudge_now([], None, 24, 48, now=NOW) == 0


def test_no_nudge_when_last_message_is_bot():
    messages = [
        _customer_msg(hours_ago=30),
        {"role": "bot", "content": "1200", "timestamp": NOW.isoformat()},
    ]
    assert should_nudge_now(messages, None, 24, 48, now=NOW) == 0


def test_no_nudge_when_last_message_is_seller_manual():
    """Seller already addressed the customer — don't pile on with a nudge."""
    messages = [
        _customer_msg(hours_ago=30),
        {"role": "seller_manual", "content": "discount mil jayega", "timestamp": NOW.isoformat()},
    ]
    assert should_nudge_now(messages, None, 24, 48, now=NOW) == 0


def test_first_nudge_fires_after_first_threshold():
    messages = [_customer_msg(hours_ago=25)]
    assert should_nudge_now(messages, None, 24, 48, now=NOW) == 1


def test_first_nudge_does_not_fire_before_first_threshold():
    messages = [_customer_msg(hours_ago=23)]
    assert should_nudge_now(messages, None, 24, 48, now=NOW) == 0


def test_second_nudge_fires_after_second_threshold_when_first_already_sent():
    messages = [_customer_msg(hours_ago=49)]
    state = {"count": 1, "last_nudged_at": (NOW - timedelta(hours=25)).isoformat()}
    assert should_nudge_now(messages, state, 24, 48, now=NOW) == 2


def test_second_nudge_does_not_fire_before_second_threshold():
    messages = [_customer_msg(hours_ago=30)]
    state = {"count": 1, "last_nudged_at": (NOW - timedelta(hours=6)).isoformat()}
    assert should_nudge_now(messages, state, 24, 48, now=NOW) == 0


def test_no_third_nudge_after_count_reaches_two():
    messages = [_customer_msg(hours_ago=100)]
    state = {"count": 2, "last_nudged_at": (NOW - timedelta(hours=52)).isoformat()}
    assert should_nudge_now(messages, state, 24, 48, now=NOW) == 0


def test_short_window_test_setting_still_fires():
    """When operator dials window down to 1h for testing, nudge should fire."""
    messages = [_customer_msg(hours_ago=2)]
    assert should_nudge_now(messages, None, first_after_hours=1, second_after_hours=2, now=NOW) == 1


def test_boundary_exactly_at_threshold_fires():
    """At exactly the threshold (>= comparison) the nudge fires."""
    messages = [_customer_msg(hours_ago=24)]
    assert should_nudge_now(messages, None, 24, 48, now=NOW) == 1
