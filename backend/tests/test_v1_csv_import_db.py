"""Actual 0053/P01 and mounted native HTTP; CSV never invokes providers."""
import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text, update

from app.models.imports_v1 import ImportAsset, ImportDraft, ImportJob
from app.models.identity import Membership
from app.models.identity_auth import UserSession
from app.models.product import Product
from app.models.checkout_v1 import CatalogueActivation
from app.schemas.imports_v1 import CandidateReviewWrite, JobMutation
from app.services import imports_v1 as service
from app.services.identity import Actor
from tests.test_v1_native_completion_import_http import native_import  # actual main + P01 fixture

DATA = b'product_ref,title,description,price,currency,stock,options_state\nA,Dress,Source description,12.50,INR,0,none\nB,Unknown,,,,,unknown\n'


async def upload(j, body=DATA, key=None, *, content_type='text/csv'):
    return await j.client.post(f'/api/v1/businesses/{j.bid}/imports/uploads',
        params={'idempotency_key':str(key or uuid4()),'source_authorized':'true'}, content=body,
        headers={**j.csrf,'Content-Type':content_type})


async def job(j, asset, document=None, key=None, **extra):
    body=dict(source_authorized=True,source_kind='csv',asset_id=asset,
        document_id=str(document or uuid4()),document_label='Seller source',idempotency_key=str(key or uuid4()))
    return await j.client.post(f'/api/v1/businesses/{j.bid}/imports/jobs',json=body|extra,headers=j.csrf)


@pytest.mark.asyncio
async def test_csv_actual_chain_original_bytes_exact_commands_and_type_binding(native_import):
    j=native_import
    key=uuid4()
    first=await upload(j,key=key); assert first.status_code==201,first.text
    asset=first.json()['asset_id']
    assert (await upload(j,key=key)).json()==first.json()
    assert (await upload(j,DATA+b'\n',key=key)).status_code==409
    assert (await upload(j,b'x'*256001)).status_code==413
    document,key=uuid4(),uuid4()
    one,two=await asyncio.gather(job(j,asset,document,key),job(j,asset,document,key))
    assert one.status_code==two.status_code==202 and one.json()['job_id']==two.json()['job_id']
    assert (await job(j,asset,document,key,document_label='Changed')).status_code==409
    media=await j.client.post(f'/api/v1/businesses/{j.bid}/imports/jobs',json={
        'idempotency_key':str(uuid4()),'source_authorized':True,'source_kind':'uploaded_media','asset_id':asset},headers=j.csrf)
    assert media.status_code==422
    png=await upload(j,b'\x89PNG\r\n\x1a\nsynthetic',content_type='image/png')
    assert png.status_code==201,png.text
    assert (await job(j,png.json()['asset_id'])).status_code==422
    async with j.sessions() as db:
        assert await db.scalar(text('SELECT version_num FROM alembic_version'))=='0053_v1_csv_import'
        original=await db.get(ImportAsset,UUID(asset)); assert original.content==DATA
        assert original.creator_id==j.uid and original.authorized_at and original.sha256==first.json()['sha256']
        assert await db.scalar(select(func.count()).select_from(ImportJob).where(ImportJob.business_id==j.bid))==1


@pytest.mark.asyncio
async def test_csv_whole_file_atomic_failure_cancel_retry_and_fenced_result(native_import):
    j=native_import
    asset=(await upload(j,DATA+b'A,Duplicate,,,,,unknown\n')).json()['asset_id']
    created=(await job(j,asset)).json(); jid=UUID(created['job_id'])
    assert not await service.run_job(j.sessions,j.bid,jid)
    async with j.sessions.begin() as db:
        stored=await db.get(ImportJob,jid)
        assert stored.state=='failed' and stored.error_code=='csv_duplicate_ref:line_4:product_ref'
        assert await db.scalar(select(func.count()).select_from(ImportDraft).where(ImportDraft.business_id==j.bid))==0
        retry=await service.mutate_job(db,Actor(j.uid,'v1_user'),j.bid,jid,
            JobMutation(expected_revision=stored.revision,idempotency_key=uuid4()),action='retry')
        stored.available_at=service.now()-timedelta(seconds=1)
    async with j.sessions.begin() as db:
        claim=await service.claim_job(db,j.bid,jid)
    async with j.sessions.begin() as db:
        stored=await db.get(ImportJob,jid)
        await service.mutate_job(db,Actor(j.uid,'v1_user'),j.bid,jid,
            JobMutation(expected_revision=stored.revision,idempotency_key=uuid4()),action='cancel')
    async with j.sessions.begin() as db:
        assert not await service.finish_claim(db,claim,error_code='source_adapter_failed')
        assert (await db.get(ImportJob,jid)).state=='cancelled'


