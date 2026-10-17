"""Disposable PostgreSQL integration tests; explicit allocated test URL required.

Uses P01 migrated_engine with its validated disposable lane and held reset lease.
No runtime.env, provider connections, Redis connections or live sends are used.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.conversation import Conversation
from app.models.instagram_ingress import InstagramIngress
from app.models.seller import Seller
from app.services.instagram_ingress import persist_message, replay_receipt
from app.workers import instagram_ingress as worker
from app.workers import message_batch

@pytest_asyncio.fixture
async def sessions(migrated_engine, monkeypatch):
    """Actual Alembic head under the portable P01 test-lane reset lease."""
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False)

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
    consume = AsyncMock(return_value={0})
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

    async def uncertain(db, seller, customer_id, events, **kwargs):
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
    consume = AsyncMock(return_value={0})
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
    consume = AsyncMock(return_value={0})
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


async def seed_conversation(sessions, seller_id, *, state=None, pending=False):
    from app.models.product import Product
    from app.models.conversation_product import ConversationProduct
    async with sessions() as db:
        product = Product(seller_id=seller_id, name="Synthetic item", listed_price=10000, floor_price=8000)
        db.add(product)
        await db.flush()
        conversation = Conversation(seller_id=seller_id, customer_instagram_id="customer", customer_name="Synthetic",
                                    product_id=product.id, messages=[{"role": "customer", "content": "old question", "mid": "older",
                                    "timestamp": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()}] if pending else [],
                                    last_seller_manual_reply_at=datetime.now(timezone.utc) - timedelta(days=1))
        db.add(conversation)
        await db.flush()
        db.add(ConversationProduct(conversation_id=conversation.id, product_id=product.id, state=state or "product_inquiry"))
        return conversation.id


@pytest.mark.asyncio
@pytest.mark.parametrize("address_first", [False, True])
async def test_payment_screenshot_does_not_complete_unprocessed_address_tail(sessions, monkeypatch, address_first):
    from app.bot import conversation as bot
    seller_id = await seed(sessions)
    await seed_conversation(sessions, seller_id, state="awaiting_payment")
    image = event("payment")
    image["message"] = {"mid": "payment", "attachments": [{"type": "image", "payload": {"url": "https://example.invalid/payment"}}]}
    address = event("address")
    address["message"]["text"] = "Deliver to synthetic address"
    if address_first:
        address_receipt = await receive(sessions, address)
        image_receipt = await receive(sessions, image)
    else:
        image_receipt = await receive(sessions, image)
        address_receipt = await receive(sessions, address)
    await make_due(sessions)
    # Stub external boundaries only: no media fetch, LLM or real send.
    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("synthetic media unavailable")))
    payment = AsyncMock()
    advance = AsyncMock()
    monkeypatch.setattr(bot, "handle_payment_screenshot", payment)
    monkeypatch.setattr(bot, "advance_conversation", advance)
    await worker._process_thread(seller_id, "account", "customer")
    payment.assert_awaited_once()
    advance.assert_not_awaited()
    async with sessions() as db:
        assert (await db.get(InstagramIngress, image_receipt.id)).status == "completed"
        tail = await db.get(InstagramIngress, address_receipt.id)
        assert tail.status == "pending" and tail.processed_indices == []
    await worker._process_thread(seller_id, "account", "customer")
    assert payment.await_count == 1
    advance.assert_awaited_once()
    assert advance.call_args.args[2] == "Deliver to synthetic address"
    async with sessions() as db:
        assert (await db.get(InstagramIngress, address_receipt.id)).status == "completed"


@pytest.mark.asyncio
async def test_legacy_media_and_durable_mid_share_review_fence_and_once_only_ledger(sessions, monkeypatch):
    seller_id = await seed(sessions)
    await seed_conversation(sessions, seller_id)
    image = event("same-media")
    image["message"] = {"mid": "same-media", "attachments": [{"type": "image", "payload": {"url": "https://example.invalid/media"}}]}
    receipt = await receive(sessions, image)
    normalized = [{"type": "image", "image_url": "https://example.invalid/media", "mid": "same-media"}]
    monkeypatch.setattr(message_batch, "peek_all_events", lambda *args: normalized)
    terminal = AsyncMock(return_value={0})
    monkeypatch.setattr(message_batch, "_process_events", terminal)
    assert await message_batch._consume_batch("account", "customer") == 1
    await make_due(sessions)
    await worker._process_thread(seller_id, "account", "customer")
    terminal.assert_not_awaited()
    async with sessions() as db:
        rows = (await db.execute(select(InstagramIngress))).scalars().all()
        assert len(rows) == 1 and rows[0].id == receipt.id
        assert rows[0].error_code == "legacy_cutover_review_required"
        with pytest.raises(ValueError, match="side_effect_review_required"):
            await replay_receipt(db, receipt.id, seller_id)
        await replay_receipt(db, receipt.id, seller_id, side_effects_reviewed=True)
    await worker._process_thread(seller_id, "account", "customer")
    await message_batch._consume_batch("account", "customer")
    await worker._process_thread(seller_id, "account", "customer")
    assert terminal.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt_status", ["processing", "error"])
async def test_unknown_effect_or_processing_quarantines_new_ingress_resume_and_nudge(sessions, monkeypatch, receipt_status):
    from app.bot import conversation as bot
    from app.integrations.instagram import InstagramClient
    from app.workers import nudge
    seller_id = await seed(sessions)
    conversation_id = await seed_conversation(sessions, seller_id, pending=True)
    old = await receive(sessions)
    async with sessions() as db:
        seller = await db.get(Seller, seller_id)
        seller.instagram_token = "synthetic-never-sent"
        row = await db.get(InstagramIngress, old.id)
        row.status = receipt_status
        row.error_code = "processing_failed_unknown_effect" if receipt_status == "error" else None
        row.started_at = datetime.now(timezone.utc)
    newer = await receive(sessions, event("newer"))
    await make_due(sessions)
    advance = AsyncMock()
    send = AsyncMock()
    phase = AsyncMock(return_value={0})
    monkeypatch.setattr(bot, "advance_conversation", advance)
    monkeypatch.setattr(InstagramClient, "send_message", send)
    monkeypatch.setattr(message_batch, "_process_events", phase)
    await worker._process_thread(seller_id, "account", "customer")
    await message_batch._wake_paused_conversation(str(conversation_id))
    await nudge._send_nudge(str(conversation_id), 1)
    advance.assert_not_awaited()
    send.assert_not_awaited()
    phase.assert_not_awaited()
    async with sessions() as db:
        assert (await db.get(InstagramIngress, newer.id)).status == "pending"
    # Legacy work is retained by transfer without invoking a sending path.
    monkeypatch.setattr(message_batch, "peek_all_events", lambda *args: [{"type": "text", "text": "legacy", "mid": "legacy"}])
    assert await message_batch._consume_batch("account", "customer") == 1
    phase.assert_not_awaited()


@pytest.mark.asyncio
async def test_multi_attachment_receipt_tracks_exact_progress_without_reprocessing(sessions, monkeypatch):
    from app.bot import conversation as bot
    seller_id = await seed(sessions)
    await seed_conversation(sessions, seller_id, state="awaiting_payment")
    image = event("two-payments")
    image["message"] = {"mid": "two-payments", "attachments": [
        {"type": "image", "payload": {"url": "https://example.invalid/first"}},
        {"type": "image", "payload": {"url": "https://example.invalid/second"}},
    ]}
    receipt = await receive(sessions, image)
    await make_due(sessions)
    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("synthetic media unavailable")))
    payment = AsyncMock()
    monkeypatch.setattr(bot, "handle_payment_screenshot", payment)
    await worker._process_thread(seller_id, "account", "customer")
    async with sessions() as db:
        row = await db.get(InstagramIngress, receipt.id)
        assert row.status == "pending" and row.processed_indices == [0]
        assert len(row.events) == 2  # Source payload stays immutable for audit.
    await worker._process_thread(seller_id, "account", "customer")
    await worker._process_thread(seller_id, "account", "customer")
    assert [call.args[2] for call in payment.call_args_list] == ["https://example.invalid/first", "https://example.invalid/second"]
    async with sessions() as db:
        row = await db.get(InstagramIngress, receipt.id)
        assert row.status == "completed" and row.processed_indices == [0, 1]


@pytest.mark.asyncio
async def test_review_can_release_quarantine_without_replaying_known_handled_event(sessions, monkeypatch):
    from app.services.instagram_ingress import resolve_receipt_without_replay
    seller_id = await seed(sessions)
    old = await receive(sessions)
    async with sessions() as db:
        row = await db.get(InstagramIngress, old.id)
        row.status, row.error_code = "error", "processing_failed_unknown_effect"
        with pytest.raises(ValueError, match="side_effect_review_required"):
            await resolve_receipt_without_replay(db, old.id, seller_id)
        assert not await resolve_receipt_without_replay(db, old.id, uuid4(), side_effects_reviewed=True)
        assert await resolve_receipt_without_replay(db, old.id, seller_id, side_effects_reviewed=True)
    new = await receive(sessions, event("next"))
    await make_due(sessions)
    consume = AsyncMock(return_value={0})
    monkeypatch.setattr(message_batch, "_consume_events", consume)
    await worker._process_thread(seller_id, "account", "customer")
    consume.assert_awaited_once()
    assert consume.call_args.args[3][0]["mid"] == "next"
    async with sessions() as db:
        assert (await db.get(InstagramIngress, old.id)).status == "resolved"
        assert (await db.get(InstagramIngress, new.id)).status == "completed"


@pytest.mark.asyncio
async def test_unidentified_legacy_snapshots_preserve_customers_and_multiplicity_without_trimming(sessions):
    await seed(sessions)
    repeated = [{"type": "text", "text": "same", "mid": None},
                {"type": "text", "text": "same", "mid": None}]
    assert await message_batch._consume_batch("account", "first-customer", events=repeated) == 0
    assert await message_batch._consume_batch("account", "second-customer", events=repeated) == 0
    # A repeated snapshot is an audit hold; it never claims events were consumed.
    assert await message_batch._consume_batch("account", "first-customer", events=repeated) == 0
    async with sessions() as db:
        rows = (await db.execute(select(InstagramIngress))).scalars().all()
        assert len(rows) == 2
        assert {row.customer_id for row in rows} == {"first-customer", "second-customer"}
        assert len({row.event_key for row in rows}) == 2
        assert all(row.events == repeated and row.error_code == "legacy_snapshot_unidentified" for row in rows)
        for row in rows:
            with pytest.raises(ValueError, match="legacy_buffer_review_required"):
                await replay_receipt(db, row.id, row.seller_id, side_effects_reviewed=True)


@pytest.mark.asyncio
async def test_stable_legacy_transfer_ids_preserve_repeats_and_successive_buffers(sessions):
    await seed(sessions)
    first = [{"type": "text", "text": "same", "mid": None, "_legacy_transfer_id": "batch-a:1"},
             {"type": "text", "text": "same", "mid": None, "_legacy_transfer_id": "batch-a:2"}]
    second = [{"type": "text", "text": "same", "mid": None, "_legacy_transfer_id": "batch-b:1"}]
    assert await message_batch._consume_batch("account", "first-customer", events=first) == 2
    assert await message_batch._consume_batch("account", "first-customer", events=first) == 2
    assert await message_batch._consume_batch("account", "first-customer", events=second) == 1
    assert await message_batch._consume_batch("account", "second-customer", events=first) == 2
    async with sessions() as db:
        rows = (await db.execute(select(InstagramIngress))).scalars().all()
        assert len(rows) == 5  # Three first-customer occurrences, two second-customer.
        assert sorted(len(row.events) for row in rows) == [1, 1, 1, 1, 1]
        assert len({row.event_key for row in rows}) == 5
        assert all(row.status == "error" and row.error_code == "legacy_cutover_review_required" for row in rows)


@pytest.mark.asyncio
async def test_real_redis_transfer_commits_every_missing_mid_occurrence_before_trim(sessions, monkeypatch):
    import json
    target = os.environ.get("TEST_REDIS_URL")
    if target is None:
        pytest.skip("Coordinator-allocated TEST_REDIS_URL required")
    if target != "redis://127.0.0.1:56441/3":
        pytest.fail("Refusing Redis access outside exact allocated test namespace")
    import redis
    await seed(sessions)
    client = redis.from_url(target, decode_responses=True)
    customer = "synthetic_" + uuid4().hex
    key = f"msg_batch:account:{customer}"
    item = {"type": "text", "text": "same", "mid": None}
    monkeypatch.setattr(message_batch, "_redis", lambda: client)
    try:
        client.rpush(key, json.dumps(item), json.dumps(item))
        await message_batch._process_batch("account", customer)
        assert client.llen(key) == 0
        client.rpush(key, json.dumps(item))
        await message_batch._process_batch("account", customer)
        assert client.llen(key) == 0
        async with sessions() as db:
            rows = (await db.execute(select(InstagramIngress).where(InstagramIngress.customer_id == customer))).scalars().all()
            assert len(rows) == 3
            assert len({row.event_key for row in rows}) == 3
            assert all(len(row.events) == 1 and row.status == "error" for row in rows)
    finally:
        client.delete(key)
