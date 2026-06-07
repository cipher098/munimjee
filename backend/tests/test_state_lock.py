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


@pytest.mark.parametrize("locking_action", ["hold_firm", "show_product"])
def test_awaiting_payment_lock_blocks_state_regression(locking_action):
    """hold_firm and same-product show_product must be neutralized to a no-op once the
    deal is locked — no re-opening on a follow-up. (counter is price-direction-dependent
    now: a downward counter is honored — see test_awaiting_payment_honors_downward_counter
    — while a non-lowering counter is still neutralized.)"""
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
    assert "agreed_price" not in extra
    assert "last_counter_price" not in extra


@pytest.mark.parametrize("modify_action", ["accept", "bulk_discount"])
def test_awaiting_payment_allows_deal_modification(modify_action):
    """accept/bulk_discount are NOT neutralized in awaiting_payment — the customer can
    change the not-yet-paid combo, so the order rebuilds (line prices come from code)."""
    decision = {"action": modify_action, "price": 900_00, "customer_intent": "warm"}
    new_state, _ = _derive_state_from_decision(
        decision,
        _conv(),
        _product(),
        effective_negotiation_round=3,
        effective_last_counter_price=1100_00,
        current_state="awaiting_payment",
    )
    assert new_state == "awaiting_payment"


def test_awaiting_payment_honors_downward_counter():
    """A counter BELOW the locked price in awaiting_payment is a genuine further discount —
    it's rewritten to an accept at the new (floor-safe) price so the order rebuilds DOWN.
    Fixes: bot said '1100 final' but kept charging the locked 1150."""
    decision = {"action": "counter", "price": 1100_00, "customer_intent": "warm"}
    new_state, extra = _derive_state_from_decision(
        decision,
        _conv(),
        _product(listed=1200_00, floor=1000_00),
        effective_negotiation_round=3,
        effective_last_counter_price=1150_00,
        current_state="awaiting_payment",
    )
    assert new_state == "awaiting_payment"
    assert decision["action"] == "accept"
    assert extra["agreed_price"] == 1100_00


def test_awaiting_payment_neutralizes_non_lowering_counter():
    """A counter at/above the locked price in awaiting_payment is still neutralized —
    the deal can't be re-opened upward by a stray counter."""
    decision = {"action": "counter", "price": 1200_00, "customer_intent": "warm"}
    new_state, _ = _derive_state_from_decision(
        decision, _conv(), _product(listed=1200_00, floor=1000_00),
        effective_negotiation_round=3,
        effective_last_counter_price=1150_00,
        current_state="awaiting_payment",
    )
    assert new_state is None  # neutralized, stays locked


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
