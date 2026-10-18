"""Real-Postgres comment ingestion/rule/dispatch regressions. All Meta I/O mocked."""
import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.api.dashboard_auth import _make_token
from app.api.routes.comment_automation import router
from app.api.webhooks.instagram import router as webhook_router
from app.config import settings
from app.database import get_db
from app.models import Seller, Product
from app.models.commerce import Storefront
from app.models.comment_automation import CommentRule, CommentEvent, CommentAction
from app.services.comment_automation import ingest_comment as verified_ingest, matches
from app.workers.comment_automation import dispatch_one
from tests.conftest_db import db_session


async def ingest_comment(db, account_id, change, entry_time=None):
    # Domain tests explicitly stand in for the trusted signature-verified hook.
    # Forged/unsigned producer denial is covered independently in binding tests.
    return await verified_ingest(db,account_id,change,entry_time,verified_source=True)


@pytest_asyncio.fixture
async def scene(db_session, monkeypatch):
    monkeypatch.setattr(settings, 'PUBLIC_BASE_URL', 'https://shop.example.com')
    monkeypatch.setattr(settings, 'META_WEBHOOK_SECRET', 'test-secret')
    sellers = [Seller(id=uuid4(), email=f'{uuid4()}@example.test', password_hash='unused', instagram_page_id=str(100+i), instagram_id=str(100+i), instagram_token='test',instagram_token_expires_at=datetime.now(timezone.utc)+timedelta(days=1)) for i in range(2)]
    db_session.add_all(sellers)
    await db_session.flush()
    from app.services.identity import ensure_legacy_owner_bridge
    from app.models.channel_operator import ChannelConnectionState
    for seller in sellers:
        await ensure_legacy_owner_bridge(db_session,seller)
        db_session.add(ChannelConnectionState(business_id=seller.id,channel='instagram',version=1,provider_account_id=seller.instagram_page_id,automation_enabled=True,check_status='verified',checked_at=datetime.now(timezone.utc)))
    products = [Product(id=uuid4(), seller_id=s.id, name='Dress', listed_price=50000, floor_price=20000, active=True) for s in sellers]
    db_session.add_all(products + [Storefront(seller_id=s.id,slug=f'store-{i}',name='Store',published=True) for i,s in enumerate(sellers)])
    await db_session.flush()
    rule = CommentRule(seller_id=sellers[0].id,name='Price', enabled=True, media_id='300', keywords=['price'], product_id=products[0].id, private_reply='Here are the details', public_reply='Details are in your inbox')
    db_session.add(rule)
    await db_session.commit()
    app = FastAPI(); app.include_router(router); app.include_router(webhook_router)
    async def db_override():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise
    app.dependency_overrides[get_db] = db_override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test',cookies={'dashboard_session':_make_token('seller',str(sellers[0].id),'test')}) as client:
        yield SimpleNamespace(db=db_session,sellers=sellers,products=products,rule=rule,client=client)


def change(**overrides):
    value = {'id':'200','media':{'id':'300'},'from':{'id':'400'},'text':'PRICE please!', 'parent_id':None, 'timestamp': datetime.now(timezone.utc).isoformat()}
    value.update(overrides)
    return {'field':'comments','value':value}


@pytest.mark.parametrize('text,expected',[('PRICE!',True),('surprise',False),('pricey',False),('the price please',True),('half-price',True)])
def test_wholeword(text, expected):
    assert matches(SimpleNamespace(media_id=None, keywords=['price']),text,'1') is expected


@pytest.mark.asyncio
async def test_duplicate_comment_one_private_across_rules(scene):
    scene.db.add(CommentRule(seller_id=scene.sellers[0].id,name='Other', enabled=True, keywords=['price'], product_id=scene.products[0].id, private_reply='Other'))
    await scene.db.commit()
    event=change()
    await ingest_comment(scene.db,'100',event)
    await ingest_comment(scene.db,'100',event)
    await scene.db.flush()
    assert await scene.db.scalar(select(func.count()).select_from(CommentEvent)) == 1
    actions=(await scene.db.scalars(select(CommentAction))).all()
    assert len(actions)==2
    assert sum(a.kind=='private' for a in actions)==1
    assert 'floor_price' not in actions[0].body
    assert f'?product={scene.products[0].id}' in next(a.body for a in actions if a.kind=='private')


