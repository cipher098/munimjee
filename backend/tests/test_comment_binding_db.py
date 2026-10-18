"""Actual0055 signed-hook/worker/constraint proof; requires allocated P01 lane.

All provider methods are synthetic. Never use create_all or another lane.
"""
import asyncio
import hashlib
import hmac
import json
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func,select,update,delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.config import settings
from app.database import get_db
from app.main import app
from app.models.seller import Seller
from app.models.product import Product
from app.models.identity import Business
from app.models.commerce import Storefront
from app.models.channel_operator import ChannelConnectionState as Control
from app.models.comment_automation import CommentRule,CommentEvent,CommentAction,CommentActionAudit
from app.services.identity import ensure_legacy_owner_bridge,legacy_owner_id
from app.services import instagram_credentials
from app.workers import comment_automation as worker


@pytest_asyncio.fixture
async def comment_lane(migrated_engine,monkeypatch):
    monkeypatch.setattr(settings,'META_WEBHOOK_SECRET','synthetic-comment-signature')
    monkeypatch.setattr(settings,'PUBLIC_BASE_URL','https://synthetic.example.com')
    sessions=async_sessionmaker(migrated_engine,expire_on_commit=False)
    bid,pid,rid=uuid4(),uuid4(),uuid4()
    async with sessions.begin() as db:
        seller=Seller(id=bid,email=f'{uuid4()}@example.com',password_hash='synthetic',is_active=True,
            instagram_page_id='100',instagram_id='100',instagram_token='synthetic-original-credential',
            instagram_token_expires_at=datetime.now(timezone.utc)+timedelta(hours=2))
        db.add(seller);await db.flush();await ensure_legacy_owner_bridge(db,seller)
        db.add_all([Product(id=pid,seller_id=bid,name='Synthetic static product',listed_price=12345,floor_price=5000,active=True),
            Storefront(seller_id=bid,slug=uuid4().hex,name='Synthetic',published=True),
            Control(business_id=bid,channel='instagram',version=1,provider_account_id='100',automation_enabled=True,
                check_status='verified',checked_at=datetime.now(timezone.utc))]);await db.flush()
        db.add(CommentRule(id=rid,seller_id=bid,name='Synthetic explicit-media rule',enabled=True,media_id='300',
            keywords=['price'],product_id=pid,private_reply='Approved details at ₹123.45'))
    async def database():
        async with sessions.begin() as db:yield db
    prior=dict(app.dependency_overrides);app.dependency_overrides[get_db]=database
    provider=AsyncMock(return_value={'message_id':'synthetic-provider-accepted'})
    monkeypatch.setattr('app.integrations.instagram.InstagramClient.send_private_reply',provider)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://synthetic.test') as client:
            yield SimpleNamespace(sessions=sessions,bid=bid,pid=pid,rid=rid,client=client,provider=provider)
    finally:app.dependency_overrides.clear();app.dependency_overrides.update(prior)


async def queue(j,cid='200',**overrides):
    value={'id':cid,'media':{'id':'300'},'from':{'id':'400'},'text':'price?',
        'timestamp':datetime.now(timezone.utc).isoformat(),'parent_id':None};value.update(overrides)
    raw=json.dumps({'object':'instagram','entry':[{'id':'100','changes':[{'field':'comments','value':value}]}]}).encode()
    signature='sha256='+hmac.new(b'synthetic-comment-signature',raw,hashlib.sha256).hexdigest()
    result=await j.client.post('/webhooks/instagram',content=raw,headers={'X-Hub-Signature-256':signature})
    assert result.status_code==200,result.text
    async with j.sessions() as db:
        event=await db.scalar(select(CommentEvent).where(CommentEvent.seller_id==j.bid,CommentEvent.comment_id==cid))
        ids=(await db.scalars(select(CommentAction.id).where(CommentAction.event_id==event.id,CommentAction.seller_id==j.bid))).all()
    return event.id,ids


