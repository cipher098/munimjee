"""Actual app.main/native sessions/signed synthetic ingress; no live proof claim."""
import asyncio
from datetime import timedelta
import hashlib
import hmac
import json
from types import SimpleNamespace
from uuid import UUID, uuid4
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.config import settings
from app.database import get_db
from app.models.customer_links import Customer, CustomerLinkChallenge as Challenge, CustomerLinkProof as Proof, CustomerAssociation as Association, CustomerLinkAudit as Audit
from app.models.identity import Membership
from app.models.identity_auth import UserSession
from app.models.conversation import Conversation
from app.models.seller import Seller
from app.models.whatsapp import WhatsAppAccount, WhatsAppContact, WhatsAppMessage
from app.services import customer_links as service


@pytest_asyncio.fixture
async def linked_native(migrated_engine,monkeypatch):
    from app.main import app
    monkeypatch.setattr(settings,'V1_AUTH_ENABLED',True)
    monkeypatch.setattr(settings,'V1_ENFORCE_LEGACY_ACCESS',True)
    monkeypatch.setattr(settings,'V1_CUSTOMER_LINKS_ENABLED',True)
    monkeypatch.setattr(settings,'PUBLIC_BASE_URL','http://test')
    monkeypatch.setattr(settings,'META_WEBHOOK_SECRET','synthetic-customer-link-signature')
    monkeypatch.setattr(settings,'WHATSAPP_APP_SECRET','synthetic-customer-link-signature')
    sessions=async_sessionmaker(migrated_engine,expire_on_commit=False)
    async def database():
        async with sessions.begin() as db:yield db
    app.dependency_overrides[get_db]=database
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test',headers={'Origin':'http://test'}) as client:
            response=await client.post('/api/v1/auth/signup',json={'email':f'{uuid4()}@example.com','password':'synthetic-customer-link-password','business_name':'Synthetic Customer Boutique'})
            assert response.status_code==201,response.text
            me=response.json();bid,uid=UUID(me['businesses'][0]['id']),UUID(me['user_id']);conversation,contact=uuid4(),uuid4()
            ig_account=str(uuid4().int)[:15];wa_account=str(uuid4().int)[:15];waba=str(uuid4().int)[:15]
            async with sessions.begin() as db:
                await db.execute(update(Seller).where(Seller.id==bid).values(instagram_id=ig_account,instagram_page_id=ig_account,instagram_token='synthetic-not-provider-credential'))
                db.add_all([Conversation(id=conversation,seller_id=bid,customer_instagram_id='12345678901',customer_name='Synthetic Customer',messages=[{'role':'customer','content':'Earlier synthetic message'}]),
                    WhatsAppAccount(seller_id=bid,phone_number_id=wa_account,waba_id=waba,access_token='synthetic-encrypted-only',enabled=False),
                    WhatsAppContact(id=contact,seller_id=bid,phone='919876543210',name='Synthetic Customer')])
            yield SimpleNamespace(client=client,sessions=sessions,bid=bid,uid=uid,conversation=conversation,contact=contact,
                ig_account=ig_account,wa_account=wa_account,waba=waba,base=f'/api/v1/businesses/{bid}/customer-links',headers={'X-CSRF-Token':client.cookies['v1_csrf']})
    finally:app.dependency_overrides.pop(get_db,None)


def create_body(j):return {'idempotency_key':str(uuid4()),'conversation_id':str(j.conversation),'contact_id':str(j.contact),'scope_confirmed':True}
async def post(j,path,body):return await j.client.post(path,json=body,headers=j.headers)


async def begin(j):
    body=create_body(j);response=await post(j,j.base,body)
    assert response.status_code==201,response.text
    assert response.headers['cache-control']=='no-store'
    row=response.json();assert row['command_id']==body['idempotency_key']
    return row,body


