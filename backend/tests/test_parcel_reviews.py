"""Real migrated PG16 + existing Worker/HMAC/SQLite; synthetic local transport only."""
import asyncio
from datetime import datetime,timezone,timedelta
from uuid import UUID,uuid4
import pytest
from sqlalchemy import select,func,text
from app.models.parcel_tracking import OrderParcelLink,ParcelAudit,ParcelObservation,ParcelNotification,ParcelConnector
from app.models.commerce import CommerceOrder
from app.models.identity import Membership
from app.models.identity_auth import UserSession
from app.services import parcel_reviews as reviews,parcel_tracking as tracking
from tests.test_parcel_tracking import api,link,control,BridgeAdapter

@pytest.fixture(autouse=True)
def review_transport(monkeypatch):monkeypatch.setattr(reviews,'ParcelAdapter',BridgeAdapter)

async def facts(api,link_id):
    data=(await api['client'].get(api['base'])).json()
    row=next(value for value in data['links'] if value['id']==str(link_id))
    return {'expected_link_fingerprint':row['fingerprint'],'expected_order_fingerprint':data['order']['fingerprint']}

async def preview(api,link_id,replacement=False,awb='44600000002'):
    body={**await facts(api,link_id),'scan_id':str(uuid4())}
    if replacement:body.update(courier_id='skyking',awb=awb)
    response=await api['client'].post(api['base']+'/'+str(link_id)+('/replacement-preview' if replacement else '/review-preview'),headers=api['data']['headers'],json=body)
    assert response.status_code==200,response.text
    return response.json(),{key:body[key] for key in ('expected_link_fingerprint','expected_order_fingerprint')}

async def command_body(api,link_id,action='resume_tracking',replacement=False,awb='44600000002'):
    if action=='close_link':context=await facts(api,link_id);candidate=None
    else:
        candidate,context=await preview(api,link_id,replacement,awb)
    body={**context,'idempotency_key':str(uuid4()),'reason':'status_conflict','confirmed':True,'remote_effects_acknowledged':True}
    if candidate:body['candidate_token']=candidate['candidate_token']
    if not replacement:body['action']=action
    return body

async def post(api,lid,body,replacement=False):
    return await api['client'].post(api['base']+'/'+str(lid)+('/replace' if replacement else '/review'),headers=api['data']['headers'],json=body)

async def terminal_conflict(api):
    result,_=await link(api);lid=UUID(result['link']['id'])
    async with api['factory']() as db:remote=str((await db.get(OrderParcelLink,lid)).remote_id)
    for status in ['Delivered','In transit']:
        stamp=datetime.now(timezone.utc).isoformat()
        await control('/__synthetic/status',{'remote_id':remote,'status':status,'checked_at':stamp,'events':[{'time':stamp,'description':status,'location':'Synthetic hub'}]})
        async with api['factory']() as db:await tracking.process_link(db,lid)
    assert (await api['client'].get(api['base'])).json()['links'][0]['state']=='review_required'
    return lid

@pytest.mark.asyncio
async def test_review_resume_preserves_history_no_order_change_no_notification_and_replays(api):
    lid=await terminal_conflict(api);body=await command_body(api,lid)
    first=await post(api,lid,body);assert first.status_code==200,first.text
    assert first.json()['link']['state']=='linked' and first.json()['link']['tracking_state']=='in_transit'
    replay=await post(api,lid,body);assert replay.status_code==200 and replay.json()['replayed']
    async with api['factory']() as db:
        assert await db.scalar(select(func.count()).select_from(ParcelObservation))==2
        assert await db.scalar(select(func.count()).select_from(ParcelAudit).where(ParcelAudit.action=='seller_resumed_tracking'))==1
        order=await db.get(CommerceOrder,api['oid']);assert order.fulfillment_status=='pending' and order.payment_status=='pending' and order.tracking_number is None
        from app.models.whatsapp import WhatsAppMessage
        assert await db.scalar(select(func.count()).select_from(WhatsAppMessage))==0
    history=await api['client'].get(api['base']+'/'+str(lid)+'/reviews?page_size=1');assert history.status_code==200 and history.json()['total']==2
    assert set(history.json()['items'][0])=={'id','action','reason','source_link_id','result_link_id','created_at'}
    changed={**body,'reason':'label_mismatch'};assert (await post(api,lid,changed)).status_code==409

