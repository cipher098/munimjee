"""Real mounted activity router/native auth on P01 actual0054; no providers."""
import asyncio
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from uuid import UUID,uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport,AsyncClient
from sqlalchemy import func,select,text,update

from app.config import settings
from app.models.activity_v1 import ActivityContext,ActivityEvent,ActivityGap,ActivityPolicy,ActivityPolicyCommand,OrderActivity
from app.models.commerce import Storefront
from app.models.identity import Membership
from app.schemas.activity_v1 import ContextWrite,EventWrite,PolicyWrite
from app.services import activity_v1 as domain
from app.services.identity import Actor
from tests.test_v1_native_completion_import_http import native_import


@pytest_asyncio.fixture
async def activity(native_import,monkeypatch):
    from app.main import app
    from app.api.v1.activity_v1 import router
    j=native_import
    if not any(getattr(route,'path',None)=='/api/v1/storefronts/{slug}/activity/contexts' for route in app.routes):app.include_router(router)
    monkeypatch.setattr(settings,'V1_ACTIVITY_ENABLED',True)
    monkeypatch.setattr(settings,'V1_ACTIVITY_RETENTION_READY',True)
    # Classification fixture simulates server deployment context; no live traffic.
    monkeypatch.setattr(settings,'APP_ENV','production')
    async with j.sessions.begin() as db:
        store=await db.get(Storefront,j.bid);store.published=True;j.slug=store.slug
    j.policy=f'/api/v1/businesses/{j.bid}/analytics/measurement-policy'
    j.activity=f'/api/v1/businesses/{j.bid}/analytics/activity'
    j.public=f'/api/v1/storefronts/{j.slug}/activity'
    async with AsyncClient(transport=ASGITransport(app=app),base_url='https://independent-canonical.example.test',
            headers={'Origin':'https://independent-canonical.example.test','User-Agent':'Synthetic fixture browser'}) as browser:
        j.browser=browser
        yield j


def command(mode='live',revision=0):
    return dict(expected_revision=revision,idempotency_key=str(uuid4()),mode=mode,first_party_measurement_acknowledged=True)


async def enable(j):
    response=await j.client.put(j.policy,json=command(),headers=j.csrf)
    assert response.status_code==200,response.text
    return response.json()


async def started(j,key=None):
    response=await j.browser.post(j.public+'/contexts',json={'idempotency_key':key or str(uuid4())})
    assert response.status_code==200,response.text
    return response.json()


@pytest.mark.asyncio
async def test_activity_default_off_owner_exact_receipt_and_stale_cas(activity):
    j=activity
    current=(await j.client.get(j.policy)).json()
    assert current['mode']=='off' and current['revision']==0 and current['can_change']
    assert (await started(j))['state']=='disabled'
    body=command()
    saved=await j.client.put(j.policy,json=body,headers=j.csrf)
    assert saved.status_code==200,saved.text
    replay=await j.client.put(j.policy,json=body,headers=j.csrf)
    assert replay.json()=={**saved.json(),'replayed':True}
    stale=await j.client.put(j.policy,json=command(),headers=j.csrf)
    assert stale.status_code==409 and stale.json()['detail']['code']=='measurement_policy_stale'
    body['mode']='off'
    assert (await j.client.put(j.policy,json=body,headers=j.csrf)).status_code==409
    assert (await j.client.get(j.policy)).headers['cache-control']=='no-store'


@pytest.mark.asyncio
@pytest.mark.parametrize('role',['manager','viewer','staff'])
async def test_only_owner_can_authorize_tracking(activity,role):
    j=activity
    async with j.sessions.begin() as db:
        await db.execute(update(Membership).where(Membership.business_id==j.bid,Membership.user_id==j.uid).values(role=role))
    assert (await j.client.put(j.policy,json=command(),headers=j.csrf)).status_code==403
    read=await j.client.get(j.policy)
    assert read.status_code==(403 if role=='staff' else 200)
    if role!='staff':assert read.json()['can_change'] is False


@pytest.mark.asyncio
async def test_policy_csrf_foreign_tenant_and_extra_fields(activity):
    j=activity
    assert (await j.client.put(j.policy,json=command())).status_code==403
    assert (await j.client.put(j.policy,json=command(),headers={**j.csrf,'Origin':'https://foreign.example'})).status_code==403
    foreign=j.policy.replace(str(j.bid),str(uuid4()))
    assert (await j.client.put(foreign,json=command(),headers=j.csrf)).status_code==404
    assert (await j.client.put(j.policy,json={**command(),'is_test':False},headers=j.csrf)).status_code==422


