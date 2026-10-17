"""Actual migrated PG16 payment sessions; every provider call is a local fake."""
import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from jose import jwt
from sqlalchemy import func, select

from app.api.v1.checkout_sessions import router, configuration_router
from app.api.routes.razorpay import router as gateway_router
from app.config import settings
from app.models.catalogue_v1 import CatalogueSKU
from app.models.checkout_v1 import SKUPaymentAttempt, SKUReservation
from app.models.commerce import CommerceCustomer, CommerceOrder, Storefront
from app.models.razorpay import RazorpayAccount
from app.services import checkout_sessions as service
from app.services import razorpay_payments as payments
from app.services.commerce import expire_pending_orders
from tests.test_v1_checkout import seed
from tests.test_v1_checkout_api import api, actor, checkout_body, online_order  # noqa: F401


@pytest_asyncio.fixture
async def payment_api(api, monkeypatch):
    client, factory = api
    client._transport.app.include_router(router)
    client._transport.app.include_router(configuration_router)
    client._transport.app.include_router(gateway_router)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://127.0.0.1:8157")
    yield client, factory


def session_path(slug, order):
    return f"/api/v1/storefronts/{slug}/orders/{order['id']}/checkout-session"


def capture(order, gateway_id="order_synthetic", **changes):
    return {"id": "pay_synthetic", "order_id": gateway_id, "amount": order["total"],
        "currency": "INR", "status": "captured", "captured": True, **changes}


def callback(gateway_id="order_synthetic", key="synthetic-key"):
    return {"razorpay_order_id": gateway_id, "razorpay_payment_id": "pay_synthetic",
        "razorpay_signature": hmac.new(key.encode(), (gateway_id + "|pay_synthetic").encode(), hashlib.sha256).hexdigest()}


def fake_provider(monkeypatch, order, *, payment=None):
    calls = []
    async def fake(account, method, path, data=None):
        calls.append((account.key_id, method, path))
        if method == "POST":
            return {"id": "order_synthetic", **data}
        if path.startswith("payments/"):
            return payment or capture(order)
        return {"items": [payment or capture(order)]}
    monkeypatch.setattr(payments, "gateway_request", fake)
    return calls


