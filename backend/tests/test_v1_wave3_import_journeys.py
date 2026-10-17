"""Independent mounted native HTTP journeys; only P01-migrated PostgreSQL.

No provider network, ORM create_all, source monkeypatch or production fallback.
The injected fetchers return literal synthetic documents after durable claims.
"""
import asyncio
import hashlib
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.database import get_db
from app.models.commerce import CommerceOrder, Storefront
from app.models.identity import Membership
from app.models.imports_v1 import ImportAsset, ImportAudit, ImportDraft, ImportJob
from app.models.product import Product
from app.models.seller import Seller
from app.services import imports_v1
from app.v1.imports.fetching import FetchedSource, FetchError


@pytest_asyncio.fixture
async def journey(migrated_engine, monkeypatch):
    from app.main import app
    monkeypatch.setattr(settings, 'V1_AUTH_ENABLED', True)
    monkeypatch.setattr(settings, 'V1_ENFORCE_LEGACY_ACCESS', True)
    monkeypatch.setattr(settings, 'PUBLIC_BASE_URL', 'http://test')
    monkeypatch.setattr(settings, 'V1_IMPORTS_ENABLED', False)
    sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async def database():
        async with sessions.begin() as db:
            yield db
    app.dependency_overrides[get_db] = database
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test', headers={'Origin': 'http://test'}) as client:
            result = await client.post('/api/v1/auth/signup', json={
                'email': f'{uuid4().hex}@example.com', 'password': 'synthetic-wave3-password',
                'business_name': 'Wave 3 independent QA'})
            assert result.status_code == 201, result.text
            owner = result.json()
            bid = UUID(owner['businesses'][0]['id'])
            yield SimpleNamespace(client=client, sessions=sessions, bid=bid, owner=owner,
                prefix=f'/api/v1/businesses/{bid}/imports', csrf={'X-CSRF-Token': client.cookies['v1_csrf']})
    finally:
        app.dependency_overrides.pop(get_db, None)


class SyntheticSource:
    def __init__(self, *, blocked=False, fail=False):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.blocked, self.fail, self.calls = blocked, fail, 0
    async def fetch(self, *args, **kwargs):
        self.calls += 1
        self.entered.set()
        if self.blocked:
            await self.release.wait()
        if self.fail:
            raise FetchError('fetch_timeout')
        return FetchedSource('https://shop.example.com/dress', 'application/ld+json',
            b'{"@type":"Product","sku":"dress","name":"Synthetic dress","description":"Literal QA source","offers":{"price":"1299","priceCurrency":"INR","availability":"https://schema.org/InStock"}}')


async def enqueue(j, **changes):
    body = {'idempotency_key': str(uuid4()), 'source_authorized': True,
        'source_kind': 'website', 'source_url': 'https://shop.example.com/dress', **changes}
    response = await j.client.post(j.prefix+'/jobs', headers=j.csrf, json=body)
    assert response.status_code == 202, response.text
    return response.json(), body


async def get_job(j, job):
    response = await j.client.get(j.prefix+'/jobs/'+job['job_id'])
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    return response.json()


async def candidates(j):
    response = await j.client.get(j.prefix+'/candidates')
    assert response.status_code == 200, response.text
    return response.json()['items']


