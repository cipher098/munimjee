"""Actual current native authority after profile/team waits and staged audit flush."""
import asyncio
from uuid import uuid4
import pytest
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.identity import Business, Membership
from app.models.identity_auth import BusinessInvitation, IdentityAuditEvent, UserSession
from app.services.auth_sessions import now_utc
from tests.test_v1_native_completion_import_http import native_import


@pytest.mark.asyncio
@pytest.mark.parametrize('revoke',['session','role'])
async def test_profile_wait_cannot_save_after_current_authority_ends(native_import,monkeypatch,revoke):
    j=native_import;waiting=asyncio.Event();original=AsyncSession.scalar
    async def scalar(db,statement,*args,**kwargs):
        if getattr(statement,'_for_update_arg',None) is not None and 'businesses' in str(statement):waiting.set()
        return await original(db,statement,*args,**kwargs)
    async with j.sessions() as blocker:
        await blocker.begin();await blocker.scalar(select(Business).where(Business.id==j.bid).with_for_update())
        monkeypatch.setattr(AsyncSession,'scalar',scalar)
        request=asyncio.create_task(j.client.put(f'/api/v1/businesses/{j.bid}/profile',headers=j.csrf,
            json={'expected_version':0,'name':'Must rollback','business_type':'boutique','country':'IN','support_email':None,'phone':None,'website':None}))
        try:
            await asyncio.wait_for(waiting.wait(),3);assert not request.done()
            async with j.sessions.begin() as db:
                if revoke=='session':await db.execute(update(UserSession).where(UserSession.user_id==j.uid).values(revoked_at=now_utc()))
                else:await db.execute(update(Membership).where(Membership.business_id==j.bid,Membership.user_id==j.uid).values(role='viewer'))
            await blocker.commit();response=await request
        finally:
            if not request.done():request.cancel()
    assert response.status_code==(401 if revoke=='session' else 403),response.text
    async with j.sessions() as db:
        row=await db.get(Business,j.bid);assert row.profile_version==0 and row.name!='Must rollback'
        assert not await db.scalar(select(IdentityAuditEvent.id).where(IdentityAuditEvent.business_id==j.bid,IdentityAuditEvent.event_type=='business_profile_updated'))


@pytest.mark.asyncio
async def test_invite_audit_flush_then_session_revoke_rolls_back_invite(native_import,monkeypatch):
    j=native_import;original=AsyncSession.flush;changed=False
    async def flush(db,*args,**kwargs):
        nonlocal changed
        trigger=not changed and any(isinstance(x,BusinessInvitation) for x in db.new)
        await original(db,*args,**kwargs)
        if trigger:
            changed=True
            async with j.sessions.begin() as other:
                await other.execute(update(UserSession).where(UserSession.user_id==j.uid).values(revoked_at=now_utc()))
    monkeypatch.setattr(AsyncSession,'flush',flush)
    response=await j.client.post(f'/api/v1/businesses/{j.bid}/invitations',headers=j.csrf,
        json={'email':f'{uuid4().hex}@example.com','role':'viewer'})
    assert changed and response.status_code==401,response.text
    async with j.sessions() as db:assert await db.scalar(select(func.count()).select_from(BusinessInvitation))==0
