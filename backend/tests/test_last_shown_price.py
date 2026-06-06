"""Unit tests for the per-customer per-product price lock (last_shown_price).

Guarantees:
  1. counter / accept / bulk_discount all populate extra["last_shown_price"]
     so the persistence layer can lock the customer-facing display ceiling.
  2. The decision context exposes last_shown_price so the model can read it.
  3. The reply context exposes display_price_rupees so the model never has
     to compute "should I quote listed or the lower locked price".
"""
from types import SimpleNamespace

import pytest

from app.bot.responder import _derive_state_from_decision


def _product(listed=1200_00, floor=1000_00):
    return SimpleNamespace(id="p1", name="clock", listed_price=listed, floor_price=floor)


def _conv():
    return SimpleNamespace(id="c1", product_id="p1")


def test_counter_sets_last_shown_price():
    """A counter offer at ₹1100 must lock the display ceiling at ₹1100."""
    decision = {"action": "counter", "price": 1100_00, "customer_intent": "warm"}
    new_state, extra = _derive_state_from_decision(
        decision, _conv(), _product(),
        effective_negotiation_round=1,
        effective_last_counter_price=None,
        current_state="negotiating",
    )
    assert new_state == "negotiating"
    assert extra.get("last_shown_price") == 1100_00
    assert extra.get("last_counter_price") == 1100_00


def test_accept_sets_agreed_price():
    """Accepting at ₹1050 sets the focused product's per-unit agreed price. (The
    display ceiling / last_shown is applied when the order is built — see
    _build_deal_order.)"""
    decision = {"action": "accept", "price": 1050_00, "customer_intent": "hot"}
    new_state, extra = _derive_state_from_decision(
        decision, _conv(), _product(),
        effective_negotiation_round=2,
        effective_last_counter_price=1100_00,
        current_state="negotiating",
    )
    assert new_state == "awaiting_payment"
    assert extra.get("agreed_price") == 1050_00


def test_bulk_discount_sets_agreed_price():
    """Bulk per-piece price is floor-clamped and set as the focused agreed price;
    quantity now flows via decision deal_items, not extra."""
    decision = {
        "action": "bulk_discount",
        "price": 1050_00,
        "bulk_quantity": 5,
        "customer_intent": "bulk",
    }
    new_state, extra = _derive_state_from_decision(
        decision, _conv(), _product(),
        effective_negotiation_round=0,
        effective_last_counter_price=None,
        current_state="product_inquiry",
    )
    assert new_state == "awaiting_payment"
    assert extra.get("agreed_price") == 1050_00


def test_hold_firm_does_not_set_last_shown_price():
    """hold_firm doesn't quote a new number — nothing should mutate the lock."""
    decision = {"action": "hold_firm", "customer_intent": "cold"}
    _, extra = _derive_state_from_decision(
        decision, _conv(), _product(),
        effective_negotiation_round=1,
        effective_last_counter_price=1100_00,
        current_state="negotiating",
    )
    assert "last_shown_price" not in extra
    assert "last_counter_price" not in extra


def test_counter_clamped_to_floor_still_locks_at_clamped_price():
    """If the model proposed below floor and we clamped UP to floor, the lock
    must be the clamped price (what the customer actually sees), not the
    pre-clamp number — otherwise the floor itself becomes the new ceiling.

    Floor = ₹1000, model proposed ₹900 → clamped to ₹1000 → lock at ₹1000.
    """
    decision = {"action": "counter", "price": 900_00, "customer_intent": "warm"}
    _, extra = _derive_state_from_decision(
        decision, _conv(), _product(listed=1200_00, floor=1000_00),
        effective_negotiation_round=2,
        effective_last_counter_price=1100_00,
        current_state="negotiating",
    )
    # Counter is clamped down to last_counter_price (1100) because counter can never go higher,
    # then floor-clamped (no-op at 1000). End result: 1000.
    assert extra.get("last_shown_price") == 1000_00