@pytest.mark.asyncio
async def test_close_then_explicit_replace_preserves_old_rows_and_blocks_plain_relink(api):
    result,normal=await link(api);lid=UUID(result['link']['id'])
    close=await command_body(api,lid,'close_link');assert (await post(api,lid,close)).status_code==200
    # An ordinary retry of the original accepted intent remains an exact receipt.
    assert (await api['client'].post(api['base'],headers=api['data']['headers'],json=normal)).json()['replayed']
    from tests.test_parcel_tracking import make_preview
    fresh=await make_preview(api,'44600000002');new={**normal,'idempotency_key':str(uuid4()),'candidate_token':fresh['candidate_token']}
    assert (await api['client'].post(api['base'],headers=api['data']['headers'],json=new)).status_code==409
    body=await command_body(api,lid,replacement=True);response=await post(api,lid,body,True);assert response.status_code==200,response.text
    new_id=UUID(response.json()['link']['id']);assert new_id!=lid
    assert (await post(api,lid,body,True)).json()['replayed']
    async with api['factory']() as db:
        assert (await db.get(OrderParcelLink,lid)).state=='unlinked'
        assert (await db.get(OrderParcelLink,new_id)).state=='linked'
        assert await db.scalar(select(func.count()).select_from(OrderParcelLink))==2
    assert (await control('/__synthetic/stats'))['shipments']==2
    events=(await api['client'].get(api['base']+'/'+str(lid)+'/reviews')).json()['items'];assert any(e['result_link_id']==str(new_id) for e in events)

@pytest.mark.asyncio
@pytest.mark.parametrize('replacement',[False,True])
async def test_close_or_replace_invalidates_inflight_enrollment_lease(api,monkeypatch,replacement):
    from tests.test_parcel_tracking import make_preview
    candidate=await make_preview(api)
    original=BridgeAdapter.ensure;ready,release=asyncio.Event(),asyncio.Event()
    async def held(self,*args):
        result=await original(self,*args)
        if args[2]=='44600000001':ready.set();await release.wait()
        return result
    monkeypatch.setattr(BridgeAdapter,'ensure',held)
    body={'idempotency_key':str(uuid4()),'candidate_token':candidate['candidate_token'],'expected_order_fingerprint':candidate['order']['fingerprint'],'confirmed':True}
    task=asyncio.create_task(api['client'].post(api['base'],headers=api['data']['headers'],json=body))
    try:
        await asyncio.wait_for(ready.wait(),10)
        lid=UUID((await api['client'].get(api['base'])).json()['links'][0]['id'])
        reviewed=await command_body(api,lid,replacement=replacement,action='resume_tracking' if replacement else 'close_link')
        response=await post(api,lid,reviewed,replacement);assert response.status_code==200,response.text
        release.set();late=await task;assert late.status_code==200 and late.json()['link']['state']=='unlinked'
        async with api['factory']() as db:
            old=await db.get(OrderParcelLink,lid);assert old.state=='unlinked' and old.lease_token is None and old.remote_id is None
            assert await db.scalar(select(func.count()).select_from(OrderParcelLink).where(OrderParcelLink.state!='unlinked'))==(1 if replacement else 0)
        assert (await control('/__synthetic/stats'))['shipments']==(2 if replacement else 1)
    finally:
        release.set()
        if not task.done():task.cancel()

@pytest.mark.asyncio
async def test_concurrent_replacements_accept_only_one_and_stale_lease_fingerprint_denies(api):
    result,_=await link(api);lid=UUID(result['link']['id'])
    a=await command_body(api,lid,replacement=True);b=await command_body(api,lid,replacement=True,awb='44600000003')
    first,second=await asyncio.gather(post(api,lid,a,True),post(api,lid,b,True))
    assert sorted([first.status_code,second.status_code])==[200,409]
    assert (await control('/__synthetic/stats'))['shipments']==2
    current=(first if first.status_code==200 else second).json()['link']['id'];body=await command_body(api,current,'close_link')
    async with api['factory'].begin() as db:
        row=await db.get(OrderParcelLink,UUID(current));row.lease_token=uuid4();row.lease_until=datetime.now(timezone.utc)+timedelta(seconds=60)
    denied=await post(api,current,body);assert denied.status_code==409 and denied.json()['detail']['code']=='parcel_review_context_changed'

