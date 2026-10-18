"""Prepared actual-PG V08 reconnect/queued intent acceptance; no live provider.

No claim follows from collection. Run only on an explicitly released P01 lane.
The owner re-enable case characterizes the current fresh-fact contract separately
from automatic paused delivery; it is not a newly invented hard generation policy.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
import hashlib
import hmac
import json

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import func, select, update

from app.config import settings
from app.database import get_db
from app.models.catalogue_v1 import CatalogueSKU
from app.models.channel_operator import ChannelConnectionState
from app.models.identity import Membership, User
from app.models.whatsapp import WhatsAppAccount, WhatsAppMessage
from app.services.auth_sessions import issue_session
from app.services.channel_credentials import decrypt, encrypt
from app.services import whatsapp_provider
from app.workers.whatsapp import deliver_one
from tests.test_sku_fact_replies_db import sku_lane, session_factory  # noqa: F401

ORIGIN = 'https://wa-generation.example.com'
PHONE_ID, WABA_ID = '9100001', '9200001'


@pytest_asyncio.fixture
async def reconnect_intent(sku_lane, monkeypatch, record_property):
    j = sku_lane
    monkeypatch.setattr(settings, 'V1_AUTH_ENABLED', True)
    monkeypatch.setattr(settings, 'PUBLIC_BASE_URL', ORIGIN)
    monkeypatch.setattr(settings, 'WHATSAPP_APP_SECRET', 'synthetic-v08-signature')
    monkeypatch.setattr(settings, 'WHATSAPP_WEBHOOK_VERIFY_TOKEN', 'synthetic-v08-verify')
    monkeypatch.setattr(settings, 'CHANNEL_ENCRYPTION_KEY', Fernet.generate_key().decode())
    async with j.sessions.begin() as db:
        db.add(Membership(business_id=j.bid, user_id=j.uid, role='owner', is_active=True))
        db.add(WhatsAppAccount(seller_id=j.bid, phone_number_id=PHONE_ID, waba_id=WABA_ID,
            access_token=encrypt('synthetic-original-credential'), enabled=True,
            automation_enabled=True, reel_replies_enabled=True))
        db.add(ChannelConnectionState(business_id=j.bid, channel='whatsapp', version=1,
            provider_account_id=PHONE_ID, automation_enabled=True, check_status='verified',
            checked_at=datetime.now(timezone.utc)))
        await db.flush()
        token, csrf, _ = await issue_session(db, await db.get(User, j.uid))
    from app.main import app
    @asynccontextmanager
    async def request_session():
        async with j.sessions.begin() as db:
            yield db
    async def dependency():
        async with request_session() as db:
            yield db
    old = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = dependency
    sends, checks = [], []
    async def provider_verify(token, waba, phone):
        checks.append((token == 'synthetic-replacement-credential', waba == WABA_ID, phone == PHONE_ID))
        return {'id': PHONE_ID, 'display_phone_number': '+91 synthetic'}
    async def provider_send(account, contact, message):
        sends.append({'replacement_credential': decrypt(account.access_token) == 'synthetic-replacement-credential',
            'message_id': message.id, 'text': message.text})
        return 'synthetic-provider-acceptance'
    monkeypatch.setattr(whatsapp_provider, 'verify_connection', provider_verify)
    monkeypatch.setattr(whatsapp_provider, 'send', provider_send)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
            cookies={'v1_session': token, 'v1_csrf': csrf}) as client:
            source_mid = 'synthetic-v08-' + uuid4().hex
            packet = {'object': 'whatsapp_business_account', 'entry': [{'id': WABA_ID, 'changes': [{
                'field': 'messages', 'value': {'metadata': {'phone_number_id': PHONE_ID}, 'messages': [{
                    'id': source_mid, 'from': '919876543210', 'timestamp': str(int(datetime.now(timezone.utc).timestamp())),
                    'type': 'text', 'text': {'body': 'price? https://www.instagram.com/reel/Exact_code/'}}]}}]}]}
            raw = json.dumps(packet).encode()
            signature = 'sha256=' + hmac.new(b'synthetic-v08-signature', raw, hashlib.sha256).hexdigest()
            response = await client.post('/webhooks/whatsapp', content=raw,
                headers={'Content-Type': 'application/json', 'X-Hub-Signature-256': signature})
            assert response.status_code == 200
            async with j.sessions() as db:
                queued = await db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.seller_id == j.bid,
                    WhatsAppMessage.direction == 'outbound', WhatsAppMessage.idempotency_key == 'auto:reel:' + source_mid))
                assert queued is not None and queued.status == 'queued'
                assert '₹123.45' in queued.text and 'PRIVATE' not in queued.text
                message_id, initial_payload = queued.id, dict(queued.payload)
            headers = {'Origin': ORIGIN, 'X-CSRF-Token': csrf}
            base = f'/api/v1/businesses/{j.bid}/channels'
            replacement = await client.post(base + '/whatsapp/connect', json={
                'idempotency_key': str(uuid4()), 'phone_number_id': PHONE_ID, 'waba_id': WABA_ID,
                'access_token': 'synthetic-replacement-credential'}, headers={**headers, 'X-Channel-Version': '1'})
            assert replacement.status_code == 200 and replacement.json()['status'] == 'paused'
            assert checks == [(True, True, True)]
            async with j.sessions() as db:
                account = await db.get(WhatsAppAccount, j.bid)
                control = await db.get(ChannelConnectionState, (j.bid, 'whatsapp'))
                assert account.phone_number_id == PHONE_ID and control.version > 1
                assert decrypt(account.access_token) == 'synthetic-replacement-credential'
                assert not account.enabled and not account.automation_enabled
                record_property("reconnect_control_automation_enabled_observed", bool(control.automation_enabled))
            yield SimpleNamespace(j=j, client=client, base=base, headers=headers,
                sends=sends, message_id=message_id, initial_payload=initial_payload)
    finally:
        if old is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = old


async def enable_current_owner(world):
    response = await world.client.post(world.base + '/whatsapp/automation',
        json={'idempotency_key': str(uuid4()), 'enabled': True}, headers=world.headers)
    assert response.status_code == 200 and response.json()['status'] == 'enabled'


@pytest.mark.asyncio
async def test_old_activated_queue_is_withheld_after_same_phone_reconnect_and_is_not_automatically_retried(reconnect_intent):
    world = reconnect_intent
    await deliver_one(world.message_id, session_factory(world.j))
    assert world.sends == []
    async with world.j.sessions() as db:
        row = await db.get(WhatsAppMessage, world.message_id)
        assert row.status == 'failed' and row.provider_message_id is None and row.error
        assert row.payload == world.initial_payload
    # Enabling later does not resurrect an already withheld terminal action.
    await enable_current_owner(world)
    await deliver_one(world.message_id, session_factory(world.j))
    assert world.sends == []
    async with world.j.sessions() as db:
        row = await db.get(WhatsAppMessage, world.message_id)
        assert row.status == 'failed' and row.provider_message_id is None
        assert await db.scalar(select(func.count()).select_from(WhatsAppMessage).where(
            WhatsAppMessage.seller_id == world.j.bid, WhatsAppMessage.direction == 'outbound')) == 1


@pytest.mark.asyncio
async def test_explicit_owner_reenable_before_dispatch_characterizes_current_fresh_fact_contract(reconnect_intent):
    world = reconnect_intent
    await enable_current_owner(world)
    async with world.j.sessions.begin() as db:
        await db.execute(update(CatalogueSKU).where(CatalogueSKU.id == world.j.sku).values(
            price_minor=45678, stock_available=0))
    await deliver_one(world.message_id, session_factory(world.j))
    await deliver_one(world.message_id, session_factory(world.j))
    assert len(world.sends) == 1
    observed = world.sends[0]
    assert observed['replacement_credential'] and observed['message_id'] == world.message_id
    assert '₹456.78' in observed['text'] and 'recorded out of stock' in observed['text']
    assert '₹123.45' not in observed['text'] and 'PRIVATE' not in observed['text']
    async with world.j.sessions() as db:
        row = await db.get(WhatsAppMessage, world.message_id)
        assert row.status == 'accepted' and row.provider_message_id == 'synthetic-provider-acceptance'


@pytest.mark.asyncio
async def test_signed_material_plus_price_question_stays_handoff_at_queue_and_dispatch(sku_lane, monkeypatch):
    """Prepared actual ingress/SQL/worker check of remote d3aacd9 vocabulary fix."""
    from app.services.sku_fact_replies import HANDOFF
    j = sku_lane
    monkeypatch.setattr(settings, 'WHATSAPP_APP_SECRET', 'synthetic-v08-signature')
    monkeypatch.setattr(settings, 'CHANNEL_ENCRYPTION_KEY', Fernet.generate_key().decode())
    async with j.sessions.begin() as db:
        db.add(WhatsAppAccount(seller_id=j.bid, phone_number_id=PHONE_ID, waba_id=WABA_ID,
            access_token=encrypt('synthetic-material-only'), enabled=True,
            automation_enabled=True, reel_replies_enabled=True))
    from app.main import app
    async def dependency():
        async with j.sessions.begin() as db:
            yield db
    old = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = dependency
    sends = []
    async def provider_send(account, contact, message):
        sends.append(message.text)
        return 'synthetic-material-handoff-acceptance'
    monkeypatch.setattr(whatsapp_provider, 'send', provider_send)
    mid = 'synthetic-material-' + uuid4().hex
    packet = {'object': 'whatsapp_business_account', 'entry': [{'id': WABA_ID, 'changes': [{
        'field': 'messages', 'value': {'metadata': {'phone_number_id': PHONE_ID}, 'messages': [{
            'id': mid, 'from': '919876543210', 'timestamp': str(int(datetime.now(timezone.utc).timestamp())),
            'type': 'text', 'text': {'body': 'material and price? https://www.instagram.com/reel/Exact_code/'}}]}}]}]}
    raw = json.dumps(packet).encode()
    signature = 'sha256=' + hmac.new(b'synthetic-v08-signature', raw, hashlib.sha256).hexdigest()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            response = await client.post('/webhooks/whatsapp', content=raw,
                headers={'Content-Type': 'application/json', 'X-Hub-Signature-256': signature})
            assert response.status_code == 200
            # Identical signed delivery must retain one inbound and one action.
            assert (await client.post('/webhooks/whatsapp', content=raw,
                headers={'Content-Type': 'application/json', 'X-Hub-Signature-256': signature})).status_code == 200
        async with j.sessions() as db:
            inbound = await db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.seller_id == j.bid,
                WhatsAppMessage.direction == 'inbound', WhatsAppMessage.provider_message_id == mid))
            assert inbound is not None
            outbound = (await db.scalars(select(WhatsAppMessage).where(WhatsAppMessage.seller_id == j.bid,
                WhatsAppMessage.direction == 'outbound', WhatsAppMessage.idempotency_key == 'auto:reel:' + mid))).all()
            assert len(outbound) == 1 and outbound[0].status == 'queued' and outbound[0].text == HANDOFF
            message_id = outbound[0].id
        await deliver_one(message_id, session_factory(j))
        await deliver_one(message_id, session_factory(j))
        assert sends == [HANDOFF]
        assert '₹' not in sends[0] and 'PRIVATE' not in sends[0]
        async with j.sessions() as db:
            row = await db.get(WhatsAppMessage, message_id)
            assert row.status == 'accepted' and row.provider_message_id == 'synthetic-material-handoff-acceptance'
    finally:
        if old is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = old