@pytest.mark.asyncio
async def test_session_scope_bearer_origin_and_capability_never_authorizes_seller(payment_api, monkeypatch):
    client, factory = payment_api
    bid, slug, order, bearer = await online_order(payment_api, monkeypatch)
    calls = fake_provider(monkeypatch, order)
    path = session_path(slug, order)
    owner, cookie, *_ = await actor(factory, bid)
    client.cookies.set("v1_session", cookie)
    assert (await client.post(path)).status_code == 404
    assert (await client.post(path, headers=owner)).status_code == 404
    assert (await client.post(path, headers={**bearer, "Origin": "https://evil.invalid"})).status_code == 403
    assert calls == []
    response = await client.post(path, headers={**bearer, "Origin": settings.PUBLIC_BASE_URL})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["amount_minor"] == order["total"] and data["provider_order_id"] == "order_synthetic"
    assert not {"key_secret", "webhook_secret", "gateway_credentials"}.intersection(data)
    cap = {"Authorization": "Bearer " + data["session_token"]}
    assert (await client.get(f"/api/v1/businesses/{bid}/orders", headers=cap)).status_code == 401
    assert (await client.get(path, headers=cap)).status_code == 404
    foreign, _, _ = await seed(factory)
    async with factory() as db:
        foreign_slug = (await db.get(Storefront, foreign)).slug
    assert (await client.post(session_path(foreign_slug, order), headers=bearer)).status_code == 404
    assert (await client.post(session_path(foreign_slug, order) + "/verify", headers=cap, json=callback())).status_code == 404
    assert (await client.post(path + "/verify", headers=bearer, json=callback())).status_code == 401
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_ready_reuses_snapshot_after_rotation_flagoff_and_unpublish(payment_api, monkeypatch):
    client, factory = payment_api
    bid, slug, order, bearer = await online_order(payment_api, monkeypatch)
    calls = fake_provider(monkeypatch, order)
    path = session_path(slug, order)
    first = (await client.post(path, headers=bearer)).json()
    async with factory.begin() as db:
        account = await db.get(RazorpayAccount, bid)
        account.key_id = "rzp_test_rotated"
        account.key_secret = payments.encrypt("rotated-secret")
        account.webhook_secret = payments.encrypt("rotated-webhook-secret")
        account.enabled = False
        (await db.get(Storefront, bid)).published = False
        from app.models.identity import Business
        from app.models.seller import Seller
        (await db.get(Business, bid)).is_active = False
        (await db.get(Seller, bid)).is_active = False
    monkeypatch.setattr(settings, "V1_PUBLIC_PAYMENTS_ENABLED", False)
    second = await client.post(path, headers=bearer)
    assert second.status_code == 200, second.text
    assert second.json()["provider_order_id"] == first["provider_order_id"]
    assert second.json()["key_id"] == "rzp_test_synthetic"
    verified = await client.post(path + "/verify", headers={"Authorization": "Bearer " + first["session_token"]}, json=callback())
    assert verified.status_code == 200 and verified.json()["payment_status"] == "paid", verified.text
    assert calls == [("rzp_test_synthetic", "POST", "orders"), ("rzp_test_synthetic", "GET", "payments/pay_synthetic")]
    assert (await client.get(path, headers=bearer)).json()["retry_allowed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["flag", "disabled", "cipher", "mode", "key"])
async def test_unusable_gateway_rejected_before_new_order_and_legacy_options_preserved(payment_api, monkeypatch, corruption):
    client, factory = payment_api
    bid, slug, existing, _ = await online_order(payment_api, monkeypatch)
    async with factory.begin() as db:
        account = await db.get(RazorpayAccount, bid)
        if corruption == "disabled": account.enabled = False
        if corruption == "cipher": account.key_secret = "broken-ciphertext"
        if corruption == "mode": account.mode = "live"
        if corruption == "key": account.key_id = "wrong"
        sku_id = UUID(existing["items"][0]["sku_id"])
        before_stock = (await db.get(CatalogueSKU, sku_id)).stock_available
    if corruption == "flag": monkeypatch.setattr(settings, "V1_PUBLIC_PAYMENTS_ENABLED", False)
    body = checkout_body(sku_id)
    body["payment_method"] = "razorpay"
    response = await client.post(f"/api/v1/storefronts/{slug}/checkout", json=body)
    assert response.status_code == 409, response.text
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(CommerceOrder)) == 1
        assert await db.scalar(select(func.count()).select_from(SKUReservation)) == 1
        assert (await db.get(CatalogueSKU, sku_id)).stock_available == before_stock
        assert (await service.public_payment_options(slug, db))["razorpay_enabled"] is False
    if corruption == "flag":
        legacy = await client.get(f"/shop-api/{slug}/payment-options")
        assert legacy.status_code == 200 and legacy.json()["razorpay_enabled"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("price,shipping,method,expected", [(0,0,"razorpay",422),(0,99,"razorpay",422),(99,0,"razorpay",422),(0,100,"razorpay",201),(100,0,"razorpay",201),(0,0,"cod",201)])
async def test_online_minimum_includes_shipping_before_any_new_customer_or_reservation(payment_api, monkeypatch, price, shipping, method, expected):
    client, factory = payment_api
    bid, slug, prior, _ = await online_order(payment_api, monkeypatch)
    sku_id = UUID(prior["items"][0]["sku_id"])
    async with factory.begin() as db:
        sku = await db.get(CatalogueSKU, sku_id)
        sku.price_minor = price
        before = sku.stock_available
        (await db.get(Storefront, bid)).shipping_fee = shipping
    body = checkout_body(sku_id)
    body["payment_method"] = method
    body["customer"]["phone"] = "+919876543211"
    result = await client.post(f"/api/v1/storefronts/{slug}/checkout", json=body)
    assert result.status_code == expected, result.text
    async with factory() as db:
        added = int(expected == 201)
        assert await db.scalar(select(func.count()).select_from(CommerceOrder)) == 1 + added
        assert await db.scalar(select(func.count()).select_from(CommerceCustomer)) == 1 + added
        assert await db.scalar(select(func.count()).select_from(SKUReservation)) == 1 + added
        assert (await db.get(CatalogueSKU, sku_id)).stock_available == before - added


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [{"amount":1},{"currency":"USD"},{"captured":False},{"status":"authorized"},{"order_id":"order_foreign"}])
async def test_sdk_callback_is_not_paid_without_exact_captured_authority(payment_api, monkeypatch, bad):
    client, factory = payment_api
    _, slug, order, bearer = await online_order(payment_api, monkeypatch)
    fake_provider(monkeypatch, order, payment=capture(order, **bad))
    path = session_path(slug, order)
    session = (await client.post(path, headers=bearer)).json()
    result = await client.post(path + "/verify", headers={"Authorization":"Bearer " + session["session_token"]}, json=callback())
    assert result.status_code == 409
    assert (await client.get(path, headers=bearer)).json()["payment_status"] == "pending"