async def signed(j,channel,command,*,mid=None,subject=None,account=None,timestamp=None,echo=False,bad_signature=False):
    mid=mid or uuid4().hex
    if channel=='instagram':
        payload={'object':'instagram','entry':[{'id':j.ig_account,'messaging':[{'sender':{'id':subject or '12345678901'},'recipient':{'id':account or j.ig_account},'timestamp':timestamp if timestamp is not None else int(service.now().timestamp()*1000),'message':{'mid':mid,'text':command,'is_echo':echo}}]}]}
    else:
        payload={'object':'whatsapp_business_account','entry':[{'id':j.waba,'changes':[{'field':'messages','value':{'metadata':{'phone_number_id':account or j.wa_account},'messages':[{'id':mid,'from':subject or '919876543210','timestamp':str(timestamp if timestamp is not None else int(service.now().timestamp())),'type':'text','text':{'body':command}}]}}]}]}
    raw=json.dumps(payload).encode();signature='sha256='+hmac.new(b'wrong' if bad_signature else b'synthetic-customer-link-signature',raw,hashlib.sha256).hexdigest()
    return await j.client.post('/webhooks/'+channel,content=raw,headers={'Content-Type':'application/json','X-Hub-Signature-256':signature})


async def prove(j,row):
    for channel in ['instagram','whatsapp']:
        response=await signed(j,channel,row['consent_command']);assert response.status_code==200,response.text
    latest=await j.client.get(j.base+'/'+row['id']);assert latest.status_code==200,latest.text
    return latest.json()


async def finalize(j,row):
    row=await prove(j,row);body={'idempotency_key':str(uuid4()),'expected_fingerprint':row['fingerprint'],'confirmed':True}
    response=await post(j,j.base+'/'+row['id']+'/finalize',body);assert response.status_code==200,response.text
    return response.json(),body


@pytest.mark.asyncio
async def test_real_signed_proof_finalize_exact_replay_unlink_and_no_transcript_secret(linked_native,monkeypatch):
    j=linked_native;row,start=await begin(j)
    assert (await post(j,j.base,start)).json()==row
    assert 'consent_command' not in (await j.client.get(j.base+'/'+row['id'])).json()
    result,body=await finalize(j,row)
    monkeypatch.setattr(service,'now',lambda:future) if (future:=service.now()+timedelta(minutes=20)) else None
    assert (await post(j,j.base+'/'+row['id']+'/finalize',body)).json()==result
    detail=(await j.client.get(j.base+'/'+row['id'])).json()
    unlink={'idempotency_key':str(uuid4()),'expected_fingerprint':detail['association_fingerprint'],'confirmed':True,'reason':'Synthetic customer requested separation'}
    separated=await post(j,j.base+'/customers/'+result['customer_id']+'/unlink',unlink);assert separated.status_code==200,separated.text
    assert (await post(j,j.base+'/customers/'+result['customer_id']+'/unlink',unlink)).json()==separated.json()
    async with j.sessions() as db:
        assert (await db.get(Conversation,j.conversation)).messages==[{'role':'customer','content':'Earlier synthetic message'}]
        assert await db.scalar(select(func.count()).select_from(WhatsAppMessage))==0
        assert await db.scalar(select(func.count()).select_from(Proof))==2
        for audit in (await db.scalars(select(Audit))).all():assert row['consent_command'].split()[1] not in json.dumps(audit.result)
        assert await service.verified_customer_id(db,j.bid,'instagram',j.ig_account,'12345678901') is None


@pytest.mark.asyncio
@pytest.mark.parametrize('bad',['signature','echo','wrong_sender','wrong_account','old','future','disabled','invalid'])
async def test_authenticated_webhook_negative_never_automates_or_proves(linked_native,monkeypatch,bad):
    j=linked_native;row,_=await begin(j);options={};command=row['consent_command']
    if bad=='signature':options['bad_signature']=True
    if bad=='echo':options['echo']=True
    if bad=='wrong_sender':options['subject']='11111111111'
    if bad=='wrong_account':options['account']='22222222222'
    if bad=='old':options['timestamp']=int((service.now()-timedelta(minutes=1)).timestamp()*1000)
    if bad=='future':options['timestamp']=int((service.now()+timedelta(minutes=2)).timestamp()*1000)
    if bad=='disabled':monkeypatch.setattr(settings,'V1_CUSTOMER_LINKS_ENABLED',False)
    if bad=='invalid':command+=' invalid'
    response=await signed(j,'instagram',command,**options);assert response.status_code==(403 if bad=='signature' else 200),response.text
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Proof))==0
        assert (await db.get(Conversation,j.conversation)).messages==[{'role':'customer','content':'Earlier synthetic message'}]
        from app.models.instagram_ingress import InstagramIngress
        assert await db.scalar(select(func.count()).select_from(InstagramIngress))==0


