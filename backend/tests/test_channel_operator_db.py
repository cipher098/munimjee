"""Actual migrated PostgreSQL + native-session HTTP operator checks; no live provider."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.v1.channel_operator import router
from app.config import settings
from app.database import get_db
from app.models.channel_operator import ChannelOperation, ChannelConnectionState
from app.models.identity import Membership, User
from app.models.instagram_ingress import InstagramIngress
from app.models.seller import Seller
from app.services.auth_sessions import issue_session
from app.services.identity import ensure_legacy_owner_bridge, legacy_owner_id


@pytest_asyncio.fixture
async def world(migrated_engine, monkeypatch):
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False)
    monkeypatch.setattr(settings, "V1_AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "META_WEBHOOK_SECRET", "synthetic-webhook")
    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", "synthetic-webhook")
    monkeypatch.setattr(settings, "WHATSAPP_WEBHOOK_VERIFY_TOKEN", "synthetic-verify")
    monkeypatch.setattr(settings, "CHANNEL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "INSTAGRAM_APP_ID", "123456")
    monkeypatch.setattr(settings, "INSTAGRAM_APP_SECRET", "synthetic-client-secret")
    app = FastAPI()
    app.include_router(router)

    @asynccontextmanager
    async def session():
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def dependency():
        async with session() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    monkeypatch.setattr("app.database.worker_session", session)
    monkeypatch.setattr("app.workers.instagram_ingress.worker_session", session)
    monkeypatch.setattr("app.workers.instagram_ingress.process_instagram_ingress.apply_async", lambda **kwargs: None)
    async with session() as db:
        seller = Seller(id=uuid4(), email="operator@example.test", password_hash="unused", business_name="Synthetic Studio",
                        instagram_page_id="1234567", instagram_id="1234567", fb_page_id="1234567", instagram_token="synthetic-token", is_active=True)
        foreign = Seller(id=uuid4(), email="foreign@example.test", password_hash="unused", business_name="Other Studio", is_active=True)
        db.add_all([seller, foreign]); await db.flush()
        await ensure_legacy_owner_bridge(db, seller); await ensure_legacy_owner_bridge(db, foreign)
        user = await db.get(User, legacy_owner_id(seller.id))
        token, csrf, native = await issue_session(db, user)
        viewers = {}
        for role in ("viewer", "staff", "manager"):
            member = User(id=uuid4(), is_active=True)
            db.add(member); await db.flush()
            db.add(Membership(business_id=seller.id, user_id=member.id, role=role, is_active=True))
            role_token, role_csrf, _ = await issue_session(db, member)
            viewers[role] = (member.id, role_token, role_csrf)
        db.add(ChannelConnectionState(business_id=seller.id, channel="instagram", automation_enabled=True,
               check_status="verified", checked_at=datetime.now(timezone.utc)))
        receipt = InstagramIngress(id=uuid4(), seller_id=seller.id, account_id="1234567", customer_id="customer1", event_key=uuid4().hex,
                    provider_message_id="synthetic-mid", events=[{"type":"text", "text":"Is this available?"}], processed_indices=[], status="error",
                    error_code="processing_failed_unknown_effect", attempts=1, occurred_at=datetime.now(timezone.utc), available_at=datetime.now(timezone.utc))
        db.add(receipt); await db.flush()
        ids = (seller.id, foreign.id, user.id, native.id, receipt.id)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://operator.test", follow_redirects=False,
                   cookies={"v1_session":token, "v1_csrf":csrf}) as client:
        yield SimpleNamespace(client=client, session=session, ids=ids, token=token, csrf=csrf, viewers=viewers,
                              base=f"/api/v1/businesses/{seller.id}/channels", app=app)


async def review_payload(world, decision="resolve", **updates):
    row = await world.client.get(world.base + f"/instagram/receipts/{world.ids[4]}")
    assert row.status_code == 200
    return {"idempotency_key":str(uuid4()), "decision":decision, "reviewed":True,
            "reason":"Checked the original Instagram conversation carefully.", "expected_updated_at":row.json()["updated_at"], **updates}


def headers(world):
    return {"Origin":"http://operator.test", "X-CSRF-Token":world.csrf}


@pytest.mark.asyncio
async def test_resolve_is_persisted_audited_idempotent_and_never_sends(world, monkeypatch):
    sent = AsyncMock()
    monkeypatch.setattr("app.integrations.instagram.InstagramClient.send_message", sent)
    body = await review_payload(world)
    path = world.base + f"/instagram/receipts/{world.ids[4]}/review"
    first = await world.client.post(path, json=body, headers=headers(world))
    second = await world.client.post(path, json=body, headers=headers(world))
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["status"] == "resolved" and first.json()["delivery_confirmed"] is False
    sent.assert_not_awaited()
    async with world.session() as db:
        assert await db.scalar(select(func.count()).select_from(ChannelOperation)) == 1
        audit = await db.scalar(select(ChannelOperation))
        assert audit.actor_user_id == world.ids[2] and audit.reason == body["reason"]
        assert audit.before_status == "error" and audit.after_status == "resolved"


@pytest.mark.asyncio
async def test_review_refuses_missing_csrf_cross_origin_revoked_session_and_unconfirmed_decision(world):
    body = await review_payload(world)
    path = world.base + f"/instagram/receipts/{world.ids[4]}/review"
    assert (await world.client.post(path, json=body)).status_code == 403
    assert (await world.client.post(path, json=body, headers={**headers(world), "Origin":"https://other.invalid"})).status_code == 403
    assert (await world.client.post(path, json={**body,"reviewed":False}, headers=headers(world))).status_code == 422
    from app.models.identity_auth import UserSession
    async with world.session() as db:
        (await db.get(UserSession, world.ids[3])).revoked_at = datetime.now(timezone.utc)
    assert (await world.client.post(path, json=body, headers=headers(world))).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", "staff"])
async def test_read_roles_cannot_review_or_connect_even_with_competing_owner_cookie(world, role):
    _, token, _ = world.viewers[role]
    auth = {"Authorization":"Bearer " + token}
    assert (await world.client.get(world.base + "/instagram/receipts", headers=auth)).status_code == 200
    body = await review_payload(world)
    assert (await world.client.post(world.base + f"/instagram/receipts/{world.ids[4]}/review", json=body, headers=auth)).status_code == 403
    assert (await world.client.post(world.base + "/instagram/connect", json={"idempotency_key":str(uuid4())}, headers=auth)).status_code == 403


@pytest.mark.asyncio
async def test_tenant_scoped_pagination_filters_and_private_media(world):
    async with world.session() as db:
        for index in range(3):
            db.add(InstagramIngress(seller_id=world.ids[0], account_id="1234567", customer_id="customer"+str(index), event_key=uuid4().hex,
                    events=[{"type":"image", "image_url":"https://example.invalid/private?access_token=secret"}], processed_indices=[],
                    status="error", error_code="processing_failed_unknown_effect", available_at=datetime.now(timezone.utc)))
        db.add(InstagramIngress(seller_id=world.ids[1], account_id="9999", customer_id="other-customer", event_key=uuid4().hex,
                    events=[{"type":"text", "text":"foreign-private-text"}], processed_indices=[], status="error", available_at=datetime.now(timezone.utc)))
    first = (await world.client.get(world.base + "/instagram/receipts?limit=2")).json()
    second = (await world.client.get(world.base + "/instagram/receipts", params={"limit":2,"cursor":first["next_cursor"]})).json()
    assert len({item["id"] for item in first["items"]+second["items"]}) == 4
    assert "access_token" not in str(first) and "foreign-private-text" not in str(first)
    assert (await world.client.get(world.base + "/instagram/receipts", params={"status":"resolved","cursor":first["next_cursor"]})).status_code == 400
    assert (await world.client.get(f"/api/v1/businesses/{world.ids[1]}/channels/instagram/receipts")).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["unknown_time","expired_time","account_changed","takeover","another_hold","revoked_membership"])
async def test_reviewed_replay_rechecks_current_eligibility(world, change):
    async with world.session() as db:
        row = await db.get(InstagramIngress, world.ids[4])
        if change == "unknown_time": row.occurred_at=None
        elif change == "expired_time": row.occurred_at=datetime.now(timezone.utc)-timedelta(days=2)
        elif change == "account_changed": row.account_id="9876543"
        elif change == "takeover":
            from app.models.conversation import Conversation
            db.add(Conversation(seller_id=world.ids[0],customer_instagram_id="customer1",last_seller_manual_reply_at=datetime.now(timezone.utc)))
        elif change == "another_hold":
            db.add(InstagramIngress(seller_id=world.ids[0], account_id="1234567",customer_id="customer1",event_key=uuid4().hex,events=[],
                   processed_indices=[],status="error",error_code="processing_failed_unknown_effect",available_at=datetime.now(timezone.utc)))
        elif change == "revoked_membership":
            member = await db.scalar(select(Membership).where(Membership.business_id==world.ids[0],Membership.user_id==world.ids[2]))
            member.revoked_at=datetime.now(timezone.utc)
    if change == "revoked_membership":
        result = await world.client.get(world.base + "/instagram/receipts")
        assert result.status_code == 404
        return
    body = await review_payload(world,"replay")
    response = await world.client.post(world.base + f"/instagram/receipts/{world.ids[4]}/review",json=body,headers=headers(world))
    assert response.status_code == 409
    async with world.session() as db:
        assert (await db.get(InstagramIngress,world.ids[4])).status == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation",["membership","business"])
async def test_eligible_replay_is_queued_once_and_worker_rechecks_reviewer_revocation(world, monkeypatch,revocation):
    body = await review_payload(world,"replay")
    response = await world.client.post(world.base + f"/instagram/receipts/{world.ids[4]}/review",json=body,headers=headers(world))
    assert response.status_code == 200 and response.json()["queued"] is True
    async with world.session() as db:
        row = await db.get(InstagramIngress,world.ids[4]); assert row.status == "retry" and row.operator_replay_pending
        member = await db.scalar(select(Membership).where(Membership.business_id==world.ids[0],Membership.user_id==world.ids[2]))
        if revocation=="membership":
            member.revoked_at=datetime.now(timezone.utc)
        else:
            from app.models.identity import Business
            (await db.get(Business,world.ids[0])).is_active=False
    consume = AsyncMock(return_value={0})
    monkeypatch.setattr("app.workers.message_batch._consume_events",consume)
    from app.workers.instagram_ingress import _process_thread
    await _process_thread(world.ids[0],"1234567","customer1")
    consume.assert_not_awaited()
    async with world.session() as db:
        row = await db.get(InstagramIngress,world.ids[4])
        assert row.status == "error" and row.error_code == "operator_replay_withheld"


@pytest.mark.asyncio
async def test_connect_whatsapp_uses_synthetic_provider_and_audits_without_credentials(world, monkeypatch):
    seen=[]
    real=httpx.AsyncClient
    def provider(request):
        seen.append(request)
        return httpx.Response(200,json={"data":[{"id":"456","display_phone_number":"synthetic"}]})
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs:real(transport=httpx.MockTransport(provider)))
    body={"idempotency_key":str(uuid4()),"waba_id":"123","phone_number_id":"456","access_token":"synthetic-private-token"}
    response=await world.client.post(world.base+"/whatsapp/connect",json=body,headers=headers(world))
    assert response.status_code==200 and response.json()["status"]=="paused"
    assert len(seen)==1 and seen[0].headers["Authorization"]=="Bearer synthetic-private-token"
    assert (await world.client.post(world.base+"/whatsapp/connect",json=body,headers=headers(world))).json()==response.json()
    assert len(seen)==1
    from app.models.whatsapp import WhatsAppAccount
    async with world.session() as db:
        account=await db.get(WhatsAppAccount,world.ids[0])
        assert not account.enabled and account.access_token!="synthetic-private-token"
        audit=await db.scalar(select(ChannelOperation))
        assert "synthetic-private-token" not in str(audit.outcome) and "access_token" not in str(audit.outcome)


@pytest.mark.asyncio
async def test_stale_review_and_reused_key_with_different_decision_are_rejected(world):
    body=await review_payload(world)
    stale={**body,"expected_updated_at":(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()}
    path=world.base+f"/instagram/receipts/{world.ids[4]}/review"
    assert (await world.client.post(path,json=stale,headers=headers(world))).status_code==409
    assert (await world.client.post(path,json=body,headers=headers(world))).status_code==200
    conflict=await world.client.post(path,json={**body,"decision":"replay"},headers=headers(world))
    assert conflict.status_code==409


@pytest.mark.asyncio
async def test_concurrent_same_review_key_has_one_audit_and_no_second_decision(world):
    import asyncio
    body=await review_payload(world)
    path=world.base+f"/instagram/receipts/{world.ids[4]}/review"
    responses=await asyncio.gather(world.client.post(path,json=body,headers=headers(world)),world.client.post(path,json=body,headers=headers(world)))
    assert [response.status_code for response in responses]==[200,200]
    assert responses[0].json()==responses[1].json()
    async with world.session() as db:
        assert await db.scalar(select(func.count()).select_from(ChannelOperation))==1


@pytest.mark.asyncio
async def test_connection_check_readiness_is_honest_and_provider_errors_do_not_leak(world, monkeypatch):
    async with world.session() as db:
        await db.delete(await db.get(ChannelConnectionState,(world.ids[0],"instagram")))
    real=httpx.AsyncClient
    seen=[]
    def provider(request):
        seen.append(request)
        return httpx.Response(200,json={"id":"1234567","user_id":"1234567","account_type":"BUSINESS"})
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs:real(transport=httpx.MockTransport(provider)))
    before=(await world.client.get(world.base)).json()["channels"][0]
    assert before["status"]=="not_checked" and before["provider_approval"]=="not_evaluated"
    body={"idempotency_key":str(uuid4())}
    assert (await world.client.post(world.base+"/instagram/verify",json=body,headers=headers(world))).json()["status"]=="verified"
    after=(await world.client.get(world.base)).json()["channels"][0]
    assert after["status"]=="access_verified" and after["provider_approval"]=="not_evaluated"
    assert seen[0].headers["Authorization"]=="Bearer synthetic-token" and "access_token" not in seen[0].url.params
    def rejected(request):
        return httpx.Response(401,json={"error":"synthetic-private-token"})
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs:real(transport=httpx.MockTransport(rejected)))
    failed=await world.client.post(world.base+"/instagram/verify",json={"idempotency_key":str(uuid4())},headers=headers(world))
    assert failed.json()["status"]=="needs_reconnect" and "synthetic-private-token" not in failed.text
    after=(await world.client.get(world.base)).json()["channels"][0]
    assert after["status"]=="needs_reconnect" and not after["automation_enabled"]


@pytest.mark.asyncio
async def test_owner_oauth_uses_actor_browser_and_current_generation_and_no_live_provider(world, monkeypatch):
    from urllib.parse import urlsplit,parse_qs
    seen=[]; real=httpx.AsyncClient
    def provider(request):
        seen.append(request)
        if request.url.host=="api.instagram.com": return httpx.Response(200,json={"access_token":"synthetic-short","user_id":"1234567"})
        if request.url.path=="/access_token": return httpx.Response(200,json={"access_token":"synthetic-long"})
        if request.url.path.endswith("/me"): return httpx.Response(200,json={"user_id":"1234567","account_type":"BUSINESS"})
        raise AssertionError("No subscription, permission mutation or message send is allowed in this test")
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs:real(transport=httpx.MockTransport(provider)))
    start=await world.client.post(world.base+"/instagram/connect",json={"idempotency_key":str(uuid4())},headers=headers(world))
    assert start.status_code==200
    query=parse_qs(urlsplit(start.json()["authorization_url"]).query)
    assert query["redirect_uri"]==[f"http://operator.test{world.base}/instagram/callback"]
    response=await world.client.get(world.base+"/instagram/callback",params={"state":query["state"][0],"code":"synthetic-code"})
    assert response.status_code==303 and response.headers["location"].endswith("connection=connected")
    assert len(seen)==3
    again=await world.client.get(world.base+"/instagram/callback",params={"state":query["state"][0],"code":"synthetic-code"})
    assert again.status_code==409 and len(seen)==3
    async with world.session() as db:
        seller=await db.get(Seller,world.ids[0]); state=await db.get(ChannelConnectionState,(world.ids[0],"instagram"))
        assert seller.instagram_token=="synthetic-long" and not state.automation_enabled


@pytest.mark.asyncio
async def test_disconnect_cancels_oauth_before_provider_exchange(world, monkeypatch):
    from urllib.parse import urlsplit,parse_qs
    start=await world.client.post(world.base+"/instagram/connect",json={"idempotency_key":str(uuid4())},headers=headers(world))
    state=parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]
    disconnected=await world.client.post(world.base+"/instagram/disconnect",json={"idempotency_key":str(uuid4())},headers=headers(world))
    assert disconnected.status_code==200
    exchange=AsyncMock(); monkeypatch.setattr("app.integrations.instagram.exchange_code_for_user_token",exchange)
    callback=await world.client.get(world.base+"/instagram/callback",params={"state":state,"code":"synthetic-code"})
    assert callback.status_code==409
    exchange.assert_not_awaited()


async def activated_product(world, db):
    from app.models.product import Product
    from app.models.catalogue_v1 import CatalogueProductMapping
    from app.models.checkout_v1 import CatalogueActivation
    product=Product(seller_id=world.ids[0],name="Activated dress",listed_price=999900,floor_price=888800,stock_quantity=99,
                    photo_url="https://example.invalid/photo",reel_urls=["https://www.instagram.com/reel/synthetic/"],active=True)
    db.add(product);await db.flush()
    db.add(CatalogueProductMapping(business_id=world.ids[0],product_id=product.id,state="reviewed",revision=1,
              legacy_fingerprint="a"*64,issues=[],legacy_variants=[]));await db.flush()
    db.add(CatalogueActivation(business_id=world.ids[0],product_id=product.id,actor_id=world.ids[2],
              reviewed_revision=1,legacy_fingerprint="a"*64));await db.flush()
    return product


@pytest.mark.asyncio
@pytest.mark.parametrize("source",["text","reel"])
async def test_activated_catalogue_handoffs_before_legacy_fact_reply(world,monkeypatch,source):
    from app.models.conversation import Conversation
    from app.workers.instagram_ingress import _process_thread
    async with world.session() as db:
        product=await activated_product(world,db)
        db.add(Conversation(seller_id=world.ids[0],customer_instagram_id="customer1",customer_name="Synthetic",customer_gender="female",
                            product_id=product.id if source=="text" else None,messages=[]))
        receipt=await db.get(InstagramIngress,world.ids[4]);receipt.status="pending";receipt.error_code=None
        if source=="reel":receipt.events=[{"type":"reel","reel_url":"https://www.instagram.com/reel/synthetic/","mid":"synthetic-mid"}]
    sent=AsyncMock();llm=AsyncMock()
    monkeypatch.setattr("app.integrations.instagram.InstagramClient.send_message",sent)
    monkeypatch.setattr("app.bot.responder.generate_bot_reply",llm)
    await _process_thread(world.ids[0],"1234567","customer1")
    sent.assert_not_awaited();llm.assert_not_awaited()
    async with world.session() as db:
        assert (await db.get(InstagramIngress,world.ids[4])).error_code=="authoritative_catalogue_handoff"


@pytest.mark.asyncio
async def test_whatsapp_activated_context_handoffs_without_frozen_price_or_stock(world):
    from app.services.whatsapp_context import reel_catalogue_reply
    async with world.session() as db:
        product=await activated_product(world,db)
        context={"references":[{"shortcode":"synthetic","status":"matched","products":[{"id":str(product.id)}]}]}
        text=await reel_catalogue_reply(db,world.ids[0],context,"price and stock?")
        assert text=="Our team will confirm the current options, price and availability for this product."
        assert "9999" not in text and "99" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("kind",["text","media","qr"])
async def test_customer_send_uncertainty_is_retained_in_receipt_quarantine(world,monkeypatch,kind):
    from app.models.conversation import Conversation
    from app.models.product import Product
    from app.models.conversation_product import ConversationProduct
    from app.models.payment_method import PaymentMethod
    from app.bot import conversation as bot
    from app.workers.instagram_ingress import _process_thread
    async with world.session() as db:
        product=Product(seller_id=world.ids[0],name="Legacy item",listed_price=10000,floor_price=8000,photo_url="https://example.invalid/photo")
        db.add(product);await db.flush()
        conversation=Conversation(seller_id=world.ids[0],customer_instagram_id="customer1",customer_name="Synthetic",product_id=product.id,messages=[])
        db.add(conversation);await db.flush()
        db.add(ConversationProduct(conversation_id=conversation.id,product_id=product.id,state="awaiting_payment",agreed_price=10000))
        db.add(PaymentMethod(seller_id=world.ids[0],category="upi",upi_id="synthetic@invalid",qr_code_url="https://example.invalid/qr",is_active=True))
        row=await db.get(InstagramIngress,world.ids[4]);row.status="pending";row.error_code=None
    sent=AsyncMock(side_effect=httpx.ReadTimeout("synthetic provider result unknown"))
    monkeypatch.setattr("app.integrations.instagram.InstagramClient.send_message",sent)
    monkeypatch.setattr("app.integrations.instagram.InstagramClient.send_image",sent)
    async def phase(events,conversation,seller,db):
        if kind=="text":
            from app.integrations.instagram import InstagramClient
            await bot._send_and_tag(conversation,InstagramClient(seller.instagram_token,seller.fb_page_id),"synthetic",db)
        elif kind=="media":
            product=await db.get(Product,conversation.product_id)
            await bot._send_next_product_photo(conversation,seller,product,None,db)
        else:
            cycle=await db.scalar(select(ConversationProduct).where(ConversationProduct.conversation_id==conversation.id))
            await bot._share_primary_payment_method(conversation,seller,cycle,db)
        return {0}
    monkeypatch.setattr("app.workers.message_batch._process_events",phase)
    await _process_thread(world.ids[0],"1234567","customer1")
    assert sent.await_count==1
    await _process_thread(world.ids[0],"1234567","customer1")
    assert sent.await_count==1
    async with world.session() as db:
        row=await db.get(InstagramIngress,world.ids[4])
        assert row.status=="error" and row.error_code=="processing_failed_unknown_effect"


@pytest.mark.asyncio
async def test_disconnect_retains_inbox_binding_and_rejects_different_instagram_account(world,monkeypatch):
    from urllib.parse import urlsplit,parse_qs
    assert (await world.client.post(world.base+"/instagram/disconnect",json={"idempotency_key":str(uuid4())},headers=headers(world))).status_code==200
    async with world.session() as db:
        assert (await db.get(ChannelConnectionState,(world.ids[0],"instagram"))).provider_account_id=="1234567"
    start=await world.client.post(world.base+"/instagram/connect",json={"idempotency_key":str(uuid4())},headers=headers(world))
    state=parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]
    real=httpx.AsyncClient
    def provider(request):
        if request.url.host=="api.instagram.com": return httpx.Response(200,json={"access_token":"synthetic-short","user_id":"9999999"})
        if request.url.path=="/access_token": return httpx.Response(200,json={"access_token":"synthetic-long"})
        if request.url.path.endswith("/me"): return httpx.Response(200,json={"user_id":"9999999","account_type":"BUSINESS"})
        raise AssertionError("No external provider mutations")
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs:real(transport=httpx.MockTransport(provider)))
    result=await world.client.get(world.base+"/instagram/callback",params={"state":state,"code":"synthetic-code"})
    assert result.status_code==303 and result.headers["location"].endswith("connection=account_change_requires_migration")
    async with world.session() as db:
        assert (await db.get(Seller,world.ids[0])).instagram_page_id is None
        assert not (await db.get(ChannelConnectionState,(world.ids[0],"instagram"))).automation_enabled


@pytest.mark.asyncio
async def test_close_without_retry_fences_old_resume_and_nudge_but_allows_new_customer_turn(world,monkeypatch):
    from app.models.conversation import Conversation
    from app.models.product import Product
    from app.services.channel_readiness import resume_messages_after_review
    from app.workers.message_batch import _wake_paused_conversation
    from app.workers.nudge import _send_nudge
    current=datetime.now(timezone.utc)
    old={"role":"customer","content":"Please confirm the price","timestamp":(current-timedelta(hours=26)).isoformat(),"mid":"synthetic-mid"}
    async with world.session() as db:
        product=Product(seller_id=world.ids[0],name="Unactivated item",listed_price=10000,floor_price=8000)
        db.add(product);await db.flush()
        conversation=Conversation(seller_id=world.ids[0],customer_instagram_id="customer1",customer_name="Synthetic",product_id=product.id,messages=[old])
        db.add(conversation);await db.flush();cid=str(conversation.id)
    body=await review_payload(world)
    assert (await world.client.post(world.base+f"/instagram/receipts/{world.ids[4]}/review",json=body,headers=headers(world))).status_code==200
    advance=AsyncMock();sent=AsyncMock()
    monkeypatch.setattr("app.bot.conversation.advance_conversation",advance)
    monkeypatch.setattr("app.integrations.instagram.InstagramClient.send_message",sent)
    await _wake_paused_conversation(cid)
    await _send_nudge(cid,1)
    advance.assert_not_awaited();sent.assert_not_awaited()
    async with world.session() as db:
        assert (await db.get(Conversation,conversation.id)).messages==[old]
        new={"role":"customer","content":"A new question","timestamp":(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat()}
        assert await resume_messages_after_review(db,world.ids[0],"customer1",[old,new])==[new]


@pytest.mark.asyncio
async def test_reviewed_eligible_retry_uses_existing_writer_once_with_synthetic_send(world,monkeypatch):
    from app.models.conversation import Conversation
    from app.bot.conversation import _send_and_tag
    from app.integrations.instagram import InstagramClient
    from app.workers.instagram_ingress import _process_thread
    async with world.session() as db:
        db.add(Conversation(seller_id=world.ids[0],customer_instagram_id="customer1",customer_name="Synthetic",messages=[]))
    body=await review_payload(world,"replay")
    assert (await world.client.post(world.base+f"/instagram/receipts/{world.ids[4]}/review",json=body,headers=headers(world))).status_code==200
    sent=[];real=httpx.AsyncClient
    def provider(request):
        assert request.method=="POST" and request.url.host=="graph.instagram.com" and request.url.path.endswith("/messages")
        sent.append(request)
        return httpx.Response(200,json={"message_id":"synthetic-success-mid"})
    monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs:real(transport=httpx.MockTransport(provider)))
    monkeypatch.setattr("app.integrations.instagram.register_outbound_mid",lambda mid:None)
    async def phase(events,conversation,seller,db):
        conversation.messages=[{"role":"bot","content":"Synthetic reviewed response"}]
        await _send_and_tag(conversation,InstagramClient(seller.instagram_token,seller.fb_page_id),"Synthetic reviewed response",db)
        return {0}
    monkeypatch.setattr("app.workers.message_batch._process_events",phase)
    await _process_thread(world.ids[0],"1234567","customer1")
    await _process_thread(world.ids[0],"1234567","customer1")
    assert len(sent)==1
    async with world.session() as db:
        row=await db.get(InstagramIngress,world.ids[4]);assert row.status=="completed" and not row.operator_replay_pending
        conversation=await db.scalar(select(Conversation).where(Conversation.seller_id==world.ids[0]))
        assert conversation.messages[-1]["mid"]=="synthetic-success-mid"


@pytest.mark.asyncio
@pytest.mark.parametrize("occurred",[None,"expired","future"])
async def test_ordinary_pending_receipt_without_current_signed_time_cannot_enter_writer(world,monkeypatch,occurred):
    from app.workers.instagram_ingress import _process_thread
    async with world.session() as db:
        row=await db.get(InstagramIngress,world.ids[4]);row.status="pending";row.error_code=None
        row.occurred_at=None if occurred is None else datetime.now(timezone.utc)+timedelta(days=-2 if occurred=="expired" else 2)
    consume=AsyncMock(return_value={0});monkeypatch.setattr("app.workers.message_batch._consume_events",consume)
    await _process_thread(world.ids[0],"1234567","customer1")
    consume.assert_not_awaited()
    async with world.session() as db:
        row=await db.get(InstagramIngress,world.ids[4]);assert row.status=="error" and row.error_code=="provider_window_unverified"


@pytest.mark.asyncio
async def test_legacy_product_authority_guard_refuses_foreign_or_missing_product_context(world):
    from app.models.product import Product
    from app.services.channel_readiness import guard_legacy_product,CatalogueAuthorityHandoff
    async with world.session() as db:
        product=Product(seller_id=world.ids[1],name="Other business private product",listed_price=123456,floor_price=100000)
        db.add(product);await db.flush()
        for product_id in (product.id,uuid4()):
            with pytest.raises(CatalogueAuthorityHandoff):
                await guard_legacy_product(db,world.ids[0],product_id)


@pytest.mark.asyncio
async def test_product_authority_readers_share_locks_and_serialize_with_activation(world):
    import asyncio
    from app.models.product import Product
    from app.services.channel_readiness import guard_legacy_product,legacy_fact_products
    async with world.session() as db:
        products=[Product(seller_id=world.ids[0],name=f"Shared item {index}",listed_price=10000,floor_price=8000) for index in range(2)]
        db.add_all(products);await db.flush();ids=[product.id for product in products]
    ready=asyncio.Event();reached=[]
    async def chat(focus):
        async with world.session() as db:
            await guard_legacy_product(db,world.ids[0],focus)
            reached.append(focus)
            if len(reached)==2:ready.set()
            await ready.wait()
            products=list((await db.scalars(select(Product).where(Product.id.in_(ids)))).all())
            assert len(await legacy_fact_products(db,world.ids[0],products))==2
    await asyncio.wait_for(asyncio.gather(chat(ids[0]),chat(ids[1])),timeout=5)
    started,acquired=asyncio.Event(),asyncio.Event()
    async def activation_lock():
        async with world.session() as db:
            started.set()
            await db.scalar(select(Product.id).where(Product.id==ids[0]).with_for_update())
            acquired.set()
    async with world.session() as db:
        await guard_legacy_product(db,world.ids[0],ids[0])
        activation=asyncio.create_task(activation_lock())
        await started.wait()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(acquired.wait(),timeout=0.1)
        assert not acquired.is_set()
    await asyncio.wait_for(activation,timeout=5)
    assert acquired.is_set()


@pytest.mark.asyncio
async def test_wa_legacy_fact_guard_never_waits_behind_product_with_account_held(world):
    import asyncio
    from app.models.product import Product
    from app.models.whatsapp import WhatsAppAccount
    from app.services.channel_readiness import guard_legacy_product, CatalogueAuthorityHandoff
    bid=world.ids[0]
    async with world.session() as db:
        product=Product(seller_id=bid,name='Changing legacy product',listed_price=10000,floor_price=8000)
        db.add(product)
        db.add(WhatsAppAccount(seller_id=bid,phone_number_id='synthetic-nowait-number',waba_id='synthetic',access_token='synthetic'))
        await db.flush();pid=product.id
    # Existing outbox Account->Product and checkout Product->Account order.
    async with world.session() as outbox:
        await outbox.scalar(select(WhatsAppAccount.seller_id).where(WhatsAppAccount.seller_id==bid).with_for_update())
        async with world.session() as checkout:
            await checkout.scalar(select(Product.id).where(Product.id==pid).with_for_update())
            with pytest.raises(CatalogueAuthorityHandoff):
                await asyncio.wait_for(guard_legacy_product(outbox,bid,pid,nowait=True),1)
            # Savepoint rollback leaves claimed outbox state usable for handoff.
            assert await outbox.scalar(select(Seller.id).where(Seller.id==bid))==bid
        await guard_legacy_product(outbox,bid,pid,nowait=True)
