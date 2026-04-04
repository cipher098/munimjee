"""Celery task — refresh Instagram long-lived tokens before they expire."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import worker_session as AsyncSessionLocal
from app.integrations.instagram import exchange_for_long_lived_token
from app.models.seller import Seller
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.refresh_tokens.refresh_expiring_instagram_tokens")
def refresh_expiring_instagram_tokens() -> None:
    asyncio.run(_refresh())


async def _refresh() -> None:
    # Refresh tokens expiring within the next 10 days
    refresh_before = datetime.now(timezone.utc) + timedelta(days=10)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Seller).where(
                Seller.is_active == True,
                Seller.instagram_token_expires_at <= refresh_before,
            )
        )
        sellers = result.scalars().all()

        if not sellers:
            logger.info("No Instagram tokens due for refresh")
            return

        for seller in sellers:
            try:
                new_token = await exchange_for_long_lived_token(seller.instagram_token)
                seller.instagram_token = new_token
                seller.instagram_token_expires_at = datetime.now(timezone.utc) + timedelta(days=60)
                logger.info("Refreshed Instagram token for seller %s", seller.id)
            except Exception as exc:
                logger.error("Failed to refresh token for seller %s: %s", seller.id, exc)

        await db.commit()
