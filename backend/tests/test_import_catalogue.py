"""Approval bridge behavior on P01-owned PG16, always actual Alembic DDL."""
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.models.identity import Business, Membership, User
from app.models.imports_v1 import ImportDraft, ImportJob, ImportAudit
from app.models.import_catalogue import ImportCatalogueBridge
from app.models.product import Product
from app.models.seller import Seller
from app.models.commerce import Storefront
from app.models.catalogue_v1 import CatalogueSKU
from app.models.checkout_v1 import CatalogueActivation, CatalogueStorePolicy
from app.schemas.import_catalogue import ImportCatalogueWrite
from app.services.identity import Actor
from app.services import import_catalogue as service
from app.v1.imports import FactField, parse_candidate


FIELDS = [field.value for field in FactField]


def command(**changes):
    return ImportCatalogueWrite.model_validate({**dict(idempotency_key=str(uuid4()), expected_revision=1,
        seller_reviewed=True, confirmed_fields=FIELDS,
        allocations=[dict(options={}, stock_available=4, active=True)]), **changes})


@pytest.fixture
async def setup(migrated_engine, monkeypatch):
    monkeypatch.setattr(settings, 'V1_IMPORT_BRIDGE_ENABLED', True)
    factory = async_sessionmaker(migrated_engine, expire_on_commit=False)
    bid, uid, jid = uuid4(), uuid4(), uuid4()
    actor = Actor(uid, 'native')
    candidate = parse_candidate({'provenance':dict(business_id=bid, import_job_id=jid,
        captured_at=datetime.now(timezone.utc), source=dict(kind='website',url='https://shop.example.com/dress'),
        source_product_id='synthetic-dress'), 'facts':dict(title='Source dress',description=None,
        price=dict(amount='1499.50',currency='INR'),stock=4,options=[])},business_id=bid)
    async with factory() as db:
        db.add(Seller(id=bid, email=f'{bid}@example.com',password_hash='synthetic',is_active=True))
        await db.flush()
        db.add_all([Business(id=bid,name='Synthetic'),User(id=uid,display_name='Reviewer')]);await db.flush()
        db.add_all([Membership(id=uuid4(),business_id=bid,user_id=uid,role='owner'),
            Storefront(seller_id=bid,slug=bid.hex,name='Synthetic',currency='INR',published=False),
            ImportJob(id=jid,business_id=bid,creator_id=uid,idempotency_key=uuid4(),request_hash='a'*64,
                source=dict(kind='website'))]);await db.flush()
        db.add(ImportDraft(id=candidate.id,business_id=bid,last_job_id=jid,document=candidate.model_dump(mode='json')))
        await db.commit()
    return factory,actor,bid,candidate


@pytest.mark.asyncio
async def test_atomic_approval_private_creation_and_exact_replay(setup):
    factory,actor,bid,candidate=setup
    payload=command()
    async with factory() as db:
        preview=await service.preview(db,actor,bid,candidate.id)
        assert preview.state=='needs_review' and preview.allocations[0]['stock_available']==4
        result=await service.create_draft(db,actor,bid,candidate.id,payload)
        await db.commit()
        assert not result.replayed and result.candidate_revision==2
        receipt=await db.get(ImportCatalogueBridge,result.receipt_id)
        assert receipt.creation_snapshot['review']==payload.model_dump(mode='json')
        assert receipt.approved_snapshot['provenance']==candidate.model_dump(mode='json')['provenance']
    async with factory() as db:
        draft=await db.get(ImportDraft,candidate.id)
        assert draft.document['state']=='approved' and draft.document['extracted']==candidate.model_dump(mode='json')['extracted']
        product=await db.get(Product,result.product_id)
        assert product.active is False and product.stock_quantity==4 and product.listed_price==149950
        sku=await db.scalar(select(CatalogueSKU).where(CatalogueSKU.product_id==product.id))
        assert sku.stock_available==4 and sku.price_minor==149950
        assert not await db.scalar(select(CatalogueActivation).where(CatalogueActivation.product_id==product.id))
        assert not await db.scalar(select(CatalogueStorePolicy).where(CatalogueStorePolicy.business_id==bid))
        replay=await service.create_draft(db,actor,bid,candidate.id,payload)
        assert replay.replayed and replay.product_id==result.product_id
        assert (await service.preview(db,actor,bid,candidate.id)).state=='already_created'
        assert await db.scalar(select(func.count()).select_from(ImportAudit).where(ImportAudit.business_id==bid))==1


