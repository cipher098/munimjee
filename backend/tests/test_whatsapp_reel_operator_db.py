"""Frozen20 P01/native0058 acceptance cases — AUTHORED ONLY, NOT RUN remotely.

Requires the integrator's actual app.main/router/model registry and real migrated
0058. No fallback mounts/create_all. Synthetic raw inbound rows and approved SKU
rows are setup, not ingress/parser proof. HTTP uses actual native session/CSRF.
Final-race tests call the actual helper, not an installed worker/provider sender.
"""
from tests.safety import install_test_safety
install_test_safety()

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from app.config import settings
from app.models.catalogue_v1 import CatalogueProductMapping, CatalogueSKU
from app.models.checkout_v1 import CatalogueActivation
from app.models.commerce import Storefront
from app.models.identity import Membership
from app.models.identity_auth import UserSession
from app.models.product import Product
from app.models.whatsapp import WhatsAppAccount, WhatsAppContact, WhatsAppMessage
from app.models.channel_operator import ChannelConnectionState
from app.models.whatsapp_reel_operator import WhatsAppReelCommand as Command, WhatsAppReelAuthorization as Authorization
from app.schemas.whatsapp_reel_operator import LinkCommand
from app.services import whatsapp_reel_operator as service
from app.services.identity import Actor
from tests.whatsapp_self_service_fixture import native_wa_setup  # actual-main native signup fixture

URL = 'https://www.instagram.com/reel/Case_Ab-1/'
EXPECTED = ('Current catalogue: Reviewed cotton kurta.\n'
            '• Size: M — ₹123.45; recorded out of stock.\n'
            'Availability is a current catalogue observation, not a reservation. Please confirm your preferred option with our team.')


@pytest_asyncio.fixture
async def lane(native_wa_setup, monkeypatch):
    j = native_wa_setup
    from app.main import app
    path = '/api/v1/businesses/{business_id}/whatsapp/reel-enquiries/{inbound_id}/link'
    assert any(getattr(r, 'path', None) == path for r in app.routes), 'Integrator must install the real native router; no fallback mount'
    monkeypatch.setattr(settings, 'V1_SKU_FACT_REPLIES_ENABLED', True)
    current = datetime.now(timezone.utc) - timedelta(seconds=3)
    j.pid, j.contact, j.other_contact, j.mid, j.other_mid = (uuid4() for _ in range(5))
    j.phone = '12345'
    context = {'source': 'message_link', 'references': [{'shortcode': 'Case_Ab-1', 'url': URL, 'status': 'unknown', 'products': []}]}
    j.original_payload = {'reel_context': context}
    async with j.sessions.begin() as db:
        db.add_all([WhatsAppAccount(seller_id=j.bid,phone_number_id=j.phone,waba_id='456',access_token='synthetic-fixture-ciphertext-no-provider',enabled=True,automation_enabled=True,reel_replies_enabled=True),
            ChannelConnectionState(business_id=j.bid,channel='whatsapp',version=3,automation_enabled=True),
            WhatsAppContact(id=j.contact,seller_id=j.bid,phone='910000000001',name='Synthetic one',last_inbound_at=current),
            WhatsAppContact(id=j.other_contact,seller_id=j.bid,phone='910000000002',name='Synthetic other',last_inbound_at=current),
            Product(id=j.pid,seller_id=j.bid,name='Reviewed cotton kurta',active=True,listed_price=99999,floor_price=88888,reel_urls=[]),
            Storefront(seller_id=j.bid,slug=uuid4().hex,name='Synthetic approved storefront',published=True)])
        await db.flush()
        db.add(CatalogueProductMapping(business_id=j.bid,product_id=j.pid,state='reviewed',revision=7,legacy_fingerprint='a'*64,issues=[],legacy_variants=[]))
        await db.flush()
        db.add_all([CatalogueActivation(business_id=j.bid,product_id=j.pid,reviewed_revision=7,legacy_fingerprint='a'*64,actor_id=j.uid),
            CatalogueSKU(id=uuid4(),business_id=j.bid,product_id=j.pid,options={'Size':'M'},price_minor=12345,currency='INR',stock_available=0,active=True)])
        for mid,cid in ((j.mid,j.contact),(j.other_mid,j.other_contact)):
            db.add(WhatsAppMessage(id=mid,seller_id=j.bid,contact_id=cid,phone_number_id=j.phone,provider_message_id='synthetic:'+str(mid),idempotency_key='in:'+str(mid),direction='inbound',kind='text',text=URL+' price and sizes?',payload=deepcopy(j.original_payload),status='received',created_at=current))
    j.route = f'/api/v1/businesses/{j.bid}/whatsapp/reel-enquiries/{j.mid}'
    return j


