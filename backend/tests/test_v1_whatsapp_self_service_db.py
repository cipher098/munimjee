"""Actual 0057 constraints/native lifecycle. All provider responses synthetic.

Shared helper invocation below is distinguished from installed webhook/worker
proof; the later mounted journey must exercise those production registrations.
"""
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError

from app.config import settings
from app.models.channel_operator import ChannelConnectionState
from app.models.identity import Membership
from app.models.identity_auth import UserSession
from app.models.whatsapp import WhatsAppAccount, WhatsAppContact, WhatsAppMessage
from app.models.whatsapp_self_service import (
    WhatsAppAuthorizationProvenance, WhatsAppConnectionTest, WhatsAppSignupAttempt,
    WhatsAppSignupChoice, WhatsAppTestAuthorization,
)
from app.services.channel_credentials import encrypt
from app.services.whatsapp_test_authority import current_provenance, exact_test_authority
from app.services.whatsapp_test_protocol import FIXED_REPLY, REDACTED_COMMAND
from tests.whatsapp_self_service_fixture import (
    native_wa_setup, attached_signup, bind_recipient, challenge, post,
    prepared_signup, send_command,
)
from tests.isolated_database import current_migration_head


@pytest.mark.asyncio
async def test_actual_0057_native_owner_attaches_paused_exact_receipts_and_ciphertext(native_wa_setup):
    j = native_wa_setup
    flow = await attached_signup(j)
    assert j.provider.calls['exchange'] == j.provider.calls['subscribe'] == j.provider.calls['register'] == 1
    before = dict(j.provider.calls)
    replay = await post(j, f'/signup/{flow.aid}/select', flow.selection)
    assert replay['receipt']['resource_id'] == str(flow.aid)
    assert replay['receipt']['idempotency_key'] == flow.selection['idempotency_key']
    assert replay['receipt']['selected_choice_id'] == flow.selection['choice_id']
    await post(j, f'/signup/{flow.aid}/exchange', flow.exchange)
    assert dict(j.provider.calls) == before
    await post(j, f'/signup/{flow.aid}/select', {**flow.selection,
        'idempotency_key': str(uuid4())}, status=409)
    async with j.sessions() as db:
        assert (await db.execute(text('SELECT version_num FROM alembic_version'))).scalar_one() == current_migration_head()
        account = await db.get(WhatsAppAccount, j.bid)
        control = await db.get(ChannelConnectionState, (j.bid, 'whatsapp'))
        attempt = await db.get(WhatsAppSignupAttempt, flow.aid)
        proof = await db.get(WhatsAppAuthorizationProvenance, (j.bid, 1))
        assert control.version == 1 and account.enabled is False and account.automation_enabled is False
        assert attempt.state == 'attached' and attempt.provisional_token_ciphertext is None
        assert attempt.requested_app_id == attempt.verified_app_id == proof.verified_app_id == '123'
        assert proof.credential_fingerprint == hashlib.sha256(account.access_token.encode()).hexdigest()
        assert proof.evidence_kind == 'synthetic_fixture' and proof.token_expires_at == j.provider.expiry
        assert account.access_token != j.provider.verified().token
    page = await j.client.get(f'/v1/businesses/{j.bid}/channels/whatsapp/setup')
    assert page.status_code == 200 and page.headers['cache-control'] == 'no-store'
    assert page.headers['x-robots-tag'] == 'noindex, nofollow'