@pytest.mark.parametrize('override,reason',[
    ({'parent_id':'parent'},'nested_comment'),
    ({'from':{'id':'100'}},'own_comment'),
    ({'timestamp':(datetime.now(timezone.utc)-timedelta(days=8)).isoformat()},'source_too_old'),
    ({'timestamp':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()},'source_time_unverified'),
    ({'media':{'id':'300','media_product_type':'LIVE'}},'live_comment_not_supported'),
])
@pytest.mark.asyncio
async def test_ineligible_comments(scene, override, reason):
    eid=await ingest_comment(scene.db,'100',change(**override))
    event=await scene.db.get(CommentEvent,eid)
    assert event.reason==reason
    assert await scene.db.scalar(select(func.count()).select_from(CommentAction))==0


@pytest.mark.asyncio
async def test_missing_timestamp_uses_provider_not_entry_time(scene,monkeypatch):
    from app.integrations.instagram import InstagramClient
    lookup=AsyncMock(return_value={'timestamp':(datetime.now(timezone.utc)-timedelta(days=8)).isoformat(),'parent_id':None})
    monkeypatch.setattr(InstagramClient,'get_comment_details',lookup)
    eid=await ingest_comment(scene.db,'100',change(timestamp=None),datetime.now(timezone.utc).timestamp())
    assert (await scene.db.get(CommentEvent,eid)).reason=='source_too_old'
    lookup.assert_awaited_once()


@pytest.mark.asyncio
async def test_rule_other_seller_and_foreign_product_denied(scene):
    other=CommentRule(seller_id=scene.sellers[1].id,name='Private',enabled=False,keywords=['price'],product_id=scene.products[1].id,private_reply='Private')
    scene.db.add(other);await scene.db.commit()
    own_id, other_id = str(scene.products[0].id), str(other.id)
    body={'name':'test','keywords':['price'],'product_id':str(scene.products[1].id),'private_reply':'Details'}
    assert (await scene.client.post('/comment-automation/rules',json=body)).status_code==400
    body['product_id']=own_id
    assert (await scene.client.put(f'/comment-automation/rules/{other_id}',json=body)).status_code==404
    assert (await scene.client.delete(f'/comment-automation/rules/{other_id}')).status_code==404
    assert (await scene.client.post('/comment-automation/preview',json={'rule_id':other_id,'text':'price','media_id':'300'})).status_code==404
    rules=(await scene.client.get('/comment-automation/rules')).json()
    assert len(rules)==1


@pytest.mark.asyncio
async def test_preview_never_sends_and_default_disabled(scene):
    response=await scene.client.post('/comment-automation/rules',json={'name':'New','keywords':['DETAILS'],'product_id':str(scene.products[0].id),'private_reply':'Shop it'})
    assert response.status_code==201
    assert response.json()['enabled'] is False
    preview=await scene.client.post('/comment-automation/preview',json={'rule_id':response.json()['id'],'text':'details','media_id':'300'})
    assert preview.json()['matches'] and not preview.json()['sends']
    assert await scene.db.scalar(select(func.count()).select_from(CommentAction))==0


@pytest.mark.asyncio
async def test_public_private_independent_and_no_ambiguous_retry(scene,monkeypatch):
    from app.integrations.instagram import InstagramClient
    private=AsyncMock(side_effect=httpx.ReadTimeout('timeout'))
    public=AsyncMock(return_value={'id':'public-id'})
    monkeypatch.setattr(InstagramClient,'send_private_reply',private)
    monkeypatch.setattr(InstagramClient,'reply_to_comment',public)
    await ingest_comment(scene.db,'100',change());await scene.db.commit()
    actions=(await scene.db.scalars(select(CommentAction))).all()
    for action in actions:
        await dispatch_one(scene.db,action.id)
        await dispatch_one(scene.db,action.id)
    assert {a.kind:a.status for a in actions}=={'private':'unknown','public':'sent'}
    assert (await scene.db.get(CommentEvent,actions[0].event_id)).status=='review_required'
    private.assert_awaited_once();public.assert_awaited_once()


