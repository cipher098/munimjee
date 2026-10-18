"""Prepared actual0057 final-claim race acceptance; collection is not execution.

Requires owner's real migrated/main-mounted fixture. Only provider I/O is fake;
no fallback router, fake DB scalar, manual outbox or synthetic authority is used.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.identity_auth import UserSession
from app.models.whatsapp import WhatsAppAccount
from app.models.whatsapp_self_service import WhatsAppSignupAttempt
from tests.whatsapp_self_service_fixture import native_wa_setup, post, prepared_signup  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['exchange', 'subscription', 'registration'])
@pytest.mark.parametrize('change', ['session_after_claim_commit', 'app_after_final_scalar'])
async def test_actual_postclaim_authority_change_starts_no_new_provider_operation(native_wa_setup, monkeypatch, stage, change):
    j = native_wa_setup
    if stage == 'exchange':
        key = str(uuid4())
        started = await post(j, '/signup', dict(idempotency_key=key,
            expected_connection_version=0, notice_reviewed=True))
        flow = SimpleNamespace(aid=UUID(started['attempt']['attempt_id']), exchange=dict(
            idempotency_key=key, signed_state=started['signed_state'], code='synthetic-one-use-code'))
        path, body, method = f'/signup/{flow.aid}/exchange', flow.exchange, 'exchange'
    else:
        flow = await prepared_signup(j)
        path, body = f'/signup/{flow.aid}/select', flow.selection
        method = 'subscribe' if stage == 'subscription' else 'register'
    before = j.provider.calls[method]
    fired = False

    if change == 'session_after_claim_commit':
        original_commit = AsyncSession.commit
        async def commit_then_revoke(db):
            nonlocal fired
            attempt = next((row for row in db.identity_map.values()
                if isinstance(row, WhatsAppSignupAttempt) and row.id == flow.aid), None)
            claim = bool(attempt is not None and (
                attempt.state == 'exchanging' if stage == 'exchange' else
                attempt.state == 'setting_up' and getattr(attempt, stage + '_state') == 'requesting'))
            await original_commit(db)
            if claim and not fired:
                fired = True  # Avoid intercepting the independent revoker txn.
                async with j.sessions.begin() as writer:
                    await writer.execute(update(UserSession).where(UserSession.user_id == j.uid).values(
                        revoked_at=datetime.now(timezone.utc)))
        monkeypatch.setattr(AsyncSession, 'commit', commit_then_revoke)
    else:
        original_scalar = AsyncSession.scalar
        async def scalar_then_rotate(db, statement, *args, **kwargs):
            nonlocal fired
            result = await original_scalar(db, statement, *args, **kwargs)
            if not fired:
                compiled = statement.compile()
                sql = str(compiled)
                # This is the actual coherent postclaim projection, not separate
                # native guards or the earlier locked Attempt fetch.
                if ('user_sessions' in sql and 'whatsapp_signup_attempts' in sql
                    and 'requested_app_id' in sql and flow.aid in compiled.params.values()):
                    assert result is not None, 'The pre-rotation scalar must establish valid authority'
                    fired = True
                    monkeypatch.setattr(settings, 'WHATSAPP_EMBEDDED_APP_ID', '456')
            return result
        monkeypatch.setattr(AsyncSession, 'scalar', scalar_then_rotate)

    response = await j.client.post(j.base + path, json=body, headers=j.csrf)
    assert fired, 'The intended real committed claim/final scalar boundary was not reached'
    assert response.status_code == (401 if change == 'session_after_claim_commit' else 409)
    assert j.provider.calls[method] == before, 'Authority changed before this NEW provider operation'
    if stage == 'subscription':
        assert j.provider.calls['register'] == 0
    elif stage == 'registration':
        assert j.provider.calls['subscribe'] == 1  # Earlier confirmed effect is preserved.
    async with j.sessions() as db:
        attempt = await db.get(WhatsAppSignupAttempt, flow.aid)
        assert attempt.state == ('exchange_unknown' if stage == 'exchange' else 'setup_unknown')
        assert attempt.provisional_token_ciphertext is None
        assert await db.get(WhatsAppAccount, j.bid) is None
        if stage != 'exchange':
            assert getattr(attempt, stage + '_state') == 'unknown'
        if stage == 'registration':
            assert attempt.subscription_state == 'confirmed'
    # An exact replay cannot rebind the old native/app claim or repeat its method.
    replay = await j.client.post(j.base + path, json=body, headers=j.csrf)
    assert replay.status_code in (200, 401, 409)
    assert j.provider.calls[method] == before
    async with j.sessions() as db:
        assert (await db.get(WhatsAppSignupAttempt, flow.aid)).state == (
            'exchange_unknown' if stage == 'exchange' else 'setup_unknown')
