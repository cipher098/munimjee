"""Disposable PostgreSQL integration tests; explicit allocated test URL required.

Creates/drops ONLY a randomly named schema in the coordinator-allocated database.
No runtime.env, provider connections, Redis connections or live sends are used.
"""
import importlib.util
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.conversation import Conversation
from app.models.instagram_ingress import InstagramIngress
from app.models.seller import Seller
from app.services.instagram_ingress import persist_message, replay_receipt
from app.workers import instagram_ingress as worker
from app.workers import message_batch

ALLOCATED_URL = "postgresql+asyncpg://v1test:v1test-only@127.0.0.1:55441/v1_social_commerce_test"


@pytest_asyncio.fixture
async def sessions(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL")
    if url is None:
        pytest.skip("TEST_DATABASE_URL not explicitly set; no DB accessed")
    if url != ALLOCATED_URL or os.environ.get("DATABASE_URL") != ALLOCATED_URL:
        pytest.fail("Refusing DB access: both URLs must exactly match the coordinator-allocated disposable DB")
    schema = "test_ig_ingress_" + uuid4().hex
    admin = create_async_engine(url)
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.begin() as connection:
            # Exercise the actual new migration over a baseline ORM schema;
            # the integrator separately verifies the complete 0040/0041 chain.
            await connection.run_sync(lambda sync: Base.metadata.create_all(
                sync, tables=[table for table in Base.metadata.sorted_tables if table.name != "instagram_ingress"],
            ))
            spec = importlib.util.spec_from_file_location("migration_0042", Path(__file__).parents[1] / "alembic/versions/0042_instagram_ingress.py")
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)

            def upgrade(sync):
                with Operations.context(MigrationContext.configure(sync)):
                    migration.upgrade()
            await connection.run_sync(upgrade)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        @asynccontextmanager
        async def session():
            async with factory() as db:
                try:
                    yield db
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise

        monkeypatch.setattr(worker, "worker_session", session)
        yield session
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


def event(mid="m1", customer="customer", account="account"):
    return {"sender": {"id": customer}, "recipient": {"id": account},
            "timestamp": 123456, "message": {"mid": mid, "text": "price?"}, "seller_id": str(uuid4())}


async def seed(sessions):
    async with sessions() as db:
        seller = Seller(email="synthetic@example.invalid", password_hash="not-used", instagram_page_id="account", is_active=True)
        db.add(seller)
        await db.flush()
        return seller.id


async def receive(sessions, item=None):
    async with sessions() as db:
        return await persist_message(db, item or event())


async def make_due(sessions):
    async with sessions() as db:
        rows = (await db.execute(select(InstagramIngress))).scalars().all()
        for row in rows:
            row.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)


@pytest.mark.asyncio
async def test_migrated_schema_commit_and_duplicate_delivery(sessions):
    seller_id = await seed(sessions)
    first = await receive(sessions)
    second = await receive(sessions)
    async with sessions() as db:
        rows = (await db.execute(select(InstagramIngress))).scalars().all()
        assert len(rows) == 1
        assert first.id == second.id == rows[0].id
        assert rows[0].seller_id == seller_id
        assert rows[0].status == "pending"


@pytest.mark.asyncio
async def test_webhook_wake_failure_still_acknowledges_committed_receipt(sessions, monkeypatch):
    from app.api.webhooks.instagram import _handle_messaging_event
    await seed(sessions)

    def unavailable(*args, **kwargs):
        raise RuntimeError("synthetic broker outage")

    monkeypatch.setattr(worker.process_instagram_ingress, "apply_async", unavailable)
    async with sessions() as db:
        await _handle_messaging_event(event(), db)
        # Read through an independent session while the webhook session is open.
        async with sessions() as other:
            row = await other.scalar(select(InstagramIngress))
            assert row is not None and row.status == "pending"


@pytest.mark.asyncio
async def test_recovery_processes_accepted_receipt_without_original_wake(sessions, monkeypatch):
    seller_id = await seed(sessions)
    receipt = await receive(sessions)
    await make_due(sessions)
    wakes = []
    monkeypatch.setattr(worker.process_instagram_ingress, "apply_async", lambda *, args: wakes.append(args))
    await worker._recover()
    assert wakes == [[str(seller_id), "account", "customer"]]
    consume = AsyncMock()
    monkeypatch.setattr(message_batch, "_consume_events", consume)
    await worker._process_thread(seller_id, "account", "customer")
    await worker._process_thread(seller_id, "account", "customer")
    assert consume.await_count == 1
    async with sessions() as db:
        row = await db.get(InstagramIngress, receipt.id)
        assert row.status == "completed" and row.attempts == 1


@pytest.mark.asyncio
async def test_claim_survives_crash_and_requires_review_before_replay(sessions, monkeypatch):
    seller_id = await seed(sessions)
    receipt = await receive(sessions)
    await make_due(sessions)
    assert await worker._claim(seller_id, "account", "customer") == [receipt.id]
    assert await worker._claim(seller_id, "account", "customer") == []
    async with sessions() as db:
        row = await db.get(InstagramIngress, receipt.id)
        row.started_at = datetime.now(timezone.utc) - timedelta(hours=1)
    monkeypatch.setattr(worker.process_instagram_ingress, "apply_async", lambda **kwargs: pytest.fail("unknown effect must not auto-replay"))
    await worker._recover()
    async with sessions() as db:
        row = await db.get(InstagramIngress, receipt.id)
        assert row.status == "error" and row.error_code == "processing_interrupted_unknown_effect"
        with pytest.raises(ValueError, match="side_effect_review_required"):
            await replay_receipt(db, receipt.id, seller_id)
        assert await replay_receipt(db, receipt.id, seller_id, side_effects_reviewed=True)
    async with sessions() as db:
        assert (await db.get(InstagramIngress, receipt.id)).status == "retry"