async def review(j):
    response = await j.client.get(j.route)
    assert response.status_code == 200
    value = response.json()
    assert value['business_id'] == str(j.bid) and value['inbound_id'] == str(j.mid)
    return value


def body(j, detail, *, action='link_and_resume', key=None):
    return dict(idempotency_key=str(key or uuid4()),action=action,product_id=str(j.pid),shortcode='Case_Ab-1',
        expected_fingerprint=detail['fingerprint'],expected_connection_version=detail['connection_version'],confirmed=True)


async def post(j, command):
    return await j.client.post(j.route+'/link',json=command,headers=j.csrf)


async def counts(j):
    async with j.sessions() as db:
        values=[]
        for model,column in ((Command,Command.business_id),(Authorization,Authorization.business_id),(WhatsAppMessage,WhatsAppMessage.seller_id)):
            values.append(await db.scalar(select(func.count()).select_from(model).where(column==j.bid)))
        return tuple(values)


async def queued(j):
    command=body(j,await review(j)); response=await post(j,command)
    assert response.status_code==200, response.text
    value=response.json();assert value['result']['resume']=='queued' and value['result']['reason'] is None
    return command,value,UUID(value['result']['outbound_id'])


async def current_binding(db,j):
    row=(await db.execute(select(UserSession).where(UserSession.user_id==j.uid,UserSession.revoked_at.is_(None)).order_by(UserSession.created_at.desc()).execution_options(populate_existing=True))).scalars().first()
    assert row is not None
    return service.ReviewerBinding(j.uid,row.id,row.auth_version)


@pytest.mark.asyncio
async def test_d01_link_only_preserves_original_classification_and_other_contact_history(lane):
    j=lane;response=await post(j,body(j,await review(j),action='link_only'))
    assert response.status_code==200 and response.json()['result']['resume']=='not_requested'
    assert response.json()['result']['reason']=='resume_not_requested'
    async with j.sessions() as db:
        assert (await db.get(Product,j.pid)).reel_urls==[URL]
        for mid in (j.mid,j.other_mid):
            assert (await db.get(WhatsAppMessage,mid)).payload==j.original_payload
        assert await db.scalar(select(func.count()).select_from(Authorization))==0
        assert await db.scalar(select(func.count()).select_from(WhatsAppMessage).where(WhatsAppMessage.direction=='outbound'))==0


@pytest.mark.asyncio
async def test_d02_eligible_once_only_resume_uses_exact_approved_facts_and_canonical_key(lane):
    j=lane;command,value,out=await queued(j)
    replay=await post(j,command);assert replay.status_code==200 and replay.json()['replayed'] is True
    assert replay.json()['command_id']==value['command_id'] and replay.json()['result']['outbound_id']==str(out)
    async with j.sessions() as db:
        message=await db.get(WhatsAppMessage,out)
        assert message.text==EXPECTED and message.idempotency_key=='auto:reel:synthetic:'+str(j.mid)
        assert (await db.get(WhatsAppMessage,j.mid)).payload==j.original_payload
        assert await db.scalar(select(func.count()).select_from(Authorization).where(Authorization.business_id==j.bid))==1
        assert await db.scalar(select(func.count()).select_from(WhatsAppMessage).where(WhatsAppMessage.contact_id==j.other_contact,WhatsAppMessage.direction=='outbound'))==0


