"""Celery task — refresh Instagram long-lived tokens before they expire."""
from app.workers.async_runner import run_async
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
    run_async(_refresh())


async def _refresh() -> None:
    # Refresh tokens expiring within the next 10 days
    refresh_before = datetime.now(timezone.utc) + timedelta(days=10)

    from app.services.instagram_credentials import snapshot, replace
    async with AsyncSessionLocal() as db:
        ids = (await db.scalars(select(Seller.id).where(
            Seller.is_active.is_(True), Seller.instagram_token_expires_at <= refresh_before))).all()
    for seller_id in ids:
        async with AsyncSessionLocal() as db:
            current = await snapshot(db, seller_id)
        if not current.active or not current.token or not current.account_id:
            continue
        try:
            new_token = await exchange_for_long_lived_token(current.token)
            async with AsyncSessionLocal() as db:
                changed = await replace(db, seller_id, expected=current.proof(), account_id=current.account_id,
                    token=new_token, expires_at=datetime.now(timezone.utc) + timedelta(days=60))
                await db.commit()
            logger.info("Instagram token refresh for seller %s: %s", seller_id, 'saved' if changed else 'connection changed; discarded')
        except Exception:
            # Provider exception text can include credentials; never log it.
            logger.warning("Failed to refresh token for seller %s", seller_id)
