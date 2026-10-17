"""Actual registered app, native session/CSRF, migrated durable import recovery."""
from uuid import uuid4
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.config import settings
from app.database import get_db
from app.v1.imports.fetching import FetchedSource
from app.v1.imports.runner import drain_jobs


@pytest.fixture
async def api(migrated_engine,monkeypatch):
    from app.main import app
    monkeypatch.setattr(settings,"V1_AUTH_ENABLED",True)
    monkeypatch.setattr(settings,"V1_ENFORCE_LEGACY_ACCESS",True)
    monkeypatch.setattr(settings,"PUBLIC_BASE_URL","http://test")
    factory=async_sessionmaker(migrated_engine,expire_on_commit=False)
    async def database():
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    app.dependency_overrides[get_db]=database
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test",headers={"Origin":"http://test"}) as c:
            yield c,factory
    finally:app.dependency_overrides.pop(get_db,None)


class FakeFetcher:
    calls=0
    async def fetch(self,*args,**kwargs):
        self.calls+=1
        return FetchedSource("https://shop.example.com/dress","application/ld+json",
            b'{"@type":"Product","sku":"dress","name":"Synthetic Dress","offers":{"price":"1299","priceCurrency":"INR"}}')


@pytest.mark.asyncio
async def test_registered_native_import_enqueue_recovery_review_and_privacy(api):
    c,factory=api
    password="synthetic-import-password"
    owner=(await c.post('/api/v1/auth/signup',json={"email":f"{uuid4().hex}@example.com","password":password,"business_name":"Native import fixture"})).json()
    bid=owner['businesses'][0]['id']
    prefix=f'/api/v1/businesses/{bid}/imports'
    csrf={"X-CSRF-Token":c.cookies['v1_csrf']}
    body={"idempotency_key":str(uuid4()),"source_authorized":True,"source_kind":"website","source_url":"https://shop.example.com/dress"}
    assert (await c.post(prefix+'/jobs',json=body)).status_code==403
    denied=await c.post(f'/api/v1/businesses/{uuid4()}/imports/jobs',headers=csrf,json=body)
    assert denied.status_code==404
    created=await c.post(prefix+'/jobs',headers=csrf,json=body)
    assert created.status_code==202,created.text
    assert created.headers['cache-control']=='no-store'
    assert created.json()['attempts']==0 and created.json()['state']=='pending'
    assert (await c.post(prefix+'/jobs',headers=csrf,json=body)).json()['job_id']==created.json()['job_id']
    assert (await c.post(prefix+'/jobs',headers=csrf,json={**body,'actor_id':owner['user_id']})).status_code==422
    # The scheduled task remains explicitly off; no fetch or queue service is called.
    from app.workers.v1_imports import recover_import_jobs
    assert not settings.V1_IMPORTS_ENABLED and recover_import_jobs()==0
    fetcher=FakeFetcher()
    assert await drain_jobs(factory,fetcher=fetcher)==1 and fetcher.calls==1
    assert await drain_jobs(factory,fetcher=fetcher)==0 and fetcher.calls==1
    candidates=await c.get(prefix+'/candidates')
    assert candidates.headers['cache-control']=='no-store'
    candidate=candidates.json()['items'][0]
    cid=candidate['candidate_id']
    edited=await c.post(prefix+f'/candidates/{cid}/review',headers=csrf,json={
        'idempotency_key':str(uuid4()),'expected_revision':candidate['revision'],'action':'edit',
        'overrides':[{'field':'stock','value':3},{'field':'options','value':[]}]})
    assert edited.status_code==200,edited.text
    from app.v1.imports import FactField
    approved=await c.post(prefix+f'/candidates/{cid}/review',headers=csrf,json={
        'idempotency_key':str(uuid4()),'expected_revision':edited.json()['revision'],'action':'approve',
        'confirmed_fields':[field.value for field in FactField]})
    assert approved.status_code==200,approved.text
    assert approved.json()['candidate']['state']=='approved'
    assert approved.json()['catalogue_bridge_status']=='pending_reviewed_allocation'
    # Unknown extracted stock was never turned into untracked inventory.
    assert candidate['candidate']['extracted']['stock'] is None
    assert approved.json()['candidate']['extracted']['stock'] is None
    # Shared mounted workspace is usable, private and links the real channel route.
    assert (await c.get('/v1')).headers['cache-control']=='no-store'
    onboarding=(await c.get(f'/api/v1/businesses/{bid}/onboarding')).json()
    channel=next(s for s in onboarding['steps'] if s['id']=='channels')
    assert channel['action_url']==f'/v1/businesses/{bid}/channels'
    assert (await c.get(channel['action_url'])).status_code==200
    # Same business staff can read drafts but never mutate/authorize a source.
    email=f"{uuid4().hex}@example.com"
    invitation=await c.post(f'/api/v1/businesses/{bid}/invitations',headers=csrf,json={'email':email,'role':'staff'})
    accepted=await c.post('/api/v1/auth/invitations/accept',json={'email':email,'password':password,'token':invitation.json()['invitation_url'].split('=',1)[1]})
    assert accepted.status_code==200
    staff_csrf={"X-CSRF-Token":c.cookies['v1_csrf']}
    assert (await c.get(prefix+'/candidates')).status_code==200
    assert (await c.post(prefix+'/jobs',headers=staff_csrf,json={**body,'idempotency_key':str(uuid4())})).status_code==403


@pytest.mark.asyncio
async def test_huge_upload_length_is_bounded_before_integer_conversion(api):
    c,_=api
    owner=(await c.post('/api/v1/auth/signup',json={'email':f'{uuid4().hex}@example.com','password':'synthetic-password','business_name':'Header fixture'})).json()
    bid=owner['businesses'][0]['id']
    response=await c.post(f'/api/v1/businesses/{bid}/imports/uploads?idempotency_key={uuid4()}&source_authorized=true',
        headers={'X-CSRF-Token':c.cookies['v1_csrf'],'Content-Type':'image/png','Content-Length':'9'*4400},content=b'\x89PNG\r\n\x1a\n')
    assert response.status_code==413
    assert response.headers['cache-control']=='no-store'


def test_import_worker_registration_defaults_off(monkeypatch):
    from app.workers.celery_app import celery_app
    from app.workers import v1_imports
    monkeypatch.setattr(settings,'V1_IMPORTS_ENABLED',False)
    assert v1_imports.recover_import_jobs()==0
    assert 'app.workers.v1_imports' in celery_app.conf.include
    assert any(item['task']=='app.workers.v1_imports.recover_import_jobs' for item in celery_app.conf.beat_schedule.values())


def test_import_task_shutdown_does_not_wait_for_abandoned_transport_task():
    import os
    from pathlib import Path
    import subprocess
    import sys
    # Bound the regression process itself: a future accidental gather-all helper
    # must fail quickly instead of hanging the complete verification run.
    script='''from tests.safety import install_test_safety
install_test_safety()
import asyncio
from app.config import settings
from app.workers import v1_imports
settings.V1_IMPORTS_ENABLED=True
cancelled=[]
async def abandoned():
    try: await asyncio.Event().wait()
    finally: cancelled.append(True)
async def drain():
    asyncio.create_task(abandoned())
    await asyncio.sleep(0)
    return 7
v1_imports._drain=drain
assert v1_imports.recover_import_jobs()==7
assert cancelled==[True]
'''
    result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ),capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stderr