@pytest.mark.asyncio
async def test_transaction_rollback_leaves_neither_approval_nor_product(setup):
    factory,actor,bid,candidate=setup
    async with factory() as db:
        await service.create_draft(db,actor,bid,candidate.id,command())
        await db.rollback()
    async with factory() as db:
        row=await db.get(ImportDraft,candidate.id)
        assert row.revision==1 and row.document['state']=='pending'
        assert not await db.scalar(select(Product.id).where(Product.seller_id==bid))
        assert not await db.scalar(select(ImportCatalogueBridge.id).where(ImportCatalogueBridge.business_id==bid))


@pytest.mark.asyncio
async def test_concurrent_same_command_produces_one_product(setup):
    factory,actor,bid,candidate=setup
    payload=command()
    async def create():
        async with factory() as db:
            result=await service.create_draft(db,actor,bid,candidate.id,payload)
            await db.commit()
            return result
    one,two=await asyncio.wait_for(asyncio.gather(create(),create()),10)
    assert one.product_id==two.product_id and {one.replayed,two.replayed}=={True,False}
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(Product).where(Product.seller_id==bid))==1


@pytest.mark.asyncio
async def test_reimport_keeps_receipt_retry_but_blocks_second_creation(setup):
    factory,actor,bid,candidate=setup
    payload=command()
    async with factory() as db:
        original=await service.create_draft(db,actor,bid,candidate.id,payload);await db.commit()
    async with factory() as db:
        document=candidate.model_dump(mode='json');document['extracted']['stock']=20
        await db.execute(update(ImportDraft).where(ImportDraft.id==candidate.id).values(document=document,revision=3));await db.commit()
    async with factory() as db:
        assert (await service.create_draft(db,actor,bid,candidate.id,payload)).product_id==original.product_id
        with pytest.raises(HTTPException) as error:
            await service.create_draft(db,actor,bid,candidate.id,command(expected_revision=3))
        assert error.value.status_code==409 and error.value.detail['code']=='candidate_already_created'
        assert (await db.get(Product,original.product_id)).stock_quantity==4


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['stale','unknown_stock','unknown_options','currency','allocation','category','photo','key_collision','disabled'])
async def test_invalid_commands_are_atomic(setup,change,monkeypatch):
    factory,actor,bid,candidate=setup
    kwargs={}
    async with factory() as db:
        document=candidate.model_dump(mode='json')
        if change=='stale':kwargs['expected_revision']=2
        if change=='unknown_stock':document['extracted']['stock']=None
        if change=='unknown_options':document['extracted']['options']=None
        if change=='currency':document['extracted']['price']['currency']='USD'
        if change=='allocation':kwargs['allocations']=[dict(options={},stock_available=3,active=True)]
        if change=='category':kwargs['category_id']=uuid4()
        if change=='photo':kwargs['photo_urls']=['https://user:secret@example.com/a.png']
        if change=='disabled':monkeypatch.setattr(settings,'V1_IMPORT_BRIDGE_ENABLED',False)
        payload=command(**kwargs)
        if change=='key_collision':
            db.add(ImportAudit(business_id=bid,actor_id=actor.user_id,idempotency_key=payload.idempotency_key,
                request_hash='f'*64,action='synthetic',details={}))
        await db.execute(update(ImportDraft).where(ImportDraft.id==candidate.id).values(document=document));await db.commit()
    async with factory() as db:
        with pytest.raises((HTTPException,ValueError)):
            await service.create_draft(db,actor,bid,candidate.id,payload)
        await db.rollback()
    async with factory() as db:
        assert (await db.get(ImportDraft,candidate.id)).revision==1
        assert not await db.scalar(select(Product.id).where(Product.seller_id==bid))


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['staff','viewer','revoked','inactive_user','inactive_business','inactive_seller','foreign'])
async def test_current_authority_and_tenant_negative(setup,kind):
    factory,actor,bid,candidate=setup
    async with factory() as db:
        if kind in ('staff','viewer','revoked'):
            await db.execute(update(Membership).where(Membership.business_id==bid).values(
                **({'role':kind} if kind!='revoked' else {'revoked_at':datetime.now(timezone.utc)})))
        if kind=='inactive_user':await db.execute(update(User).where(User.id==actor.user_id).values(is_active=False))
        if kind=='inactive_business':await db.execute(update(Business).where(Business.id==bid).values(is_active=False))
        if kind=='inactive_seller':await db.execute(update(Seller).where(Seller.id==bid).values(is_active=False))
        await db.commit()
    async with factory() as db:
        with pytest.raises(HTTPException) as error:
            await service.create_draft(db,actor,uuid4() if kind=='foreign' else bid,candidate.id,command())
        assert error.value.status_code in (401,403,404)


