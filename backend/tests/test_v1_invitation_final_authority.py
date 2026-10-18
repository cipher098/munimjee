"""An invitation never survives its inviter losing current authority mid-accept."""
from uuid import uuid4
import pytest
from sqlalchemy import func, select, update
from app.models.identity import Membership, User
from app.models.identity_auth import BusinessInvitation, UserSession
from app.api.v1 import auth
from tests.test_v1_auth_onboarding import client, signup, invite


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['role', 'inactive'])
async def test_inviter_loss_after_new_session_staging_rolls_back_acceptance(client, monkeypatch, change):
    owner = await signup(client)
    bid, uid = owner['businesses'][0]['id'], owner['user_id']
    email = f'{uuid4().hex}@example.com'
    invitation = await invite(client, bid, email)
    token = invitation['invitation_url'].split('=', 1)[1]
    original = auth.start_session
    async def staged(db, user, request, response, **kwargs):
        result = await original(db, user, request, response, **kwargs)
        await db.flush()
        async with client.factory.begin() as other:
            if change == 'role':
                await other.execute(update(Membership).where(Membership.business_id == bid,
                    Membership.user_id == uid).values(role='viewer'))
            else:
                await other.execute(update(User).where(User.id == uid).values(is_active=False))
        return result
    monkeypatch.setattr(auth, 'start_session', staged)
    response = await client.post('/api/v1/auth/invitations/accept', json={
        'email': email, 'password': 'synthetic-invite-password', 'token': token})
    assert response.status_code in (401, 403), response.text
    async with client.factory() as db:
        row = await db.scalar(select(BusinessInvitation).where(BusinessInvitation.auth_email == email))
        assert row.consumed_at is None and row.accepted_by is None
        assert await db.scalar(select(User.id).where(User.auth_email == email)) is None
        assert await db.scalar(select(func.count()).select_from(UserSession)) == 1