@pytest.mark.asyncio
async def test_lost_provider_response_never_reposts_and_reconciles_while_inflight(payment_api, monkeypatch):
    client, factory = payment_api
    bid, slug, order, bearer = await online_order(payment_api, monkeypatch)
    owner, *_ = await actor(factory, bid)
    started, finish = asyncio.Event(), asyncio.Event()
    calls = []
    async def fake(account, method, path, data=None):
        calls.append((method, path))
        if method == "POST":
            started.set()
            await finish.wait()
            raise HTTPException(502, "Synthetic committed provider response lost")
        return {"id":"order_synthetic", "amount":order["total"], "currency":"INR", "receipt":order["id"]}
    monkeypatch.setattr(payments, "gateway_request", fake)
    path = session_path(slug, order)
    task = asyncio.create_task(client.post(path, headers=bearer))
    await asyncio.wait_for(started.wait(), 5)
    assert (await client.get(path, headers=bearer)).json()["attempt_state"] == "requesting"
    assert (await client.post(path, headers=bearer)).status_code == 409
    reconciled = await client.post(f"/api/v1/businesses/{bid}/orders/{order['id']}/reconcile-gateway-order", headers=owner, json={"gateway_order_id":"order_synthetic"})
    assert reconciled.status_code == 200, reconciled.text
    finish.set()
    response = await asyncio.wait_for(task, 5)
    assert response.status_code == 200, response.text
    assert (await client.post(path, headers=bearer)).json()["provider_order_id"] == "order_synthetic"
    assert sum(method == "POST" for method, _ in calls) == 1
    async with factory() as db:
        assert (await db.get(SKUPaymentAttempt, UUID(order["id"]))).state == "ready"


