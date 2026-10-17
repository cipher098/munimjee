"""Real HTTP routes, native session/CSRF/tenant checks, and fake gateway transports."""
import asyncio
from pathlib import Path
import json
from uuid import uuid4
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from cryptography.fernet import Fernet

from app.api.v1.catalogue import router
from app.api.routes.commerce import public_router as legacy_public_router
from app.config import settings
from app.database import get_db
from app.models.identity import User, Membership
from app.models.identity_auth import UserSession
from app.models.checkout_v1 import SKUPaymentAttempt
from app.models.commerce import CommerceOrder
from app.models.product import Product
from app.models.razorpay import RazorpayAccount
from app.schemas.checkout_v1 import ProductRead, ProductCreate, CheckoutWrite, PUBLIC_PRODUCT_FIELDS
from app.services.auth_sessions import issue_session
from app.services import razorpay_payments as payments
from tests.test_v1_checkout import seed


@pytest_asyncio.fixture
async def api(migrated_engine, monkeypatch):
    monkeypatch.setattr(settings, "V1_AUTH_ENABLED", True)
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(router)
    app.include_router(legacy_public_router)
    async def database():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    app.dependency_overrides[get_db] = database
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, factory


async def actor(factory, business, role="owner"):
    async with factory.begin() as db:
        user = User(id=uuid4(), display_name="Synthetic operator", is_active=True)
        db.add(user)
        await db.flush()
        db.add(Membership(id=uuid4(), business_id=business, user_id=user.id, role=role, is_active=True))
        token, csrf, session = await issue_session(db, user)
        return {"Authorization": "Bearer " + token}, token, csrf, session.id


def create_body():
    return json.loads((Path(__file__).resolve().parents[2] / "docs/contracts/catalogue-v2/product-create.json").read_text())


def checkout_body(sku_id):
    data = json.loads((Path(__file__).resolve().parents[2] / "docs/contracts/catalogue-v2/checkout-write.json").read_text())
    data["items"][0]["sku_id"] = str(sku_id)
    data["idempotency_key"] = str(uuid4())
    return data


@pytest.mark.asyncio
async def test_reviewed_create_activation_public_browse_checkout_and_protected_status(api):
    client, factory = api
    bid, _, _ = await seed(factory, activate=False, enabled=False)
    headers, *_ = await actor(factory, bid)
    prefix = f"/api/v1/businesses/{bid}/catalogue"
    async with factory() as db:
        from app.models.commerce import Storefront
        slug = (await db.get(Storefront, bid)).slug
    public = f"/api/v1/storefronts/{slug}"
    assert (await client.get(public + "/products")).json()["items"] == []
    body = create_body()
    made = await client.post(prefix + "/products", json=body, headers=headers)
    assert made.status_code == 201, made.text
    data = made.json()
    pid = data["product"]["product_id"]
    assert data["inventory_mode"] == "legacy" and not data["product"]["checkout_enabled"]
    assert (await client.post(prefix + "/products", json=body, headers=headers)).status_code == 200
    async with factory() as db:
        from uuid import UUID
        assert not (await db.get(Product, UUID(pid))).active  # no accidental legacy listing
    assert (await client.get(public + "/products/" + pid)).status_code == 404
    activated = await client.post(prefix + f"/products/{pid}/activate", headers=headers, json={
        "seller_reviewed": True, "expected_mapping_revision": data["mapping_revision"],
        "expected_legacy_fingerprint": data["legacy_fingerprint"]})
    assert activated.status_code == 200, activated.text
    assert not activated.json()["product"]["checkout_enabled"]
    assert (await client.put(prefix + "/checkout-policy", headers=headers, json={"checkout_enabled": True})).status_code == 200
    product = (await client.get(public + "/products/" + pid)).json()
    assert set(product) == PUBLIC_PRODUCT_FIELDS and product["mode"] == "operational"
    assert "floor_price" not in json.dumps(product)
    assert product["checkout_enabled"] and product["skus"][0]["price_minor"] == 129900
    assert (await client.get(f"/shop-api/{slug}/products/{pid}")).status_code == 404
    assert (await client.get(f"/shop-api/{slug}/products")).json()["items"] == []
    request = checkout_body(product["skus"][0]["sku_id"])
    placed = await client.post(public + "/checkout", json=request)
    assert placed.status_code == 201, placed.text
    order = placed.json()
    assert order["total"] == 129900 and order["items"][0]["options"] == {"Size": "S"}
    assert not any(k.startswith("_") for k in order["items"][0])
    replay = await client.post(public + "/checkout", json=request)
    assert replay.status_code == 200 and replay.json()["id"] == order["id"]
    status = public + "/orders/" + order["id"]
    assert (await client.get(status)).status_code == 404
    assert (await client.get(status, headers={"Authorization": "Bearer wrong"})).status_code == 404
    assert (await client.get(status, headers={"Authorization": "Bearer " + order["access_token"]})).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["staff", "viewer"])
