"""Actual0051 migrations and explicit support authority; no membership shortcuts."""
import pytest
from sqlalchemy import text
from app.models.support_grants import SupportGrant, SupportCommand


@pytest.mark.asyncio
async def test_actual_0051_constraints_and_immutable_triggers(migrated_engine):
    async with migrated_engine.connect() as db:
        assert await db.scalar(text('SELECT version_num FROM alembic_version'))=='0051_v1_support_grants'
        names=set(await db.scalars(text("SELECT conname FROM pg_constraint WHERE conrelid='v1_support_grants'::regclass")))
        assert {'v1_support_grant_tenant','v1_support_grant_owner','v1_support_grant_revoker','v1_support_grant_expiry'}<=names
        names=set(await db.scalars(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")))
        assert {'v1_support_consent_immutable','v1_support_command_immutable'}<=names

import asyncio
from datetime import datetime,timedelta,timezone
from uuid import UUID,uuid4
import pytest_asyncio
from sqlalchemy import select,update,func
from sqlalchemy.exc import DBAPIError
from app.config import settings
from app.api.v1.support_grants import router
from app.models.identity import User,Membership,Business
from app.models.identity_auth import UserSession
from app.services.auth_sessions import issue_session
from app.services import support_grants as domain
from tests.test_v1_checkout_api import api,actor  # noqa:F401
from tests.test_v1_checkout import seed


@pytest_asyncio.fixture
async def support(api,monkeypatch):
    client,factory=api;client._transport.app.include_router(router)
    monkeypatch.setattr(settings,'V1_SUPPORT_GRANTS_ENABLED',True)
    bid,_,_=await seed(factory)
    owner_headers,_,_,owner_sid=await actor(factory,bid)
    async with factory.begin() as db:
        owner_uid=(await db.get(UserSession,owner_sid)).user_id
        user=User(id=uuid4(),display_name='Provisioned operator',auth_email='operator@example.com',password_hash='synthetic-only',is_active=True)
        db.add(user);await db.flush();token,csrf,session=await issue_session(db,user)
        uid=user.id;sid=session.id
    monkeypatch.setattr(settings,'V1_SUPPORT_OPERATOR_IDS',[uid])
    return client,factory,bid,owner_headers,owner_sid,owner_uid,{'Authorization':'Bearer '+token},uid,sid,token,csrf


def create_body(uid,*,key=None,minutes=20):
    return {'idempotency_key':str(key or uuid4()),'subject_user_id':str(uid),'scope':'readiness.summary',
        'reason':'Assist with owner-reviewed setup','expires_at':(datetime.now(timezone.utc)+timedelta(minutes=minutes)).isoformat(),'consented':True}

def action_body(key=None):return {'idempotency_key':str(key or uuid4()),'confirmed':True}
def owner_path(bid):return f'/api/v1/businesses/{bid}/support/grants'
def open_path(gid):return f'/api/v1/support/grants/{gid}/open'


@pytest.mark.asyncio
async def test_consent_never_becomes_membership_and_open_is_audited(support):
    c,f,bid,headers,_,_,op,uid,*_=support
    body=create_body(uid);r=await c.post(owner_path(bid),headers=headers,json=body)
    assert r.status_code==200,r.text
    gid=r.json()['grant_id'];assert r.headers['cache-control']=='no-store'
    replay=await c.post(owner_path(bid),headers=headers,json=body)
    assert replay.status_code==200 and replay.json()['replayed'] and replay.json()['grant_id']==gid
    board=await c.get('/api/v1/support/grants',headers=op)
    assert board.status_code==200 and len(board.json()['items'])==1
    assert not any(x in board.text for x in ('reason','auth_email','key_secret','source_url'))
    payload=action_body();opened=await c.post(open_path(gid),headers=op,json=payload)
    assert opened.status_code==200,opened.text
    assert opened.json()['onboarding_complete'] is False and opened.json()['provider_approval']=='not_evaluated'
    assert not any(x in opened.text for x in ('auth_email','key_secret','customer_id','source_url','phone_number_id','action_url'))
    assert (await c.post(open_path(gid),headers=op,json=payload)).json()['replayed']
    assert (await c.get(f'/api/v1/businesses/{bid}/catalogue/products',headers=op)).status_code==404
    async with f() as db:
        assert await db.scalar(select(func.count()).select_from(Membership).where(Membership.business_id==bid,Membership.user_id==uid))==0
        assert await db.scalar(select(func.count()).select_from(SupportCommand))==2
    for table in ('v1_support_grants','v1_support_commands'):
        async with f.begin() as db:
            with pytest.raises(DBAPIError):await db.execute(text(f'DELETE FROM {table}'))


@pytest.mark.asyncio
@pytest.mark.parametrize('role',['manager','staff','viewer'])
async def test_nonowners_cannot_consent_or_lookup(support,role):
    c,f,bid,_,_,_,_,uid,*_=support;headers,*_=await actor(f,bid,role)
    assert (await c.post(owner_path(bid),headers=headers,json=create_body(uid))).status_code==403
    assert (await c.get(owner_path(bid),headers=headers)).status_code==403
    assert (await c.post(f'/api/v1/businesses/{bid}/support/recipient',headers=headers,json={'email':'operator@example.com'})).status_code==403


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['disabled','unlisted','legacy','foreign_tenant','self','scope','expiry_short','expiry_long','missing_consent','numeric_consent'])
async def test_privilege_and_input_negatives_do_not_write(support,monkeypatch,kind):
    c,f,bid,headers,_,owner_uid,op,uid,*_=support;body=create_body(uid)
    if kind=='disabled':monkeypatch.setattr(settings,'V1_SUPPORT_GRANTS_ENABLED',False)
    if kind=='unlisted':monkeypatch.setattr(settings,'V1_SUPPORT_OPERATOR_IDS',[])
    if kind=='legacy':
        from jose import jwt
        token=jwt.encode({'sub':str(bid),'role':'seller','exp':int(datetime.now(timezone.utc).timestamp())+300},settings.SECRET_KEY,algorithm='HS256');headers={'Authorization':'Bearer '+token}
    if kind=='foreign_tenant':headers=op
    if kind=='self':
        monkeypatch.setattr(settings,'V1_SUPPORT_OPERATOR_IDS',[owner_uid]);body['subject_user_id']=str(owner_uid)
    if kind=='scope':body['scope']='orders.write'
    if kind=='expiry_short':body=create_body(uid,minutes=1)
    if kind=='expiry_long':body=create_body(uid,minutes=70)
    if kind=='missing_consent':body['consented']=False
    if kind=='numeric_consent':body['consented']=1
    r=await c.post(owner_path(bid),headers=headers,json=body)
    assert r.status_code in (401,403,404,409,422),r.text
    async with f() as db:assert await db.scalar(select(func.count()).select_from(SupportGrant))==0


@pytest.mark.asyncio
async def test_irreversible_revoke_and_replay_cannot_return_summary(support):
    c,f,bid,h,_,_,op,uid,*_=support
    gid=(await c.post(owner_path(bid),headers=h,json=create_body(uid))).json()['grant_id']
    payload=action_body();assert (await c.post(open_path(gid),headers=op,json=payload)).status_code==200
    revoke=action_body();r=await c.post(owner_path(bid)+f'/{gid}/revoke',headers=h,json=revoke)
    assert r.status_code==200 and r.json()['grant']['revoked_at']
    assert (await c.post(owner_path(bid)+f'/{gid}/revoke',headers=h,json=revoke)).json()['replayed']
    assert (await c.post(open_path(gid),headers=op,json=payload)).status_code==404
    assert (await c.get('/api/v1/support/grants',headers=op)).json()['items']==[]
    async with f.begin() as db:
        with pytest.raises(DBAPIError):await db.execute(update(SupportGrant).values(revoked_at=None,revoked_by_user_id=None))


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['allowlist','owner_role','owner_revoked','subject_revoked','owner_version','subject_version','business','seller'])
async def test_every_open_and_receipt_replay_uses_current_authority(support,monkeypatch,change):
    c,f,bid,h,_,owner_uid,op,uid,*_=support
    gid=UUID((await c.post(owner_path(bid),headers=h,json=create_body(uid))).json()['grant_id'])
    payload=action_body();assert (await c.post(open_path(gid),headers=op,json=payload)).status_code==200
    if change=='allowlist':monkeypatch.setattr(settings,'V1_SUPPORT_OPERATOR_IDS',[])
    else:
        async with f.begin() as db:
            if change=='owner_role':await db.execute(update(Membership).where(Membership.business_id==bid,Membership.user_id==owner_uid).values(role='manager'))
            elif change=='owner_revoked':await db.execute(update(Membership).where(Membership.business_id==bid,Membership.user_id==owner_uid).values(revoked_at=func.clock_timestamp()))
            elif change=='subject_revoked':await db.execute(update(User).where(User.id==uid).values(revoked_at=func.clock_timestamp()))
            elif change.endswith('_version'):
                target=owner_uid if change.startswith('owner') else uid
                await db.execute(update(User).where(User.id==target).values(auth_version=User.auth_version+1))
            elif change=='business':await db.execute(update(Business).where(Business.id==bid).values(is_active=False))
            elif change=='seller':
                from app.models.seller import Seller
                await db.execute(update(Seller).where(Seller.id==bid).values(is_active=False))
    r=await c.post(open_path(gid),headers=op,json=payload)
    assert r.status_code in (401,404),r.text


