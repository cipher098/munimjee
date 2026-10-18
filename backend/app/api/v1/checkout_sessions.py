"""Public order-scoped session handoff. No native/seller cookie authorization."""
from uuid import UUID
import json
import asyncio
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import Field
import hmac
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.config import settings
from app.api.routes.razorpay import VerifyInput, GatewayInput
from app.api.routes import razorpay as gateway
from app.api.v1.identity import current_actor
from app.api.v1.session import require_v1_mutation, business_mutation
from app.services.identity import Actor, require_business_access
from app.models.seller import Seller
from app.schemas.checkout_sessions import CheckoutSessionRead, CheckoutStateRead, PaymentReviewRead, GatewayConfigurationRead
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


class NativeGatewayInput(GatewayInput):
    expected_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


@configuration_router.get("/{business_id}/payments/razorpay", response_model=GatewayConfigurationRead,
                          dependencies=[Depends(no_store)])
async def payment_configuration(business_id: UUID, request: Request,
        actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    await require_business_access(db, actor, business_id, "business.write")
    return await service.gateway_configuration_view(db, business_id, request)


@configuration_router.put("/{business_id}/payments/razorpay", response_model=GatewayConfigurationRead,
                          dependencies=[Depends(no_store)])
async def update_payment_configuration(business_id: UUID, request: Request,
        actor: Actor = Depends(business_mutation("business.write")), db: AsyncSession = Depends(get_db)):
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
        body = NativeGatewayInput.model_validate(json.loads(b"".join(chunks)))
    except (ValueError, TypeError, RecursionError):
        raise HTTPException(422, "Payment configuration is invalid")
    await db.scalar(select(Seller.id).where(Seller.id == business_id).with_for_update())
    # Revocation/session changes during a lock wait must not authorize this write.
    fresh_actor = await require_v1_mutation(request, db)
    await require_business_access(db, fresh_actor, business_id, "business.write")
    current = await service.current_account(db, business_id)
    if body.expected_revision is not None and not hmac.compare_digest(body.expected_revision,
            service.gateway_configuration_revision(business_id, current)):
        raise HTTPException(409, {"code": "gateway_config_stale",
            "message": "Payment settings changed. Refresh the current settings before replacing credentials."})
    command = GatewayInput.model_validate(body.model_dump(exclude={"expected_revision"}))
    await gateway.update_settings(command, request, str(business_id), db, verify_connection=False, commit=False)
    return await service.gateway_configuration_view(db, business_id, request)


@configuration_router.get("/{business_id}/orders/{order_id}/payment-review", response_model=PaymentReviewRead,
                          dependencies=[Depends(no_store)])
async def review_payment(business_id: UUID, order_id: UUID,
        actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    if not settings.V1_AUTH_ENABLED:
        raise HTTPException(404, "V1 sign-in is unavailable")
    if actor.auth_method != "v1_user":
        raise HTTPException(401, "Native V1 sign-in required")
    await require_business_access(db, actor, business_id, "orders.write")
    return await service.payment_review(db, business_id, order_id)
