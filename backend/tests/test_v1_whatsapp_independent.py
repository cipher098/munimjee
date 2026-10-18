"""Independent no-DB regressions of exact frozen helpers; no provider calls.

No raw command/challenge is emitted by assertions or artifact output.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.config import settings
from app.services import whatsapp_test_authority as authority
from app.services.whatsapp_test_protocol import (
    RESERVED_NAMESPACE, SessionBinding, challenge_command, reserved_command,
)


@pytest.mark.asyncio
async def test_reserved_secret_in_provider_mid_never_reaches_any_retained_message_scalar(monkeypatch):
    monkeypatch.setattr(settings, 'V1_CHANNEL_TESTS_ENABLED', False)
    command = challenge_command('synthetic-independent-only', UUID(int=5),
        SessionBinding(UUID(int=1), UUID(int=2), UUID(int=3), 0))
    rows = []
    db = SimpleNamespace(scalar=AsyncMock(return_value=None), add=rows.append, flush=AsyncMock())
    account = SimpleNamespace(seller_id=UUID(int=1), phone_number_id='12345', waba_id='67890')
    at = datetime(2026, 10, 18, tzinfo=timezone.utc)
    packet = {'id': 'wamid.' + command, 'from': '919876543210',
        'timestamp': str(int(at.timestamp())), 'type': 'text', 'text': {'body': 'ordinary text'}}
    assert await authority.intercept_reserved(db, account, packet, received_at=at) is True
    # Keep raw packet/command out of pytest assertion diagnostics.
    retained_reserved_metadata = any(reserved_command(getattr(row, field, None))
        for row in rows for field in ('provider_message_id', 'idempotency_key'))
    assert retained_reserved_metadata is False
    assert rows == []


@pytest.mark.asyncio
async def test_cancelled_graph_waiters_keep_admission_until_the_underlying_jobs_finish(monkeypatch):
    """Four interrupted callers cannot create an unbounded pending IO backlog."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock
    from app.services import whatsapp_signup_provider as provider

    release, all_started = Event(), Event()
    count_lock = Lock()
    started = 0
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='independent-wa-fixture')

    class Isolated(provider.PinnedGraphTransport):
        _pool = pool
        _lock = Lock()
        _inflight = set()

    def bounded_fake_io(request):
        nonlocal started
        with count_lock:
            started += 1
            if started == 4:
                all_started.set()
        if not release.wait(2):
            raise RuntimeError('Synthetic fixture deadline, no network')
        return {}

    monkeypatch.setattr(Isolated, '_request', staticmethod(bounded_fake_io))
    request = provider.GraphRequest('GET', '/v26.0/oauth/access_token',
        query=(('client_id', '123'), ('client_secret', 'synthetic-only'), ('code', 'synthetic-only')))
    transport = Isolated()
    tasks = [asyncio.create_task(transport.request(request)) for _ in range(4)]
    try:
        async def wait_started():
            while not all_started.is_set():
                await asyncio.sleep(.001)
        await asyncio.wait_for(wait_started(), 1)
        for task in tasks:
            task.cancel()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(value, asyncio.CancelledError) for value in outcomes)
        with pytest.raises(provider.SignupProviderError):
            await transport.request(request)
        assert started == 4
        assert len(Isolated._inflight) == 4
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        pool.shutdown(wait=True)


@pytest.mark.asyncio
async def test_global_test_gate_revoked_during_final_projection_withholds_dispatch(monkeypatch):
    from datetime import timedelta
    from fastapi import HTTPException
    at = datetime(2026, 10, 18, tzinfo=timezone.utc)
    bid, uid, sid, contact_id, message_id = (UUID(int=i) for i in range(1, 6))
    account = SimpleNamespace(seller_id=bid, phone_number_id='12345', waba_id='67890')
    contact = SimpleNamespace(id=contact_id, opted_out=False, last_inbound_at=at)
    from app.services.whatsapp_test_protocol import FIXED_REPLY
    message = SimpleNamespace(id=message_id, seller_id=bid, phone_number_id='12345',
        contact_id=contact_id, direction='outbound', kind='text', text=FIXED_REPLY, payload={})
    auth = SimpleNamespace(expires_at=at+timedelta(seconds=120), authorized_at=at,
        business_id=bid, phone_number_id='12345', recipient_contact_id=contact_id,
        actor_user_id=uid, actor_session_id=sid, actor_auth_version=0, connection_version=1)
    db = SimpleNamespace(scalar=AsyncMock(return_value=auth))
    monkeypatch.setattr(settings, 'V1_CHANNEL_TESTS_ENABLED', True)
    monkeypatch.setattr(authority, 'current_provenance', AsyncMock())
    monkeypatch.setattr(authority, 'current_owner_session', AsyncMock())
    async def latest_projection(*args, **kwargs):
        monkeypatch.setattr(settings, 'V1_CHANNEL_TESTS_ENABLED', False)
        return True
    monkeypatch.setattr(authority, 'final_test_projection', latest_projection)
    with pytest.raises(HTTPException):
        await authority.exact_test_authority(db, account, contact, message, at=at)


