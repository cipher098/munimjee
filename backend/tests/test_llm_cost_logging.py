"""Tests for the LLM cost-logging layer.

Covers:
  - compute_cost_usd: priced model math, unpriced model → None, a used
    bucket with a null sub-rate → None, an unused null bucket → ignored.
  - llm_logging: record is a no-op outside a turn; inside a turn it snapshots
    context; set_product updates subsequent records; base64 image data is
    elided from the stored request; records propagate from a child asyncio
    task (the intent-classifier path).
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest

from app.integrations import llm_logging
from app.integrations.llm_pricing import compute_cost_usd


# ---------------------------------------------------------------------------
# Pricing math (reads the real app/pricing.yaml)
# ---------------------------------------------------------------------------

def test_priced_model_computes_cost():
    # claude-sonnet-4: input 3.00/M, output 15.00/M, cache_read 0.30/M
    cost = compute_cost_usd("claude-sonnet-4-20250514", 1000, 500, 2000, 0)
    expected = (
        Decimal(1000) / Decimal(1_000_000) * Decimal("3.00")
        + Decimal(500) / Decimal(1_000_000) * Decimal("15.00")
        + Decimal(2000) / Decimal(1_000_000) * Decimal("0.30")
    )
    assert cost == expected


def test_unknown_model_returns_none():
    assert compute_cost_usd("totally-made-up-model", 100, 100) is None


def test_used_bucket_with_null_rate_returns_none():
    # sarvam-105b is listed but has all sub-rates null in pricing.yaml; a call
    # that used input/output tokens cannot be priced → None.
    assert compute_cost_usd("sarvam-105b", 1000, 500) is None


def test_null_rate_ignored_when_bucket_unused():
    # Zero cache tokens means the null cache rates don't matter — sonnet has
    # real input/output rates, so cost is still computable.
    cost = compute_cost_usd("claude-sonnet-4-20250514", 100, 0, 0, 0)
    assert cost == Decimal(100) / Decimal(1_000_000) * Decimal("3.00")


# ---------------------------------------------------------------------------
# Capture context
# ---------------------------------------------------------------------------

def test_record_is_noop_outside_turn():
    # No begin() — must not raise and must not crash.
    llm_logging.record("anthropic", "claude-x", "decide", input_tokens=10)
    # current context is None, so nothing to assert beyond "didn't raise".


def test_record_snapshots_context():
    conv = uuid4()
    seller = uuid4()
    token = llm_logging.begin(seller_id=seller, conversation_id=conv, customer_message_mid="mid_123")
    try:
        llm_logging.record(
            "sarvam", "sarvam-30b", "generate_reply",
            input_tokens=10, output_tokens=20, request={"x": 1}, response="hi",
        )
        ctx = llm_logging._ctx.get()
        assert len(ctx.records) == 1
        rec = ctx.records[0]
        assert rec.provider == "sarvam"
        assert rec.method == "generate_reply"
        assert rec.conversation_id == conv
        assert rec.seller_id == seller
        assert rec.customer_message_mid == "mid_123"
        assert rec.input_tokens == 10 and rec.output_tokens == 20
    finally:
        llm_logging.end(token)


def test_set_product_applies_to_later_records():
    token = llm_logging.begin(conversation_id=uuid4())
    try:
        llm_logging.record("anthropic", "m", "intent_classifier")  # before product known
        pid = uuid4()
        cpid = uuid4()
        llm_logging.set_product(product_id=pid, conversation_product_id=cpid)
        llm_logging.record("anthropic", "m", "decide")
        ctx = llm_logging._ctx.get()
        assert ctx.records[0].product_id is None
        assert ctx.records[1].product_id == pid
        assert ctx.records[1].conversation_product_id == cpid
    finally:
        llm_logging.end(token)


def test_base64_image_data_is_elided():
    token = llm_logging.begin(conversation_id=uuid4())
    try:
        big = "A" * 5000
        request = {
            "model": "m",
            "messages": [
                {"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "data": big}},
                    {"type": "text", "text": "what is this?"},
                ]}
            ],
        }
        llm_logging.record("anthropic", "m", "describe_product_image", request=request)
        stored = llm_logging._ctx.get().records[0].request
        img = stored["messages"][0]["content"][0]["source"]["data"]
        assert img.startswith("<base64 elided")
        # text is preserved
        assert stored["messages"][0]["content"][1]["text"] == "what is this?"
        # original request object not mutated
        assert request["messages"][0]["content"][0]["source"]["data"] == big
    finally:
        llm_logging.end(token)


@pytest.mark.asyncio
async def test_records_propagate_from_child_task():
    """The intent classifier runs in asyncio.create_task — records made there
    must land in the parent turn's sink (contextvars copy into child tasks)."""
    token = llm_logging.begin(conversation_id=uuid4())
    try:
        async def child():
            llm_logging.record("anthropic", "haiku", "intent_classifier", input_tokens=5)

        # Task created AFTER begin() inherits the context.
        await asyncio.create_task(child())
        ctx = llm_logging._ctx.get()
        assert any(r.method == "intent_classifier" for r in ctx.records)
    finally:
        llm_logging.end(token)
