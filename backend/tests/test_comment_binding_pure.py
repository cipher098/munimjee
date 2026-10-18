"""No DB/network: acceptance types and real dispatcher phase schedules.

Injected query rows isolate dispatch control flow, not PostgreSQL visibility,
constraints, lock ordering, signed-hook composition or provider entitlement.
"""
import asyncio
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock
import httpx
import pytest
from app.config import settings
from app.models.comment_automation import CommentAction,CommentEvent,CommentActionAudit
from app.schemas import comment_binding as claims
from app.services import comment_binding as policy
from app.services.comment_automation import ingest_comment,comment_time
from app.services.instagram_credentials import Connection
from app.workers import comment_automation as worker


@pytest.fixture
def scene(monkeypatch):
    monkeypatch.setattr(settings,'META_WEBHOOK_SECRET','synthetic-comment-signature')
    monkeypatch.setattr(settings,'PUBLIC_BASE_URL','https://synthetic.example.com')
    bid,eid,rule=uuid4(),uuid4(),uuid4()
    connection=Connection('100','synthetic-private-credential',datetime.now(timezone.utc)+timedelta(hours=1),1,'100',True)
    rule_data={'id':str(rule),'product_id':str(uuid4()),'media_id':'300','keywords':['price']}
    ctx=policy.Context(connection,True,{'frozen':'synthetic-approved-static-config','control':{'check_status':'verified','checked_at':'synthetic-local-check'}},
        {'id':str(rule),'enabled':True,'media_id':'300'},(rule_data,),True,False,True)
    event=CommentEvent(id=eid,seller_id=bid,rule_id=rule,comment_id='200',media_id='300',actor_id='400',text='price?',
        commented_at=datetime.now(timezone.utc),source_account_id='100',source_binding=connection.proof(),
        source_verified_at=datetime.now(timezone.utc),source_verification='signed_webhook',status='queued')
    action=CommentAction(id=uuid4(),seller_id=bid,event_id=eid,kind='private',body='Approved static reply',status='pending')
    action.accepted_claim=claims.accepted_claim(event,action.kind,action.body,ctx.config)
    action.claim_hash=claims.digest(action.accepted_claim)
    return SimpleNamespace(context=ctx,current=ctx,event=event,action=action)


class Rows:
    def __init__(self,rows=()):self.rows=rows
    def all(self):return self.rows


class DB:
    def __init__(self,scene):self.scene=scene;self.audits=[];self.commits=0;self.on_commit=None;self.rolled_back=False
    async def scalar(self,query):
        entity=query.column_descriptions[0]['entity']
        if entity is CommentAction:
            claim=getattr(query,'_for_update_arg',None)
            return None if getattr(claim,'skip_locked',False) and self.scene.action.status!='pending' else self.scene.action
        if entity is CommentEvent:return self.scene.event
        return 0
    async def execute(self,query,*args):
        if hasattr(query,'column_descriptions') and len(query.column_descriptions)==2:
            return Rows([(self.scene.action.status,self.scene.action.error_code)])
        return Rows()
    async def flush(self):pass
    async def commit(self):
        self.commits+=1
        if self.on_commit:self.on_commit(self)
    async def rollback(self):self.rolled_back=True
    def add(self,row):self.audits.append(row)


def install(scene,monkeypatch):
    db=DB(scene)
    async def context(*args,**kwargs):return scene.current
    monkeypatch.setattr(policy,'context',context)
    provider=AsyncMock(return_value={'message_id':'synthetic-provider-acceptance'})
    monkeypatch.setattr('app.integrations.instagram.InstagramClient.send_private_reply',provider)
    return db,provider


@pytest.mark.parametrize('key,value',[('version',True),('version',-1),('version',1.5),('credential_hash','x'),
    ('expires_at','2026-10-18T10:00:00'),('expires_at',None),('account_id','')])
def test_private_source_proof_rejects_coerced_or_incomplete_authority(scene,key,value):
    bad={**scene.event.source_binding,key:value}
    assert not claims.valid_proof(bad)


def test_claim_binds_event_body_source_and_configuration_without_raw_credential(scene):
    assert claims.valid_claim(scene.action,scene.event)
    assert scene.context.connection.token not in repr(scene.context)
    assert scene.context.connection.token not in str(scene.action.accepted_claim)
    scene.action.body='Changed reply'
    assert not claims.valid_claim(scene.action,scene.event)


@pytest.mark.parametrize('value',[None,True,False,[],{},float('nan'),float('inf'),'NaN','not-a-time'])
def test_unverified_source_age_never_becomes_a_delivery_time(value):
    assert comment_time({'timestamp':value},datetime.now(timezone.utc).timestamp()) is None


