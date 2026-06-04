"""Tests for the shared prompt builders that keep Claude and Sarvam in sync.

The Sarvam provider used to carry a drifted copy of the reply prompt missing
~8 context fields (warranty/stock/policy/display_price/price_context/…). These
tests lock in that the single shared builder injects those fields, and that the
transcript renderer + reply cleanup behave.
"""
from __future__ import annotations

import pytest

from app.bot import prompt_builders
from app.bot.prompt_builders import build_decide_prompt, build_reply_prompt, render_transcript
from app.integrations.sarvam import _clean_reply_text
from app.prompts import DECISION_PROMPT, REPLY_PROMPT


@pytest.fixture(autouse=True)
def _stub_prompt_store(monkeypatch):
    """Avoid the DB — resolve prompts to the in-repo constants."""
    async def fake_get(name: str) -> str:
        return {"generate_reply": REPLY_PROMPT, "decide": DECISION_PROMPT}[name]
    monkeypatch.setattr(prompt_builders.prompt_store, "get", fake_get)


def _reply_context() -> dict:
    return {
        "decision": {"action": "counter", "price": 150000, "customer_intent": "warm"},
        "persona": {"tone": "friendly"},
        "product_name": "Gold Clock",
        "product_description": "A gold wall clock",
        "product_tag_values": {"Material": "brass"},
        "listed_price_rupees": 1800,
        "display_price_rupees": 1600,
        "floor_price_rupees": 1400,
        "warranty_months": 12,
        "stock_quantity": 2,
        "policies": {"cod": True, "return_days": 7, "payment_modes": ["upi"]},
        "last_counter_price": 160000,
        "last_shown_price": 160000,
        "total_photos": 3,
        "address_term": "ji",
        "other_active_products": [],
        "other_inquiry_products": [],
        "message_history": [{"role": "customer", "content": "kitna?"}],
    }


# ---------------------------------------------------------------------------
# build_reply_prompt — the fields Sarvam used to be missing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reply_prompt_includes_previously_missing_fields():
    prompt = await build_reply_prompt(_reply_context())
    # price_context (explicit counter instruction) — was implicit in Sarvam
    assert "YOUR COUNTER OFFER IS ₹1500" in prompt
    # warranty — absent from old Sarvam prompt
    assert "12 months" in prompt
    # stock — absent from old Sarvam prompt
    assert "Only 2 left" in prompt
    # policy — absent from old Sarvam prompt
    assert "COD available" in prompt
    assert "7-day returns accepted" in prompt
    # display price (post-discount lock) — Sarvam only had listed price
    assert "₹1600" in prompt


@pytest.mark.asyncio
async def test_reply_prompt_no_price_change_when_no_counter():
    ctx = _reply_context()
    ctx["decision"] = {"action": "engage", "customer_intent": "cold"}
    prompt = await build_reply_prompt(ctx)
    assert "No price change" in prompt


@pytest.mark.asyncio
async def test_decide_prompt_formats_prices_and_state():
    ctx = {
        "state": "negotiating",
        "listed_price": 180000,
        "floor_price": 140000,
        "last_counter_price": 160000,
        "negotiation_round": 2,
        "available_products": [{"id": "x", "name": "Gold Clock"}],
    }
    prompt = await build_decide_prompt(ctx)
    assert "negotiating" in prompt
    assert "160000 paise" in prompt  # last_counter rendered with paise + rupees
    assert "Gold Clock" in prompt


# ---------------------------------------------------------------------------
# render_transcript
# ---------------------------------------------------------------------------

def test_render_transcript_maps_roles():
    history = [
        {"role": "customer", "content": "hi"},
        {"role": "bot", "content": "hello ji"},
        {"role": "seller_manual", "content": "haan bolo"},
    ]
    assert render_transcript(history) == "Customer: hi\nSeller: hello ji\nSeller: haan bolo"


def test_render_transcript_empty():
    assert render_transcript([]) == "(no prior messages)"
    assert render_transcript(None) == "(no prior messages)"


def test_render_transcript_respects_limit_and_skips_blank():
    history = [{"role": "customer", "content": f"m{i}"} for i in range(20)]
    history.append({"role": "bot", "content": "   "})  # blank skipped
    out = render_transcript(history, limit=3)
    # last 3 of the 21 entries: m18, m19, blank(skipped)
    assert "m18" in out and "m19" in out
    assert "m0" not in out


# ---------------------------------------------------------------------------
# _clean_reply_text (Sarvam output cleanup)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ('"namaste ji"', "namaste ji"),
    ("'namaste ji'", "namaste ji"),
    ("Seller: namaste ji", "namaste ji"),
    ("Reply: ₹1500 final", "₹1500 final"),
    ("namaste ji", "namaste ji"),
    ("“namaste”", "namaste"),
])
def test_clean_reply_text(raw, expected):
    assert _clean_reply_text(raw) == expected