@pytest.mark.asyncio
async def test_visible_context_exact_replay_event_null_dedup_and_wrong_proof(activity):
    j=activity;await enable(j)
    key=str(uuid4());one=await started(j,key);two=await started(j,key)
    assert one==two and one['state']=='ready'
    headers={'Authorization':'Bearer '+one['capability']}
    first=await j.browser.post(j.public+'/events',json={'event_kind':'checkout_opened'},headers=headers)
    second=await j.browser.post(j.public+'/events',json={'event_kind':'checkout_opened'},headers=headers)
    assert first.json()['replayed'] is False and second.json()['replayed'] is True
    assert (await j.browser.post(j.public+'/events',json={'event_kind':'checkout_opened'},headers={'Authorization':'Bearer fake'})).status_code==401
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ActivityContext))==1
        assert await db.scalar(select(func.count()).select_from(ActivityEvent))==1
        row=await db.get(ActivityContext,UUID(one['context_id']));assert row.classification=='live'


@pytest.mark.asyncio
@pytest.mark.parametrize('headers',[
    {'DNT':'1'},{'Sec-GPC':'1'},{'User-Agent':'Googlebot'},{'Sec-Purpose':'prefetch'}])
async def test_known_exclusions_do_not_write_context(activity,headers):
    j=activity;await enable(j)
    response=await j.browser.post(j.public+'/contexts',json={'idempotency_key':str(uuid4())},headers=headers)
    assert response.json()['state']=='excluded'
    async with j.sessions() as db:assert await db.scalar(select(func.count()).select_from(ActivityContext))==0


@pytest.mark.asyncio
async def test_native_context_is_test_and_cannot_promote_live_replay(activity):
    j=activity;await enable(j)
    response=await j.client.post(j.public+'/contexts',json={'idempotency_key':str(uuid4())},headers={'Origin':'https://independent-canonical.example.test'})
    assert response.status_code==200,response.text
    cid=UUID(response.json()['context_id'])
    async with j.sessions() as db:assert (await db.get(ActivityContext,cid)).classification=='test'
    key=str(uuid4());live=await started(j,key)
    response=await j.client.post(j.public+'/contexts',json={'idempotency_key':key},headers={'Origin':'https://independent-canonical.example.test'})
    assert response.json()['state']=='excluded'
    async with j.sessions() as db:assert (await db.get(ActivityContext,UUID(live['context_id']))).classification=='live'


@pytest.mark.asyncio
async def test_public_strict_origin_size_json_and_private_defaults(activity):
    j=activity;await enable(j)
    assert (await j.browser.post(j.public+'/contexts',json={'idempotency_key':str(uuid4())},headers={'Origin':'https://foreign.test'})).status_code==403
    assert (await j.browser.post(j.public+'/contexts',json={'idempotency_key':str(uuid4()),'mode':'live'})).status_code==422
    assert (await j.browser.post(j.public+'/contexts',content='{"idempotency_key":"x","idempotency_key":"y"}',headers={'Content-Type':'application/json'})).status_code==422
    assert (await j.browser.post(j.public+'/contexts',content='x'*1025,headers={'Content-Type':'application/json'})).status_code==413
    assert (await j.browser.post(j.public+'/contexts',content='['*500,headers={'Content-Type':'application/json'})).status_code==422
    result=await j.browser.post(j.public+'/contexts',json={'idempotency_key':str(uuid4())})
    assert result.headers['cache-control']=='no-store' and result.headers['referrer-policy']=='no-referrer'


@pytest.mark.asyncio
async def test_context_cap_marks_coverage_without_more_rows(activity,monkeypatch):
    j=activity;await enable(j);monkeypatch.setattr(domain,'CONTEXT_CAP',1)
    first=await started(j)
    assert (await started(j))['state']=='capped'
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ActivityGap))==1
        assert await db.scalar(select(func.count()).select_from(ActivityContext))==1
    result=await j.client.get(j.activity)
    assert result.status_code==200,result.text
    assert 'ingestion_capped' in result.json()['coverage']['reasons']
    assert result.json()['conversion']['percentage'] is None