@pytest.mark.asyncio
@pytest.mark.parametrize('change',['sid','role','order','connector'])
async def test_review_wait_rechecks_native_authority_and_current_facts(api,change):
    result,_=await link(api);lid=UUID(result['link']['id']);body=await command_body(api,lid,'close_link')
    holder=api['factory']();await holder.begin();await holder.scalar(select(CommerceOrder).where(CommerceOrder.id==api['oid']).with_for_update())
    task=asyncio.create_task(post(api,lid,body))
    try:
        async with api['factory']() as db:
            for _ in range(200):
                await db.execute(text('SELECT pg_stat_clear_snapshot()'))
                waits=await db.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'"))
                if waits:break
                await asyncio.sleep(.01)
            assert waits
        if change=='order':
            order=await holder.get(CommerceOrder,api['oid']);order.fulfillment_status='confirmed'
        else:
            async with api['factory'].begin() as db:
                if change=='sid':(await db.scalar(select(UserSession))).revoked_at=datetime.now(timezone.utc)
                elif change=='role':(await db.scalar(select(Membership))).role='viewer'
                else:(await db.get(ParcelConnector,api['connector_id'])).enabled=False
        await holder.commit();response=await task
        # Closing is local-only and remains available with a disabled connector.
        assert response.status_code==({'sid':401,'role':403,'order':409,'connector':200}[change]),response.text
        async with api['factory']() as db:assert (await db.get(OrderParcelLink,lid)).state==('unlinked' if change=='connector' else 'linked')
    finally:
        await holder.close()
        if not task.done():task.cancel()

@pytest.mark.asyncio
async def test_resume_preview_session_revoked_during_remote_read_no_candidate(api,monkeypatch):
    result,_=await link(api);lid=UUID(result['link']['id']);original=BridgeAdapter.read
    async def revoke(self,*args,**kw):
        response=await original(self,*args,**kw)
        async with api['factory'].begin() as db:(await db.scalar(select(UserSession))).revoked_at=datetime.now(timezone.utc)
        return response
    monkeypatch.setattr(BridgeAdapter,'read',revoke)
    response=await api['client'].post(api['base']+'/'+str(lid)+'/review-preview',headers=api['data']['headers'],json={**await facts(api,lid),'scan_id':str(uuid4())})
    assert response.status_code==401 and 'candidate_token' not in response.text

@pytest.mark.asyncio
async def test_same_parcel_unknown_unowned_and_not_found_cannot_be_ensured_by_resume(api,monkeypatch):
    result,_=await link(api);lid=UUID(result['link']['id']);context=await facts(api,lid)
    same=await api['client'].post(api['base']+'/'+str(lid)+'/replacement-preview',headers=api['data']['headers'],json={**context,'scan_id':str(uuid4()),'courier_id':'skyking','awb':'44600000001'})
    assert same.status_code==409
    async with api['factory'].begin() as db:
        row=await db.get(OrderParcelLink,lid);row.state='enrollment_unknown';row.remote_id=None
    for state in ['not_found','manual_review']:
        async def resolve(self,*args):return {'state':state}
        monkeypatch.setattr(BridgeAdapter,'resolve',resolve)
        response=await api['client'].post(api['base']+'/'+str(lid)+'/review-preview',headers=api['data']['headers'],json={**await facts(api,lid),'scan_id':str(uuid4())})
        assert response.status_code==409
    assert (await control('/__synthetic/stats'))['shipments']==1

@pytest.mark.asyncio
async def test_receipt_precedes_expired_candidate_without_remote_retry(api,monkeypatch):
    lid=await terminal_conflict(api);body=await command_body(api,lid)
    assert (await post(api,lid,body)).status_code==200
    from jose import JWTError
    original_decode=reviews.jwt.decode
    def expired(token,*args,**kwargs):
        if token==body['candidate_token']:raise JWTError('synthetic expiry')
        return original_decode(token,*args,**kwargs)
    async def forbidden(*args,**kwargs):raise AssertionError('Accepted replay must not contact the tracker')
    monkeypatch.setattr(reviews.jwt,'decode',expired);monkeypatch.setattr(BridgeAdapter,'read',forbidden);monkeypatch.setattr(BridgeAdapter,'ensure',forbidden)
    replay=await post(api,lid,body);assert replay.status_code==200 and replay.json()['replayed']