@pytest.mark.asyncio
async def test_serialized_duplicate_consent_and_command_collision(support):
    c,f,bid,h,_,_,_,uid,*_=support;body=create_body(uid)
    results=await asyncio.wait_for(asyncio.gather(*(c.post(owner_path(bid),headers=h,json=body) for _ in range(2))),10)
    assert [r.status_code for r in results]==[200,200]
    assert sorted(r.json()['replayed'] for r in results)==[False,True]
    assert (await c.post(owner_path(bid),headers=h,json=create_body(uid))).status_code==409
    assert (await c.post(owner_path(bid),headers=h,json={**body,'reason':'Different'})).status_code==409
    async with f() as db:assert await db.scalar(select(func.count()).select_from(SupportGrant))==1


@pytest.mark.asyncio
@pytest.mark.parametrize('operation',['create','open','revoke'])
async def test_session_revoked_after_real_audit_flush_rolls_back(support,monkeypatch,operation):
    c,f,bid,h,owner_sid,_,op,uid,subject_sid,*_=support
    gid=None
    if operation!='create':gid=(await c.post(owner_path(bid),headers=h,json=create_body(uid))).json()['grant_id']
    original=domain.record
    async def revoke_after_flush(*args,**kwargs):
        result=await original(*args,**kwargs)
        async with f.begin() as other:await other.execute(update(UserSession).where(UserSession.id==(subject_sid if operation=='open' else owner_sid)).values(revoked_at=func.clock_timestamp()))
        return result
    monkeypatch.setattr(domain,'record',revoke_after_flush)
    path=owner_path(bid) if operation=='create' else open_path(gid) if operation=='open' else owner_path(bid)+f'/{gid}/revoke'
    r=await c.post(path,headers=op if operation=='open' else h,json=create_body(uid) if operation=='create' else action_body())
    assert r.status_code==401,r.text
    async with f() as db:
        assert await db.scalar(select(func.count()).select_from(SupportCommand).where(SupportCommand.operation==operation))==0
        if operation=='create':assert await db.scalar(select(func.count()).select_from(SupportGrant))==0
        elif operation=='revoke':assert (await db.get(SupportGrant,UUID(gid))).revoked_at is None


