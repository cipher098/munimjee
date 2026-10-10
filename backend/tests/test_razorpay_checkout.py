"""DB/API payment regressions; only outbound Razorpay transport is stubbed."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock
import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from app.main import app
from app.database import get_db
from app.config import settings
from app.api.dashboard_auth import _make_token
from app.models import Seller, Product
from app.models.commerce import Storefront, CommerceCustomer, CommerceOrder
from app.models.razorpay import RazorpayAccount
from app.services import razorpay_payments as payments
from app.services.commerce import order_token
from tests.conftest_db import db_session  # noqa: F401


@pytest_asyncio.fixture
async def shop(db_session, monkeypatch):
    monkeypatch.setattr(
        settings, "PAYMENT_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    seller = Seller(id=uuid4(), email=f"{uuid4()}@example.com", password_hash="unused")
    db_session.add(seller)
    await db_session.flush()
    store = Storefront(
        seller_id=seller.id, name="Test shop", slug="test-shop", published=True
    )
    product = Product(
        id=uuid4(),
        seller_id=seller.id,
        name="Kurta",
        listed_price=12000,
        floor_price=8000,
        stock_quantity=4,
    )
    customer = CommerceCustomer(
        id=uuid4(), seller_id=seller.id, name="Test customer", phone="+919876543210"
    )
    db_session.add_all([store, product, customer])
    await db_session.flush()
    order = CommerceOrder(
        id=uuid4(),
        seller_id=seller.id,
        customer_id=customer.id,
        idempotency_key=uuid4(),
        request_hash="a" * 64,
        customer={"name": "Test customer", "phone": "+919876543210"},
        address={"line1": "123 Test Road"},
        items=[
            {
                "product_id": str(product.id),
                "name": "Kurta",
                "quantity": 1,
                "unit_price": 12000,
                "_stock_reserved": True,
            }
        ],
        subtotal=12000,
        shipping_fee=500,
        total=12500,
        payment_method="razorpay",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=20),
    )
    account = RazorpayAccount(
        seller_id=seller.id,
        key_id="rzp_test_demo",
        key_secret=payments.encrypt("secret-for-api"),
        webhook_secret=payments.encrypt("secret-for-webhooks"),
        mode="test",
        enabled=True,
    )
    db_session.add_all([order, account])
    await db_session.commit()
    state = SimpleNamespace(
        seller=seller.id,
        order=order.id,
        product=product.id,
        token=order_token(order),
        db=db_session,
    )

    async def database():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db] = database
    state.gateway = AsyncMock(
        return_value={"id": "order_test123", "amount": 12500, "currency": "INR"}
    )
    monkeypatch.setattr(payments, "gateway_request", state.gateway)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        state.client = client
        yield state
    app.dependency_overrides.clear()


def headers(s):
    return {"Authorization": "Bearer " + s.token}


def path(s):
    return f"/shop-api/test-shop/orders/{s.order}/razorpay"


def captured(**overrides):
    return {
        "id": "pay_test123",
        "order_id": "order_test123",
        "amount": 12500,
        "currency": "INR",
        "status": "captured",
        "captured": True,
        **overrides,
    }


def signed_event(payment):
    body = json.dumps(
        {"event": "payment.captured", "payload": {"payment": {"entity": payment}}}
    ).encode()
    signature = hmac.new(b"secret-for-webhooks", body, hashlib.sha256).hexdigest()
    return body, {"x-razorpay-signature": signature, "Content-Type": "application/json"}


async def test_server_creates_and_reuses_gateway_order(shop):
    response = await shop.client.post(path(shop), headers=headers(shop))
    assert response.status_code == 200, response.text
    assert response.json()["amount"] == 12500 and response.json()["mode"] == "test"
    assert "secret" not in response.text
    assert (
        await shop.client.post(path(shop), headers=headers(shop))
    ).status_code == 200
    assert shop.gateway.await_count == 1
    assert shop.gateway.call_args.args[3]["amount"] == 12500
    assert (await shop.db.get(CommerceOrder, shop.order)).payment_status == "pending"


async def test_order_capability_is_required(shop):
    assert (await shop.client.post(path(shop))).status_code == 404
    assert (
        await shop.client.post(path(shop), headers={"Authorization": "Bearer wrong"})
    ).status_code == 404
    assert shop.gateway.await_count == 0


async def test_customer_signature_needs_exact_captured_payment(shop):
    await shop.client.post(path(shop), headers=headers(shop))
    body = {
        "razorpay_order_id": "order_test123",
        "razorpay_payment_id": "pay_test123",
        "razorpay_signature": "0" * 64,
    }
    assert (
        await shop.client.post(path(shop) + "/verify", json=body, headers=headers(shop))
    ).status_code == 400
    body["razorpay_signature"] = hmac.new(
        b"secret-for-api", b"order_test123|pay_test123", hashlib.sha256
    ).hexdigest()
    shop.gateway.return_value = captured(status="authorized", captured=False)
    assert (
        await shop.client.post(path(shop) + "/verify", json=body, headers=headers(shop))
    ).status_code == 409
    assert (await shop.db.get(CommerceOrder, shop.order)).payment_status == "pending"
    shop.gateway.return_value = captured()
    result = await shop.client.post(
        path(shop) + "/verify", json=body, headers=headers(shop)
    )
    assert result.status_code == 200, result.text
    assert result.json()["payment_status"] == "paid"


@pytest.mark.parametrize(
    "overrides",
    [{"amount": 1}, {"currency": "USD"}, {"captured": False}, {"status": "authorized"}],
)
async def test_webhook_rejects_wrong_settlement(shop, overrides):
    await shop.client.post(path(shop), headers=headers(shop))
    body, eventheaders = signed_event(captured(**overrides))
    result = await shop.client.post(
        f"/webhooks/razorpay/{shop.seller}", content=body, headers=eventheaders
    )
    assert result.status_code == 409, result.text
    assert (await shop.db.get(CommerceOrder, shop.order)).payment_status == "pending"


async def test_webhook_signature_and_replay(shop):
    await shop.client.post(path(shop), headers=headers(shop))
    body, eventheaders = signed_event(captured())
    url = f"/webhooks/razorpay/{shop.seller}"
    assert (
        await shop.client.post(
            url, content=body, headers={**eventheaders, "x-razorpay-signature": "wrong"}
        )
    ).status_code == 400
    for _ in range(2):
        response = await shop.client.post(url, content=body, headers=eventheaders)
        assert response.status_code == 200, response.text
    order = await shop.db.get(CommerceOrder, shop.order)
    assert order.payment_status == "paid" and order.gateway_payment_id == "pay_test123"
    assert (await shop.db.get(Product, shop.product)).stock_quantity == 4


async def test_late_payment_requires_review_and_releases_stock_once(shop):
    await shop.client.post(path(shop), headers=headers(shop))
    order = await shop.db.get(CommerceOrder, shop.order)
    order.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await shop.db.commit()
    body, eventheaders = signed_event(captured())
    for _ in range(2):
        response = await shop.client.post(
            f"/webhooks/razorpay/{shop.seller}", content=body, headers=eventheaders
        )
        assert response.status_code == 200, response.text
    await shop.db.refresh(order)
    assert (
        order.payment_status == "review_required"
        and order.fulfillment_status == "cancelled"
    )
    assert (await shop.db.get(Product, shop.product)).stock_quantity == 5


async def test_settings_are_scoped_and_never_return_secrets(shop):
    shop.client.cookies.set(
        "dashboard_session", _make_token("seller", str(shop.seller), "seller")
    )
    result = await shop.client.get("/commerce/razorpay")
    assert result.status_code == 200 and result.json()["configured"]
    assert "key_secret" not in result.json() and "webhook_secret" not in result.json()
    other = Seller(id=uuid4(), email=f"{uuid4()}@example.com", password_hash="unused")
    shop.db.add(other)
    await shop.db.commit()
    shop.client.cookies.clear()
    shop.client.cookies.set(
        "dashboard_session", _make_token("seller", str(other.id), "other")
    )
    assert (await shop.client.get("/commerce/razorpay")).json()["configured"] is False
    assert (
        await shop.client.post(f"/commerce/orders/{shop.order}/reconcile-payment")
    ).status_code == 404


async def test_configuration_encrypted_and_rotation_blocked_with_pending_order(shop):
    shop.client.cookies.set(
        "dashboard_session", _make_token("seller", str(shop.seller), "seller")
    )
    body = {
        "key_id": "rzp_test_newkey",
        "key_secret": "new-key-secret",
        "webhook_secret": "new-webhook-secret",
        "mode": "test",
        "enabled": True,
    }
    assert (await shop.client.put("/commerce/razorpay", json=body)).status_code == 409
    order = await shop.db.get(CommerceOrder, shop.order)
    order.payment_status = "expired"
    await shop.db.commit()
    result = await shop.client.put("/commerce/razorpay", json=body)
    assert result.status_code == 200, result.text
    account = await shop.db.get(RazorpayAccount, shop.seller)
    assert (
        account.key_secret != "new-key-secret"
        and payments.decrypt(account.key_secret) == "new-key-secret"
    )
    assert "new-key-secret" not in result.text and shop.gateway.await_count == 1


async def test_old_payment_keeps_credential_snapshot_after_rotation(shop):
    await shop.client.post(path(shop), headers=headers(shop))
    order = await shop.db.get(CommerceOrder, shop.order)
    assert order.gateway_credentials["key_secret"] != "secret-for-api"
    order.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    account = await shop.db.get(RazorpayAccount, shop.seller)
    account.key_secret = payments.encrypt("rotated-key-secret")
    account.webhook_secret = payments.encrypt("rotated-webhook-secret")
    await shop.db.commit()
    body, eventheaders = signed_event(captured())
    response = await shop.client.post(
        f"/webhooks/razorpay/{shop.seller}", content=body, headers=eventheaders
    )
    assert response.status_code == 200, response.text
    assert (
        await shop.db.get(CommerceOrder, shop.order)
    ).payment_status == "review_required"


def test_invalid_signature_characters_are_rejected():
    assert not payments.valid_signature(b"payload", "é" * 64, "secret")
    assert not payments.valid_signature(b"payload", None, "secret")


async def test_invalid_encryption_disables_payment_option(shop, monkeypatch):
    monkeypatch.setattr(settings, "PAYMENT_ENCRYPTION_KEY", "invalid")
    response = await shop.client.get("/shop-api/test-shop/payment-options")
    assert response.status_code == 200
    assert response.json()["razorpay_enabled"] is False
