"""DB-backed Instagram inbox dispatcher using the existing conversation writer."""
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, text

from app.database import worker_session
from app.models.instagram_ingress import InstagramIngress
from app.models.seller import Seller
from app.services.instagram_ingress import PROCESSING_TIMEOUT_SECONDS, thread_quarantined
from app.workers.async_runner import run_async
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
READY = ("pending", "retry")


@celery_app.task(name="app.workers.instagram_ingress.process_instagram_ingress", acks_late=True)
def process_instagram_ingress(seller_id: str, account_id: str, customer_id: str) -> None:
    run_async(_process_thread(UUID(seller_id), account_id, customer_id))


@celery_app.task(name="app.workers.instagram_ingress.recover_instagram_ingress")
def recover_instagram_ingress() -> None:
    run_async(_recover())


def _thread(seller_id, account_id, customer_id):
    return (InstagramIngress.seller_id == seller_id,
            InstagramIngress.account_id == account_id,
            InstagramIngress.customer_id == customer_id)


async def _claim(seller_id, account_id, customer_id) -> list:
    now = datetime.now(timezone.utc)
    async with worker_session() as db:
        # Serialize claimers for this provider thread, independently of worker
        # count. The actual conversation writer also takes its existing lock.
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:thread))"), {
            "thread": f"ig-ingress:{seller_id}:{account_id}:{customer_id}",
        })
        from app.services.channel_readiness import instagram_automation_enabled
        if not await instagram_automation_enabled(db, seller_id):
            return []
        filters = _thread(seller_id, account_id, customer_id)
        active = await db.scalar(select(InstagramIngress.id).where(
            *filters, InstagramIngress.status == "processing",
        ).limit(1))
        if active is not None or await thread_quarantined(db, seller_id, customer_id):
            return []
        # Wait for a full silence window, preserving the existing debounce.
        newest = await db.scalar(select(InstagramIngress.available_at).where(
            *filters, InstagramIngress.status.in_(READY),
        ).order_by(InstagramIngress.available_at.desc()).limit(1))
        if newest is None or newest > now:
            return []
        rows = (await db.execute(select(InstagramIngress).where(
            *filters, InstagramIngress.status.in_(READY), InstagramIngress.available_at <= now,
        ).order_by(InstagramIngress.created_at, InstagramIngress.id).limit(100).with_for_update())).scalars().all()
        for row in rows:
            row.status, row.started_at, row.error_code = "processing", now, None
            row.attempts += 1
        return [row.id for row in rows]


