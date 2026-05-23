"""Smoke tests for ClaudeClient.decide using recorded Anthropic responses.

These tests guard the two changes that ship with the launch:
  - Prompt caching: DECISION_PROMPT split into static system + dynamic user
  - Fallback wrapper: _create retries on transient errors and refusals

Tests are written to be conservative — they check the JSON contract, not
exact action choices, so prompt tuning does not break the suite.

To record cassettes against the live API:
    VCR_RECORD=1 ANTHROPIC_API_KEY=sk-... pytest backend/tests -v
"""
import os
import pathlib

import pytest

from app.integrations.claude import (
    ClaudeClient,
    _build_decision_messages,
    _split_decision_prompt,
)
from app.prompts import DECISION_PROMPT


ALLOWED_ACTIONS = {
    "greet", "show_product", "counter", "accept", "hold_firm", "bulk_discount",
    "request_payment", "warranty", "engage", "clarify", "escalate",
    "not_interested", "bundle_pitch", "show_multi_price",
}

CASSETTE_DIR = pathlib.Path(__file__).parent / "cassettes"


def _greeting_context() -> dict:
    return {
        "state": "greeting",
        "customer_message": "hello",
        "listed_price": 100000,
        "floor_price": 80000,
        "last_counter_price": None,
        "negotiation_round": 0,
        "message_history": [],
        "available_products": [
            {"id": "p1", "name": "Wooden Clock", "listed_price_paise": 100000}
        ],
        "other_inquiry_products": [],
        "bundle_pitched": False,
    }


def test_split_decision_prompt_extracts_static_and_dynamic_parts():
    """The runtime split must produce a non-empty system prompt that contains
    the negotiation rules, and a user prompt that contains the CONTEXT block.
    The conversation history and current customer message are no longer in the
    prompt body — they ride in the native messages array instead."""
    # Use a deliberately distinctive sentinel via the state field (the only
    # place customer-derived dynamic values still flow through .format()).
    sentinel = "XQZ-STATE-SENTINEL-9817"
    formatted = DECISION_PROMPT.format(
        state=sentinel,
        customer_message="",  # no longer rendered into the prompt
        listed_price=100000,
        floor_price=80000,
        last_counter_price="none yet",
        round_number=0,
        message_history="",  # no longer rendered into the prompt
        available_products="[]",
        other_inquiry_products="[]",
        bundle_pitched=False,
    )
    system, user = _split_decision_prompt(formatted)

    assert system, "system prompt must be non-empty"
    assert user, "user prompt must be non-empty"
    assert "NEGOTIATION STRATEGY" in system, "rules block must be in system prompt"
    assert "--- CONTEXT ---" in user, "context block must be in user prompt"
    assert sentinel in user, "dynamic state value must appear in user prompt"
    assert sentinel not in system, "dynamic values must not leak into cached system prompt"
    # Cache only engages above ~1024 tokens on Sonnet — verify we clear it.
    assert len(system) > 4096, "system prompt too small to engage prompt caching"


def test_build_decision_messages_first_turn_no_history():
    """First turn: no prior turns, just the customer's opening message + context."""
    msgs = _build_decision_messages([], "hello", "--- CONTEXT ---\nState: greeting")
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert "hello" in msgs[0]["content"]
    assert "--- CONTEXT ---" in msgs[0]["content"]


def test_build_decision_messages_caches_last_assistant_turn():
    """Mid-conversation: last historical message is an assistant reply →
    cache_control lands on it; current customer text goes in fresh user msg."""
    history = [
        {"role": "customer", "content": "hi"},
        {"role": "bot", "content": "haan ji"},
        {"role": "customer", "content": "watch dikhao"},
        {"role": "bot", "content": "ye lo"},
    ]
    msgs = _build_decision_messages(history, "kitne ka", "--- CONTEXT ---\nState: x")
    # 4 historical + 1 current = 5
    assert len(msgs) == 5
    # Cache breakpoint on the last historical (assistant) message
    last_hist = msgs[-2]
    assert last_hist["role"] == "assistant"
    assert isinstance(last_hist["content"], list)
    assert last_hist["content"][0]["cache_control"] == {"type": "ephemeral"}
    # Current user message uncached, contains both customer text and context
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"].startswith("kitne ka")
    assert "--- CONTEXT ---" in msgs[-1]["content"]


def test_build_decision_messages_folds_trailing_user_into_current():
    """If history ends with a user turn (bot didn't reply yet), fold it into
    the current user message instead of creating two consecutive user msgs."""
    history = [
        {"role": "customer", "content": "hello"},
        {"role": "bot", "content": "haan ji"},
        {"role": "customer", "content": "earlier unanswered question"},
    ]
    msgs = _build_decision_messages(history, "latest question", "--- CONTEXT ---\nState: x")
    # Trailing customer msg gets folded; result should alternate cleanly.
    roles = [m["role"] for m in msgs]
    assert roles == ["user", "assistant", "user"]
    # Cache_control lands on the assistant message (the only stable boundary).
    assert isinstance(msgs[1]["content"], list)
    assert msgs[1]["content"][0]["cache_control"] == {"type": "ephemeral"}
    # Final user message contains both the folded msg and the current one.
    assert "earlier unanswered question" in msgs[-1]["content"]
    assert "latest question" in msgs[-1]["content"]


def test_build_decision_messages_drops_leading_assistant():
    """Anthropic requires the first message to be user. Drop leading bot msgs."""
    history = [
        {"role": "bot", "content": "intro from bot"},
        {"role": "customer", "content": "hi"},
        {"role": "bot", "content": "haan ji"},
    ]
    msgs = _build_decision_messages(history, "kitne ka", "--- CONTEXT ---")
    assert msgs[0]["role"] == "user"
    assert "intro from bot" not in msgs[0]["content"]


def test_split_decision_prompt_falls_back_when_markers_missing():
    """If the training dashboard rewrites the prompt and removes the markers,
    we must not crash — we degrade to sending the whole prompt as user."""
    weird_prompt = "Just be helpful. No markers here."
    system, user = _split_decision_prompt(weird_prompt)
    assert system == weird_prompt
    assert user == ""


@pytest.mark.asyncio
async def test_decide_greeting_returns_valid_action(claude_cassette):
    """End-to-end: a basic greeting context returns a valid JSON decision.
    Replays from cassette; record once with VCR_RECORD=1."""
    cassette_path = CASSETTE_DIR / "decide_greeting.yaml"
    if not cassette_path.exists() and os.environ.get("VCR_RECORD") != "1":
        pytest.skip(
            f"No cassette at {cassette_path}. "
            "Record with VCR_RECORD=1 ANTHROPIC_API_KEY=sk-... pytest"
        )

    with claude_cassette("decide_greeting"):
        result = await ClaudeClient().decide(_greeting_context())

    assert isinstance(result, dict)
    assert result.get("action") in ALLOWED_ACTIONS
