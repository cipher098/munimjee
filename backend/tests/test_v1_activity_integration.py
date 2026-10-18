"""Actual app.main writer/provenance boundaries; no provider transports."""
import hashlib
import json
from uuid import UUID, uuid4
import pytest
from sqlalchemy import func, select
from app.models.activity_v1 import OrderActivity
from app.schemas.checkout_v1 import CheckoutWrite
from app.services.checkout_v1 import request_hash
from tests.test_v1_activity_http import activity, enable, started  # noqa: F401
from tests.test_v1_native_completion_import_http import native_import  # noqa: F401


async def product(j):
    response = await j.client.post(f'/api/v1/businesses/{j.bid}/catalogue/products', headers=j.csrf,
        json={'idempotency_key':str(uuid4()),'seller_reviewed':True,'name':'Measured synthetic dress',
              'skus':[{'options':{'Size':'M'},'price_minor':1250,'currency':'INR','stock_available':10,'active':True}]})
    assert response.status_code==201,response.text
    data=response.json();pid=data['product']['product_id']
    response=await j.client.post(f'/api/v1/businesses/{j.bid}/catalogue/products/{pid}/activate',headers=j.csrf,
        json={'seller_reviewed':True,'expected_mapping_revision':data['mapping_revision'],
              'expected_legacy_fingerprint':data['legacy_fingerprint']})
    assert response.status_code==200,response.text
    response=await j.client.put(f'/api/v1/businesses/{j.bid}/catalogue/checkout-policy',headers=j.csrf,
        json={'checkout_enabled':True})
    assert response.status_code==200,response.text
    return data['skus'][0]['sku_id']


def payload(sku,**extra):
    return {'idempotency_key':str(uuid4()),'customer':{'name':'Synthetic Buyer','phone':'9876543210','email':None},
        'address':{'line1':'Synthetic Street','line2':'','city':'Jaipur','state':'Rajasthan','postal_code':'302001','country':'IN'},
        'items':[{'sku_id':sku,'quantity':1}],'note':'','payment_method':'cod','whatsapp_updates_opt_in':False,**extra}


@pytest.mark.asyncio
async def test_actual_main_new_order_link_and_accepted_replay_precedes_proof(activity):
    j=activity;await enable(j);sku=await product(j);context=await started(j)
    body=payload(sku,activity_context_id=context['context_id'])
    path=f'/api/v1/storefronts/{j.slug}/checkout'
    accepted=await j.browser.post(path,json=body,headers={'X-Activity-Context':'Bearer '+context['capability']})
    assert accepted.status_code==201,accepted.text
    replay=await j.browser.post(path,json=body,headers={'X-Activity-Context':'Bearer invalid'})
    assert replay.status_code==200 and replay.json()['id']==accepted.json()['id']
    async with j.sessions() as db:
        row=await db.get(OrderActivity,UUID(accepted.json()['id']))
        assert row.classification=='live' and str(row.context_id)==context['context_id']
        assert await db.scalar(select(func.count()).select_from(OrderActivity))==1
    assert (await j.browser.post(path,json={**body,'activity_context_id':str(uuid4())})).status_code==409


@pytest.mark.asyncio
@pytest.mark.parametrize('proof',['missing','invalid','foreign','native'])
async def test_bad_optional_proof_keeps_shopping_and_never_promotes(activity,proof):
    j=activity;await enable(j);sku=await product(j);context=await started(j)
    body=payload(sku,activity_context_id=context['context_id'])
    headers={}
    if proof in {'foreign','native'}:headers['X-Activity-Context']='Bearer '+context['capability']
    if proof=='invalid':headers['X-Activity-Context']='Bearer invalid'
    if proof=='foreign':body['activity_context_id']=str(uuid4())
    browser=j.client if proof=='native' else j.browser
    response=await browser.post(f'/api/v1/storefronts/{j.slug}/checkout',json=body,headers=headers)
    assert response.status_code==201,response.text
    async with j.sessions() as db:
        row=await db.get(OrderActivity,UUID(response.json()['id']))
        assert row.classification==('test' if proof=='native' else 'unknown') and row.context_id is None


@pytest.mark.asyncio
async def test_legacy_absent_null_financial_hash_and_no_replay_backfill(activity):
    j=activity;await enable(j);sku=await product(j);body=payload(sku)
    normalized=CheckoutWrite.model_validate(body).model_dump(mode='json',exclude={'idempotency_key','activity_context_id'})
    old=hashlib.sha256(json.dumps(normalized,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert request_hash(CheckoutWrite.model_validate(body))==old
    assert request_hash(CheckoutWrite.model_validate({**body,'activity_context_id':None}))==old
    path=f'/api/v1/storefronts/{j.slug}/checkout'
    accepted=await j.browser.post(path,json=body);assert accepted.status_code==201,accepted.text
    context=await started(j)
    replay=await j.browser.post(path,json={**body,'activity_context_id':None},headers={'X-Activity-Context':'Bearer '+context['capability']})
    assert replay.status_code==200,replay.text
    async with j.sessions() as db:
        row=await db.get(OrderActivity,UUID(accepted.json()['id']))
        assert row.classification=='unknown' and row.context_id is None


@pytest.mark.asyncio
async def test_registered_cleanup_deletes_only_expired_raw_when_collection_off(activity,monkeypatch):
    import asyncio
    from datetime import timedelta
    from app.config import settings
    from app.models.activity_v1 import ActivityContext,ActivityEvent,ActivityPolicyCommand
    from app.workers.v1_activity import cleanup_activity
    from tests.test_v1_activity_schema import policy,context
    j=activity
    async with j.sessions.begin() as db:
        from sqlalchemy import func
        old=await db.scalar(select(func.clock_timestamp()))-timedelta(days=91)
        await policy(j,db,at=old-timedelta(seconds=1))
        expired=await context(j,db,at=old)
        db.add(ActivityEvent(business_id=j.bid,context_id=expired.id,event_kind='checkout_opened',created_at=old+timedelta(seconds=1)))
        current=await context(j,db)
        current_id=current.id
    monkeypatch.setattr(settings,'V1_ACTIVITY_ENABLED',False)
    monkeypatch.setattr(settings,'V1_ACTIVITY_RETENTION_READY',False)
    deleted=await asyncio.to_thread(cleanup_activity.run)
    assert deleted['v1_activity_contexts']==1
    async with j.sessions() as db:
        assert await db.get(ActivityContext,current_id) is not None
        assert await db.scalar(select(func.count()).select_from(ActivityContext))==1
        assert await db.scalar(select(func.count()).select_from(ActivityEvent))==0
        assert await db.scalar(select(func.count()).select_from(ActivityPolicyCommand))==1
