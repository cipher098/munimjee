"""Native payment setup shell; credential facts come only from protected APIs."""
from pathlib import Path
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.auth import enabled
from app.api.v1.identity import current_actor
from app.database import get_db
from app.services.identity import Actor, require_business_access

router = APIRouter(tags=["v1-payment-settings"], dependencies=[Depends(enabled)])
_STATIC = Path(__file__).resolve().parents[3] / "static"


@router.get("/v1/businesses/{business_id}/payments", include_in_schema=False)
async def payment_settings(business_id: UUID, actor: Actor = Depends(current_actor),
                           db: AsyncSession = Depends(get_db)):
    if actor.auth_method != "v1_user":
        raise HTTPException(403, "Sign in with your own V1 account to open payment setup")
    await require_business_access(db, actor, business_id, "business.read")
    return FileResponse(_STATIC / "payment_settings.html", headers={
        "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
