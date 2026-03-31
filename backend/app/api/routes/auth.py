"""JWT auth endpoints for sellers and delivery team members."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.integrations.instagram import exchange_for_long_lived_token
from app.models.delivery_member import DeliveryMember
from app.models.seller import Seller

router = APIRouter(prefix="/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _create_token(payload: dict) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {**payload, "exp": expire},
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def _verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


class SellerLoginRequest(BaseModel):
    email: str
    password: str


class DeliveryLoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


@router.post("/seller/login", response_model=TokenResponse)
async def seller_login(body: SellerLoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Seller).where(Seller.email == body.email))
    seller = result.scalar_one_or_none()
    if not seller or not _verify_password(body.password, seller.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not seller.is_active:
        raise HTTPException(status_code=403, detail="Account inactive")

    token = _create_token({"sub": str(seller.id), "role": "seller"})
    return TokenResponse(access_token=token, role="seller")


class ConnectInstagramRequest(BaseModel):
    seller_id: str
    short_lived_token: str


@router.post("/seller/connect-instagram")
async def connect_instagram(body: ConnectInstagramRequest, db: AsyncSession = Depends(get_db)):
    """Exchange a short-lived Instagram token for a long-lived one and save it to the seller."""
    result = await db.execute(select(Seller).where(Seller.id == body.seller_id))
    seller = result.scalar_one_or_none()
    if not seller:
        raise HTTPException(status_code=404, detail="Seller not found")

    try:
        long_lived_token = await exchange_for_long_lived_token(body.short_lived_token)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {exc}")

    seller.instagram_token = long_lived_token
    seller.instagram_token_expires_at = datetime.now(timezone.utc) + timedelta(days=60)
    await db.commit()

    return {"detail": "Instagram token updated", "expires_at": seller.instagram_token_expires_at}


@router.post("/delivery/login", response_model=TokenResponse)
async def delivery_login(body: DeliveryLoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DeliveryMember).where(DeliveryMember.username == body.username)
    )
    member = result.scalar_one_or_none()
    if not member or not _verify_password(body.password, member.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not member.is_active:
        raise HTTPException(status_code=403, detail="Account inactive")

    token = _create_token({
        "sub": str(member.id),
        "role": "delivery",
        "seller_id": str(member.seller_id),
    })
    return TokenResponse(access_token=token, role="delivery")
