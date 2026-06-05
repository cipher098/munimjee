"""Capture every LLM method invocation the bot makes, with its inputs + output.

`recording()` swaps each registered provider for a thin wrapper that delegates
to the real provider and appends a record per call. decide/generate_reply
capture the structured `context` (re-invokable with a different prompt/model —
that's what makes teacher-forced replay + tuning work); subagent calls that go
through complete_text/complete_vision capture their rendered inputs + output
(enough to SCORE; full subagent tuning needs structured-input capture — a
follow-up noted in DESIGN.md).

Records are plain dicts:
  {"method", "context"|"inputs", "output", "model"}
"""
from __future__ import annotations

import contextlib
import copy

from app.integrations.llm_provider import LLMProvider


class RecordingProvider(LLMProvider):
    def __init__(self, inner: LLMProvider, sink: list) -> None:
        self._inner = inner
        self.name = inner.name
        self._sink = sink

    async def decide(self, context: dict, *, model: str, max_tokens: int) -> dict:
        out = await self._inner.decide(context, model=model, max_tokens=max_tokens)
        self._sink.append({
            "method": "decide", "context": copy.deepcopy(context),
            "output": copy.deepcopy(out), "model": model,
        })
        return out

    async def generate_reply(self, context: dict, *, model: str, max_tokens: int) -> str:
        out = await self._inner.generate_reply(context, model=model, max_tokens=max_tokens)
        self._sink.append({
            "method": "generate_reply", "context": copy.deepcopy(context),
            "output": out, "model": model,
        })
        return out

    async def complete_text(self, *, system: str, user: str, model: str,
                            max_tokens: int, log_method: str | None = None) -> str:
        out = await self._inner.complete_text(
            system=system, user=user, model=model, max_tokens=max_tokens, log_method=log_method)
        self._sink.append({
            "method": log_method or "complete_text",
            "inputs": {"system": system, "user": user}, "output": out, "model": model,
        })
        return out

    async def complete_vision(self, *, prompt: str, image: dict, model: str,
                              max_tokens: int, log_method: str | None = None) -> str:
        out = await self._inner.complete_vision(
            prompt=prompt, image=image, model=model, max_tokens=max_tokens, log_method=log_method)
        self._sink.append({
            "method": log_method or "complete_vision",
            "inputs": {"prompt": prompt}, "output": out, "model": model,
        })
        return out


@contextlib.contextmanager
def recording():
    """Wrap every registered provider so calls are captured. Yields the record
    list (populated as the bot runs); restores the registry on exit."""
    from app.integrations import llm_provider as lp
    lp._ensure_providers_registered()
    sink: list = []
    original = dict(lp._PROVIDERS)
    for name, prov in original.items():
        lp._PROVIDERS[name] = RecordingProvider(prov, sink)
    try:
        yield sink
    finally:
        lp._PROVIDERS.clear()
        lp._PROVIDERS.update(original)