@pytest.mark.asyncio
async def test_board_configuration_removal_during_final_guard_clears_names(support,monkeypatch):
    c,f,bid,h,_,_,_,uid,*_=support
    assert (await c.post(owner_path(bid),headers=h,json=create_body(uid))).status_code==200
    calls=0
    async def reauthorize():
        nonlocal calls
        calls+=1
        if calls==2:monkeypatch.setattr(settings,'V1_SUPPORT_OPERATOR_IDS',[])
    from app.services.identity import Actor
    async with f() as db:value=await domain.board(db,Actor(uid,'v1_user'),reauthorize=reauthorize)
    assert calls==2 and value['items']==[] and value['next_after'] is None


@pytest.mark.asyncio
async def test_persisted_near_expiry_uses_wallclock_and_withholds_old_receipt(support):
    c,f,bid,h,_,owner_uid,op,uid,*_=support
    now=datetime.now(timezone.utc);gid=uuid4()
    async with f.begin() as db:
        db.add(SupportGrant(id=gid,business_id=bid,subject_user_id=uid,consented_by_user_id=owner_uid,
            subject_auth_version=0,owner_auth_version=0,scope='readiness.summary',reason='Historical nearing-expiry consent',
            created_at=now-timedelta(minutes=10),expires_at=now+timedelta(seconds=1.2)))
    payload=action_body();assert (await c.post(open_path(gid),headers=op,json=payload)).status_code==200
    from app.services.identity import Actor
    from fastapi import HTTPException
    async with f() as db:
        transaction_start=await db.scalar(select(func.transaction_timestamp()))
        assert transaction_start<now+timedelta(seconds=1.2)
        await asyncio.sleep(1.3)
        with pytest.raises(HTTPException) as denied:await domain.access(db,Actor(uid,'v1_user'),gid)
        assert denied.value.status_code==404
    assert (await c.post(open_path(gid),headers=op,json=payload)).status_code==404
    assert (await c.get('/api/v1/support/grants',headers=op)).json()['items']==[]


