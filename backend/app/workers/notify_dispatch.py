"""
Celery task: notify customer on Instagram when order is dispatched.
IDEMPOTENT — checks notified_at before sending to prevent duplicate DMs.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task
def retry_failed() -> None:
    """Re-queue dispatch notifications that never got sent (no notified_at after 5 min)."""
    asyncio.run(_retry_failed())


async def _retry_failed() -> None:
    from app.database import worker_session as AsyncSessionLocal
    from app.models.delivery_update import DeliveryUpdate

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DeliveryUpdate).where(
                DeliveryUpdate.notified_at.is_(None),
                DeliveryUpdate.dispatched_at < cutoff,
            )
        )
        pending = result.scalars().all()

    for update in pending:
        logger.info("retry_failed: re-queuing DeliveryUpdate %s", update.id)
        notify_customer_dispatch.delay(str(update.id))


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def notify_customer_dispatch(self, delivery_update_id: str) -> None:
    try:
        asyncio.run(_notify(delivery_update_id))
    except Exception as exc:
        logger.error("notify_customer_dispatch failed: %s", exc)
        raise self.retry(exc=exc)


async def _notify(delivery_update_id: str) -> None:
    from app.database import worker_session as AsyncSessionLocal
    from app.models.conversation import Conversation
    from app.models.delivery_update import DeliveryUpdate
    from app.models.order import Order
    from app.integrations.instagram import InstagramClient

    async with AsyncSessionLocal() as db:
        # Fetch delivery update
        result = await db.execute(
            select(DeliveryUpdate).where(DeliveryUpdate.id == UUID(delivery_update_id))
        )
        update = result.scalar_one_or_none()
        if not update:
            logger.error("DeliveryUpdate %s not found", delivery_update_id)
            return

        # IDEMPOTENCY: skip if already notified
        if update.notified_at:
            logger.info("DeliveryUpdate %s already notified — skipping", delivery_update_id)
            return

        # Fetch order
        order_result = await db.execute(select(Order).where(Order.id == update.order_id))
        order = order_result.scalar_one_or_none()
        if not order:
            logger.error("Order %s not found for DeliveryUpdate %s", update.order_id, delivery_update_id)
            return

        # Fetch conversation for Instagram IDs
        conv_result = await db.execute(
            select(Conversation).where(Conversation.id == order.conversation_id)
        )
        conversation = conv_result.scalar_one_or_none()
        if not conversation:
            logger.error("Conversation not found for order %s", order.id)
            return

        # Fetch seller token
        from app.models.seller import Seller
        seller_result = await db.execute(select(Seller).where(Seller.id == order.seller_id))
        seller = seller_result.scalar_one_or_none()
        if not seller:
            logger.error("Seller not found for order %s", order.id)
            return

        # Build customer message
        message = update.message or "Aapka order dispatch ho gaya! 🎉"
        if update.tracking_id:
            message += f"\nTracking ID: {update.tracking_id}"
            if update.courier_name:
                message += f" ({update.courier_name})"
        message += "\nKoi sawaal ho toh yahan message karo 😊"

        client = InstagramClient(seller.instagram_token, seller.instagram_id)

        # Send parcel photo if present
        if update.image_url:
            await client.send_image(conversation.customer_instagram_id, update.image_url)

        await client.send_message(conversation.customer_instagram_id, message)

        # Mark notified + update order status
        update.notified_at = datetime.now(timezone.utc)
        order.status = "dispatched"
        conversation.state = "dispatched_notified"
        await db.commit()

        logger.info("Customer notified for order %s via Instagram", order.id)