@pytest.mark.asyncio
async def test_rule_disabled_cancels_queued(scene,monkeypatch):
    await ingest_comment(scene.db,'100',change());await scene.db.commit()
    scene.rule.enabled=False;await scene.db.commit()
    actions=(await scene.db.scalars(select(CommentAction))).all()
    for a in actions:
        assert await dispatch_one(scene.db,a.id) is False
        assert a.status=='review_required'


@pytest.mark.asyncio
async def test_concurrent_ingress_and_dispatch(scene,monkeypatch):
    from app.integrations.instagram import InstagramClient
    factory=async_sessionmaker(scene.db.bind,expire_on_commit=False)
    async def ingest():
        async with factory() as db:
            await ingest_comment(db,'100',change())
            await db.commit()
    await asyncio.gather(ingest(),ingest())
    ids=(await scene.db.scalars(select(CommentAction.id).where(CommentAction.kind=='private'))).all()
    assert len(ids)==1
    private=AsyncMock(return_value={'message_id':'private-id'})
    monkeypatch.setattr(InstagramClient,'send_private_reply',private)
    async def dispatch():
        async with factory() as db:
            await dispatch_one(db,ids[0])
    await asyncio.gather(dispatch(),dispatch())
    private.assert_awaited_once()


@pytest.mark.asyncio
async def test_signed_webhook_and_dotted_challenge(scene,monkeypatch):
    monkeypatch.setattr(settings,'META_VERIFY_TOKEN','test-token')
    result=await scene.client.get('/webhooks/instagram',params={'hub.mode':'subscribe','hub.verify_token':'test-token','hub.challenge':'123'})
    assert result.status_code==200 and result.text=='123'
    body=json.dumps({'object':'instagram','entry':[{'id':'100','changes':[change()]}]}).encode()
    assert (await scene.client.post('/webhooks/instagram',content=body)).status_code==400
    sig='sha256='+hmac.new(b'test-secret',body,hashlib.sha256).hexdigest()
    assert (await scene.client.post('/webhooks/instagram',content=body,headers={'X-Hub-Signature-256':sig})).status_code==200
    assert await scene.db.scalar(select(func.count()).select_from(CommentAction))==2
    monkeypatch.setattr(settings,'META_WEBHOOK_SECRET','')
    assert (await scene.client.post('/webhooks/instagram',content=body,headers={'X-Hub-Signature-256':sig})).status_code==503


@pytest.mark.asyncio
async def test_graph_rejection_and_rule_edit_prevents_stale_send(scene,monkeypatch):
    from app.integrations.instagram import InstagramClient
    request=httpx.Request('POST','https://graph.instagram.com/test')
    rejected=AsyncMock(side_effect=httpx.HTTPStatusError('rejected',request=request,response=httpx.Response(400,request=request)))
    monkeypatch.setattr(InstagramClient,'send_private_reply',rejected)
    await ingest_comment(scene.db,'100',change());await scene.db.commit()
    actions=(await scene.db.scalars(select(CommentAction))).all()
    private=next(a for a in actions if a.kind=='private')
    public=next(a for a in actions if a.kind=='public')
    await dispatch_one(scene.db,private.id)
    assert private.status=='unknown' and private.error_code=='provider_http_result_unconfirmed'
    scene.rule.public_reply='Changed since queuing';await scene.db.commit()
    assert await dispatch_one(scene.db,public.id) is False
    assert public.status=='review_required'
    await dispatch_one(scene.db,private.id)
    rejected.assert_awaited_once()


