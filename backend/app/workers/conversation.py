"""
Celery task: drop the negotiation focus on stale conversations that have had no
activity for 24 hours. Runs every 2 hours via Beat.

Conversations are permanent now (no status) — instead of closing them, we clear
the current-focus pointer (product_id) and any quiet-window flags so a stalled
negotiation doesn't keep the thread "stuck" on a half-finished product. The
customer's next message is then handled fresh (returning_customer if they have
past orders), with full history intact.
"""
from app.workers.async_runner import run_async
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

STALE_AFTER_HOURS = 24


@celery_app.task(name="app.workers.conversation.expire_stale")
def expire_stale() -> None:
    run_async(_expire_stale())


async def _expire_stale() -> None:
    from app.database import worker_session as AsyncSessionLocal
    from app.models.conversation import Conversation

    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_AFTER_HOURS)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Conversation).where(
                Conversation.product_id.isnot(None),
                Conversation.updated_at < cutoff,
            )
        )
        stale = result.scalars().all()

        if not stale:
            logger.info("expire_stale: no stale conversations found")
            return

        for conv in stale:
            conv.product_id = None
            conv.nudge_state = None
            conv.disengage_paused_until = None

        await db.commit()
        logger.info("expire_stale: cleared focus on %d stale conversations", len(stale))
