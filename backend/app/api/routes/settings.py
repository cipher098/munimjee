"""Seller settings — policies (COD, returns, delivery)."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dashboard_auth import verify_dashboard_cookie
from app.database import get_db
from app.models.seller import Seller

logger = logging.getLogger(__name__)

SELLER_ID = "ac2303e0-00f3-4470-98ca-36a8f4ae5866"

router = APIRouter(
    prefix="/settings",
    tags=["settings"],
    dependencies=[Depends(verify_dashboard_cookie)],
)


class PoliciesUpdate(BaseModel):
    cod: bool
    cod_charges: int = 0          # extra rupees charged for COD, 0 = free COD
    return_days: int = 0          # 0 = no returns
    exchange_days: int = 0        # 0 = no exchange
    delivery_days: str = ""       # e.g. "3-5 days", empty = not specified
    payment_modes: list[str] = ["upi"]  # e.g. ["upi", "bank_transfer", "card"]


@router.get("/policies")
async def get_policies(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Seller).where(Seller.id == SELLER_ID))
    seller = result.scalar_one_or_none()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")
    return seller.policies or {}


@router.post("/policies")
async def save_policies(body: PoliciesUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Seller).where(Seller.id == SELLER_ID))
    seller = result.scalar_one_or_none()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")

    seller.policies = {
        "cod": body.cod,
        "cod_charges": body.cod_charges if body.cod else 0,
        "return_days": body.return_days,
        "exchange_days": body.exchange_days,
        "delivery_days": body.delivery_days.strip(),
        "payment_modes": body.payment_modes or ["upi"],
    }
    await db.commit()
    logger.info("Seller policies updated: %s", seller.policies)
    return {"status": "saved", "policies": seller.policies}
