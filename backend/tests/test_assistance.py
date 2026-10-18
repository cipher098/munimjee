"""Actual0050 DDL, native HTTP and authority at transaction boundaries."""
import asyncio
from datetime import datetime,timezone
from uuid import UUID,uuid4
import pytest
import pytest_asyncio
from sqlalchemy import func,select,update,text
from sqlalchemy.exc import IntegrityError,DBAPIError
from app.api.v1.assistance import router
from app.models.assistance import AssistanceCommand,OnboardingAssignment
from app.models.identity import Business,Membership,User
from app.models.identity_auth import IdentityAuditEvent,UserSession
from app.services import assistance as domain
from app.services.auth_sessions import issue_session
from tests.test_v1_checkout_api import api,actor  # noqa:F401
from tests.test_v1_checkout import seed


@pytest_asyncio.fixture
async def console(api):
    client,factory=api;client._transport.app.include_router(router)
    bid,_,_=await seed(factory)
    headers,token,csrf,sid=await actor(factory,bid)
    async with factory() as db:uid=(await db.get(UserSession,sid)).user_id
    return client,factory,bid,headers,token,csrf,sid,uid


def base(bid):return f'/api/v1/businesses/{bid}/assistance'
def body(uid=None,version=0,key=None):return dict(idempotency_key=str(key or uuid4()),expected_version=version,assignee_user_id=str(uid) if uid else None,reviewed=True)


@pytest.mark.asyncio
async def test_actual_chain_and_private_readiness_projection(console):
    client,factory,bid,headers,*_=console
    async with factory() as db:assert await db.scalar(text('SELECT version_num FROM alembic_version'))=='0052_v1_customer_links'
    page=await client.get('/api/v1/assistance/businesses',headers=headers)
    assert page.status_code==200,page.text
    assert page.headers['cache-control']=='no-store' and page.headers['referrer-policy']=='no-referrer'
    value=page.json();assert value['contract_version']=='assistance-page.v1' and len(value['items'])==1
    item=value['items'][0];assert item['business_id']==str(bid) and item['onboarding_complete'] is False
    assert {step['status'] for step in item['steps']} >= {'pending_external','action_required'}
    assert not any(private in page.text for private in ('key_secret','provider_account_id','access_token','password_hash','auth_email'))
    shell=await client.get(f'/v1/businesses/{bid}/assistance',headers=headers)
    assert shell.status_code==200 and shell.headers['x-robots-tag']=='noindex, nofollow'


@pytest.mark.asyncio
async def test_assignment_replay_is_atomic_immutable_and_never_a_grant(console):
    client,factory,bid,headers,token,csrf,sid,uid=console
    payload=body(uid)
    made=await client.put(base(bid)+'/assignment',headers=headers,json=payload)
    assert made.status_code==200,made.text
    assert made.json()['version']==1 and not made.json()['replayed']
    repeated=await client.put(base(bid)+'/assignment',headers=headers,json=payload)
    assert repeated.status_code==200 and repeated.json()['replayed']
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(AssistanceCommand))==1
        assert await db.scalar(select(func.count()).select_from(IdentityAuditEvent).where(IdentityAuditEvent.event_type=='assistance_assignment_updated'))==1
        assert (await db.get(OnboardingAssignment,bid)).assignee_user_id==uid
        assert (await db.scalar(select(Membership.role).where(Membership.business_id==bid,Membership.user_id==uid)))=='owner'
    async with factory.begin() as db:
        with pytest.raises(DBAPIError):await db.execute(update(AssistanceCommand).values(result={'forged':True}))


@pytest.mark.asyncio
async def test_stale_version_and_key_collision_do_not_write(console):
    client,factory,bid,headers,token,csrf,sid,uid=console
    payload=body(uid)
    assert (await client.put(base(bid)+'/assignment',headers=headers,json=payload)).status_code==200
    stale=await client.put(base(bid)+'/assignment',headers=headers,json=body(None))
    assert stale.status_code==409 and stale.json()['detail']['code']=='assistance_assignment_stale'
    changed={**payload,'assignee_user_id':None}
    assert (await client.put(base(bid)+'/assignment',headers=headers,json=changed)).status_code==409
    async with factory() as db:assert (await db.get(OnboardingAssignment,bid)).version==1


@pytest.mark.asyncio
async def test_concurrent_same_version_and_same_key_each_have_one_effect(console):
    client,factory,bid,headers,token,csrf,sid,uid=console
    payloads=[body(uid),body(None)]
    results=await asyncio.wait_for(asyncio.gather(*(client.put(base(bid)+'/assignment',headers=headers,json=p) for p in payloads)),10)
    assert sorted(r.status_code for r in results)==[200,409]
    current=next(r for r in results if r.status_code==200).json()['version']
    payload=body(uid,current)
    results=await asyncio.wait_for(asyncio.gather(*(client.put(base(bid)+'/assignment',headers=headers,json=payload) for _ in range(2))),10)
    assert [r.status_code for r in results]==[200,200]
    assert sorted(r.json()['replayed'] for r in results)==[False,True]
    async with factory() as db:assert (await db.get(OnboardingAssignment,bid)).version==2


