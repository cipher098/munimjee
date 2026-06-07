"""Post-payment change detection that escalates to the seller's manual-action queue."""
import pytest

from app.workers.message_batch import post_order_change_kind


@pytest.mark.parametrize("text,kind", [
    ("mujhe refund chahiye", "refund"),
    ("paise wapas kar do", "refund"),
    ("order cancel kar do please", "cancellation"),
    ("ye cancel karo", "cancellation"),
    ("isko exchange karna hai", "item_change"),
    ("LED ki jagah gold clock bhej do", "item_change"),
    ("ye wala badal do", "item_change"),
    ("dusra bhej do iske badle", "item_change"),
])
def test_detects_post_order_change(text, kind):
    assert post_order_change_kind(text) == kind


@pytest.mark.parametrize("text", [
    "kitne ka hai",
    "theek hai le lunga",
    "2 piece bhej do",          # plain order, not a change
    "address le lo",
    "",
    None,
])
def test_ignores_normal_messages(text):
    assert post_order_change_kind(text) is None