@pytest.mark.asyncio
async def test_actual_0057_one_exact_recipient_fixed_outbox_and_no_synthetic_delivery_claim(native_wa_setup):
    j = native_wa_setup
    await attached_signup(j)
    challenged = await challenge(j)
    recipient = await bind_recipient(j, challenged)
    tid = challenged['test']['test_id']
    body = send_command(recipient)
    queued = await post(j, f'/tests/{tid}/send', body)
    assert queued['result']['status'] == 'queued' and queued['result']['proof_source'] == 'synthetic_fixture'
    assert queued['receipt']['idempotency_key'] == body['idempotency_key']
    await post(j, f'/tests/{tid}/send', body)
    await post(j, f'/tests/{tid}/send', {**body, 'idempotency_key': str(uuid4())}, status=409)
    async with j.sessions.begin() as db:
        account = await db.scalar(select(WhatsAppAccount).where(WhatsAppAccount.seller_id == j.bid).with_for_update())
        contact = await db.scalar(select(WhatsAppContact).where(WhatsAppContact.id == UUID(recipient['recipient_contact_id'])).with_for_update())
        auth = await db.get(WhatsAppTestAuthorization, UUID(tid))
        outbound = await db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.id == auth.outbound_message_id).with_for_update())
        assert await exact_test_authority(db, account, contact, outbound) is not None
        assert outbound.text == FIXED_REPLY and outbound.payload == {} and outbound.direction == 'outbound'
        assert auth.expires_at <= auth.authorized_at + timedelta(seconds=120)
        assert auth.expires_at <= j.provider.expiry
        inbound = await db.get(WhatsAppMessage, UUID(recipient['inbound_message_id']))
        assert inbound.text == REDACTED_COMMAND and inbound.payload == {}
        raw_command_absent = challenged['command'] not in repr(inbound.__dict__)
        assert raw_command_absent, 'Canonical inbound must contain redaction only'
        assert await db.scalar(select(func.count()).select_from(WhatsAppTestAuthorization)) == 1
        outbound.provider_message_id = 'synthetic-provider-acceptance'
        outbound.status = 'delivered'
    observed = await j.client.get(j.base + f'/tests/{tid}')
    assert observed.status_code == 200
    assert observed.json()['status'] == 'delivered' and observed.json()['delivery_confirmed'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['app', 'ciphertext', 'generation', 'opt_out', 'session', 'role', 'flag'])
async def test_actual_0057_fixed_message_authority_denies_current_changes(native_wa_setup, monkeypatch, change):
    j = native_wa_setup
    await attached_signup(j)
    challenged = await challenge(j)
    recipient = await bind_recipient(j, challenged)
    await post(j, f'/tests/{challenged["test"]["test_id"]}/send', send_command(recipient))
    async with j.sessions.begin() as db:
        if change == 'ciphertext':
            account = await db.get(WhatsAppAccount, j.bid)
            account.access_token = encrypt(j.provider.verified().token)
        elif change == 'generation':
            await db.execute(update(ChannelConnectionState).where(ChannelConnectionState.business_id == j.bid,
                ChannelConnectionState.channel == 'whatsapp').values(version=2))
        elif change == 'opt_out':
            await db.execute(update(WhatsAppContact).where(WhatsAppContact.id == UUID(recipient['recipient_contact_id'])).values(opted_out=True))
        elif change == 'session':
            await db.execute(update(UserSession).where(UserSession.user_id == j.uid).values(revoked_at=datetime.now(timezone.utc)))
        elif change == 'role':
            await db.execute(update(Membership).where(Membership.business_id == j.bid, Membership.user_id == j.uid).values(role='viewer'))
    if change == 'app': monkeypatch.setattr(settings, 'WHATSAPP_EMBEDDED_APP_ID', '999')
    if change == 'flag': monkeypatch.setattr(settings, 'V1_CHANNEL_TESTS_ENABLED', False)
    async with j.sessions.begin() as db:
        account = await db.get(WhatsAppAccount, j.bid)
        contact = await db.get(WhatsAppContact, UUID(recipient['recipient_contact_id']))
        auth = await db.get(WhatsAppTestAuthorization, UUID(challenged['test']['test_id']))
        message = await db.get(WhatsAppMessage, auth.outbound_message_id)
        with pytest.raises(HTTPException):
            await exact_test_authority(db, account, contact, message)


@pytest.mark.asyncio
@pytest.mark.parametrize('target', ['attempt_app', 'choice', 'provenance', 'auth', 'inbound_delete', 'outbound_delete', 'outbound_text', 'provider_replace'])
async def test_actual_0057_sql_evidence_and_bound_transcript_are_immutable(native_wa_setup, target):
    j = native_wa_setup
    flow = await attached_signup(j)
    challenged = await challenge(j)
    recipient = await bind_recipient(j, challenged)
    await post(j, f'/tests/{challenged["test"]["test_id"]}/send', send_command(recipient))
    async with j.sessions() as db:
        auth = await db.get(WhatsAppTestAuthorization, UUID(challenged['test']['test_id']))
        outbound_id = auth.outbound_message_id
    if target == 'provider_replace':
        async with j.sessions.begin() as db:
            await db.execute(update(WhatsAppMessage).where(WhatsAppMessage.id == outbound_id).values(provider_message_id='synthetic-initial'))
    statements = {
        'attempt_app': update(WhatsAppSignupAttempt).where(WhatsAppSignupAttempt.id == flow.aid).values(requested_app_id='999'),
        'choice': update(WhatsAppSignupChoice).where(WhatsAppSignupChoice.attempt_id == flow.aid).values(phone_number_id='999'),
        'provenance': update(WhatsAppAuthorizationProvenance).where(WhatsAppAuthorizationProvenance.business_id == j.bid).values(token_expires_at=j.provider.expiry + timedelta(days=1)),
        'auth': update(WhatsAppTestAuthorization).where(WhatsAppTestAuthorization.test_id == UUID(challenged['test']['test_id'])).values(expires_at=datetime.now(timezone.utc) + timedelta(days=1)),
        'inbound_delete': delete(WhatsAppMessage).where(WhatsAppMessage.id == UUID(recipient['inbound_message_id'])),
        'outbound_delete': delete(WhatsAppMessage).where(WhatsAppMessage.id == outbound_id),
        'outbound_text': update(WhatsAppMessage).where(WhatsAppMessage.id == outbound_id).values(text='Replacement forbidden'),
        'provider_replace': update(WhatsAppMessage).where(WhatsAppMessage.id == outbound_id).values(provider_message_id='synthetic-replacement'),
    }
    with pytest.raises(DBAPIError):
        async with j.sessions.begin() as db:
            await db.execute(statements[target])


