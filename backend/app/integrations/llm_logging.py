"""Turn-scoped capture of every LLM call for cost accounting.

Design: a context variable holds the current turn's logging context
(seller / conversation / triggering message id) plus an in-memory list of
records. Low-level clients (`ClaudeClient._create`, `SarvamClient._chat`,
`intent_classifier.classify`) call `record(...)` after each API call; the
record snapshots the current context. The orchestrator brackets a turn with
`begin()` / `persist(db)` / `end(token)`.

Why a contextvar instead of threading args through every method:
  - The providers (claude/sarvam) and the factory don't know the
    conversation/message ids, and the subagent calls don't go through the
    factory at all. A contextvar lets the *outermost* handler set the
    context once and have every nested call attribute itself correctly,
    including calls made inside `asyncio.create_task` (the intent
    classifier) — contextvars are copied into child tasks at creation time.

`record()` is a no-op when no turn is active (e.g. admin/training flows),
and never raises — logging must never break the bot.
"""
from __future__ import annotations

import contextvars
import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class LLMCallRecord:
    provider: str
    model: str
    method: str
    status: str = "success"
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_read_input_tokens: Optional[int] = None
    cache_creation_input_tokens: Optional[int] = None
    request: Any = None
    response: Optional[str] = None
    error: Optional[str] = None
    # context snapshot
    seller_id: Optional[UUID] = None
    conversation_id: Optional[UUID] = None
    conversation_product_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    customer_message_mid: Optional[str] = None


@dataclass
class _TurnContext:
    seller_id: Optional[UUID] = None
    conversation_id: Optional[UUID] = None
    customer_message_mid: Optional[str] = None
    product_id: Optional[UUID] = None
    conversation_product_id: Optional[UUID] = None
    records: list[LLMCallRecord] = field(default_factory=list)


_ctx: contextvars.ContextVar[Optional[_TurnContext]] = contextvars.ContextVar(
    "llm_log_ctx", default=None
)


def begin(
    *,
    seller_id: Optional[UUID] = None,
    conversation_id: Optional[UUID] = None,
    customer_message_mid: Optional[str] = None,
) -> contextvars.Token:
    """Start capturing LLM calls for a turn. Returns a token for `end()`."""
    return _ctx.set(
        _TurnContext(
            seller_id=seller_id,
            conversation_id=conversation_id,
            customer_message_mid=customer_message_mid,
        )
    )


def set_product(
    product_id: Optional[UUID] = None,
    conversation_product_id: Optional[UUID] = None,
) -> None:
    """Attach the resolved product to subsequent records in this turn."""
    ctx = _ctx.get()
    if ctx is None:
        return
    if product_id is not None:
        ctx.product_id = product_id
    if conversation_product_id is not None:
        ctx.conversation_product_id = conversation_product_id


def end(token: contextvars.Token) -> None:
    try:
        _ctx.reset(token)
    except Exception:  # pragma: no cover - defensive
        pass


def _elide_base64(obj: Any) -> Any:
    """Deep-copy a request payload, replacing base64 image bytes with a
    short marker so we don't store megabytes of image data per row."""
    if isinstance(obj, dict):
        new: dict = {}
        for k, v in obj.items():
            if k == "data" and isinstance(v, str) and len(v) > 256:
                new[k] = f"<base64 elided: {len(v)} chars>"
            else:
                new[k] = _elide_base64(v)
        return new
    if isinstance(obj, list):
        return [_elide_base64(x) for x in obj]
    return obj


def record(
    provider: str,
    model: str,
    method: Optional[str],
    *,
    status: str = "success",
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    cache_read_input_tokens: Optional[int] = None,
    cache_creation_input_tokens: Optional[int] = None,
    request: Any = None,
    response: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Append a record to the active turn. No-op outside a turn; never raises."""
    ctx = _ctx.get()
    if ctx is None:
        return
    try:
        safe_request = _elide_base64(copy.deepcopy(request)) if request is not None else None
        ctx.records.append(
            LLMCallRecord(
                provider=provider,
                model=model,
                method=method or "unknown",
                status=status,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
                cache_creation_input_tokens=cache_creation_input_tokens,
                request=safe_request,
                response=response,
                error=error,
                seller_id=ctx.seller_id,
                conversation_id=ctx.conversation_id,
                conversation_product_id=ctx.conversation_product_id,
                product_id=ctx.product_id,
                customer_message_mid=ctx.customer_message_mid,
            )
        )
    except Exception:  # pragma: no cover - logging must not break the bot
        logger.exception("llm_logging.record failed")


async def persist(db) -> int:
    """Flush captured records into llm_call_logs via the given session.

    Rows are added to the session (not committed) so they ride the caller's
    transaction and stay atomic with the conversation update. Cost is
    computed from pricing.yaml at write time. Returns the number of rows.
    """
    ctx = _ctx.get()
    if ctx is None or not ctx.records:
        return 0

    # Lazy imports keep this module free of model/DB import cycles.
    from app.integrations.llm_pricing import compute_cost_usd
    from app.models.llm_call_log import LLMCallLog

    rows = []
    for r in ctx.records:
        cost = compute_cost_usd(
            r.model,
            r.input_tokens,
            r.output_tokens,
            r.cache_read_input_tokens,
            r.cache_creation_input_tokens,
        )
        rows.append(
            LLMCallLog(
                seller_id=r.seller_id,
                conversation_id=r.conversation_id,
                conversation_product_id=r.conversation_product_id,
                product_id=r.product_id,
                customer_message_mid=r.customer_message_mid,
                method=r.method,
                provider=r.provider,
                model=r.model,
                status=r.status,
                input_tokens=r.input_tokens,
                output_tokens=r.output_tokens,
                cache_read_input_tokens=r.cache_read_input_tokens,
                cache_creation_input_tokens=r.cache_creation_input_tokens,
                cost_usd=cost,
                request=r.request,
                response=r.response,
                error=r.error,
            )
        )
    db.add_all(rows)
    count = len(rows)
    ctx.records.clear()
    return count