@pytest.mark.asyncio
@pytest.mark.parametrize('change',['sid','role','config','status','order'])
async def test_authority_and_snapshot_rechecked_after_review_http(api,monkeypatch,change):
    lid=await terminal_conflict(api);body=await command_body(api,lid);original=BridgeAdapter.read
    async def mutate(self,*args,**kw):
        response=await original(self,*args,**kw)
        if change=='status':response['shipment']['status']='Out for delivery'
        else:
            async with api['factory'].begin() as db:
                if change=='sid':(await db.scalar(select(UserSession))).revoked_at=datetime.now(timezone.utc)
                elif change=='role':(await db.scalar(select(Membership))).role='viewer'
                elif change=='config':(await db.get(ParcelConnector,api['connector_id'])).enabled=False
                else:(await db.get(CommerceOrder,api['oid'])).fulfillment_status='confirmed'
        return response
    monkeypatch.setattr(BridgeAdapter,'read',mutate)
    response=await post(api,lid,body)
    assert response.status_code=={'sid':401,'role':403,'config':409,'status':409,'order':409}[change],response.text
    async with api['factory']() as db:
        assert (await db.get(OrderParcelLink,lid)).state=='review_required'
        assert await db.scalar(select(func.count()).select_from(ParcelAudit).where(ParcelAudit.action=='seller_resumed_tracking'))==0

async def messaging(api):
    from app.models.whatsapp import WhatsAppAccount,WhatsAppContact,WhatsAppTemplate
    async with api['factory'].begin() as db:
        (await db.get(CommerceOrder,api['oid'])).whatsapp_updates_opt_in=True
        db.add(WhatsAppAccount(seller_id=api['bid'],phone_number_id='synthetic-pni',waba_id='synthetic-waba',access_token='synthetic-unused',enabled=True,order_templates={f'parcel_{key}':{'name':'synthetic','language':'en'} for key in ['in_transit','out_for_delivery','delivered']}))
        db.add(WhatsAppContact(id=uuid4(),seller_id=api['bid'],phone='919876543210',utility_opt_in=True,last_inbound_at=datetime.now(timezone.utc)-timedelta(days=2)))
        db.add(WhatsAppTemplate(seller_id=api['bid'],name='synthetic',language='en',status='APPROVED',category='UTILITY',components=[{'type':'BODY','text':'{{1}} {{2}} {{3}}'}]))

