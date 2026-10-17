"""Read-only identity views. Mount this router independently of legacy routes."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.database import get_db
from app.schemas.identity import BusinessReadinessView, BusinessView, MeView, ReadinessCheck
from app.services.identity import (
    Actor, BusinessAccess, accessible_businesses, require_business_access,
    resolve_legacy_owner, resolve_user_actor,
)

router = APIRouter(prefix="/api/v1", tags=["v1-identity"])


def decode_actor_credentials(request: Request) -> tuple[str, UUID]:
    """Bearer wins; a bad explicit credential never falls back to a cookie."""
    authorization = request.headers.get("authorization")
    if authorization is not None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(status_code=401, detail="Login required")
    else:
        token = (request.cookies.get("v1_session") or request.cookies.get("dashboard_session")
                 or request.cookies.get("seller_session") or "")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM],
                             options={"require_exp": True, "require_sub": True})
        if payload.get("role") == "v1_user" and payload.get("purpose") == "v1_actor":
            return "v1_user", UUID(payload["sub"])
        if payload.get("role") == "seller" and not payload.get("purpose"):
            # Dashboard sub is an email; API seller sub is the seller UUID.
            sid = UUID(payload.get("seller_id") or payload["sub"])
            if payload.get("seller_id"):
                try:
                    sub_uuid = UUID(payload["sub"])
                except ValueError:
                    sub_uuid = None
                if sub_uuid is not None and sub_uuid != sid:
                    raise ValueError("Conflicting legacy seller identity")
            return "legacy_owner", sid
        # Admin view_seller cookies, delivery roles and support impersonation fail closed.
        raise ValueError("Unsupported identity credential")
    except (JWTError, ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(status_code=401, detail="Login required")


async def current_actor(request: Request, db: AsyncSession = Depends(get_db)) -> Actor:
    kind, subject = decode_actor_credentials(request)
    if kind == "legacy_owner":
        return await resolve_legacy_owner(db, subject)
    return await resolve_user_actor(db, subject, "v1_user")


def business_view(access: BusinessAccess) -> BusinessView:
    return BusinessView(id=access.business.id, name=access.business.name,
                        role=access.membership.role, capabilities=sorted(access.capabilities))


@router.get("/me", response_model=MeView)
async def me(actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    return MeView(user_id=actor.user_id, auth_method=actor.auth_method,
                  businesses=[business_view(a) for a in await accessible_businesses(db, actor)])


@router.get("/businesses", response_model=list[BusinessView])
async def businesses(actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    return [business_view(a) for a in await accessible_businesses(db, actor)]


@router.get("/businesses/{business_id}", response_model=BusinessView)
async def business(business_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    return business_view(await require_business_access(db, actor, business_id))


@router.get("/businesses/{business_id}/readiness", response_model=BusinessReadinessView)
async def readiness(business_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    access = await require_business_access(db, actor, business_id, "readiness.read")
    return BusinessReadinessView(
        business_id=business_id, identity_ready=True, legacy_onboarding_state=access.seller.onboarding_state,
        checks=[ReadinessCheck(key="active_business", status="ready"),
                ReadinessCheck(key="active_membership", status="ready"),
                *[ReadinessCheck(key=key, status="not_evaluated") for key in
                  ("catalogue_review", "channel_connections", "storefront_publication", "checkout")]],
    )
