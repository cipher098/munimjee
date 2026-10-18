"""Scoped public Razorpay handoff. Existing order/attempt/capture state owns authority."""
from datetime import datetime, timedelta, timezone
import math
import hashlib
import hmac
import json
import re
from types import SimpleNamespace
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy import select

from app.config import settings
from app.models.checkout_v1 import SKUPaymentAttempt
from app.models.commerce import CommerceOrder, Storefront
from app.models.identity import Business
from app.models.razorpay import RazorpayAccount
from app.models.seller import Seller
from app.schemas.checkout_sessions import CheckoutSessionRead, CheckoutStateRead, PaymentReviewRead
from app.services import razorpay_payments as payments
from app.services.commerce import authorize_order, order_token
from app.services.sku_payments import eligible, ensure_gateway_order
from app.v1.storefront.rendering import canonical_origin

ROLE = "public_checkout_session"
PURPOSE = "v1_public_checkout"
AUDIENCE = "munimjee.checkout-session.v1"
SESSION_SECONDS = 900


def now():
    return datetime.now(timezone.utc)


def new_payments_enabled():
    return bool(getattr(settings, "V1_PUBLIC_PAYMENTS_ENABLED", False))


def check_origin(request):
    """Order/session bearers are explicit, never ambient seller/native cookies."""
    supplied = request.headers.get("origin")
    if supplied is None:
        return
    try:
        configured = canonical_origin(settings.PUBLIC_BASE_URL)
    except ValueError:
        raise HTTPException(503, "Public payment origin is not configured")
    if supplied != configured:
        raise HTTPException(403, "Untrusted checkout origin")


def validate_account(account):
    """Local usability only. A real gateway canary remains a separate external gate."""
    if (account is None or getattr(account, "mode", None) not in {"test", "live"}
            or not isinstance(getattr(account, "key_id", None), str)
            or not re.fullmatch(r"rzp_" + account.mode + r"_[A-Za-z0-9]+", account.key_id)
            or any(not isinstance(getattr(account, field, None), str) for field in ("key_secret", "webhook_secret"))):
        raise HTTPException(409, "Online payment is unavailable for this storefront")
    try:
        if not 8 <= len(payments.decrypt(account.key_secret)) <= 500 or not 16 <= len(payments.decrypt(account.webhook_secret)) <= 500:
            raise ValueError()
    except (HTTPException, ValueError, TypeError):
        raise HTTPException(409, "Online payment is unavailable for this storefront")
    return account


async def current_account(db, seller_id):
    # Current scalar fields, independent of retained ORM authorization/config state.
    row = (await db.execute(select(RazorpayAccount.key_id, RazorpayAccount.key_secret,
        RazorpayAccount.webhook_secret, RazorpayAccount.mode, RazorpayAccount.enabled).where(
        RazorpayAccount.seller_id == seller_id).execution_options(autoflush=False))).one_or_none()
    return SimpleNamespace(**row._mapping) if row else None


async def require_public_gateway(db, seller_id):
    if not new_payments_enabled():
        raise HTTPException(409, "Online checkout is not enabled for this storefront")
    active = await db.scalar(select(Business.id).join(Seller, Seller.id == Business.id).where(
        Business.id == seller_id, Business.is_active.is_(True), Seller.is_active.is_(True))
        .execution_options(autoflush=False))
    if active is None:
        raise HTTPException(409, "Online payment is unavailable for this storefront")
    account = await current_account(db, seller_id)
    if account is None or account.enabled is not True:
        raise HTTPException(409, "Online payment is unavailable for this storefront")
    return validate_account(account)


async def public_payment_options(slug, db):
    """Versioned projector only; legacy Product gateway options are unchanged."""
    store = await db.scalar(select(Storefront).join(Seller, Seller.id == Storefront.seller_id).join(
        Business, Business.id == Storefront.seller_id).where(Storefront.slug == slug,
        Storefront.published.is_(True), Seller.is_active.is_(True), Business.is_active.is_(True)))
    if store is None:
        raise HTTPException(404, "Store not found")
    account = None
    try:
        account = await require_public_gateway(db, store.seller_id)
    except HTTPException:
        pass
    return {"cod_enabled": store.cod_enabled, "razorpay_enabled": account is not None,
        "razorpay_mode": account.mode if account else None}


