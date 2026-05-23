"""Test-only hooks for the scenario harness.

Production code calls `record(key=value)` to push observations into the
current turn's record. The hook is a no-op unless a test fixture has
seeded a non-None dict into `LAST_TURN` for the current asyncio task.

Why a contextvar rather than logging:
  - log parsing is fragile; format changes break tests
  - contextvars carry through async boundaries automatically — both
    `claude.decide()` (intervention evaluator) and `responder.generate_bot_reply`
    (action/state/reply) can contribute to the same per-turn record
  - cost in prod: one dict.get() per call. Effectively free.

Test harness usage:
    token = LAST_TURN.set({})
    try:
        await advance_conversation(...)
        record = LAST_TURN.get()
        assert record["action"] == "hold_firm"
    finally:
        LAST_TURN.reset(token)
"""
from __future__ import annotations

import contextvars
from typing import Any

LAST_TURN: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "responder_last_turn", default=None
)


def record(**fields: Any) -> None:
    """Merge `fields` into the current turn's record if a test fixture is listening."""
    current = LAST_TURN.get()
    if current is None:
        return
    current.update(fields)