@pytest.mark.asyncio
async def test_actual_0057_unbound_message_delete_still_works(native_wa_setup):
    j = native_wa_setup
    await attached_signup(j)
    async with j.sessions.begin() as db:
        contact = WhatsAppContact(id=uuid4(), seller_id=j.bid, phone='910000000002')
        db.add(contact)
        await db.flush()
        ordinary = WhatsAppMessage(id=uuid4(), seller_id=j.bid, contact_id=contact.id,
            phone_number_id=j.provider.phone, idempotency_key='ordinary-'+uuid4().hex,
            direction='outbound', kind='text', text='Ordinary synthetic message', payload={}, status='queued')
        db.add(ordinary)
        await db.flush()
        mid = ordinary.id
    async with j.sessions.begin() as db:
        result = await db.execute(delete(WhatsAppMessage).where(WhatsAppMessage.id == mid))
        assert result.rowcount == 1
    async with j.sessions() as db:
        assert await db.get(WhatsAppMessage, mid) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['disabled', 'csrf', 'foreign', 'viewer', 'secret_mismatch'])
async def test_actual_0057_start_denial_has_no_provider_operation(native_wa_setup, monkeypatch, mode):
    j = native_wa_setup
    headers, bid = j.csrf, j.bid
    if mode == 'disabled': monkeypatch.setattr(settings, 'V1_WHATSAPP_ONBOARDING_ENABLED', False)
    if mode == 'csrf': headers = {}
    if mode == 'foreign': bid = (await j.signup('Other private tenant')).bid
    if mode == 'viewer':
        async with j.sessions.begin() as db:
            await db.execute(update(Membership).where(Membership.business_id == j.bid, Membership.user_id == j.uid).values(role='viewer'))
    if mode == 'secret_mismatch': monkeypatch.setattr(settings, 'WHATSAPP_APP_SECRET', 'different-synthetic-secret')
    response = await j.client.post(f'/api/v1/businesses/{bid}/channels/whatsapp/signup', headers=headers,
        json=dict(idempotency_key=str(uuid4()), expected_connection_version=0, notice_reviewed=True))
    assert response.status_code in (401, 403, 404, 409)
    assert sum(j.provider.calls.values()) == 0
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WhatsAppSignupAttempt)) == 0


@pytest.mark.asyncio
async def test_actual_0057_enable_advances_test_generation_without_copying_or_extending_grants(native_wa_setup, monkeypatch):
    from app.services import whatsapp_connection_tests as test_service
    j = native_wa_setup
    await attached_signup(j)
    old = await challenge(j)
    enabled = await j.client.post(f'/api/v1/businesses/{j.bid}/channels/whatsapp/automation',
        headers=j.csrf, json={'idempotency_key': str(uuid4()), 'enabled': True})
    assert enabled.status_code == 200
    stale = await j.client.get(j.base + f'/tests/{old["test"]["test_id"]}')
    assert stale.status_code == 200 and stale.json()['status'] == 'stale_connection'
    # Move only the service's cooldown clock. Immutable grant expiry is unchanged;
    # no challenge or expiry row is rewritten to make the new generation ready.
    future = datetime.now(timezone.utc) + timedelta(seconds=61)
    monkeypatch.setattr(test_service, 'now', lambda: future)
    fresh = await challenge(j, version=2)
    assert fresh['test']['is_current_generation'] is True
    async with j.sessions() as db:
        account = await db.get(WhatsAppAccount, j.bid)
        proof = await current_provenance(db, account, 2)
        assert account.enabled is True and account.automation_enabled is True
        assert proof.token_expires_at == j.provider.expiry
        assert await db.scalar(select(func.count()).select_from(WhatsAppAuthorizationProvenance)) == 1
        with pytest.raises(HTTPException):
            await current_provenance(db, account, 2, at=j.provider.expiry + timedelta(seconds=1))
    monkeypatch.setattr(settings, 'WHATSAPP_EMBEDDED_CONFIG_ID', '987')
    async with j.sessions() as db:
        account = await db.get(WhatsAppAccount, j.bid)
        assert (await current_provenance(db, account, 2)).token_expires_at == j.provider.expiry