@pytest.mark.asyncio
async def test_revoked_while_waiting_for_business_lock_cannot_append_access(support,monkeypatch):
    c,f,bid,h,_,owner_uid,op,uid,*_=support
    gid=UUID((await c.post(owner_path(bid),headers=h,json=create_body(uid))).json()['grant_id'])
    entered=asyncio.Event();original=domain.access
    async def observed(*args,**kwargs):
        value=await original(*args,**kwargs);entered.set();return value
    monkeypatch.setattr(domain,'access',observed)
    async with f() as blocker:
        await blocker.scalar(select(Business.id).where(Business.id==bid).with_for_update(key_share=True))
        pending=asyncio.create_task(c.post(open_path(gid),headers=op,json=action_body()))
        await asyncio.wait_for(entered.wait(),5)
        await blocker.execute(update(SupportGrant).where(SupportGrant.id==gid).values(revoked_at=func.clock_timestamp(),revoked_by_user_id=owner_uid))
        await blocker.commit()
    response=await asyncio.wait_for(pending,5)
    assert response.status_code==404,response.text
    async with f() as db:assert await db.scalar(select(func.count()).select_from(SupportCommand).where(SupportCommand.operation=='open'))==0


@pytest.mark.asyncio
async def test_cookie_csrf_and_foreign_origin_cannot_create_or_read_summary(support):
    c,f,bid,h,_,_,op,uid,sid,token,csrf=support
    gid=(await c.post(owner_path(bid),headers=h,json=create_body(uid))).json()['grant_id']
    c.cookies.set('v1_session',token);c.cookies.set('v1_csrf',csrf)
    r=await c.post(open_path(gid),json=action_body(),headers={'Origin':'http://foreign.example','X-CSRF-Token':csrf})
    assert r.status_code==403
    r=await c.post(open_path(gid),json=action_body(),headers={'Origin':'http://test'})
    assert r.status_code==403
    assert (await c.post(open_path(gid),json=action_body(),headers={'Origin':'http://test','X-CSRF-Token':csrf})).status_code==200


def test_support_confirmations_reject_numeric_truth():
    from app.schemas.support_grants import GrantAction
    from pydantic import ValidationError
    with pytest.raises(ValidationError):GrantAction(idempotency_key=uuid4(),confirmed=1)
