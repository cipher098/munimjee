"""Seller settings — policies (COD, returns, delivery) + allowed channels."""
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
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


# ---------------------------------------------------------------------------
# Approved alternative channels
# ---------------------------------------------------------------------------

ChannelType = Literal["whatsapp", "phone", "email"]


class Channel(BaseModel):
    type: ChannelType
    value: str = Field(min_length=1, max_length=200)

    @field_validator("value")
    @classmethod
    def strip_value(cls, v: str) -> str:
        return v.strip()


class ChannelsUpdate(BaseModel):
    channels: list[Channel] = []


@router.get("/channels")
async def get_channels(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Seller).where(Seller.id == SELLER_ID))
    seller = result.scalar_one_or_none()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")
    return {"channels": seller.channels or []}


@router.post("/channels")
async def save_channels(body: ChannelsUpdate, db: AsyncSession = Depends(get_db)):
    """Replace the seller's approved-channels list. Pass [] to clear."""
    result = await db.execute(select(Seller).where(Seller.id == SELLER_ID))
    seller = result.scalar_one_or_none()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")

    seller.channels = [c.model_dump() for c in body.channels] or None
    await db.commit()
    logger.info("Seller channels updated: %s", seller.channels)
    return {"status": "saved", "channels": seller.channels or []}


# ---------------------------------------------------------------------------
# Per-seller LLM model preferences
# ---------------------------------------------------------------------------

# Whitelist what the dashboard offers. Adding a new model here is a one-line
# change. Anything outside this set is rejected on save.
_ALLOWED_DECIDE_MODELS = {
    "anthropic": {"claude-sonnet-4-20250514", "claude-3-5-sonnet-20241022", "claude-haiku-4-5-20251001"},
    "sarvam": {"sarvam-30b", "sarvam-105b"},
}
_ALLOWED_REPLY_MODELS = {
    "anthropic": {"claude-sonnet-4-20250514", "claude-3-5-sonnet-20241022", "claude-haiku-4-5-20251001"},
    "sarvam": {"sarvam-30b", "sarvam-105b"},
}


class ModelChoice(BaseModel):
    provider: Literal["anthropic", "sarvam"]
    model: str = Field(min_length=1, max_length=120)


class LlmPreferencesUpdate(BaseModel):
    decide: ModelChoice | None = None
    reply: ModelChoice | None = None


@router.get("/llm-preferences")
async def get_llm_preferences(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Seller).where(Seller.id == SELLER_ID))
    seller = result.scalar_one_or_none()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")
    return seller.llm_preferences or {}


@router.post("/llm-preferences")
async def save_llm_preferences(body: LlmPreferencesUpdate, db: AsyncSession = Depends(get_db)):
    """Upsert per-seller LLM overrides. Pass `null` for either key to fall
    back to the app default from agents.yaml."""
    result = await db.execute(select(Seller).where(Seller.id == SELLER_ID))
    seller = result.scalar_one_or_none()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")

    new_prefs: dict = {}
    if body.decide is not None:
        if body.decide.model not in _ALLOWED_DECIDE_MODELS.get(body.decide.provider, set()):
            raise HTTPException(
                status_code=400,
                detail=f"Model {body.decide.model!r} not allowed for provider {body.decide.provider!r} on decide",
            )
        new_prefs["decide"] = body.decide.model_dump()
    if body.reply is not None:
        if body.reply.model not in _ALLOWED_REPLY_MODELS.get(body.reply.provider, set()):
            raise HTTPException(
                status_code=400,
                detail=f"Model {body.reply.model!r} not allowed for provider {body.reply.provider!r} on reply",
            )
        new_prefs["reply"] = body.reply.model_dump()

    seller.llm_preferences = new_prefs or None
    await db.commit()
    logger.info("Seller llm_preferences updated: %s", seller.llm_preferences)
    return {"status": "saved", "llm_preferences": seller.llm_preferences or {}}