def test_allocation_cartesian_exactness_and_unknown_preserved():
    from app.v1.imports import DraftFacts
    facts=DraftFacts(title='Dress',price={'amount':'10','currency':'INR'},stock=4,
        options=[{'name':'Size','values':['S','M']},{'name':'Colour','values':['Red','Blue']}])
    allocations=[{'options':options,'stock_available':1,'active':True} for options in service.combinations(facts)]
    assert len(service.canonical_skus(facts,command(allocations=allocations).allocations))==4
    for invalid in [allocations[:3],allocations[:3]+[allocations[0]],
                    [{**row,'stock_available':2} for row in allocations]]:
        with pytest.raises(ValueError):service.canonical_skus(facts,command(allocations=invalid).allocations)
    unknown=DraftFacts(title='Unknown',price={'amount':'10','currency':'INR'},stock=None,options=[])
    with pytest.raises(ValueError):service.combinations(unknown)
    assert unknown.stock is None


@pytest.mark.asyncio
async def test_revocation_during_store_lock_wait_fails_current_authority(setup):
    factory,actor,bid,candidate=setup
    from sqlalchemy import text
    task = None
    try:
        async with factory() as blocker:
            blocker_pid = await blocker.scalar(text('SELECT pg_backend_pid()'))
            await blocker.scalar(select(Storefront).where(Storefront.seller_id==bid).with_for_update())
            async def create():
                async with factory() as db:
                    try:
                        await service.create_draft(db,actor,bid,candidate.id,command())
                    finally:
                        await db.rollback()
            task=asyncio.create_task(create())
            for _ in range(200):
                await blocker.execute(text('SELECT pg_stat_clear_snapshot()'))
                waiting=await blocker.scalar(text('SELECT count(*) FROM pg_stat_activity WHERE :pid = ANY(pg_blocking_pids(pid))'),{'pid':blocker_pid})
                if waiting:break
                await asyncio.sleep(.01)
            assert waiting
            await blocker.execute(update(Membership).where(Membership.business_id==bid).values(role='viewer'))
            await blocker.commit()
            with pytest.raises(HTTPException) as error:await asyncio.wait_for(task,5)
            assert error.value.status_code==403
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
    async with factory() as db:
        assert not await db.scalar(select(Product.id).where(Product.seller_id==bid))