@pytest.mark.asyncio
async def test_d03_inferred_source_can_link_but_never_gain_explicit_resume_authority(lane):
    j=lane
    async with j.sessions.begin() as db:
        message=await db.get(WhatsAppMessage,j.mid);value=deepcopy(message.payload);value['reel_context']['source']='recent_message';message.payload=value
    detail=await review(j);assert detail['source']['classification']=='recent_message' and detail['eligibility']['can_resume'] is False
    response=await post(j,body(j,detail));assert response.status_code==200
    assert response.json()['result']['resume']=='held' and response.json()['result']['reason']=='inferred_context'
    assert await counts(j)==(1,0,2)


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['foreign_source','foreign_product','wrong_account','ambiguous'])
async def test_d04_no_cross_scope_or_ambiguous_mutation(lane,change):
    j=lane;detail=await review(j);command=body(j,detail)
    if change in {'foreign_source','foreign_product'}:
        foreign=await j.signup('Independent foreign business')
        async with j.sessions.begin() as db:
            if change=='foreign_source':
                foreign_id=uuid4();cid=uuid4();db.add(WhatsAppContact(id=cid,seller_id=foreign.bid,phone='910000000003'));await db.flush()
                db.add(WhatsAppMessage(id=foreign_id,seller_id=foreign.bid,contact_id=cid,phone_number_id='98765',provider_message_id='foreign',idempotency_key='in:foreign',direction='inbound',kind='text',text=URL,payload=deepcopy(j.original_payload),status='received'))
                j.route=f'/api/v1/businesses/{j.bid}/whatsapp/reel-enquiries/{foreign_id}'
            else:
                foreign_id=uuid4();db.add(Product(id=foreign_id,seller_id=foreign.bid,name='Foreign',active=True,listed_price=1,floor_price=1,reel_urls=[]));command['product_id']=str(foreign_id)
    else:
        async with j.sessions.begin() as db:
            if change=='wrong_account':(await db.get(WhatsAppAccount,j.bid)).phone_number_id='98765'
            else:
                for _ in range(2):db.add(Product(id=uuid4(),seller_id=j.bid,name='Ambiguous',active=True,listed_price=1,floor_price=1,reel_urls=[URL]))
    before=await counts(j);response=await post(j,command)
    assert response.status_code in {404,409}, response.text
    assert await counts(j)==before
    async with j.sessions() as db:assert (await db.get(Product,j.pid)).reel_urls==[]


@pytest.mark.asyncio
async def test_d05_product_nowait_uses_savepoint_and_same_transaction_remains_usable(lane):
    j=lane;command=LinkCommand(**body(j,await review(j)))
    async with j.sessions() as holder,j.sessions() as caller:
        await holder.execute(select(Product).where(Product.id==j.pid).with_for_update())
        async def authority():return await current_binding(caller,j)
        with pytest.raises(HTTPException) as caught:
            await asyncio.wait_for(service.link_enquiry(caller,Actor(j.uid,'v1_user'),j.bid,j.mid,command,request_authority=authority),2)
        assert caught.value.status_code==409 and caught.value.detail['reason']=='catalogue_busy'
        assert await caller.scalar(text('SELECT 1'))==1  # same transaction, no outer rollback first
        assert await caller.scalar(select(func.count()).select_from(Command))==0
        await caller.rollback();await holder.rollback()


@pytest.mark.asyncio
async def test_d06_lost_result_exact_replay_rejects_different_route_and_changed_body(lane):
    j=lane;command,value,out=await queued(j)
    # Same actor/key/exact digest is resolved before lookup of path UUID.
    old_route=j.route;j.route=old_route.rsplit('/',1)[0]+'/'+str(uuid4())
    wrong=await post(j,command);assert wrong.status_code==409  # inbound participates in digest
    j.route=old_route;replay=await post(j,command)
    assert replay.status_code==200 and replay.json()['command_id']==value['command_id'] and replay.json()['replayed'] is True
    conflict=await post(j,{**command,'action':'link_only'});assert conflict.status_code==409 and isinstance(conflict.json()['detail'],str)
    assert await counts(j)==(1,1,3)


@pytest.mark.asyncio
async def test_d07_concurrent_native_operators_cannot_queue_two_replies(lane):
    j=lane;other=await j.signup('Second real native operator')
    async with j.sessions.begin() as db:db.add(Membership(business_id=j.bid,user_id=other.uid,role='manager'))
    detail=await review(j);one,two=body(j,detail),body(j,detail)
    first,second=await asyncio.gather(post(j,one),other.client.post(j.route+'/link',json=two,headers=other.csrf))
    assert sorted([first.status_code,second.status_code])==[200,409]
    assert await counts(j)==(1,1,3)