@pytest.mark.asyncio
async def test_concurrent_session_posts_once_and_invalid_session_claims_fail_closed(payment_api, monkeypatch):
    client, _ = payment_api
    _, slug, order, bearer = await online_order(payment_api, monkeypatch)
    calls = fake_provider(monkeypatch, order)
    path = session_path(slug, order)
    results = await asyncio.wait_for(asyncio.gather(client.post(path, headers=bearer), client.post(path, headers=bearer)), 10)
    assert all(r.status_code in (200,409) for r in results)
    assert len(calls) == 1
    data = next(r.json() for r in results if r.status_code == 200)
    claims = jwt.get_unverified_claims(data["session_token"])
    for changes, code in (({"role":"owner"},401),({"purpose":"v1_user"},401),({"aud":"other"},401),({"amount_minor":True},401),({"amount_minor":order["total"]+1},404),({"currency":"USD"},401),({"business_id":str(uuid4())},404),({"exp":int(datetime.now(timezone.utc).timestamp())-1},401)):
        token = jwt.encode({**claims, **changes}, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        result = await client.post(path + "/verify", headers={"Authorization":"Bearer " + token}, json=callback())
        assert result.status_code == code, result.text
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("settler", ["webhook", "verify", "reconcile"])
async def test_expiry_and_capture_use_store_order_lock_order_and_release_once(payment_api, monkeypatch, settler):
    client, factory = payment_api
    bid, slug, order, bearer = await online_order(payment_api, monkeypatch)
    fake_provider(monkeypatch, order)
    path = session_path(slug, order)
    ready = (await client.post(path, headers=bearer)).json()
    async with factory.begin() as db:
        (await db.get(CommerceOrder, UUID(order["id"]))).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    owner, *_ = await actor(factory, bid)
    # Hold the checkout/expiry store lock. Capture must wait here, never acquire
    # Order first and deadlock when expiry subsequently locks that same Order.
    async with factory.begin() as expiry:
        await expiry.scalar(select(Storefront).where(Storefront.seller_id == bid).with_for_update())
        raw = json.dumps({"event":"payment.captured", "payload":{"payment":{"entity":capture(order)}}}).encode()
        signature = hmac.new(b"synthetic-webhook-key", raw, hashlib.sha256).hexdigest()
        async def settle():
            if settler == "webhook":
                return await client.post(f"/webhooks/razorpay/{bid}", content=raw, headers={"X-Razorpay-Signature":signature})
            if settler == "verify":
                return await client.post(f"/api/v1/storefronts/{slug}/orders/{order['id']}/razorpay/verify", headers=bearer, json=callback())
            return await client.post(f"/api/v1/businesses/{bid}/orders/{order['id']}/reconcile-payment", headers=owner)
        task = asyncio.create_task(settle())
        await asyncio.sleep(.05)
        assert not task.done()
        await asyncio.wait_for(expire_pending_orders(expiry, bid), 3)
    response = await asyncio.wait_for(task, 5)
    assert response.status_code == 200, response.text
    again = await client.post(f"/webhooks/razorpay/{bid}", content=raw, headers={"X-Razorpay-Signature":signature})
    assert again.status_code == 200
    async with factory() as db:
        saved = await db.get(CommerceOrder, UUID(order["id"]))
        assert saved.payment_status == "review_required" and saved.stock_released
        assert (await db.get(CatalogueSKU, UUID(order["items"][0]["sku_id"]))).stock_available == 2
    assert (await client.post(path, headers=bearer)).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("role,expected", [("owner",200),("manager",200),("staff",403),("viewer",403)])
async def test_native_gateway_configuration_capabilities_scope_and_no_provider_calls(payment_api, monkeypatch, role, expected):
    client, factory = payment_api
    bid, _, _ = await seed(factory)
    foreign, _, _ = await seed(factory)
    from cryptography.fernet import Fernet
    monkeypatch.setattr(settings, "PAYMENT_ENCRYPTION_KEY", Fernet.generate_key().decode())
    async def forbidden(*args, **kwargs):
        raise AssertionError("Configuration must not contact a live provider")
    monkeypatch.setattr(payments, "gateway_request", forbidden)
    owner, *_ = await actor(factory, bid, role)
    path = f"/api/v1/businesses/{bid}/payments/razorpay"
    payload = {"key_id":"rzp_test_synthetic", "key_secret":"synthetic-key", "webhook_secret":"synthetic-webhook-key", "mode":"test", "enabled":True}
    assert (await client.get(path, headers=owner)).status_code == expected
    result = await client.put(path, headers=owner, json=payload)
    assert result.status_code == expected, result.text
    if expected == 200:
        assert result.json()["connection_verification"] == "not_performed"
        assert "synthetic-key" not in result.text and "synthetic-webhook-key" not in result.text
        assert "key_secret" not in (await client.get(path, headers=owner)).text
        rejected = await client.put(path, headers=owner, json={**payload, "key_secret":"tiny-sensitive" * 100})
        assert rejected.status_code == 422 and "tiny-sensitive" not in rejected.text
        rejected_mode = await client.put(path, headers=owner, json={**payload, "mode":"live"})
        assert rejected_mode.status_code == 422
    assert (await client.put(f"/api/v1/businesses/{foreign}/payments/razorpay", headers=owner, json=payload)).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["role", "session"])
