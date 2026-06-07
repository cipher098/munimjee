"""Tests for the generic OpenAI-compatible provider (used for Gemini).

No real HTTP — httpx.AsyncClient is faked. Covers URL normalization, content
parsing, empty-content failure (so the factory falls back), missing-key guard,
and that decide/generate_reply go through the shared builders + reply cleanup.
"""
from __future__ import annotations

import pytest

from app.integrations import openai_compat
from app.integrations._json_utils import LLMOutputParseError
from app.integrations.openai_compat import OpenAICompatClient


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient; returns a queued payload from post()."""
    payload = {"choices": [{"message": {"content": "hi ji"}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 10, "completion_tokens": 3}}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        return _FakeResp(type(self).payload)


@pytest.fixture(autouse=True)
def _fake_httpx(monkeypatch):
    monkeypatch.setattr(openai_compat.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.payload = {
        "choices": [{"message": {"content": "hi ji"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3},
    }


def test_url_normalization():
    a = OpenAICompatClient("gemini", "https://x.ai/v1", "k")
    b = OpenAICompatClient("gemini", "https://x.ai/v1/chat/completions", "k")
    c = OpenAICompatClient("gemini", "https://x.ai/v1/", "k")
    assert a._url == "https://x.ai/v1/chat/completions"
    assert b._url == "https://x.ai/v1/chat/completions"
    assert c._url == "https://x.ai/v1/chat/completions"


@pytest.mark.asyncio
async def test_chat_returns_content():
    client = OpenAICompatClient("gemini", "https://x.ai/v1", "key")
    out = await client._chat(model="m", max_tokens=50, system="s", user="u")
    assert out == "hi ji"


@pytest.mark.asyncio
async def test_chat_missing_key_raises():
    client = OpenAICompatClient("gemini", "https://x.ai/v1", "")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        await client._chat(model="m", max_tokens=50, system="s", user="u")


@pytest.mark.asyncio
async def test_chat_empty_content_raises_parse_error():
    _FakeAsyncClient.payload = {
        "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 0},
    }
    client = OpenAICompatClient("gemini", "https://x.ai/v1", "key")
    with pytest.raises(LLMOutputParseError):
        await client._chat(model="m", max_tokens=50, system="s", user="u")


@pytest.mark.asyncio
async def test_decide_parses_json(monkeypatch):
    _FakeAsyncClient.payload = {
        "choices": [{"message": {"content": '{"action":"counter","price":150000}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 8},
    }

    async def fake_build_decide(ctx):
        return "DECIDE PROMPT"
    monkeypatch.setattr(openai_compat, "build_decide_prompt", fake_build_decide)
    monkeypatch.setattr(openai_compat, "evaluate_interventions", lambda ctx: "")

    client = OpenAICompatClient("gemini", "https://x.ai/v1", "key")
    out = await client.decide({"customer_message": "1500", "message_history": []}, model="m", max_tokens=350)
    assert out == {"action": "counter", "price": 150000}


@pytest.mark.asyncio
async def test_generate_reply_uses_builder_and_cleans(monkeypatch):
    _FakeAsyncClient.payload = {
        "choices": [{"message": {"content": '"namaste ji"'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3},
    }

    async def fake_build_reply(ctx):
        return "REPLY PROMPT"
    monkeypatch.setattr(openai_compat, "build_reply_prompt", fake_build_reply)

    client = OpenAICompatClient("gemini", "https://x.ai/v1", "key")
    out = await client.generate_reply(
        {"decision": {"action": "engage"}, "customer_message": "hi", "message_history": []},
        model="m", max_tokens=200,
    )
    assert out == "namaste ji"  # surrounding quotes stripped by _clean_reply_text