async def authorized_order(db, slug, order_id, authorization):
    # Status/settlement survives publication changes. Match stock writer lock order.
    store = await db.scalar(select(Storefront).where(Storefront.slug == slug).with_for_update())
    order = await db.scalar(select(CommerceOrder).where(CommerceOrder.id == order_id,
        CommerceOrder.seller_id == store.seller_id).with_for_update().execution_options(
        populate_existing=True)) if store else None
    authorize_order(order, authorization)
    if order.payment_method != "razorpay" or not order.items or any(
            item.get("_inventory_engine") != "sku.v1" for item in order.items):
        raise HTTPException(409, "This order does not use online SKU checkout")
    if type(order.total) is not int or not 100 <= order.total <= 2_000_000_000 or order.currency != "INR":
        raise HTTPException(409, "Order payment facts are invalid")
    return store, order


def order_pending(order):
    return (order.payment_status == "pending" and order.fulfillment_status == "pending"
        and not order.stock_released and order.expires_at is not None and order.expires_at > now())


async def state(db, order):
    attempt = await db.scalar(select(SKUPaymentAttempt).where(SKUPaymentAttempt.order_id == order.id)
        .execution_options(populate_existing=True))
    attempt_state = attempt.state if attempt else "not_started"
    retry = False
    if order_pending(order) and attempt_state not in {"requesting", "unknown"}:
        try:
            if order.gateway_order_id:
                validate_account(payments.order_account(order, await current_account(db, order.seller_id)))
                retry = attempt_state == "ready"
            elif attempt is None:
                await require_public_gateway(db, order.seller_id)
                retry = True
        except HTTPException:
            pass
    return CheckoutStateRead(order_id=order.id, amount_minor=order.total, currency=order.currency,
        payment_status=order.payment_status, fulfillment_status=order.fulfillment_status,
        attempt_state=attempt_state, expires_at=order.expires_at, retry_allowed=retry)


def issue_capability(order):
    if not order.expires_at or not order.gateway_order_id:
        raise HTTPException(409, "The payment session is not ready")
    expires = min(int(order.expires_at.timestamp()), int((now() + timedelta(seconds=SESSION_SECONDS)).timestamp()))
    if expires <= int(now().timestamp()):
        raise HTTPException(409, "The payment reservation expired")
    claims = {"role": ROLE, "purpose": PURPOSE, "aud": AUDIENCE, "sub": str(order.id),
        "business_id": str(order.seller_id), "gateway_order_id": order.gateway_order_id,
        "amount_minor": order.total, "currency": order.currency, "jti": str(uuid4()),
        "iat": int(now().timestamp()), "exp": expires}
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM), datetime.fromtimestamp(expires, timezone.utc)