@pytest.mark.asyncio
async def test_meta_private_reply_payload_and_echo_registry(monkeypatch):
    import app.integrations.instagram as integration
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'message_id':'sent-mid'})
    real_client=httpx.AsyncClient
    monkeypatch.setattr(integration.httpx,'AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(handler)))
    registered=[]
    monkeypatch.setattr(integration,'register_outbound_mid',registered.append)
    client=integration.InstagramClient('test-token','100')
    await client.send_private_reply('200','Details')
    assert json.loads(calls[0].content)=={'recipient':{'comment_id':'200'},'message':{'text':'Details'}}
    assert str(calls[0].url).endswith('/100/messages')
    assert registered==['sent-mid']
    await integration.subscribe_ig_user_to_messages('100','test-token')
    assert calls[1].url.params['subscribed_fields']=='messages,comments'
    assert 'instagram_business_manage_comments' in integration.INSTAGRAM_OAUTH_SCOPES


def load_lambda(monkeypatch):
    import importlib.util
    from pathlib import Path
    import boto3
    from unittest.mock import Mock
    fake=Mock()
    monkeypatch.setenv('META_VERIFY_TOKEN','verify')
    monkeypatch.setenv('META_WEBHOOK_SECRET','secret')
    monkeypatch.setenv('SQS_QUEUE_URL','test-queue')
    monkeypatch.setattr(boto3,'client',lambda *a,**k:fake)
    path=Path(__file__).resolve().parents[2]/'infra/lambda/handler.py'
    spec=importlib.util.spec_from_file_location('comment_test_lambda',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module,fake


def test_production_lambda_enqueues_comments_signed_only(monkeypatch):
    module,sqs=load_lambda(monkeypatch)
    body=json.dumps({'object':'instagram','entry':[{'id':'100','time':123,'changes':[change()],'messaging':[{'sender':{'id':'400'},'recipient':{'id':'100'},'message':{'mid':'m1','text':'hi'}}]}]})
    event={'body':body,'headers':{},'requestContext':{'http':{'method':'POST'}}}
    assert module.lambda_handler(event,None)['statusCode']==403
    sqs.send_message.assert_not_called()
    event['headers']['x-hub-signature-256']='sha256='+hmac.new(b'secret',body.encode(),hashlib.sha256).hexdigest()
    assert module.lambda_handler(event,None)['statusCode']==200
    assert sqs.send_message.call_count==2
    envelopes=[json.loads(c.kwargs['MessageBody']) for c in sqs.send_message.call_args_list]
    assert envelopes[0]['message']['mid']=='m1'
    assert envelopes[1]['type']=='instagram_comment' and envelopes[1]['account_id']=='100'
    module.WEBHOOK_SECRET=''
    assert module.lambda_handler(event,None)['statusCode']==403


@pytest.mark.asyncio
async def test_sqs_routes_typed_comment_and_legacy_message(scene,monkeypatch):
    from contextlib import asynccontextmanager
    import app.workers.sqs_consumer as consumer
    @asynccontextmanager
    async def session():
        yield scene.db
        await scene.db.commit()
    monkeypatch.setattr(consumer,'worker_session',session)
    dm=AsyncMock()
    monkeypatch.setattr(consumer,'_handle_messaging_event',dm)
    monkeypatch.setattr(consumer,'_maybe_route_to_local',AsyncMock(return_value=False))
    await consumer._process_event({'type':'instagram_comment','account_id':'100','change':change()})
    assert await scene.db.scalar(select(func.count()).select_from(CommentAction))==2
    dm.assert_not_called()
    legacy={'sender':{'id':'400'},'recipient':{'id':'100'},'message':{'text':'hi'}}
    await consumer._process_event(legacy)
    dm.assert_awaited_once_with(legacy,scene.db)


@pytest.mark.asyncio
async def test_disabled_or_wrong_media_no_actions_and_event_tenant_filter(scene):
    scene.rule.media_id='999';await scene.db.commit()
    eid=await ingest_comment(scene.db,'100',change())
    assert (await scene.db.get(CommentEvent,eid)).reason=='no_matching_rule'
    await ingest_comment(scene.db,'101',change(id='201'))
    await scene.db.commit()
    events=(await scene.client.get('/comment-automation/events')).json()
    assert len(events)==1 and events[0]['comment_id']=='200'
    scene.rule.enabled=False;await scene.db.commit()
    await ingest_comment(scene.db,'100',change(id='202',media={'id':'999'}))
    assert await scene.db.scalar(select(func.count()).select_from(CommentAction))==0


@pytest.mark.asyncio
async def test_creation_lookup_transient_error_retries_read_not_send(scene,monkeypatch):
    from app.integrations.instagram import InstagramClient
    monkeypatch.setattr(InstagramClient,'get_comment_details',AsyncMock(side_effect=httpx.ReadTimeout('temporary')))
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as failure:
        await ingest_comment(scene.db,'100',change(timestamp=None))
    assert failure.value.status_code==503
    assert await scene.db.scalar(select(func.count()).select_from(CommentEvent))==0
    monkeypatch.setattr(InstagramClient,'get_comment_details',AsyncMock(return_value={'timestamp':datetime.now(timezone.utc).isoformat(),'parent_id':'existing-parent'}))
    eid=await ingest_comment(scene.db,'100',change(timestamp=None))
    assert (await scene.db.get(CommentEvent,eid)).reason=='nested_comment'


@pytest.mark.asyncio
async def test_unknown_comment_creation_time_never_uses_delivery_time(scene,monkeypatch):
    from app.integrations.instagram import InstagramClient
    monkeypatch.setattr(InstagramClient,'get_comment_details',AsyncMock(return_value={}))
    eid=await ingest_comment(scene.db,'100',change(timestamp=None),datetime.now(timezone.utc).timestamp())
    assert (await scene.db.get(CommentEvent,eid)).reason=='source_time_unverified'
    assert await scene.db.scalar(select(func.count()).select_from(CommentAction))==0


@pytest.mark.asyncio
async def test_stale_inflight_held_for_review(scene,monkeypatch):
    from contextlib import asynccontextmanager
    import app.workers.comment_automation as worker
    await ingest_comment(scene.db,'100',change());await scene.db.commit()
    actions=(await scene.db.scalars(select(CommentAction))).all()
    for action in actions:
        action.status='sending';action.claim_token=uuid4();action.attempted_at=datetime.now(timezone.utc)-timedelta(minutes=10)
    await scene.db.commit()
    @asynccontextmanager
    async def session():
        yield scene.db
        await scene.db.commit()
    monkeypatch.setattr(worker,'worker_session',session)
    await worker.dispatch_pending()
    for action in actions:
        await scene.db.refresh(action)
        assert action.status=='unknown'
    event=await scene.db.get(CommentEvent,actions[0].event_id)
    await scene.db.refresh(event)
    assert event.status=='review_required'


@pytest.mark.asyncio
async def test_seller_rate_budget_defers_without_claiming(scene,monkeypatch):
    from app.integrations.instagram import InstagramClient
    now=datetime.now(timezone.utc)
    existing=[CommentEvent(id=uuid4(),seller_id=scene.sellers[0].id,comment_id=f'history-{i}',media_id='300',actor_id='400',text='price',commented_at=now,status='complete') for i in range(250)]
    scene.db.add_all(existing);await scene.db.flush()
    scene.db.add_all([CommentAction(seller_id=scene.sellers[0].id,event_id=e.id,kind='private',body='old',status='sent',attempted_at=now) for e in existing])
    await scene.db.commit()
    await ingest_comment(scene.db,'100',change());await scene.db.commit()
    action=await scene.db.scalar(select(CommentAction).where(CommentAction.status=='pending',CommentAction.kind=='private'))
    send=AsyncMock()
    monkeypatch.setattr(InstagramClient,'send_private_reply',send)
    assert await dispatch_one(scene.db,action.id) is False
    assert action.status=='pending' and action.attempted_at is None
    send.assert_not_awaited()


def test_malformed_unicode_signature_rejected(monkeypatch):
    from fastapi import HTTPException
    from app.api.webhooks.instagram import _verify_signature
    monkeypatch.setattr(settings,'META_WEBHOOK_SECRET','test')
    with pytest.raises(HTTPException) as exc:
        _verify_signature(b'{}','sha256=non-ascii-é')
    assert exc.value.status_code==403
    module,_=load_lambda(monkeypatch)
    assert not module._valid_signature(b'{}','sha256=non-ascii-é')