@pytest.mark.asyncio
async def test_unavailable_activity_is_null_not_zero_and_never_exposes_private_rows(activity):
    j=activity
    response=await j.client.get(j.activity)
    assert response.status_code==200,response.text
    value=response.json()
    assert value['counts']['visits'] is None and value['conversion']['percentage'] is None
    assert value['channel_activity']['enquiry_messages'] is None
    assert value['production_orders']['placed'] is None
    assert set(value)=={'contract_version','business_id','from_date','to_date','generated_at','coverage','counts','conversion','production_orders','channel_activity','attribution'}
    for needle in ('gateway_credentials','provider_id','customer_id','capability','context_id','request_hash'):
        assert needle not in response.text


@pytest.mark.asyncio
async def test_policy_owner_revocation_while_waiting_rolls_back(activity):
    j=activity
    async with j.sessions() as blocker:
        from app.models.identity import Business
        await blocker.scalar(select(Business.id).where(Business.id==j.bid).with_for_update(key_share=True))
        pending=asyncio.create_task(j.client.put(j.policy,json=command(),headers=j.csrf))
        # Prove the actual backend has reached its lock, rather than racing on sleep.
        for _ in range(100):
            async with j.sessions() as observer:
                waiting=await observer.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE '%businesses%'"))
            if waiting:break
            await asyncio.sleep(.01)
        assert waiting
        async with j.sessions.begin() as revoker:
            await revoker.execute(update(Membership).where(Membership.business_id==j.bid,Membership.user_id==j.uid).values(role='manager'))
        await blocker.rollback()
        response=await asyncio.wait_for(pending,5)
        assert response.status_code==403,response.text
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ActivityPolicy))==0
        assert await db.scalar(select(func.count()).select_from(ActivityPolicyCommand))==0


@pytest.mark.asyncio
async def test_retention_readiness_blocks_collection_but_not_policy_or_cleanup(activity,monkeypatch):
    j=activity;monkeypatch.setattr(settings,'V1_ACTIVITY_RETENTION_READY',False)
    await enable(j)
    assert (await started(j))['state']=='disabled'
    current=(await j.client.get(j.policy)).json();assert current['mode']=='live' and current['collector_available'] is False
    report=(await j.client.get(j.activity)).json()
    assert report['coverage']['retention_ready'] is False and 'collector_disabled' in report['coverage']['reasons']
    assert report['conversion']['percentage'] is None
    async with j.sessions.begin() as db:assert await domain.delete_expired(db)=={'v1_activity_contexts':0,'v1_activity_sources':0,'v1_activity_gaps':0}


@pytest.mark.asyncio
async def test_disabled_public_storefront_cannot_collect_anonymous_live_context(activity,monkeypatch):
    j=activity;await enable(j)
    monkeypatch.setattr(settings,'V1_STOREFRONT_ENABLED',False)
    assert (await started(j))['state']=='disabled'
    assert (await j.client.get(j.policy)).json()['collector_available'] is False


@pytest.mark.asyncio
async def test_native_final_owner_guard_rolls_back_already_staged_policy(activity,monkeypatch):
    j=activity;original=domain.change_policy
    async def revoked_after_staging(*args,**kwargs):
        result=await original(*args,**kwargs)
        async with j.sessions.begin() as revoker:
            await revoker.execute(update(Membership).where(Membership.business_id==j.bid,Membership.user_id==j.uid).values(role='manager'))
        return result
    monkeypatch.setattr(domain,'change_policy',revoked_after_staging)
    response=await j.client.put(j.policy,json=command(),headers=j.csrf)
    assert response.status_code==403,response.text
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ActivityPolicy))==0
        assert await db.scalar(select(func.count()).select_from(ActivityPolicyCommand))==0


@pytest.mark.asyncio
async def test_publication_revoked_during_policy_wait_discards_context(activity):
    j=activity;await enable(j)
    async with j.sessions() as blocker:
        await blocker.scalar(select(ActivityPolicy).where(ActivityPolicy.business_id==j.bid).with_for_update())
        pending=asyncio.create_task(j.browser.post(j.public+'/contexts',json={'idempotency_key':str(uuid4())}))
        waiting=0
        for _ in range(100):
            async with j.sessions() as observer:
                waiting=await observer.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE '%v1_activity_policies%'"))
            if waiting:break
            await asyncio.sleep(.01)
        assert waiting
        async with j.sessions.begin() as publisher:
            await publisher.execute(update(Storefront).where(Storefront.seller_id==j.bid).values(published=False))
        await blocker.rollback();response=await asyncio.wait_for(pending,5)
        assert response.status_code==404,response.text
    async with j.sessions() as db:assert await db.scalar(select(func.count()).select_from(ActivityContext))==0
