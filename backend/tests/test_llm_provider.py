"""Tests for the multi-provider LLM factory.

Covers:
  - resolve_choice picks the app default from agents.yaml when seller has no override.
  - resolve_choice honours per-seller override on decide + reply.
  - resolve_choice IGNORES seller override for subagent methods.
  - resolve_and_call dispatches to the right provider's method.
  - resolve_and_call falls back to fallback_provider/fallback_model on parse failure.
  - resolve_and_call falls back on generic exception too.
  - resolve_and_call re-raises if primary == fallback (no infinite recursion).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.integrations import llm_provider
from app.integrations._json_utils import LLMOutputParseError
from app.integrations.llm_provider import (
    LLMProvider,
    resolve_and_call,
    resolve_choice,
)


@dataclass
class _FakeSeller:
    """Minimal seller stand-in — only the attributes the factory reads."""
    llm_preferences: dict | None = None


# ---------------------------------------------------------------------------
# Helper fake provider — records what was called and what it returned.
# ---------------------------------------------------------------------------

class _FakeProvider(LLMProvider):
    def __init__(self, name: str, *, decide_result=None, reply_result=None,
                 decide_raises=None, reply_raises=None):
        self.name = name
        self.calls: list[tuple[str, dict, str, int]] = []
        self._decide_result = decide_result or {"action": "noop"}
        self._reply_result = reply_result or "hi"
        self._decide_raises = decide_raises
        self._reply_raises = reply_raises

    async def decide(self, context, *, model, max_tokens):
        self.calls.append(("decide", context, model, max_tokens))
        if self._decide_raises:
            raise self._decide_raises
        return self._decide_result

    async def generate_reply(self, context, *, model, max_tokens):
        self.calls.append(("generate_reply", context, model, max_tokens))
        if self._reply_raises:
            raise self._reply_raises
        return self._reply_result


@pytest.fixture(autouse=True)
def _swap_provider_registry(monkeypatch):
    """Replace the global registry with fresh fakes so each test is isolated."""
    monkeypatch.setattr(llm_provider, "_PROVIDERS", {}, raising=False)
    # Block lazy-registration of the real providers — tests control the registry.
    monkeypatch.setattr(llm_provider, "_ensure_providers_registered", lambda: None)
    yield


# ---------------------------------------------------------------------------
# resolve_choice
# ---------------------------------------------------------------------------

def test_resolve_choice_uses_app_default_when_seller_has_no_prefs():
    seller = _FakeSeller(llm_preferences=None)
    provider, model, max_tokens = resolve_choice("decide", seller)
    # agents.yaml decide default is anthropic / claude-sonnet-4-...
    assert provider == "anthropic"
    assert model.startswith("claude-")
    assert max_tokens > 0


def test_resolve_choice_uses_app_default_when_seller_pref_is_for_other_key():
    """Seller overrode reply only — decide should still use app default."""
    seller = _FakeSeller(llm_preferences={"reply": {"provider": "sarvam", "model": "sarvam-m"}})
    provider, model, _ = resolve_choice("decide", seller)
    assert provider == "anthropic"
    assert model.startswith("claude-")


def test_resolve_choice_honours_seller_override_for_decide():
    seller = _FakeSeller(llm_preferences={"decide": {"provider": "sarvam", "model": "sarvam-m"}})
    provider, model, _ = resolve_choice("decide", seller)
    assert provider == "sarvam"
    assert model == "sarvam-m"


def test_resolve_choice_honours_seller_override_for_reply():
    seller = _FakeSeller(llm_preferences={"reply": {"provider": "anthropic", "model": "claude-sonnet-4-20250514"}})
    provider, model, _ = resolve_choice("generate_reply", seller)
    assert provider == "anthropic"
    assert model == "claude-sonnet-4-20250514"


def test_resolve_choice_ignores_seller_override_for_subagent_methods():
    """Subagent methods (intent_classifier, etc.) must NEVER honour seller prefs."""
    seller = _FakeSeller(llm_preferences={
        "decide": {"provider": "sarvam", "model": "sarvam-m"},
        # Even if (hypothetically) a key matched a subagent method, it must be ignored.
    })
    provider, _, _ = resolve_choice("intent_classifier", seller)
    assert provider == "anthropic"  # subagent stays on app default


def test_resolve_choice_works_with_seller_none():
    provider, model, _ = resolve_choice("decide", None)
    assert provider == "anthropic"


# ---------------------------------------------------------------------------
# resolve_and_call dispatch + fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatches_to_resolved_provider_for_decide(monkeypatch):
    fake = _FakeProvider("anthropic", decide_result={"action": "hold_firm"})
    llm_provider.register("anthropic", fake)
    seller = _FakeSeller(llm_preferences=None)
    result = await resolve_and_call("decide", seller, {"x": 1})
    assert result == {"action": "hold_firm"}
    assert fake.calls and fake.calls[0][0] == "decide"
    assert fake.calls[0][1] == {"x": 1}


@pytest.mark.asyncio
async def test_dispatches_to_resolved_provider_for_reply():
    fake = _FakeProvider("anthropic", reply_result="namaste ji")
    llm_provider.register("anthropic", fake)
    seller = _FakeSeller(llm_preferences=None)
    reply = await resolve_and_call("generate_reply", seller, {"y": 2})
    assert reply == "namaste ji"


@pytest.mark.asyncio
async def test_falls_back_on_parse_failure():
    """Primary raises LLMOutputParseError → factory tries fallback."""
    primary = _FakeProvider("sarvam", decide_raises=LLMOutputParseError("bad json"))
    fallback = _FakeProvider("anthropic", decide_result={"action": "ok"})
    llm_provider.register("sarvam", primary)
    llm_provider.register("anthropic", fallback)
    seller = _FakeSeller(llm_preferences={"decide": {"provider": "sarvam", "model": "sarvam-m"}})
    result = await resolve_and_call("decide", seller, {})
    assert result == {"action": "ok"}
    # Both providers should have been called.
    assert any(c[0] == "decide" for c in primary.calls)
    assert any(c[0] == "decide" for c in fallback.calls)


@pytest.mark.asyncio
async def test_falls_back_on_generic_exception():
    primary = _FakeProvider("sarvam", reply_raises=RuntimeError("timeout"))
    fallback = _FakeProvider("anthropic", reply_result="fallback reply")
    llm_provider.register("sarvam", primary)
    llm_provider.register("anthropic", fallback)
    seller = _FakeSeller(llm_preferences={"reply": {"provider": "sarvam", "model": "sarvam-m"}})
    reply = await resolve_and_call("generate_reply", seller, {})
    assert reply == "fallback reply"


@pytest.mark.asyncio
async def test_reraises_when_primary_and_fallback_are_the_same():
    """If the agent spec's fallback matches the primary choice, don't retry —
    just re-raise. Prevents accidental infinite-fallback loops."""
    # decide's app default IS anthropic / claude-sonnet-4-... (matches its own fallback shape
    # at provider granularity). With seller override to anthropic+the fallback model, we
    # expect the call to raise on the second collision.
    only = _FakeProvider("anthropic", decide_raises=RuntimeError("boom"))
    llm_provider.register("anthropic", only)
    seller = _FakeSeller(llm_preferences={
        "decide": {"provider": "anthropic", "model": "claude-3-5-sonnet-20241022"},
    })
    with pytest.raises(RuntimeError, match="boom"):
        await resolve_and_call("decide", seller, {})


def test_resolve_and_call_rejects_non_customer_facing_methods():
    """Subagent methods are not supported by the factory — they call directly."""
    seller = _FakeSeller()
    import asyncio
    with pytest.raises(ValueError, match="only supports decide / generate_reply"):
        asyncio.run(resolve_and_call("intent_classifier", seller, {}))
