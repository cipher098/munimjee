"""Runtime overrides the harness wraps around the real bot pipeline.

force_opus()       — route EVERY method (decide, reply, all subagents) to
                     claude-opus-4-8 while keeping each method's configured
                     max_tokens. Used for golden generation + judging + tuning.
override_prompts() — serve a tweaked in-memory prompt set during replay/tuning
                     without writing prompts.py or the prompt_store DB.

Both are context managers that restore the originals on exit. They monkeypatch
module attributes the pipeline already reads (`agent_spec.get`,
`prompt_store.get`), so no callsite changes are needed.
"""
from __future__ import annotations

import contextlib
from dataclasses import replace

OPUS_MODEL = "claude-opus-4-8"


@contextlib.contextmanager
def force_opus(model: str = OPUS_MODEL):
    """Force provider=anthropic, model=opus for every method spec (and its
    fallback), preserving per-method max_tokens."""
    from app.bot import agent_spec
    original = agent_spec.get

    def patched(name: str):
        spec = original(name)
        return replace(
            spec, provider="anthropic", model=model,
            fallback_provider="anthropic", fallback_model=model,
        )

    agent_spec.get = patched
    try:
        yield
    finally:
        agent_spec.get = original


@contextlib.contextmanager
def force_model(model: str, provider: str | None = None):
    """Force every method to `model` (and optionally `provider`), keeping each
    method's max_tokens. Used by `test` to evaluate an arbitrary candidate."""
    from app.bot import agent_spec
    original = agent_spec.get

    def patched(name: str):
        spec = original(name)
        return replace(
            spec, provider=(provider or spec.provider), model=model,
            fallback_provider=(provider or spec.provider), fallback_model=model,
        )

    agent_spec.get = patched
    try:
        yield
    finally:
        agent_spec.get = original


@contextlib.contextmanager
def override_prompts(mapping: dict[str, str]):
    """Serve `mapping[name]` for prompt `name` (e.g. 'decide', 'generate_reply',
    'extract_feature_query'); fall through to the real store otherwise."""
    from app.bot import prompt_store
    original = prompt_store.get

    async def patched(name: str) -> str:
        if name in mapping:
            return mapping[name]
        return await original(name)

    prompt_store.get = patched
    try:
        yield
    finally:
        prompt_store.get = original
