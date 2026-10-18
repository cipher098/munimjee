"""Actual-main/P01 fixtures for 0057; only the Meta transport is synthetic.

No fallback router/schema registration. This deliberately fails if production
composition has not installed the owned router. Never run without a lane lease.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.database import get_db
from app.models.whatsapp import WhatsAppAccount
from app.services.whatsapp_test_protocol import PhoneChoice, VerifiedToken


class SyntheticSignupProvider:
    evidence_kind = 'synthetic_fixture'

    def __init__(self, *, phone='12345', waba='456'):
        self.phone, self.waba = phone, waba
        self.expiry = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=2)
        self.calls = Counter()
        self.before = {}

    async def called(self, operation):
        self.calls[operation] += 1
        if operation in self.before:
            await self.before[operation]()

    def verified(self):
        return VerifiedToken('synthetic-wa-token-never-live', '123', self.expiry, frozenset({self.waba}))

    async def exchange(self, code, *, now):
        await self.called('exchange')
        return self.verified()

    async def inspect(self, token, *, now):
        await self.called('inspect')
        return self.verified()

    async def choices(self, verified, waba_id):
        await self.called('choices')
        assert waba_id == self.waba and waba_id in verified.waba_ids
        return (PhoneChoice(self.waba, self.phone, 'Synthetic test account', '+910000000000'),)

    async def subscribe(self, token, waba_id):
        await self.called('subscribe')

    async def register(self, token, phone_id, pin):
        await self.called('register')


@pytest_asyncio.fixture
async def native_wa_setup(migrated_engine, monkeypatch):
    from app.main import app
    from app.api.v1.whatsapp_self_service import provider_dependency
    assert any(getattr(r, 'path', None) == '/v1/businesses/{business_id}/channels/whatsapp/setup'
               for r in app.router.routes), 'Real app.main must mount 0057 before this actual acceptance gate'
    for key, value in {
        'V1_AUTH_ENABLED': True, 'V1_ENFORCE_LEGACY_ACCESS': True,
        'V1_WHATSAPP_ONBOARDING_ENABLED': True, 'V1_CHANNEL_TESTS_ENABLED': True,
        'WHATSAPP_EMBEDDED_APP_ID': '123', 'WHATSAPP_EMBEDDED_CONFIG_ID': '789',
        'WHATSAPP_EMBEDDED_APP_SECRET': 'synthetic-matching-app-secret',
        'WHATSAPP_APP_SECRET': 'synthetic-matching-app-secret',
        'WHATSAPP_EMBEDDED_GRAPH_VERSION': 'v26.0',
        'WHATSAPP_WEBHOOK_VERIFY_TOKEN': 'synthetic-verify-only',
        'CHANNEL_ENCRYPTION_KEY': Fernet.generate_key().decode(),
        'PUBLIC_BASE_URL': 'https://test',
    }.items():
        monkeypatch.setattr(settings, key, value)
    sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)
    original_overrides = dict(app.dependency_overrides)
    provider = SyntheticSignupProvider()

    async def database():
        # Production permits consumed/step claim commits before network I/O.
        async with sessions() as db:
            try:
                yield db
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    app.dependency_overrides[get_db] = database
    app.dependency_overrides[provider_dependency] = lambda: provider
    clients = []

    async def signup(name='Synthetic WA owner'):
        client = AsyncClient(transport=ASGITransport(app=app), base_url='https://test',
                             headers={'Origin': 'https://test'})
        clients.append(client)
        response = await client.post('/api/v1/auth/signup', json={
            'email': f'{uuid4().hex}@example.test', 'password': 'synthetic-owner-password-only',
            'business_name': name})
        assert response.status_code == 201, 'Synthetic native signup must succeed'
        data = response.json()
        bid = UUID(data['businesses'][0]['id'])
        return SimpleNamespace(client=client, sessions=sessions, provider=provider,
            bid=bid, uid=UUID(data['user_id']), csrf={'X-CSRF-Token': client.cookies['v1_csrf']},
            base=f'/api/v1/businesses/{bid}/channels/whatsapp', signup=signup,
            engine=migrated_engine)

    try:
        yield await signup()
    finally:
        for client in clients:
            await client.aclose()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)


async def post(j, path, body, *, status=200):
    response = await j.client.post(j.base + path, json=body, headers=j.csrf)
    # Never put secret-bearing request/response bodies into assertion output.
    assert response.status_code == status, f'Unexpected WA command status {response.status_code} at {path.rsplit("/", 1)[-1]}'
    for header, expected in [('cache-control', 'no-store'), ('referrer-policy', 'no-referrer')]:
        assert response.headers.get(header) == expected
    return response.json()


async def prepared_signup(j, *, version=0):
    key = str(uuid4())
    start_body = dict(idempotency_key=key, expected_connection_version=version, notice_reviewed=True)
    started = await post(j, '/signup', start_body)
    aid = started['attempt']['attempt_id']
    exchange = dict(idempotency_key=key, signed_state=started['signed_state'], code='synthetic-one-use-code')
    await post(j, f'/signup/{aid}/exchange', exchange)
    assets = dict(idempotency_key=key, event='FINISH', waba_id=j.provider.waba,
                  phone_number_id=j.provider.phone, provider_business_id='789')
    await post(j, f'/signup/{aid}/assets', assets)
    choices = await j.client.get(j.base + f'/signup/{aid}/choices')
    assert choices.status_code == 200
    choice = choices.json()['choices'][0]
    selected = dict(idempotency_key=str(uuid4()), expected_connection_version=version,
        choice_id=choice['choice_id'], waba_id=choice['waba_id'], phone_number_id=choice['phone_number_id'],
        expected_choice_fingerprint=choice['fingerprint'], owner_confirmed=True,
        subscription_confirmed=True, request_registration=True, registration_pin='123456')
    return SimpleNamespace(aid=UUID(aid), start=started, start_body=start_body,
                           exchange=exchange, assets=assets, selection=selected)


async def attached_signup(j):
    flow = await prepared_signup(j)
    result = await post(j, f'/signup/{flow.aid}/select', flow.selection)
    assert result['result']['status'] == 'attached'
    return flow


async def challenge(j, *, version=1):
    return await post(j, '/tests', dict(idempotency_key=str(uuid4()),
        expected_connection_version=version, recipient_authorized=True))


async def bind_recipient(j, challenged, *, phone='910000000001', mid=None):
    """Direct shared-helper proof, not evidence of installed signed ingress."""
    from app.services.whatsapp_test_authority import intercept_reserved
    at = datetime.now(timezone.utc)
    event = dict(id=mid or 'synthetic-inbound-' + uuid4().hex, type='text', **{'from': phone},
                 timestamp=str(int(at.timestamp())), text={'body': challenged['command']})
    async with j.sessions.begin() as db:
        account = await db.scalar(select(WhatsAppAccount).where(WhatsAppAccount.seller_id == j.bid).with_for_update())
        assert await intercept_reserved(db, account, event, received_at=at) is True
    response = await j.client.get(j.base + f'/tests/{challenged["test"]["test_id"]}/recipient')
    assert response.status_code == 200
    return response.json()


def send_command(recipient):
    return dict(idempotency_key=str(uuid4()), expected_connection_version=recipient['connection_version'],
        recipient_authorized=True, recipient_contact_id=recipient['recipient_contact_id'],
        inbound_message_id=recipient['inbound_message_id'], fixed_text_version='wa-connection-test.v1')