@pytest.mark.asyncio
async def test_cookie_csrf_no_assertion_cross_tenant_current_role_and_pagination(linked_native):
    j=linked_native;body=create_body(j)
    assert (await j.client.post(j.base,json=body)).status_code==403
    assert (await post(j,j.base,{**body,'verified':True})).status_code==422
    assert (await post(j,j.base,{**body,'contact_id':str(uuid4())})).status_code==404
    assert (await j.client.get(j.base.replace(str(j.bid),str(uuid4())))).status_code==404
    async with j.sessions.begin() as db:await db.execute(update(Membership).where(Membership.business_id==j.bid,Membership.user_id==j.uid).values(role='staff'))
    assert (await j.client.get(j.base)).status_code==200
    assert (await post(j,j.base,body)).status_code==403
    assert (await j.client.get(j.base+'/sources?channel=whatsapp&page=2&page_size=1')).json()['items']==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation',['create','finalize','cancel','unlink'])
async def test_session_revoked_after_staged_real_audit_rolls_back(linked_native,monkeypatch,operation):
    j=linked_native;row=None;result=None
    if operation!='create':row,_=await begin(j)
    if operation=='finalize':row=await prove(j,row)
    if operation=='unlink':result,_=await finalize(j,row);row=(await j.client.get(j.base+'/'+row['id'])).json()
    real=service.record
    async def revoke_after_audit(*args,**kwargs):
        value=await real(*args,**kwargs)
        async with j.sessions.begin() as other:await other.execute(update(UserSession).where(UserSession.user_id==j.uid).values(revoked_at=func.clock_timestamp()))
        return value
    monkeypatch.setattr(service,'record',revoke_after_audit)
    if operation=='create':path,body=j.base,create_body(j)
    elif operation=='unlink':path,body=j.base+'/customers/'+result['customer_id']+'/unlink',{'idempotency_key':str(uuid4()),'expected_fingerprint':row['association_fingerprint'],'confirmed':True,'reason':'Synthetic requested separation'}
    else:path,body=j.base+'/'+row['id']+'/'+operation,{'idempotency_key':str(uuid4()),'expected_fingerprint':row['fingerprint'],'confirmed':True}
    response=await post(j,path,body);assert response.status_code==401,response.text
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Audit).where(Audit.idempotency_key==UUID(body['idempotency_key'])))==0
        if operation=='create':assert await db.scalar(select(func.count()).select_from(Challenge))==0
        if operation=='finalize':assert await db.scalar(select(func.count()).select_from(Customer))==0
        if operation=='cancel':assert (await db.get(Challenge,UUID(row['id']))).state=='pending'
        if operation=='unlink':assert await db.scalar(select(func.count()).select_from(Association).where(Association.revoked_at.is_(None)))==2


@pytest.mark.asyncio
async def test_session_revoked_while_waiting_for_challenge_lock_cannot_finalize(linked_native):
    j=linked_native;row,_=await begin(j);row=await prove(j,row)
    body={'idempotency_key':str(uuid4()),'expected_fingerprint':row['fingerprint'],'confirmed':True}
    async with j.sessions() as blocker:
        await blocker.begin();await blocker.scalar(select(Challenge).where(Challenge.id==UUID(row['id'])).with_for_update())
        task=asyncio.create_task(post(j,j.base+'/'+row['id']+'/finalize',body))
        await asyncio.sleep(.1);assert not task.done()
        async with j.sessions.begin() as other:await other.execute(update(UserSession).where(UserSession.user_id==j.uid).values(revoked_at=func.clock_timestamp()))
        await blocker.commit()
        response=await asyncio.wait_for(task,5);assert response.status_code==401,response.text
    async with j.sessions() as db:assert await db.scalar(select(func.count()).select_from(Customer))==0