@pytest.mark.asyncio
async def test_direct_unsigned_producer_cannot_create_work_or_request_metadata():
    class NoQueries:
        def __getattr__(self,name):raise AssertionError('Untrusted producer reached '+name)
    assert await ingest_comment(NoQueries(),'100',{'field':'comments','value':{'id':'200'}}) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['pause','inactive','generation','expiry','rule','activated','config','not_checked','unbound'])
async def test_post_claim_current_gate_prevents_provider_after_committed_change(scene,monkeypatch,change):
    db,provider=install(scene,monkeypatch)
    def after_commit(db):
        if db.commits!=1:return
        ctx=scene.context
        if change=='pause':ctx=replace(ctx,automation_enabled=False)
        elif change=='inactive':ctx=replace(ctx,connection=replace(ctx.connection,active=False))
        elif change=='generation':ctx=replace(ctx,connection=replace(ctx.connection,version=2,token='replacement-credential'))
        elif change=='expiry':ctx=replace(ctx,connection=replace(ctx.connection,expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)))
        elif change=='rule':ctx=replace(ctx,rule={**ctx.rule,'enabled':False})
        elif change=='activated':ctx=replace(ctx,activated=True)
        elif change=='not_checked':ctx=replace(ctx,config={**ctx.config,'control':{'check_status':'not_checked','checked_at':None}})
        elif change=='unbound':ctx=replace(ctx,rule={**ctx.rule,'media_id':None})
        else:ctx=replace(ctx,config={**ctx.config,'frozen':'changed'})
        scene.current=ctx
    db.on_commit=after_commit
    assert not await worker.dispatch_one(db,scene.action.id)
    provider.assert_not_awaited()
    assert scene.action.status=='review_required' and scene.action.claim_token is not None
    assert any(a.stage=='withheld' for a in db.audits)
    assert not await worker.dispatch_one(db,scene.action.id)
    provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_fences_old_worker_after_claim_before_provider(scene,monkeypatch):
    db,provider=install(scene,monkeypatch)
    def recovered(db):
        if db.commits==1:
            scene.action.status='unknown'
            scene.current=replace(scene.context,claim_active=False)
    db.on_commit=recovered
    assert not await worker.dispatch_one(db,scene.action.id)
    assert db.rolled_back and scene.action.status=='unknown'
    provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_activated_static_price_copy_is_withheld_before_claim(scene,monkeypatch):
    db,provider=install(scene,monkeypatch)
    scene.current=replace(scene.context,activated=True)
    assert not await worker.dispatch_one(db,scene.action.id)
    assert scene.action.error_code=='activated_context_requires_review'
    assert scene.action.claim_token is None
    provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_pending_is_reviewed_without_promoting_current_binding(scene,monkeypatch):
    db,provider=install(scene,monkeypatch)
    scene.action.accepted_claim=scene.action.claim_hash=None
    assert not await worker.dispatch_one(db,scene.action.id)
    assert scene.action.accepted_claim is None and scene.action.claim_token is None
    assert scene.action.error_code=='legacy_binding_unverified'
    provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_change_during_provider_preserves_receipt_original_claim_and_review(scene,monkeypatch):
    db,provider=install(scene,monkeypatch)
    async def send(*args):
        scene.current=replace(scene.context,automation_enabled=False)
        return {'id':'synthetic-provider-acceptance'}
    provider.side_effect=send
    assert await worker.dispatch_one(db,scene.action.id)
    provider.assert_awaited_once()
    assert scene.action.status=='sent' and scene.action.provider_id=='synthetic-provider-acceptance'
    assert scene.event.status=='review_required' and scene.action.error_code=='post_send_automation_paused'
    assert scene.action.accepted_claim['connection']['version']==1
    assert any(a.stage=='provider_result' and a.provider_id==scene.action.provider_id for a in db.audits)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',['timeout','http409','cancelled','malformed','credential_receipt'])
async def test_ambiguous_outcome_never_becomes_pending_or_repeated(scene,monkeypatch,failure):
    db,provider=install(scene,monkeypatch)
    if failure=='timeout':provider.side_effect=TimeoutError('synthetic uncertainty')
    elif failure=='http409':
        request=httpx.Request('POST','https://synthetic.invalid/comments')
        provider.side_effect=httpx.HTTPStatusError('synthetic intermediary',request=request,response=httpx.Response(409,request=request))
    elif failure=='cancelled':provider.side_effect=asyncio.CancelledError()
    elif failure=='credential_receipt':provider.return_value={'id':scene.context.connection.token}
    else:provider.return_value=['malformed']
    if failure=='cancelled':
        with pytest.raises(asyncio.CancelledError):await worker.dispatch_one(db,scene.action.id)
    else:assert await worker.dispatch_one(db,scene.action.id)
    assert scene.action.status=='unknown' and scene.event.status=='review_required'
    assert scene.action.provider_id is None and all(a.provider_id is None for a in db.audits)
    assert not await worker.dispatch_one(db,scene.action.id)
    provider.assert_awaited_once()