@pytest.mark.asyncio
async def test_fixed_reply_authorization_never_outlives_its_verified_token(monkeypatch):
    from datetime import timedelta
    from app.services import whatsapp_connection_tests as tests
    from app.schemas.whatsapp_self_service import SendTest
    at = datetime(2026, 10, 18, tzinfo=timezone.utc)
    bid, uid, sid, test_id, contact_id, inbound_id = (UUID(int=i) for i in range(1, 7))
    binding = SessionBinding(bid, uid, sid, 0)
    row = SimpleNamespace(id=test_id, business_id=bid, actor_user_id=uid, actor_session_id=sid,
        actor_auth_version=0, connection_version=1, phone_number_id='12345',
        recipient_contact_id=contact_id, inbound_message_id=inbound_id,
        cancelled_at=None, expires_at=at+timedelta(minutes=5))
    account = SimpleNamespace(seller_id=bid, phone_number_id='12345')
    contact = SimpleNamespace(id=contact_id, opted_out=False, last_inbound_at=at)
    token_expiry = at + timedelta(seconds=10)
    provenance = SimpleNamespace(token_expiry_kind='at', token_expires_at=token_expiry)
    rows = []
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        one_or_none=lambda: SimpleNamespace(recipient_contact_id=contact_id))),
        scalar=AsyncMock(side_effect=[account, contact, None, None]), add=rows.append, flush=AsyncMock())
    auth = SimpleNamespace(binding=binding, check=AsyncMock(), finalize=AsyncMock())
    monkeypatch.setattr(settings, 'V1_CHANNEL_TESTS_ENABLED', True)
    monkeypatch.setattr(tests, 'now', lambda: at)
    monkeypatch.setattr(tests, 'own_test', AsyncMock(return_value=row))
    monkeypatch.setattr(tests, 'current_provenance', AsyncMock(return_value=provenance))
    monkeypatch.setattr(tests, 'test_view', AsyncMock(return_value=SimpleNamespace()))
    payload = SendTest(idempotency_key=UUID(int=7), expected_connection_version=1,
        recipient_authorized=True, recipient_contact_id=contact_id, inbound_message_id=inbound_id,
        fixed_text_version='wa-connection-test.v1')
    await tests.queue_fixed_reply(db, auth, test_id, payload)
    authorization = next(value for value in rows if isinstance(value, authority.WhatsAppTestAuthorization))
    assert authorization.expires_at <= token_expiry


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['subscription', 'exchange'])
async def test_native_revocation_at_claim_commit_starts_no_new_provider_operation(monkeypatch, operation):
    """Ordering proof only: a committed claim must not bypass later authority."""
    from datetime import timedelta
    from fastapi import HTTPException
    from app.services import whatsapp_self_service as service
    at = datetime(2026, 10, 18, tzinfo=timezone.utc)
    key = UUID(int=10)
    state = {'revoked': False}
    row = SimpleNamespace(id=UUID(int=5), state='pending' if operation=='exchange' else 'setting_up',
        idempotency_key=key, selected_key=key, connection_version=1,
        expires_at=at+timedelta(minutes=5), provisional_token_ciphertext='synthetic-only',
        token_expires_at=at+timedelta(hours=1), subscription_state='not_started')
    class NativeAuthority:
        async def check(self, db):
            if state['revoked']:
                raise HTTPException(401, 'Synthetic native session ended')
        async def finalize(self, db):
            await self.check(db)
    auth = NativeAuthority()
    async def lock(db, authority):
        await authority.check(db)
        return SimpleNamespace(version=1), None
    async def claim_commit():
        state['revoked'] = True
    db = SimpleNamespace(commit=AsyncMock(side_effect=claim_commit))
    client = SimpleNamespace(subscribe=AsyncMock(), exchange=AsyncMock(), evidence_kind='provider')
    payload = SimpleNamespace(idempotency_key=key, waba_id='12345')
    monkeypatch.setattr(service, 'embedded_configuration', lambda value: {})
    monkeypatch.setattr(service, 'locked_configuration', lock)
    monkeypatch.setattr(service, 'owned_attempt', AsyncMock(return_value=row))
    monkeypatch.setattr(service, 'verify_browser', lambda *args: None)
    monkeypatch.setattr(service, 'effect_unknown', AsyncMock())
    monkeypatch.setattr(service, 'now', lambda: at)
    with pytest.raises(HTTPException):
        if operation == 'subscription':
            await service.provider_step(db, auth, row.id, payload, client, stage='subscription', token='synthetic-only')
        else:
            auth.binding = SimpleNamespace()
            payload.code = 'synthetic-only'
            await service.exchange_signup(db, auth, row.id, payload, 'synthetic-only', provider=client)
    attempts = client.subscribe.await_count + client.exchange.await_count
    assert attempts == 0
