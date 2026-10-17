"""Actual PG16 + separate Worker/HMAC/SQLite loopback service; no live providers."""
import asyncio
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
from uuid import UUID,uuid4
import httpx
from fastapi import FastAPI
from sqlalchemy import select,func,text
from sqlalchemy.ext.asyncio import async_sessionmaker
import pytest
import pytest_asyncio
from app.config import settings
from app.database import get_db
from app.api.v1.auth import router as auth_router
from app.api.v1.catalogue import router as catalogue_router
from app.api.v1.parcel_tracking import router,Preview,Confirm
from app.models.parcel_tracking import ParcelConnector,OrderParcelLink,ParcelObservation,ParcelNotification,ParcelAudit
from app.models.identity import Membership,User,Business
from app.models.commerce import CommerceOrder
from app.models.whatsapp import WhatsAppAccount,WhatsAppContact,WhatsAppTemplate,WhatsAppMessage
from app.services import parcel_tracking as service
from app.services.parcel_connector import ParcelAdapter,ConnectorUnavailable
from tests.parcel_transport import NodeConnectorTransport
from tests.test_storefront_publication import setup,checkout

ROOT=Path(__file__).resolve().parents[2]
CONNECTOR=ROOT.parent/'parcel-desk-v1-connector'
SECRET='synthetic-parcel-machine-secret-at-least32characters'

class BridgeAdapter(ParcelAdapter):
    def __init__(self,connector):super().__init__(connector,transport=NodeConnectorTransport())

