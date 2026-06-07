"""Tests for the sticky awaiting_payment state guard in _derive_state_from_decision.

Regression test for the bug where the bot agreed at ₹1100 (state moved to
awaiting_payment), then on a follow-up question the model picked hold_firm
and the state derivation reset the conv_product back to negotiating —
losing the locked deal.
"""
from types import SimpleNamespace

import pytest

from app.bot.responder import _derive_state_from_decision


def _product(listed=1200_00, floor=1100_00):
    return SimpleNamespace(id="p1", name="clock", listed_price=listed, floor_price=floor)


def _conv():
    return SimpleNamespace(id="c1", product_id="p1")


@pytest.mark.parametrize("locking_action", ["hold_firm", "counter", "accept", "bulk_discount", "show_product"])
def test_awaiting_payment_lock_blocks_state_regression(locking_action):
    """Any action that would normally transition out of awaiting_payment must
    be neutralized to a no-op state change once the deal is locked."""
    decision = {"action": locking_action, "price": 900_00, "customer_intent": "warm"}
    new_state, extra = _derive_state_from_decision(
        decision,
        _conv(),
        _product(),
        effective_negotiation_round=3,
        effective_last_counter_price=1100_00,
        current_state="awaiting_payment",
    )
    assert new_state is None, f"action {locking_action!r} regressed locked state"
    # Crucially, no agreed_price/last_counter_price write — would silently lower the deal.
    assert "agreed_price" not in extra
    assert "last_counter_price" not in extra


def test_awaiting_payment_lock_allows_escalate():
    """Escalation is a legitimate exit from awaiting_payment (manual review)."""
    decision = {"action": "escalate", "customer_intent": "cold"}
    new_state, _ = _derive_state_from_decision(
        decision, _conv(), _product(),
        effective_negotiation_round=3,
        effective_last_counter_price=1100_00,
        current_state="awaiting_payment",
    )
    assert new_state == "manual_review"


def test_awaiting_payment_lock_allows_not_interested():
    """Customer can still cancel the agreed deal."""
    decision = {"action": "not_interested", "customer_intent": "cold"}
    new_state, _ = _derive_state_from_decision(
        decision, _conv(), _product(),
        effective_negotiation_round=3,
        effective_last_counter_price=1100_00,
        current_state="awaiting_payment",
    )
    assert new_state == "not_interested"


def test_awaiting_payment_lock_passes_through_rejected_product_ids():
    """Customer might reject a sibling product mid-payment — the rejection
    metadata should still propagate even if the state is locked."""
    decision = {
        "action": "hold_firm",
        "customer_intent": "warm",
        "rejected_product_ids": ["other-product-uuid"],
    }
    new_state, extra = _derive_state_from_decision(
        decision, _conv(), _product(),
        effective_negotiation_round=3,
        effective_last_counter_price=1100_00,
        current_state="awaiting_payment",
    )
    assert new_state is None
    assert extra.get("rejected_product_ids") == ["other-product-uuid"]


def test_negotiating_hold_firm_still_advances_round():
    """Outside the locked state, hold_firm continues to behave as before:
    state stays at 'negotiating' and the round counter advances by 1."""
    decision = {"action": "hold_firm", "customer_intent": "warm"}
    new_state, extra = _derive_state_from_decision(
        decision, _conv(), _product(),
        effective_negotiation_round=2,
        effective_last_counter_price=None,
        current_state="negotiating",
    )
    assert new_state == "negotiating"
    assert extra.get("negotiation_round") == 3


def test_request_payment_in_awaiting_payment_does_not_lock_out():
    """request_payment is in the safe set — it should pass through and stay
    at awaiting_payment (its own handler returns awaiting_payment)."""
    decision = {"action": "request_payment", "customer_intent": "hot"}
    new_state, _ = _derive_state_from_decision(
        decision, _conv(), _product(),
        effective_negotiation_round=3,
        effective_last_counter_price=1100_00,
        current_state="awaiting_payment",
    )
    assert new_state == "awaiting_payment"
