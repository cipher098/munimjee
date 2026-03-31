"""FastAPI dependency injection — auth and DB."""
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.delivery_member import DeliveryMember
from app.models.seller import Seller

bearer_scheme = HTTPBearer()


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


async def get_current_seller(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: AsyncSession = Depends(get_db),
) -> Seller:
    payload = _decode_token(credentials.credentials)
    if payload.get("role") != "seller":
        raise HTTPException(status_code=403, detail="Seller access required")
    result = await db.execute(select(Seller).where(Seller.id == UUID(payload["sub"])))
    seller = result.scalar_one_or_none()
    if not seller or not seller.is_active:
        raise HTTPException(status_code=401, detail="Seller not found or inactive")
    return seller


async def get_current_delivery_member(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: AsyncSession = Depends(get_db),
) -> DeliveryMember:
    payload = _decode_token(credentials.credentials)
    if payload.get("role") != "delivery":
        raise HTTPException(status_code=403, detail="Delivery team access required")
    result = await db.execute(
        select(DeliveryMember).where(DeliveryMember.id == UUID(payload["sub"]))
    )
    member = result.scalar_one_or_none()
    if not member or not member.is_active:
        raise HTTPException(status_code=401, detail="Delivery member not found or inactive")
    return member