@pytest.mark.asyncio
async def test_final_scalar_query_compiles_without_row_locks_or_credential_writer(monkeypatch):
    from sqlalchemy.dialects import postgresql
    from contextlib import nullcontext
    class Capture:
        no_autoflush=nullcontext()
        async def execute(self,query):
            self.sql=str(query.compile(dialect=postgresql.dialect()))
            return SimpleNamespace(mappings=lambda:SimpleNamespace(one_or_none=lambda:None))
    db=Capture()
    assert await policy.context(db,uuid4(),uuid4(),action_id=uuid4(),claim_token=uuid4()) is None
    assert 'FOR UPDATE' not in db.sql and 'FOR SHARE' not in db.sql
    assert 'comment_actions.claim_token' in db.sql and 'catalogue_activations' in db.sql


class ProducerDB:
    def __init__(self,bid):self.bid=bid;self.inserted=None;self.added=[]
    async def scalars(self,query):return Rows([self.bid])
    async def scalar(self,query):
        if getattr(query,'is_insert',False):
            self.inserted={key if isinstance(key,str) else key.key:getattr(value,'value',value) for key,value in query._values.items()}
            return self.inserted['id']
        return None
    async def flush(self):pass
    def add(self,row):self.added.append(row)


def producer_context(scene):
    ctx=scene.context
    scope=ctx.rules[0]
    return replace(ctx,rule={**scope,'enabled':True,'private_reply':'Approved static reply','public_reply':None},
        config={**ctx.config,'owner_account':'100','store':{'slug':'synthetic-store'},'frozen':'approved'})


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['generation','pause','activated'])
async def test_metadata_wait_cannot_accept_changed_source_or_static_authority(scene,monkeypatch,change):
    ctx=producer_context(scene);scene.current=ctx;db=ProducerDB(scene.event.seller_id)
    async def context(*args,**kwargs):return scene.current
    async def metadata(*args):
        scene.current=replace(ctx,connection=replace(ctx.connection,version=2)) if change=='generation' else (
            replace(ctx,automation_enabled=False) if change=='pause' else replace(ctx,activated=True))
        return {'timestamp':datetime.now(timezone.utc).isoformat(),'parent_id':None}
    monkeypatch.setattr(policy,'context',context)
    monkeypatch.setattr('app.integrations.instagram.InstagramClient.get_comment_details',metadata)
    eid=await ingest_comment(db,'100',{'field':'comments','value':{'id':'200','media':{'id':'300'},'from':{'id':'400'},'text':'price?'}},verified_source=True)
    assert eid and db.inserted['status']=='review_required' and not db.added
    assert db.inserted['source_binding']['version']==1
    assert db.inserted['reason'] in {'source_generation_changed','automation_paused','activated_context_requires_review'}


@pytest.mark.asyncio
async def test_account_change_between_tenant_lookup_and_snapshot_never_reads_with_replacement_credential(scene,monkeypatch):
    ctx=producer_context(scene)
    ctx=replace(ctx,connection=replace(ctx.connection,account_id='999',bound_account='999'))
    db=ProducerDB(scene.event.seller_id)
    monkeypatch.setattr(policy,'context',AsyncMock(return_value=ctx))
    metadata=AsyncMock(side_effect=AssertionError('Replacement credential must not read old comment'))
    monkeypatch.setattr('app.integrations.instagram.InstagramClient.get_comment_details',metadata)
    assert await ingest_comment(db,'100',{'field':'comments','value':{'id':'200','media':{'id':'300'},'from':{'id':'400'},'text':'price?'}},verified_source=True)
    metadata.assert_not_awaited()
    assert db.inserted['reason']=='source_generation_changed' and db.inserted['source_binding'] is None
    assert not db.added


@pytest.mark.asyncio
async def test_transient_metadata_read_is_redacted_retryable_and_unacknowledged(scene,monkeypatch):
    from fastapi import HTTPException
    ctx=producer_context(scene);db=ProducerDB(scene.event.seller_id)
    monkeypatch.setattr(policy,'context',AsyncMock(return_value=ctx))
    metadata=AsyncMock(side_effect=httpx.ReadTimeout('secret-provider-url-never-emit'))
    monkeypatch.setattr('app.integrations.instagram.InstagramClient.get_comment_details',metadata)
    with pytest.raises(HTTPException) as exc:
        await ingest_comment(db,'100',{'field':'comments','value':{'id':'200','media':{'id':'300'},'from':{'id':'400'},'text':'price?'}},verified_source=True)
    assert exc.value.status_code==503 and 'secret-provider-url' not in exc.value.detail
    assert db.inserted is None and not db.added