async def test_capabilities_and_foreign_business_are_enforced(api, role):
    client, factory = api
    bid, _, _ = await seed(factory)
    foreign, _, _ = await seed(factory)
    headers, *_ = await actor(factory, bid, role)
    path = f"/api/v1/businesses/{bid}/catalogue/products"
    assert (await client.get(path, headers=headers)).status_code == 200
    assert (await client.post(path, headers=headers, json=create_body())).status_code == 403
    assert (await client.get(f"/api/v1/businesses/{foreign}/catalogue/products", headers=headers)).status_code == 404
    assert (await client.post(path, json=create_body())).status_code == 401


@pytest.mark.asyncio
async def test_cookie_csrf_origin_and_revoked_sessions_block_mutations(api):
    client, factory = api
    bid, _, _ = await seed(factory)
    _, token, csrf, sid = await actor(factory, bid)
    path = f"/api/v1/businesses/{bid}/catalogue/checkout-policy"
    client.cookies.set("v1_session", token)
    client.cookies.set("v1_csrf", csrf)
    payload = {"checkout_enabled": False}
    assert (await client.put(path, json=payload)).status_code == 403
    assert (await client.put(path, json=payload, headers={"Origin": "https://evil.invalid", "X-CSRF-Token": csrf})).status_code == 403
    assert (await client.put(path, json=payload, headers={"Origin": "http://test", "X-CSRF-Token": csrf})).status_code == 200
    async with factory.begin() as db:
        from datetime import datetime, timezone
        (await db.get(UserSession, sid)).revoked_at = datetime.now(timezone.utc)
    assert (await client.get(path)).status_code == 401


@pytest.mark.asyncio
async def test_checkout_rejects_customer_price_tenant_and_invalid_quantities(api):
    client, factory = api
    bid, _, ids = await seed(factory)
    from app.models.commerce import Storefront
    async with factory() as db:
        slug = (await db.get(Storefront, bid)).slug
    path = f"/api/v1/storefronts/{slug}/checkout"
    for name, value in (("price_minor", 1), ("business_id", str(uuid4())), ("stock_available", 999)):
        body = checkout_body(ids[0])
        body["items"][0][name] = value
        assert (await client.post(path, json=body)).status_code == 422
    for quantity in (True, 0, -1, "1", 21):
        body = checkout_body(ids[0])
        body["items"][0]["quantity"] = quantity
        assert (await client.post(path, json=body)).status_code == 422


async def online_order(api, monkeypatch):
    client, factory = api
    monkeypatch.setattr(settings, "V1_PUBLIC_PAYMENTS_ENABLED", True)
    monkeypatch.setattr(settings, "PAYMENT_ENCRYPTION_KEY", Fernet.generate_key().decode())
    bid, _, ids = await seed(factory)
    from app.models.commerce import Storefront
    async with factory.begin() as db:
        db.add(RazorpayAccount(seller_id=bid, key_id="rzp_test_synthetic", key_secret=payments.encrypt("synthetic-key"),
            webhook_secret=payments.encrypt("synthetic-webhook-key"), enabled=True, mode="test"))
        slug = (await db.get(Storefront, bid)).slug
    payload = checkout_body(ids[0])
    payload["payment_method"] = "razorpay"
    result = await client.post(f"/api/v1/storefronts/{slug}/checkout", json=payload)
    assert result.status_code == 201, result.text
    order = result.json()
    return bid, slug, order, {"Authorization": "Bearer " + order["access_token"]}


