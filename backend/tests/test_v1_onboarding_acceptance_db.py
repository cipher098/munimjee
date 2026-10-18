"""Independent native channel-session races on actual app.main/Alembic schema.

Desired safety assertions intentionally expose current source gaps until the
runtime owner supplies the coordinated fix. Only synthetic provider functions;
P01 must allocate a fresh explicit disposable lane before executing this file.
"""
import asyncio
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import pytest_asyncio
from app.database import get_db
from cryptography.fernet import Fernet
from sqlalchemy import func, select, update

from app.config import settings
from app.models.channel_operator import ChannelConnectionState, ChannelOperation
from app.models.identity_auth import UserSession
from app.models.seller import Seller
from app.models.whatsapp import WhatsAppAccount
from tests.test_v1_native_completion_import_http import native_import


@pytest_asyncio.fixture
async def native_channels(native_import):
    # The actual OAuth callback deliberately commits consumption before network
    # exchange. Match production get_db instead of sessions.begin() spanning yield.
    from app.main import app
    j = native_import
    previous = app.dependency_overrides[get_db]
    async def database():
        async with j.sessions() as db:
            try:
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
    app.dependency_overrides[get_db] = database
    try:
        yield j
    finally:
        app.dependency_overrides[get_db] = previous


def setup_settings(monkeypatch):
    for field, value in {
        'CHANNEL_ENCRYPTION_KEY': Fernet.generate_key().decode(),
        'INSTAGRAM_APP_ID': '123456', 'INSTAGRAM_APP_SECRET': 'synthetic-app-secret',
        'META_WEBHOOK_SECRET': 'synthetic-webhook-secret',
        'WHATSAPP_APP_SECRET': 'synthetic-wa-secret',
        'WHATSAPP_WEBHOOK_VERIFY_TOKEN': 'synthetic-wa-verify',
    }.items():
        monkeypatch.setattr(settings, field, value)


async def revoke_session(j):
    async with j.sessions.begin() as db:
        await db.execute(update(UserSession).where(UserSession.user_id == j.uid).values(
            revoked_at=datetime.now(timezone.utc)))


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['instagram_verify', 'whatsapp_connect'])
async def test_native_channel_provider_wait_cannot_commit_after_session_revoke(native_channels, monkeypatch, operation):
    j = native_channels
    setup_settings(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    async def provider(*args, **kwargs):
        entered.set()
        await release.wait()
        return {'user_id': '1234567', 'id': '7654321', 'display_phone_number': '+910000000000'}
    if operation == 'instagram_verify':
        async with j.sessions.begin() as db:
            seller = await db.get(Seller, j.bid)
            seller.instagram_id = seller.instagram_page_id = '1234567'
            seller.instagram_token = 'synthetic-ig-token'
            db.add(ChannelConnectionState(business_id=j.bid, channel='instagram',
                provider_account_id='1234567', check_status='not_checked', automation_enabled=False))
        monkeypatch.setattr('app.services.channel_connections.ig.fetch_ig_user', provider)
        path, body = '/instagram/verify', {'idempotency_key': str(uuid4())}
    else:
        monkeypatch.setattr('app.services.channel_connections.whatsapp_provider.verify_connection', provider)
        path, body = '/whatsapp/connect', {'idempotency_key': str(uuid4()), 'waba_id': '1234567',
            'phone_number_id': '7654321', 'access_token': 'synthetic-whatsapp-token'}
    base = f'/api/v1/businesses/{j.bid}/channels'
    request = asyncio.create_task(j.client.post(base+path, json=body, headers=j.csrf))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await asyncio.wait_for(revoke_session(j), 5)
    finally:
        release.set()
    result = await asyncio.wait_for(request, 5)
    async with j.sessions() as db:
        audits = await db.scalar(select(func.count()).select_from(ChannelOperation).where(ChannelOperation.business_id == j.bid))
        account = await db.get(WhatsAppAccount, j.bid)
        state = await db.get(ChannelConnectionState, (j.bid, 'instagram'))
        observed = {'status': result.status_code, 'audit_count': audits,
            'wa_credentials_saved': bool(account and account.access_token),
            'ig_access_verified': bool(state and state.check_status == 'verified' and state.checked_at)}
    assert result.status_code == 401, f'Revoked native session mutation persisted: {observed}'
    assert audits == 0
    if operation == 'whatsapp_connect': assert account is None
    else: assert state.check_status == 'not_checked' and state.checked_at is None


@pytest.mark.asyncio
async def test_native_instagram_callback_rechecks_session_after_consumed_exchange(native_channels, monkeypatch):
    j = native_channels
    setup_settings(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    async def exchange(*args, **kwargs):
        entered.set()
        await release.wait()
        return {'access_token': 'synthetic-short-token'}
    async def long_token(*args, **kwargs): return 'synthetic-long-token'
    async def principal(*args, **kwargs): return {'user_id': '1234567', 'account_type': 'BUSINESS'}
    monkeypatch.setattr('app.services.channel_connections.ig.exchange_code_for_user_token', exchange)
    monkeypatch.setattr('app.services.channel_connections.ig.exchange_for_long_lived_token', long_token)
    monkeypatch.setattr('app.services.channel_connections.ig.fetch_ig_user', principal)
    base = f'/api/v1/businesses/{j.bid}/channels'
    start = await j.client.post(base+'/instagram/connect', json={'idempotency_key': str(uuid4())}, headers=j.csrf)
    assert start.status_code == 200, start.text
    state = parse_qs(urlsplit(start.json()['authorization_url']).query)['state'][0]
    request = asyncio.create_task(j.client.get(base+'/instagram/callback', params={'state': state, 'code': 'synthetic-one-use-code'}))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await asyncio.wait_for(revoke_session(j), 5)
    finally:
        release.set()
    result = await asyncio.wait_for(request, 5)
    async with j.sessions() as db:
        seller = await db.get(Seller, j.bid)
        saved = bool(seller.instagram_token or seller.instagram_page_id)
    assert result.status_code == 401, f'Revoked-session OAuth returned {result.status_code}; credentials_saved={saved}'
    assert saved is False