@pytest.mark.asyncio
async def test_actual_0057_uncommitted_phone_claim_serializes_two_tenants_before_provider_posts(native_wa_setup, monkeypatch):
    from app.services.whatsapp_self_service import Authority
    j = native_wa_setup
    other = await j.signup('Separate synthetic tenant')
    first, second = await prepared_signup(j), await prepared_signup(other)
    entered, release = asyncio.Event(), asyncio.Event()
    original = Authority.finalize
    held = False

    async def final_boundary(authority, db):
        nonlocal held
        await original(authority, db)
        if authority.binding.business_id == j.bid and not held:
            claim = next((row for row in db.identity_map.values() if isinstance(row, WhatsAppSignupAttempt)
                and row.id == first.aid and row.state == 'setting_up' and row.subscription_state == 'not_started'), None)
            if claim is not None:
                held = True
                entered.set()
                await release.wait()

    monkeypatch.setattr(Authority, 'finalize', final_boundary)
    task_a = asyncio.create_task(j.client.post(j.base + f'/signup/{first.aid}/select',
        json=first.selection, headers=j.csrf))
    task_b = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task_b = asyncio.create_task(other.client.post(other.base + f'/signup/{second.aid}/select',
            json=second.selection, headers=other.csrf))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(task_b), .2)
        assert j.provider.calls['subscribe'] == j.provider.calls['register'] == 0
    finally:
        release.set()
    result_a, result_b = await asyncio.wait_for(asyncio.gather(task_a, task_b), 10)
    assert result_a.status_code == 200 and result_b.status_code == 409
    assert j.provider.calls['subscribe'] == j.provider.calls['register'] == 1
    async with j.sessions() as db:
        assert (await db.get(WhatsAppAccount, j.bid)).phone_number_id == j.provider.phone
        assert await db.get(WhatsAppAccount, other.bid) is None


@pytest.mark.asyncio
async def test_actual_0057_unknown_provider_claim_never_retries_or_frees_phone_on_cleanup(native_wa_setup, monkeypatch):
    from app.services.whatsapp_self_service import cleanup_provisional
    j = native_wa_setup
    flow = await prepared_signup(j)
    async def uncertain():
        raise RuntimeError('Synthetic provider response lost')
    j.provider.before['subscribe'] = uncertain
    result = await post(j, f'/signup/{flow.aid}/select', flow.selection, status=409)
    assert result['detail']['code'] == 'signup_setup_unknown'
    assert j.provider.calls['subscribe'] == 1 and j.provider.calls['register'] == 0
    replay = await post(j, f'/signup/{flow.aid}/select', flow.selection)
    assert replay['result']['status'] == 'setup_unknown'
    await post(j, f'/signup/{flow.aid}/cancel', {'idempotency_key': flow.start_body['idempotency_key']}, status=409)
    monkeypatch.setattr(settings, 'V1_WHATSAPP_ONBOARDING_ENABLED', False)
    monkeypatch.setattr(settings, 'V1_CHANNEL_TESTS_ENABLED', False)
    async with j.sessions.begin() as db:
        await cleanup_provisional(db, at=datetime.now(timezone.utc) + timedelta(days=1))
    async with j.sessions() as db:
        attempt = await db.get(WhatsAppSignupAttempt, flow.aid)
        assert attempt.state == 'setup_unknown' and attempt.selected_phone_number_id == j.provider.phone
        assert attempt.provisional_token_ciphertext is None
        assert await db.get(WhatsAppAccount, j.bid) is None
    monkeypatch.setattr(settings, 'V1_WHATSAPP_ONBOARDING_ENABLED', True)
    other = await j.signup('Other synthetic tenant')
    other_flow = await prepared_signup(other)
    blocked = await post(other, f'/signup/{other_flow.aid}/select', other_flow.selection, status=409)
    assert blocked['detail']['code'] == 'signup_phone_claimed'
    assert j.provider.calls['subscribe'] == 1 and j.provider.calls['register'] == 0
