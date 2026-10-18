"""Typed rejection is issued only after receipt lookup and before domain writes."""
from uuid import uuid4
import pytest
from sqlalchemy import select,func
from app.models.storefront_theme_v1 import StorefrontThemeCommand
from app.models.imports_v1 import ImportAudit,ImportDraft,ImportJob
from app.models.import_catalogue import ImportCatalogueBridge
from app.models.product import Product
from tests.test_v1_native_completion_import_http import command,post
from types import SimpleNamespace
from uuid import UUID
import pytest_asyncio
from httpx import AsyncClient,ASGITransport
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.config import settings
from app.database import get_db
from app.models.commerce import Storefront

@pytest_asyncio.fixture
async def native_import(migrated_engine,monkeypatch):
    from app.main import app
    monkeypatch.setattr(settings,"V1_AUTH_ENABLED",True)
    monkeypatch.setattr(settings,"V1_ENFORCE_LEGACY_ACCESS",True)
    monkeypatch.setattr(settings,"V1_IMPORT_BRIDGE_ENABLED",True)
    monkeypatch.setattr(settings,"PUBLIC_BASE_URL","http://test")
    sessions=async_sessionmaker(migrated_engine,expire_on_commit=False)
    async def database():
        async with sessions.begin() as db:yield db
    app.dependency_overrides[get_db]=database
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test",headers={"Origin":"http://test"}) as client:
            response=await client.post("/api/v1/auth/signup",json={"email":f"{uuid4().hex}@example.com","password":"synthetic-native-recovery-password","business_name":"Synthetic Recovery Boutique"})
            assert response.status_code==201,response.text
            owner=response.json();bid,uid=UUID(owner["businesses"][0]["id"]),UUID(owner["user_id"])
            async with sessions.begin() as db:db.add(Storefront(seller_id=bid,slug=uuid4().hex,name="Synthetic Recovery Boutique",currency="INR",published=False,cod_enabled=True))
            yield SimpleNamespace(client=client,sessions=sessions,bid=bid,uid=uid,prefix=f"/api/v1/businesses/{bid}/imports/candidates",csrf={"X-CSRF-Token":client.cookies["v1_csrf"]})
    finally:app.dependency_overrides.pop(get_db,None)


async def seed(j):
    from datetime import datetime,timezone
    from app.v1.imports import parse_candidate
    jid=uuid4()
    candidate=parse_candidate({'provenance':{'business_id':j.bid,'import_job_id':jid,'captured_at':datetime.now(timezone.utc),'source':{'kind':'website','url':'https://shop.example.com/dress'},'source_product_id':uuid4().hex},'facts':{'title':'Synthetic recovery dress','description':'Synthetic source','price':{'amount':'12.50','currency':'INR'},'stock':5,'options':[{'name':'Size','values':['S','M']},{'name':'Colour','values':['Red','Blue']}]}},business_id=j.bid)
    async with j.sessions.begin() as db:
        db.add(ImportJob(id=jid,business_id=j.bid,creator_id=j.uid,idempotency_key=uuid4(),request_hash='a'*64,source={'kind':'website'}));await db.flush()
        db.add(ImportDraft(id=candidate.id,business_id=j.bid,last_job_id=jid,document=candidate.model_dump(mode='json')))
    return candidate

@pytest.mark.asyncio
async def test_theme_stale_is_typed_no_receipt_and_accepted_replay_precedes_version_check(native_import):
    j=native_import;path=f'/api/v1/businesses/{j.bid}/theme-settings'
    first={'expected_version':0,'idempotency_key':str(uuid4()),'config':{'hero_headline':'Original saved facts'}}
    saved=await j.client.put(path,headers=j.csrf,json=first);assert saved.status_code==200,saved.text
    second={'expected_version':1,'idempotency_key':str(uuid4()),'config':{'hero_headline':'Later saved facts'}}
    assert (await j.client.put(path,headers=j.csrf,json=second)).status_code==200
    assert (await j.client.put(path,headers=j.csrf,json=first)).json()==saved.json()
    stale={**first,'idempotency_key':str(uuid4())}
    rejected=await j.client.put(path,headers=j.csrf,json=stale)
    assert rejected.status_code==409 and rejected.json()['detail']['code']=='theme_version_stale'
    collision=await j.client.put(path,headers=j.csrf,json={**first,'config':{'hero_headline':'Different command'}})
    assert collision.status_code==409 and isinstance(collision.json()['detail'],str)
    current=(await j.client.get(path)).json();assert current['version']==2 and current['draft']['hero_headline']=='Later saved facts'
    async with j.sessions() as db:assert await db.scalar(select(func.count()).select_from(StorefrontThemeCommand))==2

@pytest.mark.asyncio
async def test_import_job_stale_is_typed_before_write_and_replay_before_revision_check(native_import):
    j=native_import;root=f'/api/v1/businesses/{j.bid}/imports'
    response=await j.client.post(root+'/jobs',headers=j.csrf,json={'idempotency_key':str(uuid4()),'source_kind':'website','source_url':'https://shop.example.com/item','source_authorized':True})
    assert response.status_code==202,response.text
    job=response.json()['job_id'];path=root+'/jobs/'+job+'/cancel';body={'expected_revision':1,'idempotency_key':str(uuid4())}
    accepted=await j.client.post(path,headers=j.csrf,json=body);assert accepted.status_code==200,accepted.text
    assert (await j.client.post(path,headers=j.csrf,json=body)).json()==accepted.json()
    stale=await j.client.post(path,headers=j.csrf,json={**body,'idempotency_key':str(uuid4())})
    assert stale.status_code==409 and stale.json()['detail']['code']=='import_revision_stale'
    async with j.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ImportAudit))==1
        row=await db.scalar(select(ImportJob));assert row.revision==2 and row.state=='cancelled'

@pytest.mark.asyncio
async def test_candidate_review_and_bridge_stale_are_typed_without_draft_or_audit(native_import):
    j=native_import;candidate=await seed(j)
    reviewed=await j.client.post(f'{j.prefix}/{candidate.id}/review',headers=j.csrf,json={'idempotency_key':str(uuid4()),'expected_revision':2,'action':'reject','reason':'Synthetic reviewed stale source'})
    assert reviewed.status_code==409 and reviewed.json()['detail']['code']=='import_revision_stale'
    body={**command(),'expected_revision':2};bridge=await post(j,candidate,body)
    assert bridge.status_code==409 and bridge.json()['detail']['code']=='import_revision_stale'
    async with j.sessions() as db:
        assert (await db.get(ImportDraft,candidate.id)).revision==1
        for model in (ImportAudit,ImportCatalogueBridge,Product):assert await db.scalar(select(func.count()).select_from(model))==0