async def test_native_gateway_cookie_csrf_revocation_and_waiting_role_recheck(payment_api, monkeypatch, revocation):
    client, factory = payment_api
    bid, _, _ = await seed(factory)
    from cryptography.fernet import Fernet
    from app.models.identity import Membership
    from app.models.identity_auth import UserSession
    monkeypatch.setattr(settings, "PAYMENT_ENCRYPTION_KEY", Fernet.generate_key().decode())
    owner, cookie, csrf, sid = await actor(factory, bid)
    client.cookies.set("v1_session", cookie)
    client.cookies.set("v1_csrf", csrf)
    path = f"/api/v1/businesses/{bid}/payments/razorpay"
    payload = {"key_id":"rzp_test_synthetic", "key_secret":"synthetic-key", "webhook_secret":"synthetic-webhook-key", "mode":"test", "enabled":True}
    assert (await client.put(path, json=payload)).status_code == 403
    assert (await client.put(path, json=payload, headers={"Origin":"https://evil.invalid","X-CSRF-Token":csrf})).status_code == 403
    async with factory.begin() as blocking:
        from app.models.seller import Seller
        await blocking.scalar(select(Seller.id).where(Seller.id == bid).with_for_update())
        task = asyncio.create_task(client.put(path, json=payload, headers={"Origin":settings.PUBLIC_BASE_URL,"X-CSRF-Token":csrf}))
        await asyncio.sleep(.05)
        assert not task.done()
        # The newly issued synthetic owner, not the bridge owner.
        user_id = (await blocking.get(UserSession, sid)).user_id
        membership = await blocking.scalar(select(Membership).where(Membership.business_id == bid, Membership.user_id == user_id))
        if revocation == "role":
            membership.role = "viewer"
        else:
            (await blocking.get(UserSession, sid)).revoked_at = datetime.now(timezone.utc)
    assert (await asyncio.wait_for(task, 5)).status_code == (403 if revocation == "role" else 401)
    async with factory.begin() as db:
        (await db.get(UserSession, sid)).revoked_at = datetime.now(timezone.utc)
    assert (await client.get(path, headers=owner)).status_code == 401
    async with factory() as db:
        assert await db.get(RazorpayAccount, bid) is None


@pytest.mark.asyncio
async def test_unknown_creation_recovery_is_readonly_and_never_mints_second_attempt(payment_api, monkeypatch):
    client, _ = payment_api
    _, slug, order, bearer = await online_order(payment_api, monkeypatch)
    calls = []
    async def unknown(*args, **kwargs):
        calls.append(1)
        raise HTTPException(502, "Synthetic response lost after provider commit")
    monkeypatch.setattr(payments, "gateway_request", unknown)
    path = session_path(slug, order)
    assert (await client.post(path, headers=bearer)).status_code == 409
    for _ in range(2):
        status = await client.get(path, headers=bearer)
        assert status.status_code == 200 and status.json()["attempt_state"] == "unknown"
        assert not status.json()["retry_allowed"]
        assert (await client.post(path, headers=bearer)).status_code == 409
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_invalid_callback_and_webhook_signatures_never_reach_captured_authority(payment_api, monkeypatch):
    client, _ = payment_api
    bid, slug, order, bearer = await online_order(payment_api, monkeypatch)
    calls = fake_provider(monkeypatch, order)
    path = session_path(slug, order)
    ready = (await client.post(path, headers=bearer)).json()
    assert (await client.post(path + "/verify", headers={"Authorization":"Bearer " + ready["session_token"]}, json={**callback(), "razorpay_signature":"0" * 64})).status_code == 400
    raw = json.dumps({"event":"payment.captured", "payload":{"payment":{"entity":capture(order)}}}).encode()
    assert (await client.post(f"/webhooks/razorpay/{bid}", content=raw, headers={"X-Razorpay-Signature":"0" * 64})).status_code == 400
    assert len(calls) == 1
    assert (await client.get(path, headers=bearer)).json()["payment_status"] == "pending"