@pytest.mark.asyncio
@pytest.mark.parametrize('model',[Command,Authorization])
async def test_d08_committed_receipt_and_authorization_are_immutable(lane,model):
    j=lane;_,value,_=await queued(j)
    async with j.sessions() as db:
        identity=UUID(value['command_id'])
        for statement in (update(model).where(model.business_id==j.bid).values(business_id=j.bid),
                          model.__table__.delete().where(model.business_id==j.bid)):
            with pytest.raises(DBAPIError) as caught:
                async with db.begin_nested():await db.execute(statement)
            assert getattr(caught.value.orig,'sqlstate',None)=='23514'
        assert await db.scalar(select(func.count()).select_from(model).where(model.business_id==j.bid))==1


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['null_outbound','wrong_contact'])
async def test_d09_mandatory_authorization_null_and_four_identity_guards_refuse_insert(lane,change):
    j=lane;command,value,out=await queued(j)
    async with j.sessions() as db:
        row=await db.get(Authorization,UUID(value['command_id']))
        values={column.name:getattr(row,column.name) for column in Authorization.__table__.columns}
        values['outbound_message_id']=None if change=='null_outbound' else out
        if change=='wrong_contact':values['contact_id']=j.other_contact
        with pytest.raises(DBAPIError) as caught:
            async with db.begin_nested():await db.execute(insert(Authorization).values(**values))
        assert getattr(caught.value.orig,'sqlstate',None) in {'23502','23514','23503'}  # never accept or rely on duplicate-key23505
        assert await db.scalar(text('SELECT 1'))==1
        assert await db.scalar(select(func.count()).select_from(Authorization))==1


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['sid','role','reconnect','newer_inbound','manual_reply','STOP'])
async def test_d10_actual_final_scalar_refuses_postclaim_authority_or_conversation_change(lane,change):
    j=lane;_,value,out=await queued(j)
    # Retain old ORM account/contact/message deliberately: helper must use scalar SQL.
    async with j.sessions() as retained:
        account=await retained.get(WhatsAppAccount,j.bid);contact=await retained.get(WhatsAppContact,j.contact);message=await retained.get(WhatsAppMessage,out)
        assert await service.revalidate_resume(retained,account,contact,message) is None
        await retained.commit()
        async with j.sessions.begin() as writer:
            if change=='sid':await writer.execute(update(UserSession).where(UserSession.user_id==j.uid).values(revoked_at=func.clock_timestamp()))
            elif change=='role':await writer.execute(update(Membership).where(Membership.business_id==j.bid,Membership.user_id==j.uid).values(role='viewer'))
            elif change=='reconnect':await writer.execute(update(ChannelConnectionState).where(ChannelConnectionState.business_id==j.bid,ChannelConnectionState.channel=='whatsapp').values(version=4))
            elif change in {'newer_inbound','STOP'}:
                writer.add(WhatsAppMessage(id=uuid4(),seller_id=j.bid,contact_id=j.contact,phone_number_id=j.phone,provider_message_id='later:'+uuid4().hex,idempotency_key='in:'+uuid4().hex,direction='inbound',kind='text',text='STOP' if change=='STOP' else 'Different product please',payload={},status='received'))
                if change=='STOP':await writer.execute(update(WhatsAppContact).where(WhatsAppContact.id==j.contact).values(opted_out=True))
            else:writer.add(WhatsAppMessage(id=uuid4(),seller_id=j.bid,contact_id=j.contact,phone_number_id=j.phone,idempotency_key='manual:'+uuid4().hex,direction='outbound',kind='text',text='Manual reviewed reply',payload={},status='queued'))
        with pytest.raises(HTTPException) as caught:await service.revalidate_resume(retained,account,contact,message)
        assert caught.value.status_code==409
        await retained.rollback()
    async with j.sessions() as db:
        assert (await db.get(WhatsAppMessage,out)).provider_message_id is None
        assert await db.scalar(select(func.count()).select_from(Authorization))==1