def decode_capability(authorization):
    try:
        if not authorization or not authorization.startswith("Bearer ") or len(authorization) > 4200:
            raise ValueError()
        claims = jwt.decode(authorization[7:], settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM],
            audience=AUDIENCE, options={"require_exp": True, "require_sub": True, "require_aud": True})
        if (set(claims) != {"role", "purpose", "aud", "sub", "business_id", "gateway_order_id", "amount_minor", "currency", "jti", "iat", "exp"}
                or claims["role"] != ROLE or claims["purpose"] != PURPOSE or claims["aud"] != AUDIENCE
                or type(claims["amount_minor"]) is not int or not 100 <= claims["amount_minor"] <= 2_000_000_000
                or claims["currency"] != "INR" or not isinstance(claims["gateway_order_id"], str)
                or not re.fullmatch(r"order_[A-Za-z0-9]+", claims["gateway_order_id"])
                or type(claims["exp"]) is not int or type(claims["iat"]) is not int
                or claims["exp"] - claims["iat"] > SESSION_SECONDS or claims["iat"] > int(now().timestamp()) + 5):
            raise ValueError()
        for field in ("sub", "business_id", "jti"):
            UUID(claims[field])
        return claims
    except (JWTError, ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(401, "Payment session is invalid or expired")


async def create_session(db, store, order):
    eligible(order)
    if not order.gateway_order_id:
        attempt = await db.get(SKUPaymentAttempt, order.id)
        if attempt is not None:
            raise HTTPException(409, "Payment setup needs seller reconciliation; do not place another order")
        account = await require_public_gateway(db, order.seller_id)
        await ensure_gateway_order(db, order, account)
    account = validate_account(payments.order_account(order, await current_account(db, order.seller_id)))
    token, expires = issue_capability(order)
    path = "/api/v1/storefronts/" + quote(store.slug, safe="") + "/orders/" + str(order.id)
    return CheckoutSessionRead(order_id=order.id, provider_order_id=order.gateway_order_id,
        key_id=account.key_id, mode=account.mode, amount_minor=order.total, currency=order.currency,
        session_token=token, expires_at=expires, merchant_name=store.name,
        prefill={"name": order.customer["name"], "contact": order.customer["phone"], "email": order.customer.get("email") or ""},
        verify_url=path + "/checkout-session/verify", status_url=path + "/checkout-session", order_status_url=path)


async def verify_session(db, slug, order_id, authorization, payload):
    claims = decode_capability(authorization)
    # Validate capability scope before deriving the existing signed order bearer.
    store = await db.scalar(select(Storefront).where(Storefront.slug == slug).with_for_update())
    order = await db.scalar(select(CommerceOrder).where(CommerceOrder.id == order_id,
        CommerceOrder.seller_id == store.seller_id).with_for_update().execution_options(
        populate_existing=True)) if store else None
    if (order is None or claims["sub"] != str(order_id) or claims["business_id"] != str(order.seller_id)
            or claims["gateway_order_id"] != order.gateway_order_id or claims["amount_minor"] != order.total
            or claims["currency"] != order.currency or not order.expires_at
            or claims["exp"] > math.floor(order.expires_at.timestamp())):
        raise HTTPException(404, "Order not found")
    # The existing verifier owns HMAC validation, snapshotted seller credentials,
    # exact captured amount/currency, immutable payment identity and late refund review.
    from app.api.routes.razorpay import verify_payment
    await verify_payment(slug, order_id, payload, "Bearer " + order_token(order), db)
    return await state(db, order)


async def payment_review(db, business_id, order_id):
    # Native callers authorize the business first; scalar facts bypass retained ORM
    # state and never expose customer bearers, prefill or credential snapshots.
    row = (await db.execute(select(CommerceOrder.id, CommerceOrder.payment_method,
        CommerceOrder.items, CommerceOrder.gateway_order_id, CommerceOrder.payment_status,
        CommerceOrder.fulfillment_status).where(CommerceOrder.id == order_id,
        CommerceOrder.seller_id == business_id).execution_options(autoflush=False))).one_or_none()
    if row is None:
        raise HTTPException(404, "Order not found")
    attempt = await db.scalar(select(SKUPaymentAttempt.state).where(SKUPaymentAttempt.order_id == order_id)
        .execution_options(autoflush=False))
    sku_online = row.payment_method == "razorpay" and bool(row.items) and all(
        item.get("_inventory_engine") == "sku.v1" for item in row.items)
    eligible = (sku_online and attempt is not None
        and row.payment_status not in {"paid", "collected", "review_required"}
        and ((row.gateway_order_id is None and attempt in {"requesting", "unknown"})
            or (row.gateway_order_id is not None and attempt == "ready")))
    return PaymentReviewRead(order_id=row.id, attempt_state=attempt or "not_started",
        gateway_order_id=row.gateway_order_id, payment_status=row.payment_status,
        fulfillment_status=row.fulfillment_status, reconciliation_eligible=eligible)


def gateway_configuration_revision(business_id, account):
    """Opaque version of the exact stored ciphertext/configuration, not secrets.

    The business ID and domain separate absent and configured states. This never
    decrypts credentials and cannot be used as a provider or native capability.
    """
    facts = {"business_id": str(business_id), "configured": account is not None}
    if account is not None:
        facts.update({name: getattr(account, name) for name in (
            "key_id", "mode", "enabled", "key_secret", "webhook_secret")})
    raw = b"munimjee.gateway-configuration.v1\0" + json.dumps(facts, sort_keys=True,
        separators=(",", ":")).encode()
    return hmac.new(settings.SECRET_KEY.encode(), raw, hashlib.sha256).hexdigest()


async def gateway_configuration_view(db, business_id, request):
    from app.api.routes.razorpay import settings_json
    from app.schemas.checkout_sessions import GatewayConfigurationRead
    account = await current_account(db, business_id)
    return GatewayConfigurationRead(**settings_json(account, request, business_id),
        configuration_revision=gateway_configuration_revision(business_id, account))
