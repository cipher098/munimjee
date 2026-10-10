"""Release abandoned online stock reservations independently of storefront visits."""

import asyncio
from datetime import datetime, timezone
from sqlalchemy import select
from app.database import worker_session
from app.models.commerce import CommerceOrder, Storefront
from app.services.commerce import expire_pending_orders
from app.workers.celery_app import celery_app


async def _expire_reservations():
    async with worker_session() as db:
        sellers = (
            await db.scalars(
                select(CommerceOrder.seller_id)
                .where(
                    CommerceOrder.payment_method == "razorpay",
                    CommerceOrder.payment_status == "pending",
                    CommerceOrder.expires_at <= datetime.now(timezone.utc),
                )
                .distinct()
            )
        ).all()
    for seller_id in sellers:
        async with worker_session() as db:
            # Same lock order as checkout and seller order transitions.
            await db.scalar(
                select(Storefront)
                .where(Storefront.seller_id == seller_id)
                .with_for_update()
            )
            await expire_pending_orders(db, seller_id)


@celery_app.task(name="app.workers.commerce.expire_reservations")
def expire_reservations():
    asyncio.run(_expire_reservations())
