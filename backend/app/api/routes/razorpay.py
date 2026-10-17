"""Razorpay configuration, checkout confirmation and signed provider webhooks."""

import json
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.dashboard_auth import current_seller_id
from app.database import get_db
from app.config import settings
from app.models.commerce import CommerceOrder, Storefront
from app.models.seller import Seller
from app.models.razorpay import RazorpayAccount
from app.services.commerce import authorize_order
from app.services import razorpay_payments as payments

router = APIRouter(tags=["payments"])


class GatewayInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key_id: str = Field(pattern=r"^rzp_(test|live)_[A-Za-z0-9]+$", max_length=100)
    key_secret: str | None = Field(default=None, min_length=8, max_length=500)
    webhook_secret: str | None = Field(default=None, min_length=16, max_length=500)
    mode: Literal["test", "live"] = "test"
    enabled: bool = False


class VerifyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    razorpay_order_id: str = Field(pattern=r"^order_[A-Za-z0-9]+$", max_length=100)
    razorpay_payment_id: str = Field(pattern=r"^pay_[A-Za-z0-9]+$", max_length=100)
    razorpay_signature: str = Field(pattern=r"^[a-f0-9]{64}$")


def settings_json(account, request, seller_id):
    base = (settings.PUBLIC_BASE_URL or str(request.base_url)).rstrip("/")
    try:
        payments.cipher()
        ready = True
    except HTTPException:
        ready = False
    return {
        "configured": account is not None,
        "enabled": bool(account and account.enabled),
        "mode": account.mode if account else "test",
        "key_id": account.key_id if account else "",
        "webhook_url": f"{base}/webhooks/razorpay/{seller_id}",
        "encryption_ready": ready,
    }


@router.get("/commerce/razorpay")
async def get_settings(
    request: Request,
    seller_id: str = Depends(current_seller_id),
    db: AsyncSession = Depends(get_db),
):
    return settings_json(
        await db.get(RazorpayAccount, UUID(seller_id)), request, seller_id
    )


@router.put("/commerce/razorpay")
async def save_settings(
    body: GatewayInput,
    request: Request,
    seller_id: str = Depends(current_seller_id),
    db: AsyncSession = Depends(get_db),
):
    if not body.key_id.startswith(f"rzp_{body.mode}_"):
        raise HTTPException(422, "The key ID does not match the selected mode")
    # Serialize settings writes, including first configuration.
    seller = await db.scalar(
        select(Seller).where(Seller.id == seller_id).with_for_update()
    )
    if not seller or not seller.is_active:
        raise HTTPException(404, "Seller not found")
    payments.cipher()
    account = await db.get(RazorpayAccount, seller.id)
    if account is None and (not body.key_secret or not body.webhook_secret):
        raise HTTPException(
            422, "Key secret and webhook secret are required for initial setup"
        )
    if account and body.key_id != account.key_id and not body.key_secret:
        raise HTTPException(422, "Enter the secret for the new key ID")
    changing = account and (
        body.key_id != account.key_id or body.key_secret or body.webhook_secret
    )
    if changing:
        pending = await db.scalar(
            select(CommerceOrder.id)
            .where(
                CommerceOrder.seller_id == seller.id,
                CommerceOrder.payment_method == "razorpay",
                CommerceOrder.payment_status == "pending",
            )
            .limit(1)
        )
        if pending:
            raise HTTPException(
                409, "Resolve pending online orders before rotating payment credentials"
            )
    if account is None:
        account = RazorpayAccount(seller_id=seller.id)
        db.add(account)
    account.key_id, account.mode, account.enabled = body.key_id, body.mode, body.enabled
    if body.key_secret:
        account.key_secret = payments.encrypt(body.key_secret)
    if body.webhook_secret:
        account.webhook_secret = payments.encrypt(body.webhook_secret)
    # Validate the account before enabling it; a stored key alone is not a connection.
    if body.enabled:
        await payments.gateway_request(account, "GET", "orders?count=1")
    await db.commit()
    return settings_json(account, request, seller.id)


async def store_by_slug(db, slug):
    store = await db.scalar(
        select(Storefront)
        .join(Seller)
        .where(
            Storefront.slug == slug,
            Storefront.published.is_(True),
            Seller.is_active.is_(True),
        )
    )
    if store is None:
        raise HTTPException(404, "Store not found")
    return store


@router.get("/shop-api/{slug}/payment-options")
async def payment_options(slug: str, db: AsyncSession = Depends(get_db)):
    store = await store_by_slug(db, slug)
    account = await db.get(RazorpayAccount, store.seller_id)
    try:
        payments.cipher()
        encryption_ready = True
    except HTTPException:
        encryption_ready = False
    enabled = bool(account and account.enabled and encryption_ready)
    return {
        "cod_enabled": store.cod_enabled,
        "razorpay_enabled": enabled,
        "razorpay_mode": account.mode if enabled else None,
    }


async def authorized_order(db, slug, order_id, authorization):
    # Customer status/payment survives store unpublishing; capability still required.
    store = await db.scalar(select(Storefront).where(Storefront.slug == slug))
    order = (
        await db.scalar(
            select(CommerceOrder)
            .where(
                CommerceOrder.id == order_id, CommerceOrder.seller_id == store.seller_id
            )
            .with_for_update()
        )
        if store
        else None
    )
    authorize_order(order, authorization)
    if order.payment_method != "razorpay":
        raise HTTPException(409, "This order uses cash on delivery")
    return store, order


