"""Admin-only endpoints — list all sellers (the admin can then 'view as' any of them)."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dashboard_auth import require_admin
from app.database import get_db
from app.models.manual_action import ManualAction
from app.models.seller import Seller

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/sellers")
async def list_sellers(db: AsyncSession = Depends(get_db)):
    """Every seller, newest first, with their count of open manual actions (so the admin sees
    at a glance who needs attention)."""
    sellers = (await db.execute(select(Seller).order_by(Seller.created_at.desc()))).scalars().all()
    open_counts = dict((await db.execute(
        select(ManualAction.seller_id, func.count())
        .where(ManualAction.status == "open")
        .group_by(ManualAction.seller_id)
    )).all())
    return [
        {
            "id": str(s.id),
            "business_name": s.business_name,
            "email": s.email,
            "whatsapp_number": s.whatsapp_number,
            "onboarding_state": s.onboarding_state,
            "is_active": s.is_active,
            "open_actions": int(open_counts.get(s.id, 0)),
        }
        for s in sellers
    ]