async def dispatch(j,aid):
    async with j.sessions() as db:return await worker.dispatch_one(db,aid)


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['pause','business','same_account_token','replacement_account','not_checked'])
async def test_queued_source_current_gates_before_claim(comment_lane,change):
    j=comment_lane;eid,ids=await queue(j);assert len(ids)==1
    async with j.sessions.begin() as db:
        if change=='pause':await db.execute(update(Control).where(Control.business_id==j.bid).values(automation_enabled=False))
        elif change=='business':await db.execute(update(Business).where(Business.id==j.bid).values(is_active=False))
        elif change=='same_account_token':await db.execute(update(Seller).where(Seller.id==j.bid).values(instagram_token='synthetic-replacement-credential'))
        elif change=='not_checked':await db.execute(update(Control).where(Control.business_id==j.bid).values(check_status='not_checked',checked_at=None))
        else:
            await db.execute(update(Seller).where(Seller.id==j.bid).values(instagram_page_id='999',instagram_id='999',instagram_token='synthetic-replacement-credential'))
            await db.execute(update(Control).where(Control.business_id==j.bid).values(provider_account_id='999',version=2))
    assert not await dispatch(j,ids[0]);j.provider.assert_not_awaited()
    async with j.sessions() as db:
        action=await db.get(CommentAction,ids[0]);event=await db.get(CommentEvent,eid)
        assert action.status==event.status=='review_required' and action.claim_token is None
        assert action.accepted_claim['connection']['version']==1
        assert event.source_account_id=='100'


@pytest.mark.asyncio
async def test_pause_committed_after_real_claim_prevents_send(comment_lane,monkeypatch):
    j=comment_lane;_,ids=await queue(j)
    async with j.sessions() as db:
        original=db.commit;done=False
        async def committed():
            nonlocal done
            await original()
            if not done:
                done=True
                async with j.sessions.begin() as writer:
                    await writer.execute(update(Control).where(Control.business_id==j.bid).values(automation_enabled=False))
        monkeypatch.setattr(db,'commit',committed)
        assert not await worker.dispatch_one(db,ids[0])
    j.provider.assert_not_awaited()
    async with j.sessions() as db:
        action=await db.get(CommentAction,ids[0])
        assert action.claim_token and action.error_code=='automation_paused'
        assert set((await db.scalars(select(CommentActionAudit.stage).where(CommentActionAudit.action_id==action.id))).all())=={'accepted','claim','withheld'}


async def activate(j):
    from app.models.catalogue_v1 import CatalogueProductMapping,CatalogueSKU
    from app.models.checkout_v1 import CatalogueActivation
    async with j.sessions.begin() as db:
        db.add(CatalogueProductMapping(business_id=j.bid,product_id=j.pid,state='reviewed',revision=2,
            legacy_fingerprint='a'*64,issues=[],legacy_variants=[]));await db.flush()
        db.add_all([CatalogueActivation(business_id=j.bid,product_id=j.pid,reviewed_revision=1,
            legacy_fingerprint='a'*64,actor_id=legacy_owner_id(j.bid)),
            CatalogueSKU(id=uuid4(),business_id=j.bid,product_id=j.pid,options={},price_minor=19999,currency='INR',stock_available=1,active=True)])


@pytest.mark.asyncio
async def test_old_static_price_and_new_activated_events_both_withheld(comment_lane):
    j=comment_lane;_,ids=await queue(j);assert ids
    await activate(j)
    assert not await dispatch(j,ids[0])
    eid,tail=await queue(j,'201');assert tail==[]
    j.provider.assert_not_awaited()
    async with j.sessions() as db:
        assert (await db.get(CommentAction,ids[0])).error_code=='activated_context_requires_review'
        assert (await db.get(CommentEvent,eid)).reason=='activated_context_requires_review'


@pytest.mark.asyncio
async def test_during_provider_pause_preserves_original_receipt_without_retry_or_catalogue_lock(comment_lane):
    j=comment_lane;eid,ids=await queue(j)
    async def provider(*args):
        async with j.sessions.begin() as writer:
            await asyncio.wait_for(writer.execute(select(Product.id).where(Product.id==j.pid).with_for_update(nowait=True)),1)
            await asyncio.wait_for(writer.execute(select(Storefront.seller_id).where(Storefront.seller_id==j.bid).with_for_update(nowait=True)),1)
            await writer.execute(update(Control).where(Control.business_id==j.bid).values(automation_enabled=False))
        return {'message_id':'synthetic-original-claim-receipt'}
    j.provider.side_effect=provider
    assert await dispatch(j,ids[0]);assert not await dispatch(j,ids[0])
    j.provider.assert_awaited_once()
    async with j.sessions() as db:
        action=await db.get(CommentAction,ids[0]);event=await db.get(CommentEvent,eid)
        assert action.status=='sent' and action.provider_id=='synthetic-original-claim-receipt'
        assert action.error_code=='post_send_automation_paused' and event.status=='review_required'
        result=await db.scalar(select(CommentActionAudit).where(CommentActionAudit.action_id==action.id,CommentActionAudit.stage=='provider_result'))
        assert result.claim_token==action.claim_token and result.provider_id==action.provider_id