@pytest.mark.asyncio
async def test_second_matching_product_is_ambiguous_before_acceptance_and_dispatch(scene,monkeypatch):
    ctx=producer_context(scene)
    other={**ctx.rules[0],'id':str(uuid4()),'product_id':str(uuid4())}
    scene.current=replace(ctx,rules=ctx.rules+(other,))
    db=ProducerDB(scene.event.seller_id)
    monkeypatch.setattr(policy,'context',AsyncMock(return_value=scene.current))
    assert await ingest_comment(db,'100',{'field':'comments','value':{'id':'200','media':{'id':'300'},'from':{'id':'400'},'text':'price?',
        'timestamp':datetime.now(timezone.utc).isoformat(),'parent_id':None}},verified_source=True)
    assert db.inserted['reason']=='product_context_ambiguous' and not db.added
    assert policy.eligibility(scene.current,scene.event,scene.action)=='product_context_ambiguous'


@pytest.mark.asyncio
@pytest.mark.parametrize('parent',[[],{},True,''])
async def test_malformed_parent_is_never_treated_as_verified_root_comment(scene,monkeypatch,parent):
    ctx=producer_context(scene);db=ProducerDB(scene.event.seller_id)
    monkeypatch.setattr(policy,'context',AsyncMock(return_value=ctx))
    assert await ingest_comment(db,'100',{'field':'comments','value':{'id':'200','media':{'id':'300'},'from':{'id':'400'},'text':'price?',
        'timestamp':datetime.now(timezone.utc).isoformat(),'parent_id':parent}},verified_source=True)
    assert db.inserted['reason']=='incomplete_event' and not db.added


def test_real_0055_upgrade_renders_offline_with_only_historical_fk_not_valid(monkeypatch):
    """Exercise Alembic operations without connecting; not PostgreSQL execution."""
    import importlib.util
    import io
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path=Path(__file__).resolve().parents[1]/'alembic/versions/0055_v1_comment_binding.py'
    spec=importlib.util.spec_from_file_location('comment_binding_migration',path)
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    output=io.StringIO()
    context=MigrationContext.configure(dialect_name='postgresql',opts={'as_sql':True,'output_buffer':output})
    monkeypatch.setattr(migration,'op',Operations(context))
    migration.upgrade()
    ddl=output.getvalue()
    assert migration.down_revision=='0054_v1_activity'
    assert ddl.count('NOT VALID')==1 # Existing action/event mismatches only.
    assert 'CREATE TABLE comment_action_audits' in ddl
    assert 'comment_audit_event_tenant FOREIGN KEY' in ddl and 'comment_audit_action_tenant FOREIGN KEY' in ddl



def test_accepted_timestamp_identity_survives_postgres_utc_projection(scene):
    offset=timezone(timedelta(hours=5,minutes=30))
    scene.event.commented_at=scene.event.commented_at.astimezone(offset)
    scene.event.source_verified_at=scene.event.source_verified_at.astimezone(offset)
    scene.action.accepted_claim=claims.accepted_claim(scene.event,scene.action.kind,scene.action.body,scene.context.config)
    scene.action.claim_hash=claims.digest(scene.action.accepted_claim)
    scene.event.commented_at=scene.event.commented_at.astimezone(timezone.utc)
    scene.event.source_verified_at=scene.event.source_verified_at.astimezone(timezone.utc)
    assert claims.valid_claim(scene.action,scene.event)


@pytest.mark.asyncio
@pytest.mark.parametrize('text',['price?\x00','price?\ud800'])
async def test_unencodable_comment_is_not_accepted_or_forwarded(scene,monkeypatch,text):
    db=ProducerDB(scene.event.seller_id)
    monkeypatch.setattr(policy,'context',AsyncMock(return_value=producer_context(scene)))
    assert await ingest_comment(db,'100',{'field':'comments','value':{'id':'200','media':{'id':'300'},'from':{'id':'400'},'text':text}},verified_source=True) is None
    assert db.inserted is None and not db.added


@pytest.mark.asyncio
async def test_actual_task_cancellation_after_provider_entry_persists_uncertainty(scene,monkeypatch):
    db,provider=install(scene,monkeypatch)
    entered=asyncio.Event();never=asyncio.Event()
    async def sending(*args):
        entered.set();await never.wait()
    provider.side_effect=sending
    task=asyncio.create_task(worker.dispatch_one(db,scene.action.id))
    await asyncio.wait_for(entered.wait(),1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert task.done() and scene.action.status=='unknown' and scene.action.finalized_at is not None
    assert any(a.stage=='provider_result' and a.reason=='delivery_not_confirmed' for a in db.audits)
    assert not await worker.dispatch_one(db,scene.action.id)
    provider.assert_awaited_once()