@pytest.mark.asyncio
async def test_raw_upload_replay_conflict_and_reupload_preserve_original_identity(journey):
    j = journey
    raw = b'\x89PNG\r\n\x1a\nsynthetic-original-garment-bytes'
    key = str(uuid4())
    async def upload(content, operation_key):
        return await j.client.post(j.prefix+f'/uploads?idempotency_key={operation_key}&source_authorized=true',
            headers={**j.csrf, 'Content-Type': 'image/png'}, content=content)
    first = await upload(raw, key)
    assert first.status_code == 201, first.text
    assert (await upload(raw, key)).json() == first.json()
    assert (await upload(raw+b'changed', key)).status_code == 409
    another = await upload(raw, str(uuid4()))
    assert another.status_code == 201
    assert another.json()['asset_id'] != first.json()['asset_id']
    for uploaded in (first.json(), another.json()):
        job, _ = await enqueue(j, source_kind='uploaded_media', source_url=None, asset_id=uploaded['asset_id'])
        assert await imports_v1.run_job(j.sessions, j.bid, UUID(job['job_id']))
    rows = await candidates(j)
    assert len(rows) == 1
    assert all(value is None for value in rows[0]['candidate']['extracted'].values())
    async with j.sessions() as db:
        assets = (await db.scalars(select(ImportAsset).where(ImportAsset.business_id == j.bid))).all()
        assert len(assets) == 2 and all(bytes(asset.content) == raw for asset in assets)
        assert all(asset.sha256 == hashlib.sha256(raw).hexdigest() for asset in assets)
        assert await db.scalar(select(func.count()).select_from(Product)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('decision', ['cancel', 'revoke'])
async def test_request_during_inflight_retrieval_fences_late_source_results(journey, decision):
    j = journey
    job, _ = await enqueue(j)
    source = SyntheticSource(blocked=True)
    task = asyncio.create_task(imports_v1.run_job(j.sessions, j.bid, UUID(job['job_id']), fetcher=source))
    try:
        await asyncio.wait_for(source.entered.wait(), timeout=5)
        running = await get_job(j, job)
        assert running['state'] == 'running' and running['attempts'] == 1
        if decision == 'cancel':
            body = {'expected_revision': running['revision'], 'idempotency_key': str(uuid4())}
            cancelled = await j.client.post(j.prefix+f"/jobs/{job['job_id']}/cancel", headers=j.csrf, json=body)
            assert cancelled.status_code == 200, cancelled.text
            assert (await j.client.post(j.prefix+f"/jobs/{job['job_id']}/cancel", headers=j.csrf, json=body)).json() == cancelled.json()
        else:
            async with j.sessions.begin() as db:
                await db.execute(update(Membership).where(Membership.business_id == j.bid).values(role='viewer'))
        source.release.set()
        assert await asyncio.wait_for(task, timeout=5) is False
        final = await get_job(j, job)
        assert final['state'] == ('cancelled' if decision == 'cancel' else 'failed')
        assert final['error_code'] == (None if decision == 'cancel' else 'authorization_revoked')
        assert await candidates(j) == []
        assert source.calls == 1
    finally:
        source.release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_retry_persists_backoff_and_is_not_run_early_after_http_replay(journey):
    j = journey
    job, _ = await enqueue(j)
    failing = SyntheticSource(fail=True)
    assert not await imports_v1.run_job(j.sessions, j.bid, UUID(job['job_id']), fetcher=failing)
    failed = await get_job(j, job)
    assert failed['state'] == 'failed' and failed['error_code'] == 'fetch_timeout'
    body = {'expected_revision': failed['revision'], 'idempotency_key': str(uuid4())}
    response = await j.client.post(j.prefix+f"/jobs/{job['job_id']}/retry", headers=j.csrf, json=body)
    assert response.status_code == 202, response.text
    assert (await j.client.post(j.prefix+f"/jobs/{job['job_id']}/retry", headers=j.csrf, json=body)).json() == response.json()
    recovered = SyntheticSource()
    assert not await imports_v1.run_job(j.sessions, j.bid, UUID(job['job_id']), fetcher=recovered)
    assert recovered.calls == 0
    async with j.sessions.begin() as db:
        row = await db.get(ImportJob, UUID(job['job_id']))
        assert row.available_at > imports_v1.now() and row.attempts == 1
        # Advance only the synthetic persisted clock boundary, without a real sleep.
        row.available_at = imports_v1.now() - timedelta(seconds=1)
    assert await imports_v1.run_job(j.sessions, j.bid, UUID(job['job_id']), fetcher=recovered)
    assert (await get_job(j, job))['attempts'] == 2
    assert len(await candidates(j)) == 1
    assert (await j.client.post(j.prefix+f"/jobs/{job['job_id']}/retry", headers=j.csrf,
        json={**body, 'idempotency_key': str(uuid4())})).status_code == 409


@pytest.mark.asyncio
async def test_import_review_replay_preserves_unknown_stock_and_never_activates(journey):
    j = journey
    job, _ = await enqueue(j)
    assert await imports_v1.run_job(j.sessions, j.bid, UUID(job['job_id']), fetcher=SyntheticSource())
    candidate = (await candidates(j))[0]
    assert candidate['candidate']['extracted']['stock'] is None
    path = j.prefix+f"/candidates/{candidate['candidate_id']}/review"
    approve = {'expected_revision': candidate['revision'], 'idempotency_key': str(uuid4()), 'action': 'approve',
        'confirmed_fields': ['title', 'description', 'price', 'stock', 'options']}
    assert (await j.client.post(path, headers=j.csrf, json=approve)).status_code == 422
    edit = await j.client.post(path, headers=j.csrf, json={'expected_revision': candidate['revision'],
        'idempotency_key': str(uuid4()), 'action': 'edit', 'overrides': [{'field': 'stock', 'value': 3}, {'field': 'options', 'value': []}]})
    assert edit.status_code == 200, edit.text
    approve.update(expected_revision=edit.json()['revision'], idempotency_key=str(uuid4()))
    approved = await j.client.post(path, headers=j.csrf, json=approve)
    assert approved.status_code == 200, approved.text
    assert (await j.client.post(path, headers=j.csrf, json=approve)).json() == approved.json()
    assert approved.json()['candidate']['state'] == 'approved'
    assert approved.json()['candidate']['extracted']['stock'] is None
    assert approved.json()['catalogue_bridge_status'] == 'pending_reviewed_allocation'
    assert (await j.client.post(path, headers=j.csrf, json={**approve, 'idempotency_key': str(uuid4())})).status_code == 409
    async with j.sessions() as db:
        for model in (Product, Storefront, CommerceOrder):
            assert await db.scalar(select(func.count()).select_from(model)) == 0
        assert await db.scalar(select(func.count()).select_from(ImportDraft)) == 1
        assert await db.scalar(select(func.count()).select_from(ImportAudit).where(ImportAudit.action == 'approve')) == 1


@pytest.mark.asyncio
async def test_connected_instagram_failure_is_durable_and_truthful(journey):
    j = journey
    async with j.sessions.begin() as db:
        await db.execute(update(Seller).where(Seller.id == j.bid).values(instagram_page_id='synthetic-owned-account'))
    job, _ = await enqueue(j, source_kind='instagram', source_url=None, media_id='synthetic-media')
    assert not await imports_v1.run_job(j.sessions, j.bid, UUID(job['job_id']))
    result = await get_job(j, job)
    assert result['state'] == 'failed' and result['error_code'] == 'provider_capability_pending'
    assert result['candidate_count'] == 0 and await candidates(j) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['upload', 'job', 'cancel', 'retry', 'review'])
