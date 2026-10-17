"""Worker lifecycle checks with fake sessions; no DB, Redis, LLM or sends."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.workers import instagram_ingress as worker
from app.workers import message_batch


def result(rows):
    value = MagicMock()
    value.scalars.return_value.all.return_value = rows
    value.all.return_value = rows
    return value


def receipt():
    return SimpleNamespace(id=uuid4(), seller_id=uuid4(), status="processing", events=[{"type": "text", "text": "hello"}])


@pytest.mark.asyncio
async def test_success_uses_existing_writer_and_completes_in_same_transaction(monkeypatch):
    row = receipt()
    seller = SimpleNamespace(id=row.seller_id)
    db = SimpleNamespace(execute=AsyncMock(side_effect=[result([row]), result([seller])]))
    boundaries = []

    @asynccontextmanager
    async def session():
        yield db
        boundaries.append(row.status)

    consume = AsyncMock()
    monkeypatch.setattr(worker, "worker_session", session)
    monkeypatch.setattr(worker, "_claim", AsyncMock(return_value=[row.id]))
    monkeypatch.setattr(message_batch, "_consume_events", consume)
    await worker._process_thread(row.seller_id, "account", "customer")
    consume.assert_awaited_once_with(db, seller, "customer", row.events)
    assert row.status == "completed"
    assert boundaries == ["completed"]


@pytest.mark.asyncio
async def test_possible_send_failure_retained_as_error_without_automatic_replay(monkeypatch):
    row = receipt()
    seller = SimpleNamespace(id=row.seller_id)
    db = SimpleNamespace(execute=AsyncMock(side_effect=[result([row]), result([seller]), result([row])]))

    @asynccontextmanager
    async def session():
        yield db

    consume = AsyncMock(side_effect=RuntimeError("provider operation may have happened"))
    monkeypatch.setattr(worker, "worker_session", session)
    monkeypatch.setattr(worker, "_claim", AsyncMock(return_value=[row.id]))
    monkeypatch.setattr(message_batch, "_consume_events", consume)
    await worker._process_thread(row.seller_id, "account", "customer")
    assert row.status == "error"
    assert row.error_code == "processing_failed_unknown_effect"
    assert consume.await_count == 1


@pytest.mark.asyncio
async def test_account_reassignment_never_invokes_writer(monkeypatch):
    row = receipt()
    db = SimpleNamespace(execute=AsyncMock(side_effect=[result([row]), result([SimpleNamespace(id=uuid4())])]))

    @asynccontextmanager
    async def session():
        yield db

    consume = AsyncMock()
    monkeypatch.setattr(worker, "worker_session", session)
    monkeypatch.setattr(worker, "_claim", AsyncMock(return_value=[row.id]))
    monkeypatch.setattr(message_batch, "_consume_events", consume)
    await worker._process_thread(row.seller_id, "account", "customer")
    consume.assert_not_awaited()
    assert row.error_code == "instagram_account_binding_changed"


@pytest.mark.asyncio
async def test_recovery_retains_interrupted_work_and_wakes_pending_after_commit(monkeypatch):
    row = receipt()
    db = SimpleNamespace(execute=AsyncMock(side_effect=[result([row]), result([(row.seller_id, "account", "customer")])]))
    committed = []

    @asynccontextmanager
    async def session():
        yield db
        committed.append(True)

    def dispatch(*, args):
        assert committed == [True]
        assert args == [str(row.seller_id), "account", "customer"]
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(worker, "worker_session", session)
    monkeypatch.setattr(worker.process_instagram_ingress, "apply_async", dispatch)
    await worker._recover()
    assert row.status == "error"
    assert row.error_code == "processing_interrupted_unknown_effect"
    assert "SKIP LOCKED" in str(db.execute.call_args_list[0].args[0].compile(dialect=postgresql.dialect()))


@pytest.mark.asyncio
async def test_new_pending_message_extends_silence_window(monkeypatch):
    db = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock(side_effect=[None, datetime.now(timezone.utc) + timedelta(seconds=20)]))

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(worker, "worker_session", session)
    assert await worker._claim(uuid4(), "account", "customer") == []
    # Only thread-lock SQL executes; no receipt can be claimed before due.
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_existing_processing_batch_prevents_second_claim(monkeypatch):
    db = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock(return_value=uuid4()))

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(worker, "worker_session", session)
    assert await worker._claim(uuid4(), "account", "customer") == []
    assert db.scalar.await_count == 1