@pytest.mark.asyncio
async def test_failed_writer_rolls_back_history_but_keeps_unknown_effect_error(sessions, monkeypatch):
    seller_id = await seed(sessions)
    receipt = await receive(sessions)
    await make_due(sessions)

    async def uncertain(db, seller, customer_id, events):
        db.add(Conversation(seller_id=seller.id, customer_instagram_id=customer_id, messages=[{"role": "bot", "content": "synthetic"}]))
        await db.flush()
        raise RuntimeError("synthetic external send may have succeeded")

    monkeypatch.setattr(message_batch, "_consume_events", uncertain)
    await worker._process_thread(seller_id, "account", "customer")
    async with sessions() as db:
        assert await db.scalar(select(Conversation)) is None
        row = await db.get(InstagramIngress, receipt.id)
        assert row.status == "error" and row.error_code == "processing_failed_unknown_effect"


@pytest.mark.asyncio
async def test_reassigned_provider_account_cannot_deliver_to_another_seller(sessions, monkeypatch):
    seller_id = await seed(sessions)
    receipt = await receive(sessions)
    await make_due(sessions)
    async with sessions() as db:
        seller = await db.get(Seller, seller_id)
        seller.instagram_page_id = None
        db.add(Seller(email="other@example.invalid", password_hash="not-used", instagram_page_id="account", is_active=True))
    consume = AsyncMock()
    monkeypatch.setattr(message_batch, "_consume_events", consume)
    await worker._process_thread(seller_id, "account", "customer")
    consume.assert_not_awaited()
    async with sessions() as db:
        row = await db.get(InstagramIngress, receipt.id)
        assert row.seller_id == seller_id and row.error_code == "instagram_account_binding_changed"


@pytest.mark.asyncio
async def test_concurrent_duplicate_receipts_have_one_persisted_identity(sessions):
    import asyncio
    await seed(sessions)
    receipts = await asyncio.gather(receive(sessions), receive(sessions))
    assert receipts[0].id == receipts[1].id
    async with sessions() as db:
        assert len((await db.execute(select(InstagramIngress))).scalars().all()) == 1


@pytest.mark.asyncio
async def test_concurrent_worker_wakes_invoke_existing_writer_once(sessions, monkeypatch):
    import asyncio
    seller_id = await seed(sessions)
    await receive(sessions)
    await make_due(sessions)
    consume = AsyncMock()
    monkeypatch.setattr(message_batch, "_consume_events", consume)
    await asyncio.gather(worker._process_thread(seller_id, "account", "customer"),
                         worker._process_thread(seller_id, "account", "customer"))
    assert consume.await_count == 1


@pytest.mark.asyncio
async def test_recovery_skips_locked_live_processing_then_recovers_after_release(sessions, monkeypatch):
    seller_id = await seed(sessions)
    receipt = await receive(sessions)
    await make_due(sessions)
    await worker._claim(seller_id, "account", "customer")
    async with sessions() as db:
        row = await db.get(InstagramIngress, receipt.id)
        row.started_at = datetime.now(timezone.utc) - timedelta(hours=1)
    monkeypatch.setattr(worker.process_instagram_ingress, "apply_async", lambda **kwargs: None)
    async with sessions() as live:
        row = await live.scalar(select(InstagramIngress).where(InstagramIngress.id == receipt.id).with_for_update())
        await worker._recover()
        async with sessions() as other:
            assert (await other.get(InstagramIngress, receipt.id)).status == "processing"
    await worker._recover()
    async with sessions() as db:
        assert (await db.get(InstagramIngress, receipt.id)).status == "error"


@pytest.mark.asyncio
async def test_real_shared_processor_preserves_manual_takeover_without_sends(sessions, monkeypatch):
    seller_id = await seed(sessions)
    async with sessions() as db:
        db.add(Conversation(seller_id=seller_id, customer_instagram_id="customer", customer_name="Synthetic",
                            messages=[], last_seller_manual_reply_at=datetime.now(timezone.utc)))
    await receive(sessions, event("m1"))
    await receive(sessions, event("m2"))
    await make_due(sessions)
    # Only the terminal LLM/send phase is stubbed. Durable worker calls the real
    # shared processor including its advisory lock and takeover policy gates.
    send_phase = AsyncMock()
    monkeypatch.setattr(message_batch, "_process_events", send_phase)
    await worker._process_thread(seller_id, "account", "customer")
    send_phase.assert_not_awaited()
    async with sessions() as db:
        conversation = await db.scalar(select(Conversation))
        assert {item["mid"] for item in conversation.messages} == {"m1", "m2"}
        assert all(row.status == "completed" for row in (await db.execute(select(InstagramIngress))).scalars().all())