async def test_every_mounted_import_mutation_requires_bound_csrf_before_work(journey, mutation):
    j = journey
    paths = {
        'upload': (j.prefix+f'/uploads?idempotency_key={uuid4()}&source_authorized=true', {'content': b'\x89PNG\r\n\x1a\n'}),
        'job': (j.prefix+'/jobs', {'json': {'source_authorized': True, 'source_kind': 'website', 'source_url': 'https://shop.example.com/dress', 'idempotency_key': str(uuid4())}}),
        'cancel': (j.prefix+f'/jobs/{uuid4()}/cancel', {'json': {'expected_revision': 1, 'idempotency_key': str(uuid4())}}),
        'retry': (j.prefix+f'/jobs/{uuid4()}/retry', {'json': {'expected_revision': 1, 'idempotency_key': str(uuid4())}}),
        'review': (j.prefix+f'/candidates/{uuid4()}/review', {'json': {'expected_revision': 1, 'idempotency_key': str(uuid4()), 'action': 'reject', 'reason': 'Synthetic'}}),
    }
    path, payload = paths[mutation]
    response = await j.client.post(path, **payload)
    assert response.status_code == 403, response.text
    assert response.headers['cache-control'] == 'no-store'
    async with j.sessions() as db:
        for model in (ImportAsset, ImportJob, ImportDraft, ImportAudit):
            assert await db.scalar(select(func.count()).select_from(model)) == 0
