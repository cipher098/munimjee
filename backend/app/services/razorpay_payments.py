"""Razorpay calls and settlement rules. Browser success is never payment authority."""

import hashlib
import hmac
import re
from types import SimpleNamespace
from datetime import datetime, timezone
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
import httpx
from sqlalchemy import select
from app.config import settings
from app.models.razorpay import RazorpayAccount
from app.services.commerce import release_stock


def cipher():
    try:
        return Fernet(settings.PAYMENT_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError):
        raise HTTPException(
            503, "Payment secret encryption is not configured on this server"
        )


def encrypt(value):
    return cipher().encrypt(value.encode()).decode()


def decrypt(value):
    try:
        return cipher().decrypt(value.encode()).decode()
    except InvalidToken:
        raise HTTPException(
            503, "Payment credentials cannot be decrypted; contact the operator"
        )


async def require_gateway(db, seller_id, *, enabled=True):
    account = await db.get(RazorpayAccount, seller_id)
    if account is None or (enabled and not account.enabled):
        raise HTTPException(409, "Online payment is unavailable for this store")
    cipher()
    return account


async def gateway_request(account, method, path, data=None):
    # Fixed origin: never derive provider URLs from merchant/customer input.
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request(
                method,
                "https://api.razorpay.com/v1/" + path,
                auth=(account.key_id, decrypt(account.key_secret)),
                json=data,
            )
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("Unexpected provider response")
            return result
    except (httpx.HTTPError, ValueError):
        # Do not expose provider response bodies or credentials in errors/logs.
        raise HTTPException(
            502, "Razorpay could not be reached or rejected the request. Please retry."
        )


def valid_signature(message, signature, secret):
    if not isinstance(signature, str) or not re.fullmatch(r"[a-f0-9]{64}", signature):
        return False
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return isinstance(signature, str) and hmac.compare_digest(expected, signature)


async def apply_captured_payment(db, order, payment):
    """Caller holds order lock. Replays are harmless and late payments need review."""
    payment_id = payment.get("id")
    if (
        not isinstance(payment_id, str)
        or not payment_id.startswith("pay_")
        or payment.get("order_id") != order.gateway_order_id
        or type(payment.get("amount")) is not int
        or payment["amount"] != order.total
        or payment.get("currency") != order.currency
        or payment.get("status") != "captured"
        or payment.get("captured") is not True
    ):
        raise HTTPException(
            409, "Payment is not captured for this order's exact amount and currency"
        )
    if order.gateway_payment_id:
        if order.gateway_payment_id != payment_id:
            raise HTTPException(409, "Order already has a different payment")
        return
    expired = order.expires_at and order.expires_at <= datetime.now(timezone.utc)
    if (
        order.stock_released
        or expired
        or order.fulfillment_status in {"cancelled", "expired"}
    ):
        # Never auto-fulfil a paid order whose stock was released. Seller must refund/review.
        await release_stock(db, order)
        order.payment_status = "review_required"
        if order.fulfillment_status not in {"cancelled", "expired"}:
            order.fulfillment_status = "cancelled"
    else:
        order.payment_status = "paid"
    order.gateway_payment_id = payment_id
    await db.flush()


def snapshot_account(account):
    return {
        key: getattr(account, key)
        for key in ("key_id", "key_secret", "webhook_secret", "mode")
    }


def order_account(order, current):
    return (
        SimpleNamespace(**order.gateway_credentials)
        if order.gateway_credentials
        else current
    )
