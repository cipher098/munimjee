"""
Celery task: expire stale conversations that have had no activity for 24 hours.
Runs every 2 hours via Beat. Moves eligible conversations to state 'expired'.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

STALE_AFTER_HOURS = 24

ACTIVE_STATES = {
    "greeting",
    "product_inquiry",
    "negotiating",
    "awaiting_payment",
    "verifying",
}


@celery_app.task(name="app.workers.conversation.expire_stale")
def expire_stale() -> None:
    asyncio.run(_expire_stale())


async def _expire_stale() -> None:
    from app.database import AsyncSessionLocal
    from app.models.conversation import Conversation

    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_AFTER_HOURS)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Conversation).where(
                Conversation.state.in_(ACTIVE_STATES),
                Conversation.updated_at < cutoff,
            )
        )
        stale = result.scalars().all()

        if not stale:
            logger.info("expire_stale: no stale conversations found")
            return

        for conv in stale:
            conv.state = "expired"

        await db.commit()
        logger.info("expire_stale: marked %d conversations as expired", len(stale))