@router.post("/shop-api/{slug}/orders/{order_id}/razorpay")
async def start_payment(
    slug: str,
    order_id: UUID,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    store, order = await authorized_order(db, slug, order_id, authorization)
    account = await payments.require_gateway(db, order.seller_id)
    if (
        order.payment_status != "pending"
        or order.fulfillment_status != "pending"
        or order.stock_released
    ):
        raise HTTPException(409, "This order is no longer awaiting payment")
    if order.expires_at and order.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(
            409, "Payment reservation expired; please place a new order"
        )
    if not order.gateway_order_id:
        if order.items and all(item.get('_inventory_engine') == 'sku.v1' for item in order.items):
            from app.services.sku_payments import ensure_gateway_order
            await ensure_gateway_order(db, order, account)
        else:
            await _create_legacy_gateway_order(db, order, account)
    account = payments.order_account(order, account)
    return {
        "key": account.key_id,
        "order_id": order.gateway_order_id,
        "amount": order.total,
        "currency": order.currency,
        "name": store.name,
        "mode": account.mode,
        "prefill": {
            "name": order.customer["name"],
            "contact": order.customer["phone"],
            "email": order.customer.get("email") or "",
        },
    }


async def _create_legacy_gateway_order(db, order, account):
    result = await payments.gateway_request(
        account,
        "POST",
        "orders",
        {
            "amount": order.total,
            "currency": order.currency,
            "receipt": str(order.id),
            "partial_payment": False,
        },
    )
    if (
        not str(result.get("id", "")).startswith("order_")
        or result.get("amount") != order.total
        or result.get("currency") != order.currency
    ):
        raise HTTPException(502, "Razorpay returned an inconsistent order")
    order.gateway_credentials = payments.snapshot_account(account)
    order.gateway_order_id = result["id"]
    await db.commit()


@router.post("/shop-api/{slug}/orders/{order_id}/razorpay/verify")
async def verify_payment(
    slug: str,
    order_id: UUID,
    body: VerifyInput,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    _, order = await authorized_order(db, slug, order_id, authorization)
    account = payments.order_account(
        order, await payments.require_gateway(db, order.seller_id, enabled=False)
    )
    if not order.gateway_order_id or body.razorpay_order_id != order.gateway_order_id:
        raise HTTPException(400, "Payment order does not match")
    message = f"{order.gateway_order_id}|{body.razorpay_payment_id}".encode()
    if not payments.valid_signature(
        message, body.razorpay_signature, payments.decrypt(account.key_secret)
    ):
        raise HTTPException(400, "Invalid payment signature")
    payment = await payments.gateway_request(
        account, "GET", "payments/" + body.razorpay_payment_id
    )
    await payments.apply_captured_payment(db, order, payment)
    await db.commit()
    return {
        "payment_status": order.payment_status,
        "fulfillment_status": order.fulfillment_status,
    }


@router.post("/webhooks/razorpay/{seller_id}")
async def webhook(
    seller_id: UUID, request: Request, db: AsyncSession = Depends(get_db)
):
    account = await payments.require_gateway(db, seller_id, enabled=False)
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > 262144:
            raise HTTPException(413, "Webhook body too large")
        chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        event = json.loads(raw)
        if event.get("event") not in {"payment.captured", "order.paid"}:
            if not payments.valid_signature(
                raw,
                request.headers.get("x-razorpay-signature"),
                payments.decrypt(account.webhook_secret),
            ):
                raise HTTPException(400, "Invalid webhook signature")
            return {"received": True, "ignored": True}
        payment = event["payload"]["payment"]["entity"]
        gateway_id = payment["order_id"]
        if not isinstance(gateway_id, str):
            raise ValueError()
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(400, "Invalid payment webhook")
    order = await db.scalar(
        select(CommerceOrder)
        .where(
            CommerceOrder.seller_id == seller_id,
            CommerceOrder.gateway_order_id == gateway_id,
        )
        .with_for_update()
    )
    signing_account = payments.order_account(order, account) if order else account
    if not payments.valid_signature(
        raw,
        request.headers.get("x-razorpay-signature"),
        payments.decrypt(signing_account.webhook_secret),
    ):
        raise HTTPException(400, "Invalid webhook signature")
    if order is None:
        # Other integrations can share this Razorpay account.
        return {"received": True, "ignored": True}
    await payments.apply_captured_payment(db, order, payment)
    await db.commit()
    return {"received": True}


@router.post("/commerce/orders/{order_id}/reconcile-payment")
async def reconcile(
    order_id: UUID,
    seller_id: str = Depends(current_seller_id),
    db: AsyncSession = Depends(get_db),
):
    order = await db.scalar(
        select(CommerceOrder)
        .where(CommerceOrder.id == order_id, CommerceOrder.seller_id == seller_id)
        .with_for_update()
    )
    if not order or not order.gateway_order_id:
        raise HTTPException(404, "Online order not found")
    account = payments.order_account(
        order, await payments.require_gateway(db, order.seller_id, enabled=False)
    )
    result = await payments.gateway_request(
        account, "GET", f"orders/{order.gateway_order_id}/payments"
    )
    for payment in result.get("items", []):
        if payment.get("status") == "captured":
            await payments.apply_captured_payment(db, order, payment)
    await db.commit()
    return {
        "payment_status": order.payment_status,
        "fulfillment_status": order.fulfillment_status,
    }
