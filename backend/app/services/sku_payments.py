"""Durable no-blind-retry boundary around SKU Razorpay order creation.

Captured-payment authority remains in razorpay_payments.apply_captured_payment.
"""
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from app.models.checkout_v1 import SKUPaymentAttempt
from app.models.commerce import CommerceOrder
from app.services import razorpay_payments as payments


def matches(order, result, expected_id=None):
    return (isinstance(result, dict) and isinstance(result.get("id"), str)
        and result["id"].startswith("order_") and (expected_id is None or result["id"] == expected_id)
        and type(result.get("amount")) is int and result["amount"] == order.total
        and result.get("currency") == order.currency and result.get("receipt") == str(order.id))


def eligible(order):
    if (order.payment_method != "razorpay" or order.payment_status != "pending"
            or order.fulfillment_status != "pending" or order.stock_released
            or (order.expires_at and order.expires_at <= datetime.now(timezone.utc))):
        raise HTTPException(409, "This order is no longer awaiting payment")


async def ensure_gateway_order(db, order, account):
    """Caller holds order lock. Commit before provider POST, then reacquire lock.

    A process dying after the first commit leaves requesting; it cannot POST again.
    Every uncertain result (including transport errors) requires exact reconciliation.
    """
    eligible(order)
    if order.gateway_order_id:
        return
    attempt = await db.get(SKUPaymentAttempt, order.id)
    if attempt is not None:
        raise HTTPException(409, "Payment order creation is uncertain; seller reconciliation is required")
    attempt = SKUPaymentAttempt(order_id=order.id, state="requesting")
    db.add(attempt)
    order.gateway_credentials = payments.snapshot_account(account)
    order_id, total, currency = order.id, order.total, order.currency
    await db.commit()
    try:
        result = await payments.gateway_request(account, "POST", "orders", {
            "amount": total, "currency": currency, "receipt": str(order_id), "partial_payment": False})
    except Exception:
        order = await db.scalar(select(CommerceOrder).where(CommerceOrder.id == order_id).with_for_update())
        attempt = await db.get(SKUPaymentAttempt, order_id)
        attempt.state = "unknown"
        await db.commit()
        raise HTTPException(409, "Payment order creation is uncertain; seller reconciliation is required")
    order = await db.scalar(select(CommerceOrder).where(CommerceOrder.id == order_id).with_for_update()
        .execution_options(populate_existing=True))
    attempt = await db.get(SKUPaymentAttempt, order_id)
    if not matches(order, result) or (order.gateway_order_id and order.gateway_order_id != result["id"]):
        attempt.state = "unknown"
        await db.commit()
        raise HTTPException(409, "Payment order response needs seller reconciliation")
    # Cancellation/expiry can proceed while the provider is working. Preserve the
    # provider identity for late callbacks, but never reopen or repay that order.
    order.gateway_order_id = result["id"]
    attempt.state = "ready"
    await db.commit()
    eligible(order)


async def reconcile_gateway_order(db, order, gateway_order_id):
    attempt = await db.get(SKUPaymentAttempt, order.id)
    if attempt is None:
        raise HTTPException(409, "No uncertain SKU payment attempt exists")
    if order.gateway_order_id and order.gateway_order_id != gateway_order_id:
        raise HTTPException(409, "Payment order is already associated")
    account = payments.order_account(order, await payments.require_gateway(db, order.seller_id, enabled=False))
    # Verified official endpoint, fixed origin/path and validated provider ID.
    result = await payments.gateway_request(account, "GET", "orders/" + gateway_order_id)
    if not matches(order, result, gateway_order_id):
        raise HTTPException(409, "Provider order does not match this order's receipt, amount and currency")
    order.gateway_order_id = gateway_order_id
    attempt.state = "ready"
    await db.flush()
    return {"gateway_order_id": gateway_order_id, "attempt_state": attempt.state,
        "payment_status": order.payment_status}