async def _process_thread(seller_id, account_id: str, customer_id: str) -> None:
    ids = await _claim(seller_id, account_id, customer_id)
    if not ids:
        return
    try:
        async with worker_session() as db:
            # Hold row locks through processing. Recovery skips live transactions
            # even if they run longer than the stale-processing threshold.
            rows = (await db.execute(select(InstagramIngress).where(
                InstagramIngress.id.in_(ids), InstagramIngress.status == "processing",
            ).order_by(InstagramIngress.created_at, InstagramIngress.id).with_for_update())).scalars().all()
            if len(rows) != len(ids):
                return
            # Revalidate the persisted tenant/account binding before any send.
            sellers = (await db.execute(select(Seller).where(
                Seller.instagram_page_id == account_id, Seller.is_active.is_(True),
            ).limit(2).with_for_update())).scalars().all()
            if len(sellers) != 1 or sellers[0].id != seller_id:
                _finish(rows, "error", "instagram_account_binding_changed")
                return
            from app.services.channel_readiness import current_provider_window
            outside_window = [row for row in rows if not current_provider_window(row.occurred_at)]
            if outside_window:
                for row in rows:
                    row.status, row.started_at = "pending", None
                _finish(outside_window, "error", "provider_window_unverified")
                return
            from app.services.channel_operator import replay_block_reason
            from app.models.channel_operator import ChannelOperation
            for row in rows:
                if row.operator_replay_pending:
                    audit = await db.scalar(select(ChannelOperation).where(ChannelOperation.business_id == seller_id,
                          ChannelOperation.resource_id == row.id, ChannelOperation.action == "ingress_replay")
                          .order_by(ChannelOperation.created_at.desc()).limit(1))
                    blocked = await replay_block_reason(db, row, actor_id=audit.actor_user_id) if audit else "No authorized review audit"
                    if blocked:
                        for item in rows:
                            item.status, item.started_at = "pending", None
                        _finish([row], "error", "operator_replay_withheld")
                        return
            from app.workers.message_batch import _consume_events
            positions = [(row, index) for row in rows for index in range(len(row.events))
                         if index not in (row.processed_indices or [])]
            consumed = await _consume_events(
                db, sellers[0], customer_id, [row.events[index] for row, index in positions],
                owned_receipt_ids=ids,
            )
            if not isinstance(consumed, set) or not consumed <= set(range(len(positions))):
                raise ValueError("Invalid conversation consumption result")
            for row in rows:
                done = set(row.processed_indices or [])
                done.update(index for position, (source, index) in enumerate(positions)
                            if source.id == row.id and position in consumed)
                row.processed_indices = sorted(done)
                if len(done) == len(row.events):
                    _finish([row], "completed")
                    row.operator_replay_pending = False
                else:
                    # Payment handling can intentionally return before later
                    # text/media. Preserve those components for the next pass.
                    row.status, row.started_at, row.finished_at = "pending", None, None
                    row.available_at = datetime.now(timezone.utc)
    except Exception as exc:
        from app.services.channel_readiness import CatalogueAuthorityHandoff
        code = "authoritative_catalogue_handoff" if isinstance(exc, CatalogueAuthorityHandoff) else "processing_failed_unknown_effect"
        # The legacy writer may send externally before its DB commit. A blind
        # retry could duplicate a reply or other side effect. Retain for review.
        logger.warning("Instagram ingress processing failed; receipts require side-effect review")
        async with worker_session() as db:
            rows = (await db.execute(select(InstagramIngress).where(
                InstagramIngress.id.in_(ids), InstagramIngress.status == "processing",
            ).with_for_update())).scalars().all()
            _finish(rows, "error", code)


def _finish(rows, status: str, code: str | None = None) -> None:
    for row in rows:
        row.status, row.error_code = status, code
        row.finished_at = datetime.now(timezone.utc)


async def _recover() -> None:
    now = datetime.now(timezone.utc)
    async with worker_session() as db:
        stale = (await db.execute(select(InstagramIngress).where(
            InstagramIngress.status == "processing",
            InstagramIngress.started_at < now - timedelta(seconds=PROCESSING_TIMEOUT_SECONDS),
        ).limit(500).with_for_update(skip_locked=True))).scalars().all()
        _finish(stale, "error", "processing_interrupted_unknown_effect")
        threads = (await db.execute(select(
            InstagramIngress.seller_id, InstagramIngress.account_id, InstagramIngress.customer_id,
        ).where(InstagramIngress.status.in_(READY), InstagramIngress.available_at <= now)
          .distinct().limit(500))).all()
    for seller_id, account_id, customer_id in threads:
        try:
            process_instagram_ingress.apply_async(args=[str(seller_id), account_id, customer_id])
        except Exception:
            # DB remains authoritative; a later scan can retry the wake-up.
            logger.warning("Instagram ingress recovery broker unavailable; receipts retained")
            break
    _recover_legacy_buffers()


def _recover_legacy_buffers() -> None:
    """Best-effort cutover transfer recovery; DB-native work needs no Redis scan."""
    from itertools import islice
    from app.workers.message_batch import _redis, process_message_batch, _BATCH_KEY_PREFIX
    try:
        redis = _redis()
        for key in islice(redis.scan_iter(match=f"{_BATCH_KEY_PREFIX}*", count=100), 500):
            parts = key.removeprefix(_BATCH_KEY_PREFIX).split(":")
            if len(parts) != 2 or not all(parts):
                continue
            redis.persist(key)
            process_message_batch.apply_async(args=parts)
    except Exception:
        logger.warning("Legacy Instagram transfer recovery unavailable; buffered work retained")