@pytest.mark.asyncio
async def test_csv_document_reimport_preserves_override_zero_private_bridge_and_exact_receipt(native_import):
    j=native_import; document=uuid4()
    async def ingest(body):
        asset=(await upload(j,body)).json()['asset_id']
        created=(await job(j,asset,document)).json()
        assert await service.run_job(j.sessions,j.bid,UUID(created['job_id']))
        return created
    first=await ingest(DATA)
    records=(await j.client.get(f'/api/v1/businesses/{j.bid}/imports/candidates')).json()['items']
    record=next(r for r in records if r['candidate']['provenance']['source_product_id']=='A')
    assert record['candidate']['extracted']['stock']==0 and record['candidate']['extracted']['options']==[]
    assert 'Source description' not in record['candidate']['provenance']['evidence']
    cid=record['candidate_id']; root=f'/api/v1/businesses/{j.bid}/imports/candidates/{cid}'
    corrected=await j.client.post(root+'/review',headers=j.csrf,json={
        'expected_revision':record['revision'],'idempotency_key':str(uuid4()),'action':'edit',
        'overrides':[{'field':'title','value':'Seller correction'}]})
    assert corrected.status_code==200,corrected.text
    bridge=dict(expected_revision=corrected.json()['revision'],idempotency_key=str(uuid4()),seller_reviewed=True,
        confirmed_fields=['title','description','price','stock','options'],allocations=[{'options':{},'stock_available':0,'active':True}])
    receipt=await j.client.post(root+'/catalogue-draft',json=bridge,headers=j.csrf)
    assert receipt.status_code==201,receipt.text
    second=await ingest(DATA.replace(b'A,Dress',b'A,Changed').replace(b'12.50',b'99.00'))
    assert second['job_id']!=first['job_id']
    replay=await j.client.post(root+'/catalogue-draft',json=bridge,headers=j.csrf)
    assert replay.status_code==200 and replay.json()=={**receipt.json(),'replayed':True}
    async with j.sessions() as db:
        rows=(await db.scalars(select(ImportDraft).where(ImportDraft.business_id==j.bid))).all()
        assert len(rows)==2
        current=service.ImportCandidate.model_validate(next(r.document for r in rows if str(r.id)==cid))
        assert current.effective_facts().title=='Seller correction' and str(current.extracted.price.amount)=='99.00'
        product=await db.get(Product,UUID(receipt.json()['product_id']))
        assert product.name=='Seller correction'
        assert await db.scalar(select(func.count()).select_from(CatalogueActivation).where(CatalogueActivation.business_id==j.bid))==0
    await ingest(b'product_ref,title\nA,Only A')
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ImportDraft).where(ImportDraft.business_id==j.bid))==2
    # Missing rows do not delete the existing B candidate; different document is
    # intentionally a different source even if it uploads identical bytes.
    asset=(await upload(j)).json()['asset_id']; third=await job(j,asset)
    assert await service.run_job(j.sessions,j.bid,UUID(third.json()['job_id']))
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ImportDraft).where(ImportDraft.business_id==j.bid))==4


@pytest.mark.asyncio
async def test_csv_native_csrf_foreign_asset_and_current_role_boundaries(native_import):
    j=native_import
    missing=await j.client.post(f'/api/v1/businesses/{j.bid}/imports/uploads',
        params={'idempotency_key':str(uuid4()),'source_authorized':'true'},content=DATA,headers={'Content-Type':'text/csv'})
    assert missing.status_code==403
    foreign=await j.client.post(f'/api/v1/businesses/{uuid4()}/imports/uploads',
        params={'idempotency_key':str(uuid4()),'source_authorized':'true'},content=DATA,headers={**j.csrf,'Content-Type':'text/csv'})
    assert foreign.status_code==404
    assert (await job(j,str(uuid4()))).status_code==404
    async with j.sessions.begin() as db:
        await db.execute(update(Membership).where(Membership.user_id==j.uid).values(role='viewer'))
    assert (await upload(j)).status_code==403
    assert (await j.client.get(f'/api/v1/businesses/{j.bid}/imports/jobs')).status_code==200


@pytest.mark.asyncio
@pytest.mark.parametrize('operation',['upload','create'])
@pytest.mark.parametrize('revocation',['session','role'])
async def test_csv_native_lock_wait_rechecks_and_rolls_back(native_import, operation, revocation):
    from app.models.identity import Business
    j=native_import; asset=None
    if operation=='create':asset=(await upload(j)).json()['asset_id']
    task=None
    try:
        async with j.sessions() as holder:
            pid=await holder.scalar(text('SELECT pg_backend_pid()'))
            await holder.scalar(select(Business.id).where(Business.id==j.bid).with_for_update())
            task=asyncio.create_task(upload(j) if operation=='upload' else job(j,asset))
            for _ in range(200):
                await holder.execute(text('SELECT pg_stat_clear_snapshot()'))
                waiting=await holder.scalar(text('SELECT count(*) FROM pg_stat_activity WHERE :pid=ANY(pg_blocking_pids(pid))'),{'pid':pid})
                if waiting:break
                await asyncio.sleep(.01)
            assert waiting
            if revocation=='role':
                await holder.execute(update(Membership).where(Membership.user_id==j.uid).values(role='viewer'))
            else:
                await holder.execute(update(UserSession).where(UserSession.user_id==j.uid).values(revoked_at=service.now()))
            await holder.commit()
            response=await asyncio.wait_for(task,8)
            assert response.status_code==(403 if revocation=='role' else 401),response.text
        async with j.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(ImportJob).where(ImportJob.business_id==j.bid))==0
            assert await db.scalar(select(func.count()).select_from(ImportAsset).where(ImportAsset.business_id==j.bid))==(1 if asset else 0)
    finally:
        if task is not None and not task.done():
            task.cancel();await asyncio.gather(task,return_exceptions=True)