@pytest.mark.asyncio
@pytest.mark.parametrize('role',['manager','staff','viewer'])
async def test_nonowners_read_without_member_management_or_assignment(console,role):
    client,factory,bid,*_=console
    headers,*_=await actor(factory,bid,role)
    response=await client.get(base(bid),headers=headers)
    assert response.status_code==200 and response.json()['can_assign'] is False
    assert (await client.get(base(bid)+'/assignees',headers=headers)).status_code==403
    assert (await client.put(base(bid)+'/assignment',headers=headers,json=body())).status_code==403
    opened=await client.post(base(bid)+'/open',headers=headers,json={'idempotency_key':str(uuid4())})
    assert opened.status_code==200 and opened.json()['operation']=='open'


@pytest.mark.asyncio
async def test_foreign_revoked_and_staff_assignees_never_receive_access(console):
    client,factory,bid,headers,token,csrf,sid,uid=console
    foreign,_,_=await seed(factory);_,_,_,other_sid=await actor(factory,foreign)
    _,_,_,staff_sid=await actor(factory,bid,'staff')
    async with factory() as db:
        foreign_uid=(await db.get(UserSession,other_sid)).user_id
        staff_uid=(await db.get(UserSession,staff_sid)).user_id
    for candidate in (foreign_uid,staff_uid):assert (await client.put(base(bid)+'/assignment',headers=headers,json=body(candidate))).status_code==409
    assert (await client.get(base(foreign),headers=headers)).status_code==404
    async with factory.begin() as db:await db.execute(update(Membership).where(Membership.business_id==bid,Membership.user_id==uid).values(is_active=False))
    assert (await client.get(base(bid),headers=headers)).status_code==404
    async with factory() as db:assert await db.scalar(select(func.count()).select_from(OnboardingAssignment))==0


@pytest.mark.asyncio
async def test_revoked_assignee_is_visible_as_needing_reassignment_and_not_assigned_to_me(console):
    client,factory,bid,headers,token,csrf,sid,uid=console
    manager,_,_,manager_sid=await actor(factory,bid,'manager')
    async with factory() as db:manager_uid=(await db.get(UserSession,manager_sid)).user_id
    assert (await client.put(base(bid)+'/assignment',headers=headers,json=body(manager_uid))).status_code==200
    assert len((await client.get('/api/v1/assistance/businesses?assigned_to_me=true',headers=manager)).json()['items'])==1
    async with factory.begin() as db:await db.execute(update(Membership).where(Membership.business_id==bid,Membership.user_id==manager_uid).values(role='viewer'))
    current=(await client.get(base(bid),headers=headers)).json()
    assert current['assignment']['assignee_user_id']==str(manager_uid) and not current['assignment']['eligible']
    assert (await client.get('/api/v1/assistance/businesses?assigned_to_me=true',headers=manager)).json()['items']==[]


@pytest.mark.asyncio
async def test_cookie_csrf_foreign_origin_and_revoked_session(console):
    client,factory,bid,headers,token,csrf,sid,uid=console
    client.cookies.set('v1_session',token);client.cookies.set('v1_csrf',csrf)
    assert (await client.put(base(bid)+'/assignment',json=body(uid))).status_code==403
    assert (await client.put(base(bid)+'/assignment',json=body(uid),headers={'X-CSRF-Token':csrf,'Origin':'https://foreign.invalid'})).status_code==403
    assert (await client.put(base(bid)+'/assignment',json=body(uid),headers={'X-CSRF-Token':csrf,'Origin':'http://test'})).status_code==200
    async with factory.begin() as db:await db.execute(update(UserSession).where(UserSession.id==sid).values(revoked_at=datetime.now(timezone.utc)))
    assert (await client.get('/api/v1/assistance/businesses',headers=headers)).status_code==401


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['role','session'])
async def test_native_authority_changed_during_business_lock_wait_has_zero_effect(console,change,monkeypatch):
    client,factory,bid,headers,token,csrf,sid,uid=console
    entered=asyncio.Event();original=domain.require_business_access
    async def observed(*args,**kwargs):
        result=await original(*args,**kwargs);entered.set();return result
    monkeypatch.setattr(domain,'require_business_access',observed)
    async with factory() as blocker:
        await blocker.scalar(select(Business.id).where(Business.id==bid).with_for_update(key_share=True))
        task=asyncio.create_task(client.put(base(bid)+'/assignment',headers=headers,json=body(uid)))
        await asyncio.wait_for(entered.wait(),5)
        if change=='role':await blocker.execute(update(Membership).where(Membership.business_id==bid,Membership.user_id==uid).values(role='viewer'))
        else:await blocker.execute(update(UserSession).where(UserSession.id==sid).values(revoked_at=datetime.now(timezone.utc)))
        await blocker.commit()
        response=await asyncio.wait_for(task,5)
    assert response.status_code==(403 if change=='role' else 401),response.text
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(AssistanceCommand))==0
        assert await db.scalar(select(func.count()).select_from(OnboardingAssignment))==0


