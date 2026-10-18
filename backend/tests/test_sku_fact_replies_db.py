"""Real0052/P01 fresh public projections and no catalogue lock across send."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
import pytest
import pytest_asyncio
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.config import settings
from app.models.catalogue_v1 import CatalogueProductMapping, CatalogueSKU
from app.models.checkout_v1 import CatalogueActivation, SKUReservation
from app.models.commerce import CommerceOrder, Storefront
from app.models.conversation_product import ConversationProduct
from app.models.identity import Business, User
from app.models.product import Product
from app.models.seller import Seller
from app.services import sku_fact_replies as service
from app.models.conversation import Conversation
from app.models.instagram_ingress import InstagramIngress
from app.models.whatsapp import WhatsAppAccount, WhatsAppContact, WhatsAppMessage


@pytest_asyncio.fixture
async def sku_lane(migrated_engine, monkeypatch):
    monkeypatch.setattr(settings,"V1_SKU_FACT_REPLIES_ENABLED",True)
    sessions=async_sessionmaker(migrated_engine,expire_on_commit=False)
    bid,uid,pid,sku=(uuid4() for _ in range(4))
    async with sessions.begin() as db:
        db.add(Seller(id=bid,email=f'{uuid4()}@example.com',password_hash='synthetic',is_active=True))
        await db.flush()
        db.add_all([Business(id=bid,name='Synthetic catalogue',is_active=True),User(id=uid,is_active=True),
            Storefront(seller_id=bid,slug=uuid4().hex,name='Synthetic',published=True),
            Product(id=pid,seller_id=bid,name='Synthetic dress',listed_price=999999,floor_price=888888,
                description='PRIVATE legacy description',stock_quantity=99,active=True,reel_urls=['https://www.instagram.com/reel/Exact_code/'])])
        await db.flush()
        db.add(CatalogueProductMapping(business_id=bid,product_id=pid,state='reviewed',revision=2,
            legacy_fingerprint='a'*64,issues=[],legacy_variants=[]))
        await db.flush()
        db.add_all([CatalogueActivation(business_id=bid,product_id=pid,reviewed_revision=1,legacy_fingerprint='a'*64,actor_id=uid),
            CatalogueSKU(id=sku,business_id=bid,product_id=pid,options={'Size':'M'},price_minor=12345,currency='INR',stock_available=None,active=True)])
    return SimpleNamespace(sessions=sessions,bid=bid,uid=uid,pid=pid,sku=sku)


@pytest.mark.asyncio
async def test_fresh_scalar_bypasses_retained_orm_without_flushing_dirty_fields(sku_lane):
    j=sku_lane
    async with j.sessions() as db:
        held=await db.get(CatalogueSKU,j.sku);seller=await db.get(Seller,j.bid)
        seller.business_name='unflushed local change'
        first=await service.read_facts(db,j.bid,j.pid)
        async with j.sessions.begin() as writer:
            await writer.execute(update(CatalogueSKU).where(CatalogueSKU.id==j.sku).values(price_minor=23456,stock_available=0))
            await writer.execute(update(CatalogueProductMapping).where(CatalogueProductMapping.business_id==j.bid).values(revision=3))
        second=await service.read_facts(db,j.bid,j.pid)
        assert second.skus[0].price_minor==23456 and second.skus[0].stock_available==0
        assert held.price_minor==12345 and seller.business_name=='unflushed local change' and seller in db.dirty
        assert first.fact_hash!=second.fact_hash and second.mapping_revision==3
        assert '9999.99' not in service.render(second) and 'PRIVATE' not in service.render(second)
        for model in (CommerceOrder,SKUReservation,ConversationProduct):
            assert await db.scalar(select(func.count()).select_from(model))==0
        await db.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['foreign','business','seller','publication','product','mapping','sku','disabled'])
async def test_missing_current_public_authority_fails_closed(sku_lane,monkeypatch,change):
    j=sku_lane
    async with j.sessions.begin() as db:
        if change=='business':(await db.get(Business,j.bid)).is_active=False
        elif change=='seller':(await db.get(Seller,j.bid)).is_active=False
        elif change=='publication':(await db.get(Storefront,j.bid)).published=False
        elif change=='product':(await db.get(Product,j.pid)).active=False
        elif change=='mapping':(await db.get(CatalogueProductMapping,(j.bid,j.pid))).state='needs_review'
        elif change=='sku':(await db.get(CatalogueSKU,j.sku)).active=False
        elif change=='disabled':monkeypatch.setattr(settings,'V1_SKU_FACT_REPLIES_ENABLED',False)
    async with j.sessions() as db:
        assert await service.read_facts(db,uuid4() if change=='foreign' else j.bid,j.pid) is None


@pytest.mark.asyncio
async def test_reader_does_not_block_concurrent_stock_writer_or_observe_uncommitted_stock(sku_lane):
    j=sku_lane
    async with j.sessions() as writer, j.sessions() as reader:
        await writer.execute(select(CatalogueSKU.id).where(CatalogueSKU.id==j.sku).with_for_update())
        await writer.execute(update(CatalogueSKU).where(CatalogueSKU.id==j.sku).values(stock_available=7))
        before=await asyncio.wait_for(service.read_facts(reader,j.bid,j.pid),1)
        assert before.skus[0].stock_available is None
        await writer.commit()
        after=await asyncio.wait_for(service.read_facts(reader,j.bid,j.pid),1)
        assert after.skus[0].stock_available==7
        # Reader transaction stays open, yet all public writer rows remain lockable.
        await asyncio.wait_for(writer.execute(select(Storefront.seller_id).where(Storefront.seller_id==j.bid).with_for_update(nowait=True)),1)
        await asyncio.wait_for(writer.execute(select(Product.id).where(Product.id==j.pid).with_for_update(nowait=True)),1)
        await asyncio.wait_for(writer.execute(select(CatalogueSKU.id).where(CatalogueSKU.id==j.sku).with_for_update(nowait=True)),1)


@pytest.mark.asyncio
async def test_exact_reel_resolves_all_matches_never_title_or_substring_guess(sku_lane):
    j=sku_lane
    async with j.sessions() as db:
        assert await service.exact_reel_products(db,j.bid,reel_url='https://instagram.com/p/Exact_code/?x=1')==(j.pid,)
        assert await service.exact_reel_products(db,j.bid,reel_url='https://evil.example/reel/Exact_code/')==()
        assert await service.exact_reel_products(db,j.bid,reel_url='https://instagram.com/reel/Exact_cod/')==()
        assert await service.exact_reel_products(db,uuid4(),reel_url='https://instagram.com/reel/Exact_code/')==()
    pid2=uuid4()
    async with j.sessions.begin() as db:
        db.add(Product(id=pid2,seller_id=j.bid,name='Other',listed_price=1,floor_price=1,active=True,reel_urls=['https://instagram.com/p/Exact_code/']))
    async with j.sessions() as db:
        assert set(await service.exact_reel_products(db,j.bid,reel_url='https://instagram.com/reel/Exact_code/'))=={j.pid,pid2}


async def instagram_turn(j, *, status='processing'):
    cid,rid=uuid4(),uuid4()
    current=datetime.now(timezone.utc)
    async with j.sessions.begin() as db:
        seller=await db.get(Seller,j.bid)
        seller.instagram_page_id=seller.fb_page_id='synthetic-ig-account'
        seller.instagram_token='synthetic-not-real-token'
        db.add_all([Conversation(id=cid,seller_id=j.bid,customer_instagram_id='synthetic-customer',
            customer_name='Synthetic',product_id=j.pid,messages=[]),
            InstagramIngress(id=rid,seller_id=j.bid,account_id='synthetic-ig-account',customer_id='synthetic-customer',
                event_key=uuid4().hex,provider_message_id=uuid4().hex,events=[{'type':'text','text':'price?','mid':uuid4().hex}],
                processed_indices=[],status=status,occurred_at=current,available_at=current)])
    return cid,rid


@pytest.mark.asyncio
async def test_ig_focused_reply_uses_single_writer_no_llm_cycle_or_commerce_mutation(sku_lane,monkeypatch):
    from app.bot.conversation import advance_conversation
    j=sku_lane;cid,_=await instagram_turn(j);sent=[]
    async def send(client,recipient,text):
        sent.append((recipient,text))
        # Provider await does not stall catalogue writers, even with the outer
        # conversation transaction still open.
        async with j.sessions.begin() as writer:
            await writer.execute(select(CatalogueSKU.id).where(CatalogueSKU.id==j.sku).with_for_update(nowait=True))
            await writer.execute(select(Product.id).where(Product.id==j.pid).with_for_update(nowait=True))
        return {'message_id':'synthetic-outbound'}
    monkeypatch.setattr('app.integrations.instagram.InstagramClient.send_message',send)
    async with j.sessions.begin() as db:
        conversation=await db.get(Conversation,cid);seller=await db.get(Seller,j.bid)
        await advance_conversation(conversation,seller,'price?',db,customer_mid='unique-source')
    assert len(sent)==1 and '₹123.45' in sent[0][1] and 'untracked' in sent[0][1]
    async with j.sessions() as db:
        messages=(await db.get(Conversation,cid)).messages
        assert len(messages)==2 and messages[-1]['mid']=='synthetic-outbound'
        assert len(messages[-1]['catalogue_fact_hash'])==64
        for model in (ConversationProduct,CommerceOrder,SKUReservation):
            assert await db.scalar(select(func.count()).select_from(model))==0


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['window','takeover','publication','pause','payment','manual','quarantine','account'])
async def test_ig_delayed_current_gate_change_withholds_before_provider(sku_lane,monkeypatch,change):
    from app.bot.conversation import advance_conversation
    from app.services.channel_readiness import CatalogueAuthorityHandoff
    from app.models.channel_operator import ChannelConnectionState
    from app.models.commerce_safeguards import PaymentReview
    from app.models.manual_action import ManualAction
    j=sku_lane;cid,rid=await instagram_turn(j)
    initial=service.is_activated
    async def delayed(*args,**kwargs):
        result=await initial(*args,**kwargs)
        async with j.sessions.begin() as writer:
            if change=='window':await writer.execute(update(InstagramIngress).where(InstagramIngress.id==rid).values(occurred_at=datetime.now(timezone.utc)-timedelta(days=2)))
            elif change=='takeover':await writer.execute(update(Conversation).where(Conversation.id==cid).values(last_seller_manual_reply_at=datetime.now(timezone.utc)))
            elif change=='publication':await writer.execute(update(Storefront).where(Storefront.seller_id==j.bid).values(published=False))
            elif change=='pause':writer.add(ChannelConnectionState(business_id=j.bid,channel='instagram',automation_enabled=False))
            elif change=='payment':writer.add(PaymentReview(seller_id=j.bid,conversation_id=cid,screenshot_url='synthetic',status='pending'))
            elif change=='manual':writer.add(ManualAction(seller_id=j.bid,conversation_id=cid,kind='other',status='open'))
            elif change=='quarantine':writer.add(InstagramIngress(seller_id=j.bid,account_id='synthetic-ig-account',customer_id='synthetic-customer',event_key=uuid4().hex,events=[],status='error',error_code='processing_failed_unknown_effect',available_at=datetime.now(timezone.utc)))
            elif change=='account':await writer.execute(update(Seller).where(Seller.id==j.bid).values(instagram_token='changed-synthetic-token'))
        return result
    monkeypatch.setattr(service,'is_activated',delayed)
    async def forbidden(*args,**kwargs):pytest.fail('Current gate must withhold before provider')
    monkeypatch.setattr('app.integrations.instagram.InstagramClient.send_message',forbidden)
    with pytest.raises(CatalogueAuthorityHandoff):
        async with j.sessions.begin() as db:
            await advance_conversation(await db.get(Conversation,cid),await db.get(Seller,j.bid),'price?',db)


async def whatsapp_intent(j):
    contact,mid=uuid4(),uuid4()
    context={'source':'message_link','references':[{'url':'https://www.instagram.com/reel/Exact_code/',
        'shortcode':'Exact_code','status':'matched','products':[{'id':str(j.pid),'name':'stale cached name'}]}]}
    async with j.sessions.begin() as db:
        db.add(WhatsAppAccount(seller_id=j.bid,phone_number_id='synthetic-wa',waba_id='synthetic-waba',
            access_token='synthetic-never-decrypted',enabled=True,automation_enabled=True,reel_replies_enabled=True))
        db.add(WhatsAppContact(id=contact,seller_id=j.bid,phone='919876543210',last_inbound_at=datetime.now(timezone.utc),opted_out=False))
        await db.flush()
        db.add(WhatsAppMessage(id=mid,seller_id=j.bid,contact_id=contact,phone_number_id='synthetic-wa',
            idempotency_key='auto:reel:synthetic-source',direction='outbound',kind='text',text='STALE PRIVATE must never send',
            payload={'reel_context':context,'customer_text':'price?'},status='queued'))
    return contact,mid


def session_factory(j):
    @asynccontextmanager
    async def factory():
        async with j.sessions.begin() as db:yield db
    return factory


@pytest.mark.asyncio
async def test_wa_delivery_regenerates_actual_current_facts_once_and_keeps_unknown_effect(sku_lane,monkeypatch):
    from app.workers.whatsapp import deliver_one
    from app.services.whatsapp_provider import SendUncertain
    j=sku_lane;_,mid=await whatsapp_intent(j);sent=[]
    async with j.sessions.begin() as db:
        await db.execute(update(CatalogueSKU).where(CatalogueSKU.id==j.sku).values(price_minor=34567,stock_available=0))
    async def send(account,contact,message):
        sent.append(message.text)
        async with j.sessions.begin() as writer:
            await writer.execute(select(Product.id).where(Product.id==j.pid).with_for_update(nowait=True))
            await writer.execute(select(CatalogueSKU.id).where(CatalogueSKU.id==j.sku).with_for_update(nowait=True))
        raise SendUncertain('Synthetic provider timeout')
    monkeypatch.setattr('app.services.whatsapp_provider.send',send)
    await deliver_one(mid,session_factory(j));await deliver_one(mid,session_factory(j))
    assert len(sent)==1 and '₹345.67' in sent[0] and 'recorded out of stock' in sent[0] and 'STALE' not in sent[0]
    async with j.sessions() as db:
        assert (await db.get(WhatsAppMessage,mid)).status=='unknown'
        assert await db.scalar(select(func.count()).select_from(CommerceOrder))==0


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['window','optout','automation','reels','publication','business','mapping','inferred'])
async def test_wa_pending_intent_cannot_bypass_current_gates(sku_lane,monkeypatch,change):
    from app.workers.whatsapp import deliver_one
    j=sku_lane;contact,mid=await whatsapp_intent(j)
    async with j.sessions.begin() as db:
        if change=='window':(await db.get(WhatsAppContact,contact)).last_inbound_at=datetime.now(timezone.utc)-timedelta(days=2)
        elif change=='optout':(await db.get(WhatsAppContact,contact)).opted_out=True
        elif change=='automation':(await db.get(WhatsAppAccount,j.bid)).automation_enabled=False
        elif change=='reels':(await db.get(WhatsAppAccount,j.bid)).reel_replies_enabled=False
        elif change=='publication':(await db.get(Storefront,j.bid)).published=False
        elif change=='business':(await db.get(Business,j.bid)).is_active=False
        elif change=='mapping':(await db.get(Product,j.pid)).reel_urls=[]
        elif change=='inferred':
            message=await db.get(WhatsAppMessage,mid)
            message.payload={**message.payload,'reel_context':{**message.payload['reel_context'],'source':'recent_message'}}
    async def forbidden(*args,**kwargs):pytest.fail('Current gate must withhold before provider')
    monkeypatch.setattr('app.services.whatsapp_provider.send',forbidden)
    await deliver_one(mid,session_factory(j))
    async with j.sessions() as db:assert (await db.get(WhatsAppMessage,mid)).status=='failed'


@pytest.mark.asyncio
async def test_final_reel_projection_rejects_new_ambiguity_after_initial_resolver(sku_lane):
    j=sku_lane;reference=dict(reel_url='https://instagram.com/reel/Exact_code/')
    async with j.sessions() as reader:
        assert await service.exact_reel_products(reader,j.bid,**reference)==(j.pid,)
        async with j.sessions.begin() as writer:
            writer.add(Product(seller_id=j.bid,name='Second mapped product',listed_price=1,floor_price=1,
                active=True,reel_urls=['https://instagram.com/p/Exact_code/']))
        assert await service.read_facts(reader,j.bid,j.pid,reel=reference) is None


@pytest.mark.asyncio
async def test_option_capacity_is_complete_or_handoff_never_partial(sku_lane):
    j=sku_lane
    async with j.sessions.begin() as db:
        for i in range(12):db.add(CatalogueSKU(business_id=j.bid,product_id=j.pid,options={'Size':str(i)},
            price_minor=100+i,currency='INR',stock_available=i,active=True))
    async with j.sessions() as db:assert await service.read_facts(db,j.bid,j.pid) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['focus','reply_to','reel','reel_text','disabled','uncertain'])
async def test_real_durable_ig_thread_context_mid_and_uncertain_send_policy(sku_lane,monkeypatch,kind):
    from app.workers import instagram_ingress as worker
    j=sku_lane;cid,rid=await instagram_turn(j,status='pending');sent=[]
    monkeypatch.setattr(worker,'worker_session',session_factory(j))
    if kind=='disabled':monkeypatch.setattr(settings,'V1_SKU_FACT_REPLIES_ENABLED',False)
    async with j.sessions.begin() as db:
        row=await db.get(InstagramIngress,rid)
        if kind=='reply_to':
            conversation=await db.get(Conversation,cid);conversation.product_id=None
            conversation.messages=[{'role':'bot','content':'obsolete private quote 999999', 'mid':'old-bot', 'product_id':str(j.pid)}]
            row.events=[{'type':'text','text':'price?','mid':'new-text','reply_to_mid':'old-bot'}]
        elif kind=='reel':
            (await db.get(Conversation,cid)).product_id=None
            row.events=[{'type':'reel','reel_url':'https://instagram.com/reel/Exact_code/','mid':'new-reel'}]
        elif kind=='reel_text':
            (await db.get(Conversation,cid)).product_id=None
            row.events=[{'type':'text','text':'https://instagram.com/reel/Exact_code/ price?','mid':'new-reel-text'}]
    async def send(client,recipient,text):
        sent.append(text)
        if kind=='uncertain':raise TimeoutError('Synthetic ambiguous transport')
        return {'message_id':'outbound-synthetic'}
    monkeypatch.setattr('app.integrations.instagram.InstagramClient.send_message',send)
    await worker._process_thread(j.bid,'synthetic-ig-account','synthetic-customer')
    await worker._process_thread(j.bid,'synthetic-ig-account','synthetic-customer')
    async with j.sessions() as db:
        row=await db.get(InstagramIngress,rid)
        assert await db.scalar(select(func.count()).select_from(ConversationProduct))==0
        assert await db.scalar(select(func.count()).select_from(CommerceOrder))==0
        if kind=='disabled':
            assert sent==[] and row.status=='error' and row.error_code=='authoritative_catalogue_handoff'
        elif kind=='uncertain':
            assert len(sent)==1 and row.status=='error' and row.error_code=='processing_failed_unknown_effect'
        else:
            assert row.status=='completed' and len(sent)==1 and '₹123.45' in sent[0] and '999999' not in sent[0]
            assert 'outbound-synthetic' in str((await db.get(Conversation,cid)).messages)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['foreign','missing','inactive'])
async def test_invalid_reply_to_never_answers_using_previous_focus(sku_lane,monkeypatch,kind):
    from app.workers import instagram_ingress as worker
    j=sku_lane;cid,rid=await instagram_turn(j,status='pending')
    monkeypatch.setattr(worker,'worker_session',session_factory(j))
    reference=uuid4()
    async with j.sessions.begin() as db:
        if kind=='inactive':
            db.add(Product(id=reference,seller_id=j.bid,name='Inactive',listed_price=1,floor_price=1,active=False))
        elif kind=='foreign':
            foreign=Seller(email=f'{uuid4()}@example.com',password_hash='synthetic');db.add(foreign);await db.flush()
            db.add(Product(id=reference,seller_id=foreign.id,name='Foreign',listed_price=1,floor_price=1,active=True))
        conversation=await db.get(Conversation,cid)
        conversation.messages=[{'role':'bot','content':'old','mid':'old-other','product_id':str(reference)}]
        (await db.get(InstagramIngress,rid)).events=[{'type':'text','text':'price?','reply_to_mid':'old-other','mid':'inbound'}]
    async def forbidden(*args,**kwargs):pytest.fail('Invalid explicit reference must not answer current focus')
    monkeypatch.setattr('app.integrations.instagram.InstagramClient.send_message',forbidden)
    await worker._process_thread(j.bid,'synthetic-ig-account','synthetic-customer')
    async with j.sessions() as db:
        assert (await db.get(InstagramIngress,rid)).error_code=='authoritative_catalogue_handoff'
