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
    return SimpleNamespace(id=uuid4(), seller_id=uuid4(), status="processing", occurred_at=datetime.now(timezone.utc), operator_replay_pending=False, processed_indices=[], events=[{"type": "text", "text": "hello"}])


@pytest.mark.asyncio
async def test_success_uses_existing_writer_and_completes_in_same_transaction(monkeypatch):
    row = receipt()
    seller = SimpleNamespace(id=row.seller_id)
    db = SimpleNamespace(get=AsyncMock(return_value=None), execute=AsyncMock(side_effect=[result([row]), result([seller])]))
    boundaries = []

    @asynccontextmanager
    async def session():
        yield db
        boundaries.append(row.status)

    consume = AsyncMock(return_value={0})
    monkeypatch.setattr(worker, "worker_session", session)
    monkeypatch.setattr(worker, "_claim", AsyncMock(return_value=[row.id]))
    monkeypatch.setattr(message_batch, "_consume_events", consume)
    await worker._process_thread(row.seller_id, "account", "customer")
    consume.assert_awaited_once_with(db, seller, "customer", row.events, owned_receipt_ids=[row.id])
    assert row.status == "completed"
    assert boundaries == ["completed"]


@pytest.mark.asyncio
async def test_possible_send_failure_retained_as_error_without_automatic_replay(monkeypatch):
    row = receipt()
    seller = SimpleNamespace(id=row.seller_id)
    db = SimpleNamespace(get=AsyncMock(return_value=None), execute=AsyncMock(side_effect=[result([row]), result([seller]), result([row])]))

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
    db = SimpleNamespace(get=AsyncMock(return_value=None), execute=AsyncMock(side_effect=[result([row]), result([SimpleNamespace(id=uuid4())])]))

    @asynccontextmanager
    async def session():
        yield db

    consume = AsyncMock(return_value={0})
    monkeypatch.setattr(worker, "worker_session", session)
    monkeypatch.setattr(worker, "_claim", AsyncMock(return_value=[row.id]))
    monkeypatch.setattr(message_batch, "_consume_events", consume)
    await worker._process_thread(row.seller_id, "account", "customer")
    consume.assert_not_awaited()
    assert row.error_code == "instagram_account_binding_changed"


@pytest.mark.asyncio
async def test_recovery_retains_interrupted_work_and_wakes_pending_after_commit(monkeypatch):
    row = receipt()
    db = SimpleNamespace(get=AsyncMock(return_value=None), execute=AsyncMock(side_effect=[result([row]), result([(row.seller_id, "account", "customer")])]))
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
    monkeypatch.setattr(worker, "_recover_legacy_buffers", lambda: None)
    await worker._recover()
    assert row.status == "error"
    assert row.error_code == "processing_interrupted_unknown_effect"
    assert "SKIP LOCKED" in str(db.execute.call_args_list[0].args[0].compile(dialect=postgresql.dialect()))


@pytest.mark.asyncio
async def test_new_pending_message_extends_silence_window(monkeypatch):
    db = SimpleNamespace(get=AsyncMock(return_value=None), execute=AsyncMock(), scalar=AsyncMock(side_effect=[None, None, datetime.now(timezone.utc) + timedelta(seconds=20)]))

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(worker, "worker_session", session)
    assert await worker._claim(uuid4(), "account", "customer") == []
    # Only thread-lock SQL executes; no receipt can be claimed before due.
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_existing_processing_batch_prevents_second_claim(monkeypatch):
    db = SimpleNamespace(get=AsyncMock(return_value=None), execute=AsyncMock(), scalar=AsyncMock(return_value=uuid4()))

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(worker, "worker_session", session)
    assert await worker._claim(uuid4(), "account", "customer") == []
    assert db.scalar.await_count == 1


def test_legacy_recovery_retains_buffer_and_dispatches_transfer_only(monkeypatch):
    persisted = []
    dispatched = []
    fake = SimpleNamespace(scan_iter=lambda **kwargs: iter(["msg_batch:account:customer"]), persist=persisted.append)
    monkeypatch.setattr(message_batch, "_redis", lambda: fake)
    monkeypatch.setattr(message_batch.process_message_batch, "apply_async", lambda *, args: dispatched.append(args))
    worker._recover_legacy_buffers()
    assert persisted == ["msg_batch:account:customer"]
    assert dispatched == [["account", "customer"]]


def test_legacy_trim_compares_prefix_before_deleting_new_events(monkeypatch):
    """Optional isolated Redis check; no key discovery or database reset."""
    import json
    import os
    target = os.environ.get("TEST_REDIS_URL")
    if target is None:
        pytest.skip("Coordinator-allocated TEST_REDIS_URL required")
    if target != "redis://127.0.0.1:56441/3":
        pytest.fail("Refusing Redis access outside exact allocated test namespace")
    import redis
    client = redis.from_url(target, decode_responses=True)
    account = "synthetic_" + uuid4().hex
    key = f"msg_batch:{account}:customer"
    first = {"type": "text", "text": "first", "mid": "first"}
    later = {"type": "text", "text": "later", "mid": "later"}
    monkeypatch.setattr(message_batch, "_redis", lambda: client)
    try:
        client.rpush(key, json.dumps(first))
        message_batch.trim_processed_events(account, "customer", 1, expected_events=[first])
        client.rpush(key, json.dumps(later))
        # A stale concurrent task cannot trim the newly arrived prefix.
        message_batch.trim_processed_events(account, "customer", 1, expected_events=[first])
        assert [json.loads(item) for item in client.lrange(key, 0, -1)] == [later]
    finally:
        client.delete(key)


def test_redis_missing_mid_transfer_ids_survive_retry_and_distinguish_next_buffer(monkeypatch):
    import json
    import os
    target = os.environ.get("TEST_REDIS_URL")
    if target is None:
        pytest.skip("Coordinator-allocated TEST_REDIS_URL required")
    if target != "redis://127.0.0.1:56441/3":
        pytest.fail("Refusing Redis access outside exact allocated test namespace")
    import redis
    client = redis.from_url(target, decode_responses=True)
    account = "synthetic_" + uuid4().hex
    key = f"msg_batch:{account}:customer"
    item = {"type": "text", "text": "same", "mid": None}
    monkeypatch.setattr(message_batch, "_redis", lambda: client)
    try:
        client.rpush(key, json.dumps(item), json.dumps(item))
        client.expire(key, 120)
        first, raw = message_batch._snapshot_legacy_events(account, "customer")
        assert client.ttl(key) == -1
        assert len({event["_legacy_transfer_id"] for event in first}) == 2
        retry, retry_raw = message_batch._snapshot_legacy_events(account, "customer")
        assert retry == first and retry_raw == raw
        message_batch.trim_processed_events(account, "customer", 2, expected_raw=raw)
        client.rpush(key, json.dumps(item))
        following, _ = message_batch._snapshot_legacy_events(account, "customer")
        assert following[0]["_legacy_transfer_id"] not in {event["_legacy_transfer_id"] for event in first}
    finally:
        client.delete(key)
