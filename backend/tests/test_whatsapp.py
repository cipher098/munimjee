"""Real tenant/transaction tests with stubbed Meta transport; never sends live messages."""
import os
import json
import hmac
import hashlib
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import UUID,uuid4
from types import SimpleNamespace
import pytest
import pytest_asyncio
import httpx
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from sqlalchemy.pool import NullPool
import app.models
from app.database import Base,get_db
from app.config import settings
from app.models.seller import Seller
from app.models.whatsapp import WhatsAppAccount,WhatsAppContact,WhatsAppMessage,WhatsAppTemplate
from app.api.routes.whatsapp import router
from app.api.webhooks.whatsapp import router as webhook
from app.api.dashboard_auth import _make_token
from app.services.channel_credentials import encrypt,decrypt
from app.services import whatsapp as service,whatsapp_provider as provider
from app.workers.whatsapp import deliver_one,drain


@pytest_asyncio.fixture
async def wa(monkeypatch):
    url=os.environ.get('TEST_DATABASE_URL','')
    if not url.rsplit('/',1)[-1].endswith(('whatsapp_test','commerce_test')):
        pytest.skip('Use isolated TEST_DATABASE_URL ending whatsapp_test or commerce_test')
    monkeypatch.setattr(settings,'CHANNEL_ENCRYPTION_KEY',Fernet.generate_key().decode())
    monkeypatch.setattr(settings,'WHATSAPP_APP_SECRET','test-app-secret')
    monkeypatch.setattr(settings,'WHATSAPP_WEBHOOK_VERIFY_TOKEN','verify-secret')
    engine=create_async_engine(url,poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory=async_sessionmaker(engine,expire_on_commit=False)
    @asynccontextmanager
    async def session():
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    async with session() as db:
        sellers=[Seller(email=f'wa{i}@test.example',password_hash='unused',business_name=f'Store {i}') for i in range(2)]
        db.add_all(sellers);await db.flush()
        accounts=[WhatsAppAccount(seller_id=s.id,phone_number_id=str(100+i),waba_id=str(200+i),access_token=encrypt('token-secret-long'),enabled=True) for i,s in enumerate(sellers)]
        contacts=[WhatsAppContact(seller_id=s.id,phone=f'91987654321{i}',name='Buyer',last_inbound_at=service.now()) for i,s in enumerate(sellers)]
        db.add_all(accounts+contacts);await db.flush()
        ids={'sellers':[s.id for s in sellers],'contacts':[c.id for c in contacts]}
    app=FastAPI();app.include_router(router);app.include_router(webhook)
    async def dependency():
        async with session() as db:
            yield db
    app.dependency_overrides[get_db]=dependency
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        client.cookies.set('dashboard_session',_make_token('seller',str(ids['sellers'][0]),'test'))
        yield SimpleNamespace(client=client,session=session,ids=ids)
    await engine.dispose()


def incoming(mid='wamid.in1',text='Hello',*,ago=0,phone='919876543210'):
    return {'object':'whatsapp_business_account','entry':[{'id':'200','changes':[{'field':'messages','value':{'metadata':{'phone_number_id':'100'},'messages':[{'id':mid,'from':phone,'timestamp':str(int((service.now()-timedelta(hours=ago)).timestamp())),'type':'text','text':{'body':text}}]}}]}]}


async def posthook(wa,payload,signature=None):
    raw=json.dumps(payload).encode()
    sig=signature if signature is not None else 'sha256='+hmac.new(b'test-app-secret',raw,hashlib.sha256).hexdigest()
    return await wa.client.post('/webhooks/whatsapp',content=raw,headers={'x-hub-signature-256':sig})


async def queue(wa,text='Hello',key=None):
    return await wa.client.post(f"/whatsapp/contacts/{wa.ids['contacts'][0]}/reply",json={'text':text,'idempotency_key':key or str(uuid4())})


@pytest.mark.asyncio
async def test_signatures_and_dotted_verification_fail_closed(wa,monkeypatch):
    assert (await posthook(wa,incoming(),signature='forged')).status_code==403
    r=await wa.client.get('/webhooks/whatsapp',params={'hub.mode':'subscribe','hub.verify_token':'verify-secret','hub.challenge':'123'})
    assert r.status_code==200 and r.text=='123'
    monkeypatch.setattr(settings,'WHATSAPP_APP_SECRET','')
    assert (await posthook(wa,incoming())).status_code==503
    async with wa.session() as db:
        assert await db.scalar(select(func.count()).select_from(WhatsAppMessage))==0


@pytest.mark.asyncio
async def test_connection_verified_encrypted_disabled_and_token_retained(wa,monkeypatch):
    calls=[]
    async def verify(token,waba,phone):
        calls.append((token,waba,phone));return {'id':phone,'display_phone_number':'+91 9876543210'}
    monkeypatch.setattr(provider,'verify_connection',verify)
    data={'phone_number_id':'100','waba_id':'200','access_token':'new-secret-access-token'}
    r=await wa.client.put('/whatsapp/account',json=data)
    assert r.status_code==200 and not r.json()['enabled'] and 'access_token' not in r.text
    async with wa.session() as db:
        account=await db.get(WhatsAppAccount,wa.ids['sellers'][0]);assert account.access_token!=data['access_token'];assert decrypt(account.access_token)==data['access_token']
    del data['access_token']
    assert (await wa.client.put('/whatsapp/account',json=data)).status_code==200
    assert len(calls)==2
    data['waba_id']='201'
    assert (await wa.client.put('/whatsapp/account',json=data)).status_code==422


@pytest.mark.asyncio
async def test_provider_membership_checks_all_pages(monkeypatch):
    calls=[]
    async def graph(token,method,path,**kw):
        calls.append(kw['params'])
        if len(calls)==1:return {'data':[{'id':'other'}],'paging':{'next':'https://untrusted.invalid','cursors':{'after':'nextcursor'}}}
        return {'data':[{'id':'100','display_phone_number':'123'}]}
    monkeypatch.setattr(provider,'graph',graph)
    assert (await provider.verify_connection('secret','200','100'))['id']=='100'
    assert calls[1]['after']=='nextcursor'
    from fastapi import HTTPException
    with pytest.raises(HTTPException):await provider.verify_connection('secret','200','missing')


@pytest.mark.asyncio
async def test_inbound_dedupe_delayed_window_and_exact_keyword(wa):
    async with wa.session() as db:
        a=await db.get(WhatsAppAccount,wa.ids['sellers'][0]);a.automation_enabled=True;a.rules=[{'keyword':'price','reply':'See our prices'}]
    for _ in range(2):assert (await posthook(wa,incoming(text='PRICE'))).status_code==200
    await posthook(wa,incoming('old','price',ago=25,phone='919888888888'))
    await posthook(wa,incoming('not-exact','what price'))
    async with wa.session() as db:
        rows=(await db.scalars(select(WhatsAppMessage))).all()
        assert len(rows)==4
        assert sum(m.direction=='outbound' for m in rows)==1
        c=await db.scalar(select(WhatsAppContact).where(WhatsAppContact.phone=='919888888888'))
        assert not service.window_open(c)


@pytest.mark.asyncio
async def test_tenant_boundaries_and_anonymous_access(wa):
    foreign=wa.ids['contacts'][1]
    assert (await wa.client.get(f'/whatsapp/contacts/{foreign}/messages')).status_code==404
    assert (await wa.client.post(f'/whatsapp/contacts/{foreign}/reply',json={'text':'x','idempotency_key':str(uuid4())})).status_code==404
    assert (await wa.client.patch(f'/whatsapp/contacts/{foreign}/consent',json={'utility_opt_in':True,'marketing_opt_in':False,'source':'explicit form'})).status_code==404
    wa.client.cookies.clear()
    assert (await wa.client.get('/whatsapp/account')).status_code in {302,303,401,403,307}


@pytest.mark.asyncio
async def test_manual_replies_idempotent_and_window_enforced(wa):
    key=str(uuid4());a=await queue(wa,key=key);b=await queue(wa,key=key)
    assert a.status_code==b.status_code==202 and a.json()['id']==b.json()['id']
    assert (await queue(wa,text='different',key=key)).status_code==409
    async with wa.session() as db:
        c=await db.get(WhatsAppContact,wa.ids['contacts'][0]);c.last_inbound_at=service.now()-timedelta(hours=25)
    assert (await queue(wa)).status_code==409


@pytest.mark.asyncio
async def test_stop_blocks_queued_and_checkout_cannot_override(wa,monkeypatch):
    r=await queue(wa);mid=UUID(r.json()['id'])
    await posthook(wa,incoming(text='STOP'))
    async with wa.session() as db:
        await service.record_checkout_opt_in(db,wa.ids['sellers'][0],'9876543210',True)
        c=await db.get(WhatsAppContact,wa.ids['contacts'][0]);assert c.opted_out and not c.utility_opt_in
    async def fail_send(*args):raise AssertionError('Must not send')
    monkeypatch.setattr(provider,'send',fail_send)
    await deliver_one(mid,wa.session)
    async with wa.session() as db:
        assert (await db.get(WhatsAppMessage,mid)).status=='failed'
    assert (await queue(wa)).status_code==409
    await posthook(wa,incoming('start1','START'))
    assert (await queue(wa)).status_code==202
    async with wa.session() as db:
        c=await db.get(WhatsAppContact,wa.ids['contacts'][0]);assert not c.utility_opt_in and not c.marketing_opt_in


@pytest.mark.asyncio
async def test_template_consent_approval_and_live_recheck(wa,monkeypatch):
    rows=[{'name':'order_update','language':'en','status':'APPROVED','category':'UTILITY','components':[{'type':'BODY','text':'Hello {{1}} order {{2}} {{3}}'}]}]
    async def fetch(*args):return rows
    monkeypatch.setattr(provider,'fetch_templates',fetch)
    assert (await wa.client.post('/whatsapp/templates/sync')).status_code==200
    url=f"/whatsapp/contacts/{wa.ids['contacts'][0]}/template"
    data={'name':'order_update','language':'en','parameters':['Buyer','123','INR 500'],'idempotency_key':str(uuid4())}
    assert (await wa.client.post(url,json=data)).status_code==409
    async with wa.session() as db:
        c=await db.get(WhatsAppContact,wa.ids['contacts'][0]);c.last_inbound_at=service.now()-timedelta(days=3)
        service.record_consent(c,True,False,'explicit checkout')
    r=await wa.client.post(url,json=data);assert r.status_code==202
    rows[0]['status']='PAUSED'
    async def fail_send(*args):raise AssertionError('Paused template cannot send')
    monkeypatch.setattr(provider,'send',fail_send)
    await deliver_one(UUID(r.json()['id']),wa.session)
    async with wa.session() as db:assert (await db.get(WhatsAppMessage,UUID(r.json()['id']))).status=='failed'


@pytest.mark.asyncio
async def test_unknown_send_never_retried_and_callback_can_resolve(wa,monkeypatch):
    calls=[]
    async def uncertain(*args):calls.append(1);raise provider.SendUncertain('timeout')
    monkeypatch.setattr(provider,'send',uncertain)
    r=await queue(wa);mid=UUID(r.json()['id']);await deliver_one(mid,wa.session);await drain(wa.session)
    async with wa.session() as db:assert (await db.get(WhatsAppMessage,mid)).status=='unknown'
    assert len(calls)==1
    body=incoming();value=body['entry'][0]['changes'][0]['value'];value.pop('messages');value['statuses']=[{'id':'wamid.out','recipient_id':'919876543210','status':'read','biz_opaque_callback_data':str(mid)}]
    assert (await posthook(wa,body)).status_code==200
    value['statuses'][0]['status']='sent';await posthook(wa,body)
    value['statuses'][0]['status']='failed';await posthook(wa,body)
    async with wa.session() as db:assert (await db.get(WhatsAppMessage,mid)).status=='read'


@pytest.mark.asyncio
async def test_delivery_claim_concurrency_and_success(wa,monkeypatch):
    import asyncio
    calls=[]
    async def send(*args):calls.append(1);await asyncio.sleep(.05);return 'wamid.sent'
    monkeypatch.setattr(provider,'send',send)
    r=await queue(wa);mid=UUID(r.json()['id'])
    await asyncio.gather(deliver_one(mid,wa.session),deliver_one(mid,wa.session))
    assert len(calls)==1
    async with wa.session() as db:assert (await db.get(WhatsAppMessage,mid)).status=='accepted'


@pytest.mark.asyncio
async def test_order_notifications_only_explicit_consent_utility_and_idempotent(wa):
    async with wa.session() as db:
        a=await db.get(WhatsAppAccount,wa.ids['sellers'][0]);a.order_templates={'placed':{'name':'order','language':'en'}}
        db.add(WhatsAppTemplate(seller_id=a.seller_id,name='order',language='en',status='APPROVED',category='UTILITY',components=[{'type':'BODY','text':'{{1}} {{2}} {{3}}'}]));await db.flush()
        order=SimpleNamespace(id=uuid4(),seller_id=a.seller_id,customer={'name':'Buyer','phone':'9876543210'},total=10000,currency='INR',whatsapp_updates_opt_in=False)
        assert await service.queue_order_update(db,order,'placed')=='skipped'
        order.whatsapp_updates_opt_in=True
        assert await service.queue_order_update(db,order,'placed')=='skipped'
        await service.record_checkout_opt_in(db,a.seller_id,'9876543210',True)
        assert await service.order_updates_available(db,a.seller_id)
        assert await service.queue_order_update(db,order,'placed')=='queued'
        assert await service.queue_order_update(db,order,'placed')=='queued'
        assert await db.scalar(select(func.count()).select_from(WhatsAppMessage))==1


@pytest.mark.asyncio
async def test_stale_keyword_never_uses_another_recent_message_window(wa):
    async with wa.session() as db:
        a=await db.get(WhatsAppAccount,wa.ids['sellers'][0]);a.automation_enabled=True;a.rules=[{'keyword':'price','reply':'Prices'}]
    await posthook(wa,incoming('delayed','price',ago=25))
    async with wa.session() as db:
        assert await db.scalar(select(func.count()).select_from(WhatsAppMessage).where(WhatsAppMessage.direction=='outbound'))==0


@pytest.mark.asyncio
async def test_disable_automation_cancels_queued_reply(wa,monkeypatch):
    async with wa.session() as db:
        a=await db.get(WhatsAppAccount,wa.ids['sellers'][0]);a.automation_enabled=True;a.rules=[{'keyword':'price','reply':'Prices'}]
    await posthook(wa,incoming(text='price'))
    async with wa.session() as db:
        a=await db.get(WhatsAppAccount,wa.ids['sellers'][0]);a.automation_enabled=False
        mid=await db.scalar(select(WhatsAppMessage.id).where(WhatsAppMessage.direction=='outbound'))
    async def forbidden(*args):raise AssertionError('Disabled automation must not send')
    monkeypatch.setattr(provider,'send',forbidden)
    await deliver_one(mid,wa.session)
    async with wa.session() as db:assert (await db.get(WhatsAppMessage,mid)).status=='failed'


@pytest.mark.asyncio
async def test_unicode_verification_token_rejected(wa):
    r=await wa.client.get('/webhooks/whatsapp',params={'hub.mode':'subscribe','hub.verify_token':'☃','hub.challenge':'1'})
    assert r.status_code==403


@pytest.mark.asyncio
async def test_number_cannot_be_claimed_by_other_seller(wa,monkeypatch):
    async def verify(token,waba,phone):return {'id':phone}
    monkeypatch.setattr(provider,'verify_connection',verify)
    wa.client.cookies.set('dashboard_session',_make_token('seller',str(wa.ids['sellers'][1]),'test'))
    r=await wa.client.put('/whatsapp/account',json={'phone_number_id':'100','waba_id':'200','access_token':'token-long-enough'})
    assert r.status_code==409


@pytest.mark.asyncio
async def test_disconnect_prevents_reenable_without_credentials(wa):
    assert (await wa.client.delete('/whatsapp/account')).status_code==200
    assert not (await wa.client.get('/whatsapp/account')).json()['configured']
    assert (await wa.client.patch('/whatsapp/account',json={'enabled':True})).status_code==409


@pytest.mark.asyncio
async def test_expired_window_at_worker_and_crash_recovery(wa,monkeypatch):
    r=await queue(wa);mid=UUID(r.json()['id'])
    async with wa.session() as db:
        c=await db.get(WhatsAppContact,wa.ids['contacts'][0]);c.last_inbound_at=service.now()-timedelta(hours=25)
    async def forbidden(*args):raise AssertionError('Expired window must not send')
    monkeypatch.setattr(provider,'send',forbidden)
    await deliver_one(mid,wa.session)
    async with wa.session() as db:
        m=await db.get(WhatsAppMessage,mid);assert m.status=='failed';m.status='sending';m.updated_at=service.now()-timedelta(minutes=20)
    await drain(wa.session)
    async with wa.session() as db:assert (await db.get(WhatsAppMessage,mid)).status=='unknown'


@pytest.mark.asyncio
async def test_order_template_recategorized_cannot_send_marketing(wa,monkeypatch):
    async with wa.session() as db:
        a=await db.get(WhatsAppAccount,wa.ids['sellers'][0]);a.order_templates={'placed':{'name':'order','language':'en'}}
        db.add(WhatsAppTemplate(seller_id=a.seller_id,name='order',language='en',status='APPROVED',category='UTILITY',components=[{'type':'BODY','text':'{{1}} {{2}} {{3}}'}]));await db.flush()
        c=await db.get(WhatsAppContact,wa.ids['contacts'][0]);service.record_consent(c,True,True,'explicit form')
        order=SimpleNamespace(id=uuid4(),seller_id=a.seller_id,customer={'name':'Buyer','phone':'9876543210'},total=10000,currency='INR',whatsapp_updates_opt_in=True)
        await service.queue_order_update(db,order,'placed')
        mid=await db.scalar(select(WhatsAppMessage.id))
    async def fetch(*args):return [{'name':'order','language':'en','status':'APPROVED','category':'MARKETING','components':[{'type':'BODY','text':'{{1}} {{2}} {{3}}'}]}]
    async def forbidden(*args):raise AssertionError('Order utility permission must not become marketing')
    monkeypatch.setattr(provider,'fetch_templates',fetch);monkeypatch.setattr(provider,'send',forbidden)
    await deliver_one(mid,wa.session)
    async with wa.session() as db:assert (await db.get(WhatsAppMessage,mid)).status=='failed'


@pytest.mark.asyncio
async def test_transport_timeout_is_unknown_not_retry(monkeypatch):
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def request(self,*args,**kwargs):raise httpx.ReadTimeout('secret provider detail')
    monkeypatch.setattr(provider.httpx,'AsyncClient',Client)
    with pytest.raises(provider.SendUncertain):await provider.graph('secret','POST','100/messages',data={})
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as err:await provider.graph('secret','GET','200/phone_numbers')
    assert err.value.status_code==502 and 'secret' not in str(err.value.detail)


@pytest.mark.asyncio
async def test_stop_same_second_as_checkout_consent_is_honored(wa):
    async with wa.session() as db:
        await service.record_checkout_opt_in(db,wa.ids['sellers'][0],'9876543210',True)
    await posthook(wa,incoming('stop-after-checkout','STOP'))
    async with wa.session() as db:
        contact=await db.get(WhatsAppContact,wa.ids['contacts'][0]);assert contact.opted_out and not contact.utility_opt_in


@pytest.mark.asyncio
async def test_create_template_scoped_pending_duplicate_and_send_guard(wa, monkeypatch):
    calls=[]
    async def graph(token,method,path,*,data=None,params=None):
        calls.append((method,path,data))
        assert token=='token-secret-long'
        return {'id':'meta-template-1','status':'PENDING','category':'UTILITY'}
    monkeypatch.setattr(provider,'graph',graph)
    payload={'name':'order_confirmation','language':'en','category':'UTILITY',
             'body':'Hi {{1}}, your order {{2}} is confirmed.', 'examples':['Ananya','DEMO-1042'], 'footer':'Reply STOP to opt out'}
    response=await wa.client.post('/whatsapp/templates',json=payload)
    assert response.status_code==201,response.text
    assert response.json()['status']=='PENDING'
    assert calls==[('POST','200/message_templates',{'name':'order_confirmation','language':'en','category':'UTILITY','components':[
        {'type':'BODY','text':payload['body'],'example':{'body_text':[['Ananya','DEMO-1042']]}},
        {'type':'FOOTER','text':'Reply STOP to opt out'}]})]
    duplicate=await wa.client.post('/whatsapp/templates',json=payload)
    assert duplicate.status_code==409 and len(calls)==1
    pending_send=await wa.client.post(f"/whatsapp/contacts/{wa.ids['contacts'][0]}/template",json={
        'name':payload['name'],'language':'en','parameters':payload['examples'],'idempotency_key':str(uuid4())})
    assert pending_send.status_code==409
    wa.client.cookies.set('dashboard_session',_make_token('seller',str(wa.ids['sellers'][1]),'other'))
    assert (await wa.client.get('/whatsapp/templates')).json()['items']==[]
    assert (await wa.client.post('/whatsapp/templates',json=payload)).status_code==201
    assert calls[-1][1]=='201/message_templates'


@pytest.mark.asyncio
async def test_template_create_validation_and_disconnected_account(wa,monkeypatch):
    async def forbidden(*args,**kwargs):
        raise AssertionError('Validation failure must not call Meta')
    monkeypatch.setattr(provider,'graph',forbidden)
    valid={'name':'order_confirmation','language':'en','category':'UTILITY','body':'Your order is confirmed.'}
    invalid=[{'name':'Upper Case'},{'category':'AUTHENTICATION'},{'body':' '},{'body':'x'*1025},
             {'body':'Hi {{2}}','examples':['A']},{'body':'Hi {{1}}','examples':[]},
             {'body':'Hi {{name}}'},{'footer':'{{1}}'},{'examples':['extra']},
             {'body':'Hi {{1}}','examples':[' ']}]
    for override in invalid:
        r=await wa.client.post('/whatsapp/templates',json={**valid,**override})
        assert r.status_code==422,(override,r.text)
    async with wa.session() as db:
        account=await db.get(WhatsAppAccount,wa.ids['sellers'][0]);account.access_token=''
    assert (await wa.client.post('/whatsapp/templates',json=valid)).status_code==409


@pytest.mark.asyncio
async def test_template_uncertain_creation_does_not_claim_success_or_retry(wa,monkeypatch):
    calls=[]
    async def graph(*args,**kwargs):
        calls.append(1)
        raise provider.SendUncertain('timeout')
    monkeypatch.setattr(provider,'graph',graph)
    payload={'name':'service_update','language':'en','category':'UTILITY','body':'Your request has been received.'}
    r=await wa.client.post('/whatsapp/templates',json=payload)
    assert r.status_code==504 and 'Sync templates' in r.json()['detail'] and len(calls)==1
    assert (await wa.client.get('/whatsapp/templates')).json()['items']==[]
    async def incomplete(*args,**kwargs): return {'id':'meta-1'}
    monkeypatch.setattr(provider,'graph',incomplete)
    assert (await wa.client.post('/whatsapp/templates',json=payload)).status_code==504


@pytest.mark.asyncio
async def test_template_create_preserves_meta_category_and_requires_auth(wa,monkeypatch):
    async def graph(*args,**kwargs): return {'id':'meta-2','status':'PENDING','category':'MARKETING'}
    monkeypatch.setattr(provider,'graph',graph)
    payload={'name':'review_message','language':'en','category':'UTILITY','body':'A message for review.'}
    r=await wa.client.post('/whatsapp/templates',json=payload)
    assert r.status_code==201 and r.json()['category']=='MARKETING'
    wa.client.cookies.clear()
    assert (await wa.client.post('/whatsapp/templates',json=payload)).status_code==302