@pytest.mark.asyncio
async def test_csv_upload_revoke_while_body_streams_and_foreign_asset_is_private(native_import):
    from tests.test_v1_import_jobs_db import seed
    from app.schemas.imports_v1 import UploadCreate
    j=native_import
    other,actor=await seed(j.sessions)
    async with j.sessions.begin() as db:
        foreign=await service.put_upload(db,actor,other,UploadCreate(idempotency_key=uuid4(),source_authorized=True,content_type='text/csv'),content=DATA)
    assert (await job(j,str(foreign.asset_id))).status_code==404
    async def stream():
        yield DATA[:10]
        async with j.sessions.begin() as db:
            await db.execute(update(UserSession).where(UserSession.user_id==j.uid).values(revoked_at=service.now()))
        yield DATA[10:]
    response=await j.client.post(f'/api/v1/businesses/{j.bid}/imports/uploads',
        params={'idempotency_key':str(uuid4()),'source_authorized':'true'},content=stream(),
        headers={**j.csrf,'Content-Type':'text/csv'})
    assert response.status_code==401,response.text
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ImportAsset).where(ImportAsset.business_id==j.bid))==0


@pytest.mark.asyncio
async def test_csv_stale_source_capture_cannot_overwrite_newer_document(native_import):
    j=native_import; doc=uuid4()
    old=(await job(j,(await upload(j)).json()['asset_id'],doc)).json()
    async with j.sessions.begin() as db:
        claim=await service.claim_job(db,j.bid,UUID(old['job_id']))
    incoming=await service.collect_claim(claim,fetcher=None)
    new=(await job(j,(await upload(j,DATA.replace(b'A,Dress',b'A,Newer'))).json()['asset_id'],doc)).json()
    assert await service.run_job(j.sessions,j.bid,UUID(new['job_id']))
    async with j.sessions.begin() as db:
        assert await service.finish_claim(db,claim,candidates=incoming)
    async with j.sessions() as db:
        records=await service.list_candidates(db,Actor(j.uid,'v1_user'),j.bid)
        assert next(r for r in records if r.candidate['provenance']['source_product_id']=='A').candidate['extracted']['title']=='Newer'


@pytest.mark.asyncio
async def test_legacy_job_request_hash_survives_csv_optional_fields(native_import):
    from app.schemas.imports_v1 import ImportJobCreate
    j=native_import
    payload=ImportJobCreate(idempotency_key=uuid4(),source_authorized=True,source_kind='website',source_url='https://example.com/product')
    before_csv=payload.model_dump(mode='json',exclude={'document_id','document_label'})
    async with j.sessions.begin() as db:
        first=await service.create_job(db,Actor(j.uid,'v1_user'),j.bid,payload)
        stored=await db.get(ImportJob,first.job_id)
        assert stored.request_hash==service.digest(before_csv)
    async with j.sessions.begin() as db:
        assert (await service.create_job(db,Actor(j.uid,'v1_user'),j.bid,payload)).job_id==first.job_id


@pytest.mark.asyncio
async def test_csv_late_claim_of_older_queued_file_does_not_rewind_document(native_import):
    j=native_import; doc=uuid4()
    old=(await job(j,(await upload(j)).json()['asset_id'],doc)).json()
    new=(await job(j,(await upload(j,DATA.replace(b'A,Dress',b'A,Latest accepted file'))).json()['asset_id'],doc)).json()
    assert await service.run_job(j.sessions,j.bid,UUID(new['job_id']))
    # This old file starts its worker only after the newer job has completed.
    assert await service.run_job(j.sessions,j.bid,UUID(old['job_id']))
    async with j.sessions() as db:
        records=await service.list_candidates(db,Actor(j.uid,'v1_user'),j.bid)
        row=next(r for r in records if r.candidate['provenance']['source_product_id']=='A')
        assert row.candidate['extracted']['title']=='Latest accepted file'
        assert row.candidate['provenance']['import_job_id']==new['job_id']
        assert row.candidate['provenance']['captured_at']==new['created_at']