@pytest.mark.asyncio
async def test_two_workers_and_duplicate_signed_ingress_produce_one_attempt(comment_lane):
    j=comment_lane
    first,second=await asyncio.gather(queue(j),queue(j))
    assert first[0]==second[0] and len(first[1])==1
    await asyncio.gather(dispatch(j,first[1][0]),dispatch(j,first[1][0]))
    j.provider.assert_awaited_once()
    await queue(j);assert not await dispatch(j,first[1][0])
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(CommentAction).where(CommentAction.seller_id==j.bid))==1


@pytest.mark.asyncio
async def test_metadata_reconnect_cannot_accept_old_proof_as_new_generation(comment_lane,monkeypatch):
    j=comment_lane
    async def metadata(*args):
        async with j.sessions.begin() as writer:
            old=await instagram_credentials.snapshot(writer,j.bid)
            assert await instagram_credentials.replace(writer,j.bid,expected=old.proof(),account_id='100',
                token='synthetic-new-generation',expires_at=datetime.now(timezone.utc)+timedelta(hours=2))
        return {'timestamp':datetime.now(timezone.utc).isoformat(),'parent_id':None}
    monkeypatch.setattr('app.integrations.instagram.InstagramClient.get_comment_details',metadata)
    eid,ids=await queue(j,timestamp=None)
    assert ids==[];j.provider.assert_not_awaited()
    async with j.sessions() as db:
        event=await db.get(CommentEvent,eid)
        assert event.source_binding['version']==1 and event.status=='review_required'
        assert event.reason in {'source_generation_changed','account_access_not_checked'}


@pytest.mark.asyncio
async def test_legacy_unbound_history_cannot_be_promoted_or_sent(comment_lane):
    j=comment_lane;eid,aid=uuid4(),uuid4()
    async with j.sessions.begin() as db:
        db.add(CommentEvent(id=eid,seller_id=j.bid,comment_id='legacy',media_id='300',actor_id='400',text='price?',status='queued'))
        await db.flush();db.add(CommentAction(id=aid,seller_id=j.bid,event_id=eid,kind='private',body='Legacy copy',status='pending'))
    assert not await dispatch(j,aid);j.provider.assert_not_awaited()
    async with j.sessions.begin() as db:
        current=await instagram_credentials.snapshot(db,j.bid)
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await db.execute(update(CommentEvent).where(CommentEvent.id==eid).values(source_account_id='100',source_binding=current.proof(),
                    source_verified_at=datetime.now(timezone.utc),source_verification='signed_webhook'))
        assert (await db.get(CommentAction,aid)).accepted_claim is None


@pytest.mark.asyncio
async def test_accepted_source_body_claim_and_audit_are_immutable_and_tenant_bound(comment_lane):
    j=comment_lane;eid,ids=await queue(j);aid=ids[0]
    async with j.sessions.begin() as db:
        for statement in (update(CommentEvent).where(CommentEvent.id==eid).values(text='rewritten'),
                          update(CommentAction).where(CommentAction.id==aid).values(body='rewritten'),
                          delete(CommentActionAudit).where(CommentActionAudit.action_id==aid)):
            with pytest.raises(IntegrityError) as failure:
                async with db.begin_nested():await db.execute(statement)
            assert failure.value.orig.sqlstate=='23514'
        with pytest.raises(IntegrityError) as foreign:
            async with db.begin_nested():
                db.add(CommentActionAudit(id=uuid4(),seller_id=uuid4(),event_id=eid,action_id=aid,stage='accepted',after_status='pending'))
                await db.flush()
        assert foreign.value.orig.sqlstate=='23503'