@pytest.mark.asyncio
async def test_signed_callback_webhook_and_seller_reconcile_race_converges_once(payment_api, monkeypatch):
    client, factory = payment_api
    bid, slug, order, bearer = await online_order(payment_api, monkeypatch)
    fake_provider(monkeypatch, order)
    owner, *_ = await actor(factory, bid)
    path = session_path(slug, order)
    ready = (await client.post(path, headers=bearer)).json()
    raw = json.dumps({"event":"payment.captured", "payload":{"payment":{"entity":capture(order)}}}).encode()
    signature = hmac.new(b"synthetic-webhook-key", raw, hashlib.sha256).hexdigest()
    responses = await asyncio.wait_for(asyncio.gather(
        client.post(path + "/verify", headers={"Authorization":"Bearer " + ready["session_token"]}, json=callback()),
        client.post(f"/webhooks/razorpay/{bid}", content=raw, headers={"X-Razorpay-Signature":signature}),
        client.post(f"/api/v1/businesses/{bid}/orders/{order['id']}/reconcile-payment", headers=owner)), 10)
    assert all(response.status_code == 200 for response in responses), [response.text for response in responses]
    async with factory() as db:
        saved = await db.get(CommerceOrder, UUID(order["id"]))
        assert saved.payment_status == "paid" and saved.gateway_payment_id == "pay_synthetic"
        assert not saved.stock_released
        assert (await db.get(CatalogueSKU, UUID(order["items"][0]["sku_id"]))).stock_available == 1
        assert (await db.scalar(select(SKUReservation))).released is False


@pytest.mark.asyncio
@pytest.mark.parametrize("entity", ["business", "seller"])
async def test_new_provider_attempt_rechecks_current_active_tenant_but_keeps_order_status(payment_api, monkeypatch, entity):
    client, factory = payment_api
    bid, slug, order, bearer = await online_order(payment_api, monkeypatch)
    calls = fake_provider(monkeypatch, order)
    from app.models.identity import Business
    from app.models.seller import Seller
    async with factory.begin() as db:
        (await db.get(Business if entity == "business" else Seller, bid)).is_active = False
    path = session_path(slug, order)
    status = await client.get(path, headers=bearer)
    assert status.status_code == 200 and status.json()["attempt_state"] == "not_started"
    assert status.json()["retry_allowed"] is False
    assert (await client.post(path, headers=bearer)).status_code == 409
    assert calls == []
    async with factory() as db:
        assert await db.get(SKUPaymentAttempt, UUID(order["id"])) is None


@pytest.mark.asyncio
async def test_native_configuration_deep_json_and_slow_body_fail_closed(payment_api, monkeypatch):
    client, factory = payment_api
    bid, _, _ = await seed(factory)
    owner, *_ = await actor(factory, bid)
    path = f"/api/v1/businesses/{bid}/payments/razorpay"
    body = '{"nested":' + '[' * 1500 + '"synthetic-secret"' + ']' * 1500 + '}'
    result = await client.put(path, headers={**owner,"Content-Type":"application/json"}, content=body)
    assert result.status_code == 422 and "synthetic-secret" not in result.text
    from app.api.v1 import checkout_sessions as routes
    monkeypatch.setattr(routes, "CONFIGURATION_BODY_TIMEOUT", .01)
    async def slow():
        yield b'{'
        await asyncio.sleep(.1)
        yield b'}'
    result = await client.put(path, headers={**owner,"Content-Type":"application/json"}, content=slow())
    assert result.status_code == 408
    async with factory() as db:
        assert await db.get(RazorpayAccount, bid) is None
