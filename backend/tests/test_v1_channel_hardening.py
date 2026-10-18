"""Independent native channel-session races on actual app.main/Alembic schema.

The first three assertions reproduced the reviewed baseline failures; this
owned repair must make them pass without relaxing their boundaries. Only synthetic provider functions;
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
from tests.test_whatsapp import wa


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


@pytest.mark.asyncio
async def test_native_channel_final_check_runs_after_staged_flush(native_channels, monkeypatch):
    from app.api.v1 import channel_operator as routes
    j = native_channels
    setup_settings(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    original = routes.finalize
    async def final_boundary(request, db, business_id, actor, capability, **kwargs):
        await db.flush()
        entered.set()
        await release.wait()
        return await original(request, db, business_id, actor, capability, **kwargs)
    async def provider(*args, **kwargs):
        return {'id': '7654321', 'display_phone_number': '+910000000000'}
    monkeypatch.setattr(routes, 'finalize', final_boundary)
    monkeypatch.setattr('app.services.channel_connections.whatsapp_provider.verify_connection', provider)
    request = asyncio.create_task(j.client.post(f'/api/v1/businesses/{j.bid}/channels/whatsapp/connect',
        headers={**j.csrf, 'X-Channel-Version': '0'}, json={'idempotency_key': str(uuid4()),
        'waba_id': '1234567', 'phone_number_id': '7654321', 'access_token': 'synthetic-staged-token'}))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await asyncio.wait_for(revoke_session(j), 5)
    finally:
        release.set()
    result = await asyncio.wait_for(request, 5)
    assert result.status_code == 401
    async with j.sessions() as db:
        assert await db.get(WhatsAppAccount, j.bid) is None
        assert await db.scalar(select(func.count()).select_from(ChannelOperation).where(ChannelOperation.business_id == j.bid)) == 0


@pytest.mark.asyncio
async def test_native_channel_read_rechecks_session_after_provider_projection(native_channels, monkeypatch):
    from app.services import channel_connections
    j = native_channels
    original = channel_connections.connection_views
    entered, release = asyncio.Event(), asyncio.Event()
    async def held(db, business_id):
        result = await original(db, business_id)
        entered.set()
        await release.wait()
        return result
    monkeypatch.setattr(channel_connections, 'connection_views', held)
    request = asyncio.create_task(j.client.get(f'/api/v1/businesses/{j.bid}/channels'))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await asyncio.wait_for(revoke_session(j), 5)
    finally:
        release.set()
    result = await asyncio.wait_for(request, 5)
    assert result.status_code == 401
    assert 'business_name' not in result.json() and 'channels' not in result.json()


@pytest.mark.asyncio
async def test_native_wa_conditional_receipts_bind_header_and_reject_late_old_request(native_channels, monkeypatch):
    from app.services.channel_credentials import decrypt
    j = native_channels
    setup_settings(monkeypatch)
    calls = []
    async def provider(*args, **kwargs):
        calls.append(True)
        return {'id': '7654321', 'display_phone_number': '+910000000000'}
    monkeypatch.setattr('app.services.channel_connections.whatsapp_provider.verify_connection', provider)
    base = f'/api/v1/businesses/{j.bid}/channels'
    body = {'idempotency_key': str(uuid4()), 'waba_id': '1234567',
        'phone_number_id': '7654321', 'access_token': 'synthetic-current-token'}
    first = await j.client.post(base+'/whatsapp/connect', json=body, headers={**j.csrf, 'X-Channel-Version': '0'})
    assert first.status_code == 200, first.text
    assert first.json()['connection_version'] == 1
    assert first.json()['business_id'] == str(j.bid) and first.json()['idempotency_key'] == body['idempotency_key']
    assert first.json()['action'] == 'connect_whatsapp'
    replay = await j.client.post(base+'/whatsapp/connect', json=body, headers={**j.csrf, 'X-Channel-Version': '0'})
    assert replay.status_code == 200 and replay.json() == first.json()
    changed_header = await j.client.post(base+'/whatsapp/connect', json=body, headers={**j.csrf, 'X-Channel-Version': '1'})
    assert changed_header.status_code == 409
    late = await j.client.post(base+'/whatsapp/connect', json={**body,
        'idempotency_key': str(uuid4()), 'access_token': 'synthetic-late-old-token'}, headers={**j.csrf, 'X-Channel-Version': '0'})
    assert late.status_code == 409 and late.json()['detail']['code'] == 'channel_generation_stale'
    assert len(calls) == 1
    current = await j.client.get(base)
    assert current.status_code == 200 and current.headers['Cache-Control'] == 'no-store'
    assert next(x for x in current.json()['channels'] if x['channel'] == 'whatsapp')['connection_version'] == 1
    assert 'synthetic-' not in current.text
    async with j.sessions() as db:
        assert decrypt((await db.get(WhatsAppAccount, j.bid)).access_token) == body['access_token']
        assert await db.scalar(select(func.count()).select_from(ChannelOperation).where(ChannelOperation.business_id == j.bid)) == 1


@pytest.mark.asyncio
async def test_native_wa_same_generation_concurrent_replacements_allow_one_provider_lookup(native_channels, monkeypatch):
    j = native_channels
    setup_settings(monkeypatch)
    calls = []
    async def provider(*args, **kwargs):
        calls.append(True)
        await asyncio.sleep(0)
        return {'id': '7654321', 'display_phone_number': '+910000000000'}
    monkeypatch.setattr('app.services.channel_connections.whatsapp_provider.verify_connection', provider)
    async def save(index):
        return await j.client.post(f'/api/v1/businesses/{j.bid}/channels/whatsapp/connect',
            headers={**j.csrf, 'X-Channel-Version': '0'}, json={'idempotency_key': str(uuid4()),
            'waba_id': '1234567', 'phone_number_id': '7654321', 'access_token': f'synthetic-replacement-{index}'})
    results = await asyncio.wait_for(asyncio.gather(save(1), save(2)), 10)
    assert sorted(x.status_code for x in results) == [200, 409]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_native_wa_readiness_uses_effective_automation_and_explicit_enable_pause(native_channels, monkeypatch):
    from app.models.whatsapp import WhatsAppMessage
    from app.services import whatsapp
    j = native_channels
    setup_settings(monkeypatch)
    async def provider(*args, **kwargs): return {'id': '7654321', 'display_phone_number': '+910000000000'}
    monkeypatch.setattr('app.services.channel_connections.whatsapp_provider.verify_connection', provider)
    base = f'/api/v1/businesses/{j.bid}/channels'
    saved = await j.client.post(base+'/whatsapp/connect', headers={**j.csrf, 'X-Channel-Version': '0'},
        json={'idempotency_key': str(uuid4()), 'waba_id': '1234567', 'phone_number_id': '7654321',
            'access_token': 'synthetic-automation-test-token'})
    assert saved.status_code == 200, saved.text
    async with j.sessions.begin() as db:
        account = await db.get(WhatsAppAccount, j.bid)
        account.enabled, account.automation_enabled = True, False
        account.rules = [{'keyword': 'price', 'reply': 'Synthetic reply must not be queued'}]
        await whatsapp.ingest_message(db, account, {}, {'id': 'synthetic-paused-inbound', 'from': '919999999999',
            'timestamp': str(int(datetime.now(timezone.utc).timestamp())), 'type': 'text', 'text': {'body': 'price'}})
        assert await db.scalar(select(func.count()).select_from(WhatsAppMessage).where(
            WhatsAppMessage.seller_id == j.bid, WhatsAppMessage.direction == 'outbound')) == 0
    current = await j.client.get(base)
    view = next(item for item in current.json()['channels'] if item['channel'] == 'whatsapp')
    assert view['configured'] is True and view['status'] == 'paused' and view['automation_enabled'] is False
    for enabled in (True, False):
        result = await j.client.post(base+'/whatsapp/automation', json={'idempotency_key': str(uuid4()), 'enabled': enabled}, headers=j.csrf)
        assert result.status_code == 200, result.text
        async with j.sessions() as db:
            account = await db.get(WhatsAppAccount, j.bid)
            state = await db.get(ChannelConnectionState, (j.bid, 'whatsapp'))
            assert account.enabled is enabled and account.automation_enabled is enabled and state.automation_enabled is enabled
        current = await j.client.get(base)
        view = next(item for item in current.json()['channels'] if item['channel'] == 'whatsapp')
        assert view['automation_enabled'] is enabled and view['status'] == ('access_verified' if enabled else 'paused')


@pytest.mark.asyncio
@pytest.mark.parametrize('header', ['true', '1.0', '-1', '+1', '00', '2000000001', '[0]'])
async def test_native_wa_version_header_is_strict_and_no_provider_on_rejection(native_channels, monkeypatch, header):
    j = native_channels
    setup_settings(monkeypatch)
    async def forbidden(*args, **kwargs): raise AssertionError('Invalid header must not reach a provider')
    monkeypatch.setattr('app.services.channel_connections.whatsapp_provider.verify_connection', forbidden)
    result = await j.client.post(f'/api/v1/businesses/{j.bid}/channels/whatsapp/connect',
        headers={**j.csrf, 'X-Channel-Version': header}, json={'idempotency_key': str(uuid4()),
        'waba_id': '1234567', 'phone_number_id': '7654321', 'access_token': 'synthetic-invalid-header-token'})
    assert result.status_code == 422
    async with j.sessions() as db:
        assert await db.get(WhatsAppAccount, j.bid) is None
        assert await db.scalar(select(func.count()).select_from(ChannelOperation).where(ChannelOperation.business_id == j.bid)) == 0


@pytest.mark.asyncio
async def test_versioned_channels_deny_legacy_owner_bearer_with_native_cookie(native_channels):
    from jose import jwt
    from datetime import timedelta
    j = native_channels
    legacy = jwt.encode({'role': 'seller', 'sub': str(j.bid),
        'exp': datetime.now(timezone.utc)+timedelta(hours=1)}, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    for path in [f'/v1/businesses/{j.bid}/channels', f'/api/v1/businesses/{j.bid}/channels']:
        result = await j.client.get(path, headers={'Authorization': 'Bearer '+legacy})
        assert result.status_code == 401
    result = await j.client.post(f'/api/v1/businesses/{j.bid}/channels/instagram/disconnect',
        json={'idempotency_key': str(uuid4())}, headers={'Authorization': 'Bearer '+legacy})
    assert result.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize('legacy_action', ['replace', 'disconnect', 'eligibility'])
async def test_native_conditional_setup_cannot_cross_newer_legacy_account_write(native_channels, monkeypatch, legacy_action):
    from app.api.dashboard_auth import _make_token
    from app.services.channel_credentials import decrypt
    j = native_channels
    setup_settings(monkeypatch)
    calls = []
    async def provider(*args, **kwargs):
        calls.append(True)
        return {'id': '7654321', 'display_phone_number': '+910000000000'}
    monkeypatch.setattr('app.services.channel_connections.whatsapp_provider.verify_connection', provider)
    endpoint = f'/api/v1/businesses/{j.bid}/channels/whatsapp/connect'
    body = {'idempotency_key': str(uuid4()), 'waba_id': '1234567', 'phone_number_id': '7654321', 'access_token': 'synthetic-first-token'}
    assert (await j.client.post(endpoint, json=body, headers={**j.csrf, 'X-Channel-Version': '0'})).status_code == 200
    j.client.cookies.set('dashboard_session', _make_token('seller', str(j.bid), 'synthetic-owner'))
    if legacy_action == 'replace':
        legacy = await j.client.put('/whatsapp/account', json={'waba_id': '1234567', 'phone_number_id': '7654321', 'access_token': 'synthetic-legacy-new-token'})
    elif legacy_action == 'disconnect':
        legacy = await j.client.delete('/whatsapp/account')
    else:
        legacy = await j.client.patch('/whatsapp/account', json={'enabled': True})
    assert legacy.status_code == 200, legacy.text
    before = len(calls)
    stale = await j.client.post(endpoint, json={**body, 'idempotency_key': str(uuid4()), 'access_token': 'synthetic-late-native-token'}, headers={**j.csrf, 'X-Channel-Version': '1'})
    assert stale.status_code == 409 and stale.json()['detail']['code'] == 'channel_generation_stale'
    assert len(calls) == before
    async with j.sessions() as db:
        assert (await db.get(ChannelConnectionState, (j.bid, 'whatsapp'))).version == 2
        account = await db.get(WhatsAppAccount, j.bid)
        if legacy_action == 'replace': assert decrypt(account.access_token) == 'synthetic-legacy-new-token'
        elif legacy_action == 'disconnect': assert account.access_token == '' and account.enabled is False
        else: assert account.enabled is True


@pytest.mark.asyncio
async def test_legacy_wa_provider_wait_rechecks_current_enforced_owner_cutoff(native_channels, monkeypatch):
    from app.api.dashboard_auth import _make_token
    from app.models.identity import User
    j = native_channels
    setup_settings(monkeypatch)
    j.client.cookies.set('dashboard_session', _make_token('seller', str(j.bid), 'synthetic-owner'))
    entered, release = asyncio.Event(), asyncio.Event()
    async def provider(*args, **kwargs):
        entered.set()
        await release.wait()
        return {'id': '7654321', 'display_phone_number': '+910000000000'}
    monkeypatch.setattr('app.services.channel_connections.whatsapp_provider.verify_connection', provider)
    request = asyncio.create_task(j.client.put('/whatsapp/account', json={'waba_id': '1234567',
        'phone_number_id': '7654321', 'access_token': 'synthetic-legacy-revoked-token'}))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        async with j.sessions.begin() as db:
            user = await db.get(User, j.uid)
            user.legacy_revoked_before = datetime.now(timezone.utc)
    finally:
        release.set()
    result = await asyncio.wait_for(request, 5)
    assert result.status_code == 401
    async with j.sessions() as db:
        assert await db.get(WhatsAppAccount, j.bid) is None
        assert await db.get(ChannelConnectionState, (j.bid, 'whatsapp')) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('first_writer', ['native', 'legacy'])
async def test_native_and_legacy_wa_provider_waits_share_tenant_state_account_lock_order(native_channels, monkeypatch, first_writer):
    from app.api.dashboard_auth import _make_token
    from app.api.routes import whatsapp as legacy_routes
    from app.services import channel_operator
    j = native_channels
    setup_settings(monkeypatch)
    endpoint = f'/api/v1/businesses/{j.bid}/channels/whatsapp/connect'
    body = {'idempotency_key': str(uuid4()), 'waba_id': '1234567', 'phone_number_id': '7654321', 'access_token': 'synthetic-seed-token'}
    async def plain(*args, **kwargs): return {'id': '7654321', 'display_phone_number': '+910000000000'}
    monkeypatch.setattr('app.services.channel_connections.whatsapp_provider.verify_connection', plain)
    assert (await j.client.post(endpoint, json=body, headers={**j.csrf, 'X-Channel-Version': '0'})).status_code == 200
    j.client.cookies.set('dashboard_session', _make_token('seller', str(j.bid), 'synthetic-owner'))
    entered, second_lock, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = channel_operator.lock_tenant_rows
    async def observed_lock(*args, **kwargs):
        if entered.is_set(): second_lock.set()
        return await original(*args, **kwargs)
    monkeypatch.setattr(channel_operator, 'lock_tenant_rows', observed_lock)
    monkeypatch.setattr(legacy_routes, 'lock_tenant_rows', observed_lock)
    async def held(token, *args, **kwargs):
        if token == f'synthetic-{first_writer}-token':
            entered.set()
            await release.wait()
        return await plain()
    monkeypatch.setattr('app.services.channel_connections.whatsapp_provider.verify_connection', held)
    async def native():
        return await j.client.post(endpoint, json={**body, 'idempotency_key': str(uuid4()), 'access_token': 'synthetic-native-token'}, headers={**j.csrf, 'X-Channel-Version': '1'})
    async def legacy():
        return await j.client.put('/whatsapp/account', json={'waba_id': '1234567', 'phone_number_id': '7654321', 'access_token': 'synthetic-legacy-token'})
    first = asyncio.create_task(native() if first_writer == 'native' else legacy())
    await asyncio.wait_for(entered.wait(), 5)
    second = asyncio.create_task(legacy() if first_writer == 'native' else native())
    try:
        await asyncio.wait_for(second_lock.wait(), 5)
    finally:
        release.set()
    results = await asyncio.wait_for(asyncio.gather(first, second), 10)
    assert sorted(x.status_code for x in results) == ([200, 200] if first_writer == 'native' else [200, 409])


@pytest.mark.asyncio
async def test_legacy_only_wa_flagoff_does_not_create_business_or_control(wa, monkeypatch):
    from app.models.identity import Business
    from app.services import whatsapp_provider
    monkeypatch.setattr(settings, 'V1_ENFORCE_LEGACY_ACCESS', False)
    async def provider(token, waba, phone): return {'id': phone, 'display_phone_number': '+910000000000'}
    monkeypatch.setattr(whatsapp_provider, 'verify_connection', provider)
    seller_id = wa.ids['sellers'][0]
    async with wa.session() as db:
        assert await db.get(Business, seller_id) is None
    response = await wa.client.put('/whatsapp/account', json={'waba_id': '200', 'phone_number_id': '100', 'access_token': 'synthetic-legacy-only-token'})
    assert response.status_code == 200, response.text
    assert 'access_token' not in response.json()
    async with wa.session() as db:
        assert await db.get(Business, seller_id) is None
        assert await db.get(ChannelConnectionState, (seller_id, 'whatsapp')) is None


@pytest.mark.asyncio
async def test_legacy_wa_admin_viewas_flag_semantics_remain_explicit(wa, monkeypatch):
    from app.api.dashboard_auth import _make_token
    from app.services import whatsapp_provider
    async def provider(token, waba, phone): return {'id': phone, 'display_phone_number': '+910000000000'}
    monkeypatch.setattr(whatsapp_provider, 'verify_connection', provider)
    wa.client.cookies.set('dashboard_session', _make_token('admin', None, 'synthetic-admin'))
    wa.client.cookies.set('view_seller', str(wa.ids['sellers'][0]))
    body = {'waba_id': '200', 'phone_number_id': '100', 'access_token': 'synthetic-admin-view-token'}
    monkeypatch.setattr(settings, 'V1_ENFORCE_LEGACY_ACCESS', True)
    assert (await wa.client.put('/whatsapp/account', json=body)).status_code == 403
    monkeypatch.setattr(settings, 'V1_ENFORCE_LEGACY_ACCESS', False)
    assert (await wa.client.put('/whatsapp/account', json=body)).status_code == 200
