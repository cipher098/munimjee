"""
Celery task: send daily 9am reminder to sellers who haven't uploaded their
bank statement for reconciliation. Runs via Beat on a daily crontab schedule.
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.process_statement.send_reminder")
def send_reminder() -> None:
    asyncio.run(_send_reminder())


async def _send_reminder() -> None:
    from app.database import AsyncSessionLocal
    from app.models.seller import Seller
    from app.models.transaction import Transaction

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    async with AsyncSessionLocal() as db:
        # Find all active sellers
        seller_result = await db.execute(
            select(Seller).where(Seller.is_active == True)  # noqa: E712
        )
        sellers = seller_result.scalars().all()

        reminded = 0
        for seller in sellers:
            # Check if seller already has a statement-verified transaction today
            txn_result = await db.execute(
                select(Transaction).where(
                    Transaction.seller_id == seller.id,
                    Transaction.verified_by == "statement",
                    Transaction.timestamp >= today_start,
                )
            )
            already_uploaded = txn_result.scalar_one_or_none()
            if already_uploaded:
                continue

            await _send_whatsapp_reminder(seller)
            reminded += 1

        logger.info("send_reminder: reminded %d sellers to upload bank statement", reminded)


async def _send_whatsapp_reminder(seller) -> None:
    """Send WhatsApp reminder via Instagram or configured channel."""
    if not seller.whatsapp_number:
        logger.debug("Seller %s has no whatsapp_number — skipping reminder", seller.id)
        return

    # Placeholder: integrate with WhatsApp Business API or SMS provider
    logger.info(
        "REMINDER → seller %s (%s): please upload today's bank statement for reconciliation",
        seller.id,
        seller.whatsapp_number,
    )
