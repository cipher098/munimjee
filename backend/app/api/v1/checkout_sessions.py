"""Public order-scoped session handoff. No native/seller cookie authorization."""
from uuid import UUID
import json
import asyncio
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.api.routes.razorpay import VerifyInput, GatewayInput
from app.api.routes import razorpay as gateway
from app.api.v1.identity import current_actor
from app.api.v1.session import require_v1_mutation
from app.services.identity import Actor, require_business_access
from app.models.seller import Seller
from app.schemas.checkout_sessions import CheckoutSessionRead, CheckoutStateRead
from app.services import checkout_sessions as service

router = APIRouter(prefix="/api/v1/storefronts", tags=["public-checkout-session"])


async def no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


@router.get("/{slug}/orders/{order_id}/checkout-session", response_model=CheckoutStateRead,
            dependencies=[Depends(no_store)])
async def checkout_state(slug: str, order_id: UUID, authorization: str | None = Header(None),
                         db: AsyncSession = Depends(get_db)):
    _, order = await service.authorized_order(db, slug, order_id, authorization)
    return await service.state(db, order)


@router.post("/{slug}/orders/{order_id}/checkout-session", response_model=CheckoutSessionRead,
             dependencies=[Depends(no_store)])
async def checkout_session(slug: str, order_id: UUID, request: Request,
                           authorization: str | None = Header(None), db: AsyncSession = Depends(get_db)):
    service.check_origin(request)
    store, order = await service.authorized_order(db, slug, order_id, authorization)
    return await service.create_session(db, store, order)


@router.post("/{slug}/orders/{order_id}/checkout-session/verify", response_model=CheckoutStateRead,
             dependencies=[Depends(no_store)])
async def verify_checkout_session(slug: str, order_id: UUID, request: Request, body: VerifyInput,
                                  authorization: str | None = Header(None), db: AsyncSession = Depends(get_db)):
    service.check_origin(request)
    return await service.verify_session(db, slug, order_id, authorization, body)


# Native configuration writes are capability/CSRF guarded. Configuration is local;
# a real-provider canary is deliberately a separate external gate.
configuration_router = APIRouter(prefix="/api/v1/businesses", tags=["native-payment-configuration"])
CONFIGURATION_BODY_TIMEOUT = 5


@configuration_router.get("/{business_id}/payments/razorpay", dependencies=[Depends(no_store)])
async def payment_configuration(business_id: UUID, request: Request,
        actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "business.write")
    return await gateway.get_settings(request, str(business_id), db)


@configuration_router.put("/{business_id}/payments/razorpay", dependencies=[Depends(no_store)])
async def update_payment_configuration(business_id: UUID, request: Request,
        actor: Actor = Depends(require_v1_mutation), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "business.write")
    # Do not echo invalid secret inputs through FastAPI's default validation detail.
    chunks, size = [], 0
    try:
        async with asyncio.timeout(CONFIGURATION_BODY_TIMEOUT):
            async for chunk in request.stream():
                size += len(chunk)
                if size > 16384:
                    raise HTTPException(413, "Payment configuration is too large")
                chunks.append(chunk)
    except TimeoutError:
        raise HTTPException(408, "Payment configuration timed out")
    try:
        body = GatewayInput.model_validate(json.loads(b"".join(chunks)))
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(422, "Payment configuration is invalid")
    await db.scalar(select(Seller.id).where(Seller.id == business_id).with_for_update())
    # Revocation/session changes during a lock wait must not authorize this write.
    fresh_actor = await require_v1_mutation(request, db)
    await require_business_access(db, fresh_actor, business_id, "business.write")
    result = await gateway.update_settings(body, request, str(business_id), db, verify_connection=False)
    return {**result, "connection_verification": "not_performed"}