@pytest_asyncio.fixture
async def api(migrated_engine,monkeypatch,tmp_path):
    monkeypatch.setattr(settings,'V1_AUTH_ENABLED',True);monkeypatch.setattr(settings,'V1_PARCEL_ENABLED',True)
    monkeypatch.setattr(settings,'PUBLIC_BASE_URL','http://test')
    app=FastAPI();app.include_router(auth_router);app.include_router(catalogue_router);app.include_router(router)
    factory=async_sessionmaker(migrated_engine,expire_on_commit=False)
    async def database():
        async with factory() as db:
            try:yield db;await db.commit()
            except Exception:await db.rollback();raise
    app.dependency_overrides[get_db]=database
    original=service.process_link;original_preview=service.preview
    async def process(db,link_id,**kwargs):return await original(db,link_id,adapter_factory=BridgeAdapter,**kwargs)
    async def preview(*args,**kwargs):return await original_preview(*args,adapter_factory=BridgeAdapter,**kwargs)
    monkeypatch.setattr(service,'process_link',process);monkeypatch.setattr(service,'preview',preview)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers={'Origin':'http://test'}) as client:
        data=await setup(client,stock=5)
        body=checkout(data['sku']);placed=await client.post(f"/api/v1/storefronts/{data['slug']}/checkout",json=body);assert placed.status_code==201,placed.text
        order_id=UUID(placed.json()['id']);instance=uuid4();connector_id=uuid4();config={'business_id':str(data['bid']),'instance_id':str(instance),'secret':SECRET}
        file=tmp_path/'config.json';file.write_text(json.dumps(config))
        monkeypatch.setattr(settings,'V1_PARCEL_ALLOWED_ORIGINS',['http://127.0.0.1:8155'])
        monkeypatch.setattr(settings,'V1_PARCEL_CONNECTORS_JSON',json.dumps({'synthetic':{**config,'origin':'http://127.0.0.1:8155','key_id':'synthetic','enabled':True}}))
        async with factory.begin() as db:db.add(ParcelConnector(id=connector_id,business_id=data['bid'],instance_id=instance,origin='http://127.0.0.1:8155',credential_ref='synthetic',enabled=True))
        process=await asyncio.create_subprocess_exec('node','tests/server.mjs',cwd=CONNECTOR,env={**os.environ,'PARCEL_FIXTURE_CONFIG':str(file),'PARCEL_FIXTURE_DATABASE':str(tmp_path/'parcel.sqlite')},stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        try:
            assert (await asyncio.wait_for(process.stdout.readline(),10)).decode().strip()=='PARCEL_FIXTURE_READY'
            yield {'client':client,'factory':factory,'bid':data['bid'],'oid':order_id,'data':data,'base':f"/api/v1/businesses/{data['bid']}/orders/{order_id}/parcels",'config':file,'instance':instance,'connector_id':connector_id,'process':process,'tmp':tmp_path}
        finally:
            if process.returncode is None:process.terminate()
            await process.wait()

async def make_preview(api,awb='44600000001'):
    response=await api['client'].post(api['base']+'/preview',headers=api['data']['headers'],json={'scan_id':str(uuid4()),'courier_id':'skyking','awb':awb})
    assert response.status_code==200,response.text
    return response.json()

async def link(api,preview=None,key=None):
    preview=preview or await make_preview(api)
    body={'idempotency_key':str(key or uuid4()),'candidate_token':preview['candidate_token'],'expected_order_fingerprint':preview['order']['fingerprint'],'confirmed':True}
    response=await api['client'].post(api['base'],headers=api['data']['headers'],json=body)
    assert response.status_code==200,response.text
    return response.json(),body

async def control(path,body=None):
    # Separate Node fixture control is test-only, hardcoded loopback, never in adapter.
    script="""import http from 'node:http';let b='';for await(const c of process.stdin)b+=c;const body=JSON.parse(b);const req=http.request('http://127.0.0.1:8155'+body.path,{method:body.data?'POST':'GET',headers:{'X-Test-Sentinel':'parcel-fixture-only','Content-Type':'application/json'}},res=>{let data='';res.on('data',c=>data+=c);res.on('end',()=>{if(res.statusCode!==200)process.exit(1);process.stdout.write(data);});});req.on('error',()=>process.exit(1));req.end(body.data?JSON.stringify(body.data):undefined);"""
    assert path in {'/__synthetic/status','/__synthetic/stats'}
    process=await asyncio.create_subprocess_exec('node','--input-type=module','-e',script,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE)
    result,_=await process.communicate(json.dumps({'path':path,'data':body}).encode());assert process.returncode==0
    return json.loads(result)

@pytest.mark.asyncio
async def test_actual_two_service_confirm_replay_poll_history_no_order_transition(api):
    result,body=await link(api);assert result['link']['state']=='linked'
    response=await api['client'].post(api['base'],headers=api['data']['headers'],json=body)
    assert response.json()['link']['id']==result['link']['id'] and response.json()['replayed']
    assert (await control('/__synthetic/stats'))['shipments']==1
    link_id=UUID(result['link']['id'])
    async with api['factory']() as db:
        row=await db.get(OrderParcelLink,link_id);remote=str(row.remote_id)
        order=await db.get(CommerceOrder,api['oid']);assert order.fulfillment_status=='pending' and order.payment_status=='pending' and order.tracking_number is None
    event={'time':'2026-10-18T10:00:00Z','description':'In transit','location':'Synthetic hub'}
    await control('/__synthetic/status',{'remote_id':remote,'status':'In transit','checked_at':datetime.now(timezone.utc).isoformat(),'events':[event]})
    refresh=await api['client'].post(api['base']+'/'+str(link_id)+'/refresh',headers=api['data']['headers'],json={'idempotency_key':str(uuid4())})
    assert refresh.status_code==200,refresh.text
    assert refresh.json()['link']['tracking_state']=='in_transit'
    history=(await api['client'].get(api['base']+'/'+str(link_id)+'/history')).json();assert history['total']==1 and history['items'][0]['description']=='In transit'
    await control('/__synthetic/status',{'remote_id':remote,'status':'In transit','checked_at':datetime.now(timezone.utc).isoformat(),'events':[]})
    async with api['factory']() as db:await service.process_link(db,link_id)
    async with api['factory']() as db:
        assert await db.scalar(select(func.count()).select_from(ParcelObservation))==1
        note=await db.scalar(select(ParcelNotification));assert note.decision=='skipped' and note.reason=='not_consented'
        assert await db.scalar(select(func.count()).select_from(WhatsAppMessage))==0

@pytest.mark.asyncio
async def test_postcommit_remote_response_loss_keeps_command_and_reconciles_exactly_once(api):
    config=json.loads(api['config'].read_text());config['drop_once']=True;api['config'].write_text(json.dumps(config))
    result,body=await link(api);assert result['link']['state']=='enrollment_unknown'
    assert (await control('/__synthetic/stats'))['shipments']==1
    replay=await api['client'].post(api['base'],headers=api['data']['headers'],json=body)
    assert replay.status_code==200 and replay.json()['link']['state']=='linked'
    assert (await control('/__synthetic/stats'))['shipments']==1
    async with api['factory']() as db:assert await db.scalar(select(func.count()).select_from(OrderParcelLink))==1

@pytest.mark.asyncio
async def test_current_tenant_actor_candidate_order_and_csrf_before_remote_effect(api):
    preview=await make_preview(api)
    body={'idempotency_key':str(uuid4()),'candidate_token':preview['candidate_token'],'expected_order_fingerprint':preview['order']['fingerprint'],'confirmed':True}
    no_csrf=await api['client'].post(api['base'],json=body);assert no_csrf.status_code==403
    wrong=api['base'].replace(str(api['bid']),str(uuid4()))
    assert (await api['client'].get(wrong)).status_code==404
    async with api['factory'].begin() as db:
        membership=await db.scalar(select(Membership).where(Membership.business_id==api['bid']));membership.role='viewer'
    denied=await api['client'].post(api['base'],headers=api['data']['headers'],json=body);assert denied.status_code==403
    assert (await control('/__synthetic/stats'))['shipments']==0

@pytest.mark.asyncio
async def test_order_change_and_foreign_host_binding_fail_closed(api,monkeypatch):
    preview=await make_preview(api)
    async with api['factory'].begin() as db:(await db.get(CommerceOrder,api['oid'])).fulfillment_status='confirmed'
    body={'idempotency_key':str(uuid4()),'candidate_token':preview['candidate_token'],'expected_order_fingerprint':preview['order']['fingerprint'],'confirmed':True}
    assert (await api['client'].post(api['base'],headers=api['data']['headers'],json=body)).status_code==409
    monkeypatch.setattr(settings,'V1_PARCEL_ALLOWED_ORIGINS',['https://foreign.example'])
    assert (await api['client'].post(api['base']+'/preview',headers=api['data']['headers'],json={'scan_id':str(uuid4()),'courier_id':'skyking','awb':'44600000001'})).status_code==409
    assert (await control('/__synthetic/stats'))['shipments']==0

@pytest.mark.asyncio
async def test_membership_revoked_during_order_lock_wait_prevents_link(api):
    preview=await make_preview(api);body={'idempotency_key':str(uuid4()),'candidate_token':preview['candidate_token'],'expected_order_fingerprint':preview['order']['fingerprint'],'confirmed':True}
    holder=api['factory']();await holder.begin();await holder.scalar(select(CommerceOrder).where(CommerceOrder.id==api['oid']).with_for_update())
    task=asyncio.create_task(api['client'].post(api['base'],headers=api['data']['headers'],json=body))
    try:
        # Wait until actual PostgreSQL sees the blocked order lock.
        async with api['factory']() as observer:
            for _ in range(100):
                waits=await observer.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'"))
                if waits:break
                await asyncio.sleep(.01)
            assert waits
        async with api['factory'].begin() as db:
            membership=await db.scalar(select(Membership).where(Membership.business_id==api['bid']));membership.is_active=False
        await holder.commit();response=await task;assert response.status_code==404,response.text
        assert (await control('/__synthetic/stats'))['shipments']==0
    finally:
        await holder.close()
        if not task.done():task.cancel()

@pytest.mark.asyncio
async def test_unique_order_association_changed_key_body_and_append_only_history(api):
    result,body=await link(api);link_id=UUID(result['link']['id'])
    changed={**body,'expected_order_fingerprint':'0'*64}
    assert (await api['client'].post(api['base'],headers=api['data']['headers'],json=changed)).status_code==409
    new_preview=await make_preview(api,'44600000002')
    other={**body,'idempotency_key':str(uuid4()),'candidate_token':new_preview['candidate_token'],'expected_order_fingerprint':new_preview['order']['fingerprint']}
    assert (await api['client'].post(api['base'],headers=api['data']['headers'],json=other)).status_code==409
    async with api['factory']() as db:
        row=await db.get(OrderParcelLink,link_id);remote=str(row.remote_id)
    event={'time':'not-a-real-date','description':'Out for delivery','location':'Synthetic hub'}
    checked=datetime.now(timezone.utc).isoformat();await control('/__synthetic/status',{'remote_id':remote,'status':'Out for delivery','checked_at':checked,'events':[event,event]})
    async with api['factory']() as db:await service.process_link(db,link_id)
    async with api['factory']() as db:
        observation=await db.scalar(select(ParcelObservation));assert observation.raw_time=='not-a-real-date' and observation.event_at is None
        assert await db.scalar(select(func.count()).select_from(ParcelObservation))==1
        with pytest.raises(Exception,match='append-only'):
            await db.execute(text("UPDATE v1_parcel_observations SET status='Changed'"))
        await db.rollback()
    await control('/__synthetic/status',{'remote_id':remote,'status':'Delivered','checked_at':checked,'events':[event]})
    async with api['factory']() as db:await service.process_link(db,link_id)
    await control('/__synthetic/status',{'remote_id':remote,'status':'In transit','checked_at':checked,'events':[]})
    async with api['factory']() as db:await service.process_link(db,link_id)
    async with api['factory']() as db:
        row=await db.get(OrderParcelLink,link_id);assert row.tracking_state=='delivered' and row.state=='review_required' and row.error_code=='terminal_status_conflict'
        assert await db.scalar(select(func.count()).select_from(ParcelObservation))==1

@pytest.mark.asyncio
async def test_tracking_without_consent_and_approved_milestone_outbox_dedup_and_sendtime_fences(api):
    result,_=await link(api);link_id=UUID(result['link']['id'])
    async with api['factory'].begin() as db:
        row=await db.get(OrderParcelLink,link_id);remote=str(row.remote_id)
        order=await db.get(CommerceOrder,api['oid']);order.whatsapp_updates_opt_in=True
        db.add(WhatsAppAccount(seller_id=api['bid'],phone_number_id='synthetic-pni',waba_id='synthetic-waba',access_token='synthetic-encrypted-not-used',enabled=True,order_templates={'parcel_delivered':{'name':'synthetic_parcel','language':'en'}}))
        db.add(WhatsAppContact(id=uuid4(),seller_id=api['bid'],phone='919876543210',name='Synthetic buyer',utility_opt_in=True,last_inbound_at=datetime.now(timezone.utc)-timedelta(days=2)))
        db.add(WhatsAppTemplate(seller_id=api['bid'],name='synthetic_parcel',language='en',status='APPROVED',category='UTILITY',components=[{'type':'BODY','text':'Hi {{1}}, order {{2}}: {{3}}'}]))
    event={'time':datetime.now(timezone.utc).isoformat(),'description':'Delivered','location':'Synthetic destination'}
    await control('/__synthetic/status',{'remote_id':remote,'status':'Delivered','checked_at':event['time'],'events':[event]})
    for _ in range(2):
        async with api['factory']() as db:await service.process_link(db,link_id)
    async with api['factory']() as db:
        message=await db.scalar(select(WhatsAppMessage));assert message.kind=='template' and message.idempotency_key==f'parcel:{link_id}:delivered' and message.status=='queued'
        contact=await db.scalar(select(WhatsAppContact));await service.revalidate_notification(db,message,contact)
        assert await db.scalar(select(func.count()).select_from(WhatsAppMessage))==1
        assert await db.scalar(select(func.count()).select_from(ParcelNotification))==1
        contact.utility_opt_in=False;await db.flush()
        with pytest.raises(Exception,match='consent'):await service.revalidate_notification(db,message,contact)
        await db.rollback()
    async with api['factory'].begin() as db:
        (await db.get(Business,api['bid'])).is_active=False
    async with api['factory']() as db:
        message=await db.scalar(select(WhatsAppMessage));contact=await db.scalar(select(WhatsAppContact))
        with pytest.raises(Exception,match='paused'):await service.revalidate_notification(db,message,contact)

@pytest.mark.asyncio
async def test_crash_after_local_intent_commit_before_wakeup_is_recovered(api):
    preview=await make_preview(api)
    async with api['factory']() as db:
        actor=await db.scalar(select(User).join(Membership,Membership.user_id==User.id).where(Membership.business_id==api['bid']))
        link_row,_=await service.confirm(db,service.Actor(actor.id,'v1_user'),api['bid'],api['oid'],Confirm(idempotency_key=uuid4(),candidate_token=preview['candidate_token'],expected_order_fingerprint=preview['order']['fingerprint'],confirmed=True))
        link_id=link_row.id;await db.commit()
    assert (await control('/__synthetic/stats'))['shipments']==0
    from app.workers import parcel_tracking as worker
    # poll_due resolves service.process_link's module import; bind only its fixture transport.
    worker_process=worker.process_link
    async def process(db,link_id):return await service.process_link(db,link_id)
    worker.process_link=process
    try:await worker.poll_due(api['factory'])
    finally:worker.process_link=worker_process
    async with api['factory']() as db:assert (await db.get(OrderParcelLink,link_id)).state=='linked'
    assert (await control('/__synthetic/stats'))['shipments']==1

@pytest.mark.asyncio
async def test_expired_preview_definitive_code_only_before_mutation_and_same_key_receipt_replays(api):
    from jose import jwt
    preview=await make_preview(api);claims=jwt.decode(preview['candidate_token'],settings.SECRET_KEY,algorithms=['HS256']);claims['exp']=1
    expired=jwt.encode(claims,settings.SECRET_KEY,algorithm='HS256')
    body={'idempotency_key':str(uuid4()),'candidate_token':expired,'expected_order_fingerprint':preview['order']['fingerprint'],'confirmed':True}
    response=await api['client'].post(api['base'],headers=api['data']['headers'],json=body)
    assert response.status_code==409 and response.json()['detail']['code']=='parcel_preview_expired_or_invalid'
    assert (await control('/__synthetic/stats'))['shipments']==0
    result,original=await link(api,preview)
    # A saved durable receipt remains replayable after wall time expires. Force
    # decode to reject; lookup must still return the original receipt first.
    import unittest.mock
    with unittest.mock.patch('app.services.parcel_tracking.jwt',new=type('ReceiptJWT',(),{'decode':staticmethod(lambda *a,**k: (_ for _ in ()).throw(AssertionError('Receipt lookup must precede candidate decode')))})()):
        replay=await api['client'].post(api['base'],headers=api['data']['headers'],json=original)
    assert replay.status_code==200 and replay.json()['link']['id']==result['link']['id']

@pytest.mark.asyncio
async def test_concurrent_two_orders_cannot_claim_same_courier_awb(api):
    body=checkout(api['data']['sku']);response=await api['client'].post(f"/api/v1/storefronts/{api['data']['slug']}/checkout",json=body);assert response.status_code==201
    second=response.json()['id'];first=await make_preview(api)
    second_base=api['base'].replace(str(api['oid']),second)
    preview=await api['client'].post(second_base+'/preview',headers=api['data']['headers'],json={'scan_id':str(uuid4()),'courier_id':'skyking','awb':'44600000001'});assert preview.status_code==200
    bodies=[{'idempotency_key':str(uuid4()),'candidate_token':value['candidate_token'],'expected_order_fingerprint':value['order']['fingerprint'],'confirmed':True} for value in (first,preview.json())]
    responses=await asyncio.gather(*[api['client'].post(path,headers=api['data']['headers'],json=value) for path,value in zip((api['base'],second_base),bodies)])
    assert sorted(r.status_code for r in responses)==[200,409]
    assert (await control('/__synthetic/stats'))['shipments']==1
    async with api['factory']() as db:assert await db.scalar(select(func.count()).select_from(OrderParcelLink))==1

@pytest.mark.asyncio
async def test_native_session_revoked_during_order_lock_wait_prevents_link(api):
    from app.models.identity_auth import UserSession
    preview=await make_preview(api);body={'idempotency_key':str(uuid4()),'candidate_token':preview['candidate_token'],'expected_order_fingerprint':preview['order']['fingerprint'],'confirmed':True}
    holder=api['factory']();await holder.begin();await holder.scalar(select(CommerceOrder).where(CommerceOrder.id==api['oid']).with_for_update())
    task=asyncio.create_task(api['client'].post(api['base'],headers=api['data']['headers'],json=body))
    try:
        async with api['factory']() as observer:
            for _ in range(100):
                waits=await observer.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'"))
                if waits:break
                await asyncio.sleep(.01)
            assert waits
        async with api['factory'].begin() as db:
            session=await db.scalar(select(UserSession));session.revoked_at=datetime.now(timezone.utc)
        await holder.commit();response=await task;assert response.status_code==401,response.text
        assert (await control('/__synthetic/stats'))['shipments']==0
        async with api['factory']() as db:assert await db.scalar(select(func.count()).select_from(OrderParcelLink))==0
    finally:
        await holder.close()
        if not task.done():task.cancel()

@pytest.mark.asyncio
async def test_connector_disabled_or_binding_changed_after_queue_prevents_notification(api,monkeypatch):
    result,_=await link(api);link_id=UUID(result['link']['id'])
    async with api['factory'].begin() as db:
        row=await db.get(OrderParcelLink,link_id);row.tracking_state='delivered';row.raw_status='Delivered'
        order=await db.get(CommerceOrder,api['oid']);order.whatsapp_updates_opt_in=True
        contact=WhatsAppContact(id=uuid4(),seller_id=api['bid'],phone='919876543210',utility_opt_in=True);db.add(contact)
        db.add(WhatsAppTemplate(seller_id=api['bid'],name='synthetic',language='en',status='APPROVED',category='UTILITY',components=[{'type':'BODY','text':'{{1}} {{2}} {{3}}'}]))
        await db.flush()
        message=WhatsAppMessage(seller_id=api['bid'],contact_id=contact.id,phone_number_id='synthetic',idempotency_key=f'parcel:{link_id}:delivered',direction='outbound',kind='template',payload={'name':'synthetic','language':'en','parameters':['Synthetic','MJ-synthetic','Delivered']},status='queued');db.add(message)
    async with api['factory']() as db:
        message=await db.scalar(select(WhatsAppMessage));contact=await db.scalar(select(WhatsAppContact));await service.revalidate_notification(db,message,contact)
        connector=await db.get(ParcelConnector,api['connector_id']);connector.enabled=False;await db.flush()
        with pytest.raises(Exception,match='connector authorization'):await service.revalidate_notification(db,message,contact)
        await db.rollback()
        message=await db.scalar(select(WhatsAppMessage));contact=await db.scalar(select(WhatsAppContact))
        monkeypatch.setattr(settings,'V1_PARCEL_CONNECTORS_JSON','{}')
        with pytest.raises(Exception,match='connector authorization'):await service.revalidate_notification(db,message,contact)
        message.idempotency_key=f'parcel:{link_id}'
        with pytest.raises(Exception,match='Invalid parcel'):await service.revalidate_notification(db,message,contact)

@pytest.mark.asyncio
async def test_deep_bounded_response_is_unconfirmed_and_database_actor_is_tenant_bound(api):
    from app.services.parcel_connector import ParcelAdapter
    from app.models.identity import User
    async with api['factory']() as db:
        connector=await db.get(ParcelConnector,api['connector_id'])
        adapter=ParcelAdapter(connector,transport=httpx.MockTransport(lambda request:httpx.Response(200,content=('['*2000+'0'+']'*2000).encode())))
        with pytest.raises(ConnectorUnavailable,match='unconfirmed'):await adapter.ensure(uuid4(),'skyking','44600000001')
    result,_=await link(api);link_id=UUID(result['link']['id'])
    async with api['factory'].begin() as db:
        foreign=User(id=uuid4(),display_name='Synthetic unrelated user',is_active=True);db.add(foreign);await db.flush();uid=foreign.id
    async with api['factory']() as db:
        with pytest.raises(Exception,match='v1_parcel_link_actor_member'):
            await db.execute(text('UPDATE v1_order_parcel_links SET actor_id=:actor WHERE id=:link'),{'actor':uid,'link':link_id})
        await db.rollback()
        checks=(await db.execute(text("SELECT conname FROM pg_constraint WHERE conrelid='v1_order_parcel_links'::regclass AND contype='c'"))).scalars().all()
        assert {'v1_parcel_link_state','v1_parcel_link_counters','v1_parcel_link_lease','v1_parcel_link_identity'}<=set(checks)

@pytest.mark.asyncio
async def test_native_session_revoked_during_remote_preview_returns_no_candidate(api,monkeypatch):
    from app.models.identity_auth import UserSession
    ready,release=asyncio.Event(),asyncio.Event();original=BridgeAdapter.resolve
    async def delayed(self,*args):
        result=await original(self,*args);ready.set();await release.wait();return result
    monkeypatch.setattr(BridgeAdapter,'resolve',delayed)
    task=asyncio.create_task(api['client'].post(api['base']+'/preview',headers=api['data']['headers'],json={'scan_id':str(uuid4()),'courier_id':'skyking','awb':'44600000001'}))
    try:
        await asyncio.wait_for(ready.wait(),10)
        async with api['factory'].begin() as db:(await db.scalar(select(UserSession))).revoked_at=datetime.now(timezone.utc)
        release.set();response=await task
        assert response.status_code==401 and 'candidate_token' not in response.text
        assert (await control('/__synthetic/stats'))['shipments']==0
    finally:
        release.set()
        if not task.done():task.cancel()

@pytest.mark.asyncio
@pytest.mark.parametrize('change',['connector_disabled','registry_removed','consent_withdrawn','provider_uncertain','accepted'])
async def test_real_outbox_sender_revalidates_after_template_wait_and_never_retries_unknown(api,monkeypatch,change):
    from app.services import whatsapp_provider as provider
    from app.workers.whatsapp import deliver_one
    result,_=await link(api);link_id=UUID(result['link']['id']);calls=[]
    async with api['factory'].begin() as db:
        row=await db.get(OrderParcelLink,link_id);row.tracking_state='delivered';row.raw_status='Delivered'
        order=await db.get(CommerceOrder,api['oid']);order.whatsapp_updates_opt_in=True
        contact=WhatsAppContact(id=uuid4(),seller_id=api['bid'],phone='919876543210',utility_opt_in=True,last_inbound_at=datetime.now(timezone.utc)-timedelta(days=2));db.add(contact)
        db.add(WhatsAppAccount(seller_id=api['bid'],phone_number_id='synthetic-pni',waba_id='synthetic-waba',access_token='synthetic-not-used',enabled=True))
        await db.flush();message=WhatsAppMessage(seller_id=api['bid'],contact_id=contact.id,phone_number_id='synthetic-pni',idempotency_key=f'parcel:{link_id}:delivered',direction='outbound',kind='template',payload={'name':'synthetic','language':'en','parameters':['Synthetic','MJ-synthetic','Delivered']},status='queued');db.add(message);await db.flush();message_id=message.id
    async def templates(account):
        # This await represents the real template refresh boundary. Revoke a
        # different authoritative record after the sender has read its context.
        if change=='connector_disabled':
            async with api['factory'].begin() as db:(await db.get(ParcelConnector,api['connector_id'])).enabled=False
        elif change=='registry_removed':monkeypatch.setattr(settings,'V1_PARCEL_CONNECTORS_JSON','{}')
        elif change=='consent_withdrawn':
            async with api['factory'].begin() as db:(await db.get(CommerceOrder,api['oid'])).whatsapp_updates_opt_in=False
        return [{'name':'synthetic','language':'en','status':'APPROVED','category':'UTILITY','components':[{'type':'BODY','text':'{{1}} {{2}} {{3}}'}]}]
    async def send(account,contact,message):
        calls.append(message.id)
        if change=='provider_uncertain':raise provider.SendUncertain('Synthetic post-submit timeout')
        return 'synthetic-provider-mid'
    monkeypatch.setattr(provider,'fetch_templates',templates);monkeypatch.setattr(provider,'send',send)
    await deliver_one(message_id,api['factory']);await deliver_one(message_id,api['factory'])
    async with api['factory']() as db:
        message=await db.get(WhatsAppMessage,message_id)
        expected='unknown' if change=='provider_uncertain' else 'accepted' if change=='accepted' else 'failed'
        assert message.status==expected
    assert len(calls)==(1 if change in {'provider_uncertain','accepted'} else 0)


@pytest.mark.asyncio
async def test_registry_disabled_during_remote_enrollment_requires_review_after_response(api,monkeypatch):
    ready,release=asyncio.Event(),asyncio.Event();original=BridgeAdapter.ensure
    async def delayed(self,*args):
        result=await original(self,*args);ready.set();await release.wait();return result
    monkeypatch.setattr(BridgeAdapter,'ensure',delayed)
    preview=await make_preview(api)
    body={'idempotency_key':str(uuid4()),'candidate_token':preview['candidate_token'],'expected_order_fingerprint':preview['order']['fingerprint'],'confirmed':True}
    task=asyncio.create_task(api['client'].post(api['base'],headers=api['data']['headers'],json=body))
    try:
        await asyncio.wait_for(ready.wait(),10);monkeypatch.setattr(settings,'V1_PARCEL_CONNECTORS_JSON','{}');release.set()
        result=await task;assert result.status_code==200,result.text
        assert result.json()['link']['state']=='review_required'
        async with api['factory']() as db:
            row=await db.scalar(select(OrderParcelLink));assert row.error_code=='business_or_connector_changed' and row.remote_id is None and row.lease_token is None
            assert await db.scalar(select(func.count()).select_from(WhatsAppMessage))==0
        assert (await control('/__synthetic/stats'))['shipments']==1
    finally:
        release.set()
        if not task.done():task.cancel()