@pytest.mark.asyncio
async def test_changed_key_payload_and_cross_candidate_cannot_replay(setup):
    factory,actor,bid,candidate=setup
    payload=command()
    async with factory() as db:
        await service.create_draft(db,actor,bid,candidate.id,payload);await db.commit()
    async with factory() as db:
        with pytest.raises(HTTPException) as error:
            await service.create_draft(db,actor,bid,candidate.id,command(idempotency_key=payload.idempotency_key,
                photo_urls=['https://images.example.com/reviewed.png']))
        assert error.value.status_code==409
        with pytest.raises(HTTPException) as error:
            await service.create_draft(db,actor,bid,uuid4(),payload)
        assert error.value.status_code==409
        await db.execute(update(Membership).where(Membership.business_id==bid).values(role='viewer'));await db.commit()
        with pytest.raises(HTTPException) as error:
            await service.create_draft(db,actor,bid,candidate.id,payload)
        assert error.value.status_code==403


@pytest.mark.asyncio
async def test_native_api_csrf_bounded_body_and_storefront_ready(setup, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.database import get_db
    from app.api.v1.auth import router as auth_router
    from app.api.v1.import_catalogue import router
    factory,_,_,_=setup
    monkeypatch.setattr(settings,'V1_AUTH_ENABLED',True)
    monkeypatch.setattr(settings,'PUBLIC_BASE_URL','http://test')
    app=FastAPI();app.include_router(auth_router);app.include_router(router)
    async def database():
        async with factory() as db:
            try:yield db;await db.commit()
            except Exception:await db.rollback();raise
    app.dependency_overrides[get_db]=database
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test',headers={'Origin':'http://test'}) as client:
        response=await client.post('/api/v1/auth/signup',json={'email':f'{uuid4().hex}@example.com',
            'password':'synthetic-native-password','business_name':'Native bridge'})
        assert response.status_code==201,response.text
        owner=response.json();bid=owner['businesses'][0]['id'];uid=owner['user_id'];jid=uuid4()
        candidate=parse_candidate({'provenance':dict(business_id=bid,import_job_id=jid,
            captured_at=datetime.now(timezone.utc),source=dict(kind='website',url='https://shop.example.com/product'),
            source_product_id='http-dress'),'facts':dict(title='Native dress',price=dict(amount='12.50',currency='INR'),
            stock=4,options=[])},business_id=__import__('uuid').UUID(bid))
        async with factory() as db:
            db.add(ImportJob(id=jid,business_id=bid,creator_id=uid,idempotency_key=uuid4(),request_hash='a'*64,source={}));await db.flush()
            db.add(ImportDraft(id=candidate.id,business_id=bid,last_job_id=jid,document=candidate.model_dump(mode='json')));await db.commit()
        path=f'/api/v1/businesses/{bid}/imports/candidates/{candidate.id}'
        body=command().model_dump(mode='json');csrf={'X-CSRF-Token':client.cookies['v1_csrf']}
        assert (await client.get(path+'/catalogue-preview')).json()['issues']==['Configure the storefront before creating a catalogue draft']
        assert (await client.post(path+'/catalogue-draft',json=body)).status_code==403
        assert (await client.post(path+'/catalogue-draft',json=body,headers={**csrf,'Origin':'https://foreign.example.com'})).status_code==403
        assert (await client.post(path+'/catalogue-draft',content=b'{}',headers={**csrf,'Content-Length':'9'*5000})).status_code==413
        assert (await client.post(path+'/catalogue-draft',content=b'{"idempotency_key":1,"idempotency_key":2}',headers=csrf)).status_code==422
        assert (await client.post(path+'/catalogue-draft',json={**body,'business_id':bid},headers=csrf)).status_code==422
        assert (await client.post(path+'/catalogue-draft',json=body,headers=csrf)).status_code==409
        async with factory() as db:
            db.add(Storefront(seller_id=bid,slug=uuid4().hex,name='Native',currency='INR'));await db.commit()
        created=await client.post(path+'/catalogue-draft',json=body,headers=csrf)
        assert created.status_code==201,created.text
        replay=await client.post(path+'/catalogue-draft',json=body,headers=csrf)
        assert replay.status_code==200 and replay.json()['product_id']==created.json()['product_id']
        assert (await client.post(path.replace(bid,str(uuid4()))+'/catalogue-draft',json=body,headers=csrf)).status_code==404
        # Native session invalidation while waiting must precede any write.
        next_candidate=candidate.model_copy(update={'id':uuid4()})
        async with factory() as db:
            db.add(ImportDraft(id=next_candidate.id,business_id=bid,last_job_id=jid,
                document=next_candidate.model_dump(mode='json')));await db.commit()
        next_path=f'/api/v1/businesses/{bid}/imports/candidates/{next_candidate.id}/catalogue-draft'
        task=None
        from sqlalchemy import text
        from app.models.identity_auth import UserSession
        try:
            async with factory() as blocker:
                pid=await blocker.scalar(text('SELECT pg_backend_pid()'))
                await blocker.scalar(select(Storefront).where(Storefront.seller_id==bid).with_for_update())
                task=asyncio.create_task(client.post(next_path,json=command().model_dump(mode='json'),headers=csrf))
                for _ in range(200):
                    await blocker.execute(text('SELECT pg_stat_clear_snapshot()'))
                    waiting=await blocker.scalar(text('SELECT count(*) FROM pg_stat_activity WHERE :pid = ANY(pg_blocking_pids(pid))'),{'pid':pid})
                    if waiting:break
                    await asyncio.sleep(.01)
                assert waiting
                await blocker.execute(update(UserSession).where(UserSession.user_id==uid).values(revoked_at=datetime.now(timezone.utc)))
                await blocker.commit()
                denied=await asyncio.wait_for(task,5)
                assert denied.status_code==401,denied.text
        finally:
            if task is not None and not task.done():
                task.cancel();await asyncio.gather(task,return_exceptions=True)
        async with factory() as db:
            assert (await db.get(ImportDraft,next_candidate.id)).revision==1
            assert await db.scalar(select(func.count()).select_from(Product).where(Product.seller_id==bid))==1


def test_strict_review_command_rejects_inferred_or_unbounded_facts():
    from pydantic import ValidationError
    valid=command().model_dump(mode='json')
    for patch in [dict(seller_reviewed=1),dict(confirmed_fields=['stock']*5),
                  dict(allocations=[dict(options={},stock_available=None,active=True)]),
                  dict(allocations=[dict(options={},stock_available=True,active=True)]),
                  dict(allocations=[dict(options={},stock_available=4,active=1)]),
                  dict(expected_revision=True),dict(title='Browser supplied facts'),
                  dict(product_id=str(uuid4()))]:
        with pytest.raises(ValidationError):ImportCatalogueWrite.model_validate({**valid,**patch})


@pytest.mark.asyncio
async def test_reauthorization_after_wait_rolls_back_on_revoked_session(setup):
    factory,actor,bid,candidate=setup
    calls=[]
    async def session_check():
        calls.append(True)
        if len(calls)==2:raise HTTPException(401,'Session revoked during allocation lock wait')
    async with factory() as db:
        with pytest.raises(HTTPException) as error:
            await service.create_draft(db,actor,bid,candidate.id,command(),reauthorize=session_check)
        assert error.value.status_code==401 and len(calls)==2
        await db.rollback()
    async with factory() as db:
        assert (await db.get(ImportDraft,candidate.id)).revision==1
        assert not await db.scalar(select(Product.id).where(Product.seller_id==bid))


@pytest.mark.asyncio
async def test_preview_exposes_disabled_creation_without_changing_unknown_facts(setup,monkeypatch):
    factory,actor,bid,candidate=setup
    monkeypatch.setattr(settings,'V1_IMPORT_BRIDGE_ENABLED',False)
    async with factory() as db:
        result=await service.preview(db,actor,bid,candidate.id)
        assert result.state=='unsupported'
        assert 'Import catalogue creation is not enabled' in result.issues
        assert result.facts['stock']==4