@pytest.mark.asyncio
async def test_revocation_after_flush_rolls_back_assignment_receipt_and_audit(console,monkeypatch):
    client,factory,bid,headers,token,csrf,sid,uid=console
    original=domain.command
    async def revoked(*args,**kwargs):
        result=await original(*args,**kwargs)
        async with factory.begin() as db:await db.execute(update(UserSession).where(UserSession.id==sid).values(revoked_at=datetime.now(timezone.utc)))
        return result
    monkeypatch.setattr(domain,'command',revoked)
    assert (await client.put(base(bid)+'/assignment',headers=headers,json=body(uid))).status_code==401
    async with factory() as db:
        for model in (OnboardingAssignment,AssistanceCommand,IdentityAuditEvent):assert await db.scalar(select(func.count()).select_from(model))==0


@pytest.mark.asyncio
async def test_composite_membership_constraints_reject_direct_foreign_actor_and_assignee(console):
    client,factory,bid,headers,token,csrf,sid,uid=console
    foreign,_,_=await seed(factory);_,_,_,other_sid=await actor(factory,foreign)
    async with factory() as db:foreign_uid=(await db.get(UserSession,other_sid)).user_id
    for changes in ({'assignee_user_id':foreign_uid},{'assigned_by_user_id':foreign_uid}):
        async with factory() as db:
            row=OnboardingAssignment(business_id=bid,assignee_user_id=uid,assigned_by_user_id=uid,version=1)
            for key,value in changes.items():setattr(row,key,value)
            db.add(row)
            with pytest.raises(IntegrityError):await db.flush()
            await db.rollback()
    async with factory() as db:
        db.add(AssistanceCommand(business_id=bid,idempotency_key=uuid4(),actor_user_id=foreign_uid,operation='open',request_hash='a'*64,result={}))
        with pytest.raises(IntegrityError):await db.flush()
        await db.rollback()


@pytest.mark.asyncio
async def test_pagination_is_membership_scoped_and_inactive_tenants_disappear(console):
    from app.models.seller import Seller
    client,factory,bid,headers,token,csrf,sid,uid=console
    business_ids=[bid]
    for index in range(3):
        business,_,_=await seed(factory);business_ids.append(business)
        async with factory.begin() as db:db.add(Membership(user_id=uid,business_id=business,role='manager'))
    foreign,_,_=await seed(factory)
    first=(await client.get('/api/v1/assistance/businesses?limit=2',headers=headers)).json()
    second=(await client.get('/api/v1/assistance/businesses?limit=2&after='+first['next_after'],headers=headers)).json()
    ids=[UUID(row['business_id']) for row in first['items']+second['items']]
    assert ids==sorted(business_ids) and foreign not in ids and second['next_after'] is None
    async with factory.begin() as db:await db.execute(update(Seller).where(Seller.id==bid).values(is_active=False))
    page=(await client.get('/api/v1/assistance/businesses',headers=headers)).json()
    assert str(bid) not in [row['business_id'] for row in page['items']]
    assert (await client.get(base(bid),headers=headers)).status_code==404


@pytest.mark.asyncio
async def test_command_receipt_is_actor_bound_even_when_both_are_owners(console):
    client,factory,bid,headers,token,csrf,sid,uid=console
    other,*_=await actor(factory,bid,'owner')
    payload={'idempotency_key':str(uuid4())}
    assert (await client.post(base(bid)+'/open',headers=headers,json=payload)).status_code==200
    assert (await client.post(base(bid)+'/open',headers=other,json=payload)).status_code==409


@pytest.mark.asyncio
async def test_legacy_owner_bearer_cannot_enter_native_assistance(console):
    from jose import jwt
    from app.config import settings
    client,factory,bid,*_=console
    token=jwt.encode({'sub':str(bid),'role':'seller','exp':int(datetime.now(timezone.utc).timestamp())+300},settings.SECRET_KEY,algorithm='HS256')
    response=await client.get('/api/v1/assistance/businesses',headers={'Authorization':'Bearer '+token})
    assert response.status_code==401