@pytest.mark.asyncio
async def test_gateway_unknown_attempt_is_durable_no_blind_retry_and_exact_reconciliation(api, monkeypatch):
    client, factory = api
    bid, slug, order, customer = await online_order(api, monkeypatch)
    calls = []
    wrong = False
    async def fake(account, method, path, data=None):
        calls.append((method, path))
        if method == "POST":
            raise HTTPException(502, "Synthetic lost response")
        return {"id": "order_synthetic", "amount": order["total"], "currency": "INR",
            "receipt": "wrong" if wrong else order["id"]}
    monkeypatch.setattr(payments, "gateway_request", fake)
    start = f"/api/v1/storefronts/{slug}/orders/{order['id']}/razorpay"
    assert (await client.post(start, headers=customer)).status_code == 409
    assert (await client.post(start, headers=customer)).status_code == 409
    assert calls == [("POST", "orders")]
    from uuid import UUID
    async with factory() as db:
        assert (await db.get(SKUPaymentAttempt, UUID(order["id"]))).state == "unknown"
        assert (await db.get(CommerceOrder, UUID(order["id"]))).gateway_credentials
    operator, *_ = await actor(factory, bid)
    reconcile = f"/api/v1/businesses/{bid}/orders/{order['id']}/reconcile-gateway-order"
    wrong = True
    assert (await client.post(reconcile, headers=operator, json={"gateway_order_id": "order_synthetic"})).status_code == 409
    wrong = False
    response = await client.post(reconcile, headers=operator, json={"gateway_order_id": "order_synthetic"})
    assert response.status_code == 200 and response.json()["payment_status"] == "pending"
    assert (await client.post(start, headers=customer)).json()["order_id"] == "order_synthetic"
    assert len([c for c in calls if c[0] == "POST"]) == 1


@pytest.mark.asyncio
async def test_competing_payment_creation_posts_once_and_replays_ready_order(api, monkeypatch):
    client, _ = api
    _, slug, order, customer = await online_order(api, monkeypatch)
    calls = []
    async def fake(account, method, path, data=None):
        calls.append((method, path))
        await asyncio.sleep(0.02)
        return {"id": "order_synthetic", "amount": data["amount"], "currency": data["currency"], "receipt": data["receipt"]}
    monkeypatch.setattr(payments, "gateway_request", fake)
    start = f"/api/v1/storefronts/{slug}/orders/{order['id']}/razorpay"
    results = await asyncio.gather(client.post(start, headers=customer), client.post(start, headers=customer))
    assert all(r.status_code in (200, 409) for r in results)
    assert any(r.status_code == 200 for r in results)
    assert calls == [("POST", "orders")]
    assert (await client.post(start, headers=customer)).status_code == 200
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_cancellation_during_provider_call_keeps_stock_released_and_provider_identity(api, monkeypatch):
    client, factory = api
    bid, slug, order, customer = await online_order(api, monkeypatch)
    operator, *_ = await actor(factory, bid)
    started, finish = asyncio.Event(), asyncio.Event()
    async def fake(account, method, path, data=None):
        started.set()
        await finish.wait()
        return {"id": "order_synthetic", "amount": data["amount"], "currency": data["currency"], "receipt": data["receipt"]}
    monkeypatch.setattr(payments, "gateway_request", fake)
    start = f"/api/v1/storefronts/{slug}/orders/{order['id']}/razorpay"
    task = asyncio.create_task(client.post(start, headers=customer))
    await asyncio.wait_for(started.wait(), 5)
    cancelled = await client.post(f"/api/v1/businesses/{bid}/orders/{order['id']}/transition",
        headers=operator, json={"status": "cancelled"})
    assert cancelled.status_code == 200, cancelled.text
    finish.set()
    response = await asyncio.wait_for(task, 5)
    assert response.status_code == 409
    from uuid import UUID
    async with factory() as db:
        saved = await db.get(CommerceOrder, UUID(order["id"]))
        assert saved.stock_released and saved.fulfillment_status == "cancelled"
        assert saved.gateway_order_id == "order_synthetic"


@pytest.mark.asyncio
async def test_reviewed_metadata_edits_preserve_authority_and_cannot_publish_a_draft(api):
    client, factory = api
    bid, pid, _ = await seed(factory, activate=False)
    headers, *_ = await actor(factory, bid)
    path = f"/api/v1/businesses/{bid}/catalogue/products/{pid}"
    record = (await client.get(path, headers=headers)).json()
    payload = {"seller_reviewed": True, "expected_mapping_revision": record["mapping_revision"],
        "name": "Reviewed name", "description": "Updated factual copy", "category_id": None,
        "photo_urls": [], "active": True}
    assert (await client.patch(path, headers=headers, json=payload)).status_code == 409
    payload["active"] = False
    response = await client.patch(path, headers=headers, json=payload)
    assert response.status_code == 200 and response.json()["product"]["name"] == "Reviewed name"
    assert (await client.patch(path, headers=headers, json=payload)).status_code == 409


def test_frozen_operational_fixtures_and_schemas_round_trip():
    root = Path(__file__).resolve().parents[2] / "docs/contracts/catalogue-v2"
    for name, model in (("product-read", ProductRead), ("checkout-write", CheckoutWrite), ("product-create", ProductCreate)):
        data = json.loads((root / (name + ".json")).read_text())
        assert model.model_validate(data).model_dump(mode="json") == data
        assert model.model_json_schema() == json.loads((root / (name + ".schema.json")).read_text())