@pytest.mark.asyncio
async def test_old_queued_update_stays_blocked_after_resume_replacement_baseline_silent_future_queues_once(api,monkeypatch):
    from app.models.whatsapp import WhatsAppMessage
    from app.services import whatsapp_provider as provider
    from app.workers.whatsapp import deliver_one
    await messaging(api);lid=await terminal_conflict(api)
    async with api['factory']() as db:
        messages=(await db.scalars(select(WhatsAppMessage))).all();assert len(messages)==1
        message_id=messages[0].id;remote=str((await db.get(OrderParcelLink,lid)).remote_id)
    from app.models.whatsapp import WhatsAppContact
    async with api['factory']() as db:
        message=await db.get(WhatsAppMessage,message_id);contact=await db.scalar(select(WhatsAppContact))
        with pytest.raises(Exception,match='paused'):await tracking.revalidate_notification(db,message,contact)
    await control('/__synthetic/status',{'remote_id':remote,'status':'Delivered','checked_at':datetime.now(timezone.utc).isoformat(),'events':[]})
    body=await command_body(api,lid);assert (await post(api,lid,body)).status_code==200
    calls=[]
    async def templates(account):return [{'name':'synthetic','language':'en','status':'APPROVED','category':'UTILITY','components':[{'type':'BODY','text':'{{1}} {{2}} {{3}}'}]}]
    async def send(*args):calls.append(True);return 'synthetic-not-expected'
    monkeypatch.setattr(provider,'fetch_templates',templates);monkeypatch.setattr(provider,'send',send)
    await deliver_one(message_id,api['factory']);await deliver_one(message_id,api['factory']);assert calls==[]
    async with api['factory']() as db:
        assert (await db.get(WhatsAppMessage,message_id)).status=='failed'
        assert await db.scalar(select(func.count()).select_from(WhatsAppMessage))==1
    replacement=await command_body(api,lid,replacement=True);original=BridgeAdapter.ensure
    async def enrolled(self,*args):
        value=await original(self,*args)
        await control('/__synthetic/status',{'remote_id':value['shipment']['id'],'status':'In transit','checked_at':datetime.now(timezone.utc).isoformat(),'events':[]})
        return await self.read(UUID(value['shipment']['id']))
    monkeypatch.setattr(BridgeAdapter,'ensure',enrolled)
    response=await post(api,lid,replacement,True);assert response.status_code==200,response.text
    new_id=UUID(response.json()['link']['id'])
    async with api['factory']() as db:
        row=await db.get(OrderParcelLink,new_id);remote=str(row.remote_id)
        note=await db.scalar(select(ParcelNotification).where(ParcelNotification.link_id==new_id));assert note.decision=='skipped' and note.reason=='reviewed_without_notification'
        assert await db.scalar(select(func.count()).select_from(WhatsAppMessage))==1
    await control('/__synthetic/status',{'remote_id':remote,'status':'Out for delivery','checked_at':datetime.now(timezone.utc).isoformat(),'events':[]})
    for _ in range(2):
        async with api['factory']() as db:await tracking.process_link(db,new_id)
    async with api['factory']() as db:
        assert await db.scalar(select(func.count()).select_from(WhatsAppMessage))==2
        assert await db.scalar(select(func.count()).select_from(ParcelNotification).where(ParcelNotification.link_id==new_id,ParcelNotification.milestone=='out_for_delivery'))==1
    assert calls==[]

@pytest.mark.asyncio
async def test_review_csrf_foreign_scope_confirmation_and_append_only_audit(api):
    result,_=await link(api);lid=UUID(result['link']['id']);body=await command_body(api,lid,'close_link');path=api['base']+'/'+str(lid)+'/review'
    assert (await api['client'].post(path,json=body)).status_code==403
    assert (await api['client'].post(path.replace(str(api['bid']),str(uuid4())),headers=api['data']['headers'],json=body)).status_code==404
    assert (await post(api,lid,{**body,'remote_effects_acknowledged':False})).status_code==422
    assert (await post(api,lid,body)).status_code==200
    from sqlalchemy.exc import DBAPIError
    async with api['factory']() as db:
        with pytest.raises(DBAPIError):await db.execute(text("UPDATE v1_parcel_audits SET action='modified'"))
        await db.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize('action',['close_link','resume_tracking','replace'])
async def test_session_revoked_after_staged_review_rolls_back_before_commit(api,monkeypatch,action):
    lid=await terminal_conflict(api);body=await command_body(api,lid,action if action!='replace' else 'resume_tracking',replacement=action=='replace')
    original=reviews.audit
    async def staged_then_revoke(*args,**kwargs):
        await original(*args,**kwargs)
        async with api['factory'].begin() as db:(await db.scalar(select(UserSession))).revoked_at=datetime.now(timezone.utc)
    monkeypatch.setattr(reviews,'audit',staged_then_revoke)
    response=await post(api,lid,body,action=='replace');assert response.status_code==401,response.text
    async with api['factory']() as db:
        source=await db.get(OrderParcelLink,lid);assert source.state=='review_required' and source.tracking_state=='delivered'
        assert await db.scalar(select(func.count()).select_from(OrderParcelLink))==1
        assert await db.scalar(select(func.count()).select_from(ParcelAudit).where(ParcelAudit.action.in_(list(reviews.ACTIONS.values()))))==0
        assert await db.scalar(select(func.count()).select_from(ParcelNotification).where(ParcelNotification.reason=='reviewed_without_notification'))==0
    assert (await control('/__synthetic/stats'))['shipments']==1
