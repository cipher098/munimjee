"""Recovery/cache polling only. Existing Parcel Desk queue owns carrier lookups."""
from sqlalchemy import select,or_
from app.database import worker_session
from app.models.parcel_tracking import OrderParcelLink
from app.services.parcel_tracking import now,process_link

async def poll_due(session_factory=worker_session,limit=20):
    from app.config import settings
    if not settings.V1_PARCEL_ENABLED:return
    async with session_factory() as db:
        ids=(await db.scalars(select(OrderParcelLink.id).where(OrderParcelLink.state.in_(['pending_enrollment','enrollment_unknown','linked']),
            OrderParcelLink.next_poll_at<=now(),or_(OrderParcelLink.lease_until.is_(None),OrderParcelLink.lease_until<=now()))
            .order_by(OrderParcelLink.next_poll_at).limit(min(max(limit,1),100)))).all()
        await db.commit()
    for link_id in ids:
        async with session_factory() as db:
            await process_link(db,link_id)
