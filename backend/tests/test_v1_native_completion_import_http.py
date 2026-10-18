"""Independent actual-main HTTP allocation checks on actual P01 Alembic DB.

Only fixture source facts are synthetic. No API/domain writer is mocked, no
provider is contacted, and no schema is manufactured with create_all.
"""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.database import get_db
from app.models.catalogue_v1 import CatalogueSKU
from app.models.checkout_v1 import CatalogueActivation, CatalogueStorePolicy
from app.models.commerce import Storefront
from app.models.identity import Business, Membership
from app.models.identity_auth import UserSession
from app.models.import_catalogue import ImportCatalogueBridge
from app.models.imports_v1 import ImportDraft, ImportJob
from app.models.product import Product
from app.v1.imports import parse_candidate

FIELDS = ['title', 'description', 'price', 'stock', 'options']


@pytest_asyncio.fixture
async def native_import(migrated_engine, monkeypatch):
    from app.main import app
    from app.api.v1.storefront_bootstrap import install_storefront
    original_routes = list(app.router.routes)
    original_startup = list(app.router.on_startup)
    original_middleware = list(app.user_middleware)
    original_stack = app.middleware_stack
    original_overrides = dict(app.dependency_overrides)
    monkeypatch.setattr(settings, 'V1_AUTH_ENABLED', True)
    monkeypatch.setattr(settings, 'V1_ENFORCE_LEGACY_ACCESS', True)
    monkeypatch.setattr(settings, 'V1_IMPORT_BRIDGE_ENABLED', True)
    monkeypatch.setattr(settings, 'PUBLIC_BASE_URL', 'https://independent-canonical.example.test')
    monkeypatch.setattr(settings, 'V1_STOREFRONT_ENABLED', True)
    # app.main may have been imported while the default-off flag was false.
    # Install the actual bootstrap only when its real public route is absent.
    sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)
    async def database():
        async with sessions.begin() as db:
            yield db
    app.dependency_overrides[get_db] = database
    try:
        if not any(getattr(route, 'path', None) == '/stores/{slug}' for route in app.router.routes):
            # Test-only reconstruction of the shared process app. Production
            # installs middleware before serving; restore its whole prior state.
            app.middleware_stack = None
            install_storefront(app)
        # Canonical HTTPS makes native cookies Secure; use HTTPS ASGI requests
        # as well so the real cookie jar exercises authentication correctly.
        async with AsyncClient(transport=ASGITransport(app=app), base_url='https://test', headers={'Origin': 'https://test'}) as client:
            response = await client.post('/api/v1/auth/signup', json={
                'email': f'{uuid4().hex}@example.com', 'password': 'synthetic-independent-qa-password',
                'business_name': 'Independent completion QA'})
            assert response.status_code == 201, response.text
            owner = response.json()
            bid, uid = UUID(owner['businesses'][0]['id']), UUID(owner['user_id'])
            async with sessions.begin() as db:
                db.add(Storefront(seller_id=bid, slug=uuid4().hex, name='Private QA boutique',
                    currency='INR', published=False, cod_enabled=True))
            yield SimpleNamespace(client=client, sessions=sessions, bid=bid, uid=uid,
                prefix=f'/api/v1/businesses/{bid}/imports/candidates',
                csrf={'X-CSRF-Token': client.cookies['v1_csrf']})
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)
        app.router.routes[:] = original_routes
        app.router.on_startup[:] = original_startup
        app.user_middleware[:] = original_middleware
        app.middleware_stack = original_stack


async def seed(j, **changes):
    jid = uuid4()
    facts = dict(title='Literal independent dress', description='Synthetic QA source',
        price={'amount': '12.50', 'currency': 'INR'}, stock=5,
        options=[{'name': 'Size', 'values': ['S', 'M']}, {'name': 'Colour', 'values': ['Red', 'Blue']}])
    facts.update(changes)
    candidate = parse_candidate({'provenance': dict(business_id=j.bid, import_job_id=jid,
        captured_at=datetime.now(timezone.utc), source={'kind': 'website', 'url': 'https://shop.example.com/dress'},
        source_product_id=uuid4().hex), 'facts': facts}, business_id=j.bid)
    async with j.sessions.begin() as db:
        db.add(ImportJob(id=jid, business_id=j.bid, creator_id=j.uid, idempotency_key=uuid4(),
            request_hash='a'*64, source={'kind': 'website'}))
        await db.flush()
        db.add(ImportDraft(id=candidate.id, business_id=j.bid, last_job_id=jid, document=candidate.model_dump(mode='json')))
    return candidate


def command():
    return dict(idempotency_key=str(uuid4()), expected_revision=1, seller_reviewed=True,
        confirmed_fields=FIELDS, allocations=[
            {'options': {'Size': 'S', 'Colour': 'Red'}, 'stock_available': 2, 'active': True},
            {'options': {'Size': 'S', 'Colour': 'Blue'}, 'stock_available': 1, 'active': True},
            {'options': {'Size': 'M', 'Colour': 'Red'}, 'stock_available': 2, 'active': True},
            {'options': {'Size': 'M', 'Colour': 'Blue'}, 'stock_available': 0, 'active': False}])


async def post(j, candidate, body):
    return await j.client.post(f'{j.prefix}/{candidate.id}/catalogue-draft', headers=j.csrf, json=body)


async def private_counts(j):
    async with j.sessions() as db:
        return [await db.scalar(select(func.count()).select_from(model).where(model.business_id == j.bid))
            for model in (ImportCatalogueBridge, CatalogueActivation)]


@pytest.mark.asyncio
async def test_actual_main_explicit_four_combo_private_receipt_replay(native_import):
    j = native_import
    candidate = await seed(j)
    preview = await j.client.get(f'{j.prefix}/{candidate.id}/catalogue-preview')
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data['state'] == 'needs_review' and data['candidate_revision'] == 1
    assert len(data['allocations']) == 4 and all(row['stock_available'] is None for row in data['allocations'])
    body = command()
    created = await post(j, candidate, body)
    assert created.status_code == 201, created.text
    receipt = created.json()
    assert receipt['creation_mode'] == 'private_draft' and receipt['candidate_revision'] == 2
    replay = await post(j, candidate, body)
    assert replay.status_code == 200, replay.text
    assert replay.json() == {**receipt, 'replayed': True}
    assert (await j.client.get(f'{j.prefix}/{candidate.id}/catalogue-preview')).json()['existing']['product_id'] == receipt['product_id']
    async with j.sessions() as db:
        product = await db.get(Product, UUID(receipt['product_id']))
        assert product.active is False and product.stock_quantity == 5 and product.listed_price == 1250
        skus = (await db.scalars(select(CatalogueSKU).where(CatalogueSKU.product_id == product.id))).all()
        assert len(skus) == 4 and sorted(row.stock_available for row in skus) == [0, 1, 2, 2]
        assert (await db.get(Storefront, j.bid)).published is False
        policy = await db.get(CatalogueStorePolicy, j.bid)
        assert policy is None or policy.checkout_enabled is False
        draft = await db.get(ImportDraft, candidate.id)
        assert draft.document['extracted'] == candidate.model_dump(mode='json')['extracted']
    assert await private_counts(j) == [1, 0]


@pytest.mark.asyncio
@pytest.mark.parametrize('invalid', ['missing_combo', 'duplicate_combo', 'unknown_combo', 'wrong_total', 'non_integer', 'stale', 'browser_facts'])
async def test_actual_main_invalid_allocation_never_approves_or_creates(native_import, invalid):
    j = native_import
    candidate, body = await seed(j), command()
    if invalid == 'missing_combo': body['allocations'].pop()
    if invalid == 'duplicate_combo': body['allocations'][-1] = body['allocations'][0]
    if invalid == 'unknown_combo': body['allocations'][0]['options']['Size'] = 'XL'
    if invalid == 'wrong_total': body['allocations'][0]['stock_available'] = 10
    if invalid == 'non_integer': body['allocations'][0]['stock_available'] = True
    if invalid == 'stale': body['expected_revision'] = 99
    if invalid == 'browser_facts': body['title'] = 'Browser authority forbidden'
    response = await post(j, candidate, body)
    assert response.status_code == (409 if invalid == 'stale' else 422), response.text
    async with j.sessions() as db:
        draft = await db.get(ImportDraft, candidate.id)
        assert draft.revision == 1 and draft.document['state'] == 'pending'
        assert await db.scalar(select(func.count()).select_from(Product).where(Product.seller_id == j.bid)) == 0
    assert await private_counts(j) == [0, 0]


@pytest.mark.asyncio
@pytest.mark.parametrize('facts', [{'stock': None}, {'options': None}, {'price': {'amount': '12.50', 'currency': 'USD'}}])
async def test_actual_main_unknown_or_unsupported_facts_remain_blocked(native_import, facts):
    j = native_import
    candidate = await seed(j, **facts)
    preview = await j.client.get(f'{j.prefix}/{candidate.id}/catalogue-preview')
    assert preview.status_code == 200 and preview.json()['state'] == 'unsupported'
    assert preview.json()['facts']['stock'] == facts.get('stock', 5)
    assert (await post(j, candidate, command())).status_code == 422
    assert await private_counts(j) == [0, 0]


@pytest.mark.asyncio
async def test_actual_main_csrf_tenant_disabled_and_current_role(native_import, monkeypatch):
    j = native_import
    candidate, body = await seed(j), command()
    path = f'{j.prefix}/{candidate.id}/catalogue-draft'
    assert (await j.client.post(path, json=body)).status_code == 403
    assert (await j.client.post(path, json=body, headers={**j.csrf, 'Origin': 'https://foreign.example.test'})).status_code == 403
    assert (await j.client.post(path.replace(str(j.bid), str(uuid4())), json=body, headers=j.csrf)).status_code == 404
    monkeypatch.setattr(settings, 'V1_IMPORT_BRIDGE_ENABLED', False)
    assert (await post(j, candidate, body)).status_code == 404
    monkeypatch.setattr(settings, 'V1_IMPORT_BRIDGE_ENABLED', True)
    async with j.sessions.begin() as db:
        await db.execute(update(Membership).where(Membership.business_id == j.bid).values(role='viewer'))
    assert (await post(j, candidate, body)).status_code == 403
    assert await private_counts(j) == [0, 0]


@pytest.mark.asyncio
async def test_actual_main_reimport_changes_do_not_overwrite_linked_inventory(native_import):
    j = native_import
    candidate, body = await seed(j), command()
    first = await post(j, candidate, body)
    assert first.status_code == 201, first.text
    async with j.sessions.begin() as db:
        draft = await db.get(ImportDraft, candidate.id)
        document = dict(draft.document)
        document['extracted'] = {**document['extracted'], 'stock': 500}
        await db.execute(update(ImportDraft).where(ImportDraft.id == candidate.id).values(document=document, revision=3))
    assert (await post(j, candidate, body)).json()['product_id'] == first.json()['product_id']
    fresh = await post(j, candidate, {**body, 'idempotency_key': str(uuid4()), 'expected_revision': 3})
    assert fresh.status_code == 409 and fresh.json()['detail']['code'] == 'candidate_already_created'
    async with j.sessions() as db:
        assert (await db.get(Product, UUID(first.json()['product_id']))).stock_quantity == 5
    assert await private_counts(j) == [1, 0]


async def wait_for_lock(blocker, pid):
    for _ in range(200):
        await blocker.execute(text('SELECT pg_stat_clear_snapshot()'))
        if await blocker.scalar(text('SELECT count(*) FROM pg_stat_activity WHERE :pid = ANY(pg_blocking_pids(pid))'), {'pid': pid}):
            return
        await asyncio.sleep(.01)
    pytest.fail('Actual PostgreSQL mutation never entered the expected row-lock wait')


@pytest.mark.asyncio
@pytest.mark.parametrize('revocation', ['role', 'session'])
@pytest.mark.parametrize('replay', [False, True])
async def test_actual_main_current_revocation_after_business_wait_blocks_new_and_replay(native_import, revocation, replay):
    j = native_import
    candidate, body = await seed(j), command()
    if replay:
        created = await post(j, candidate, body)
        assert created.status_code == 201, created.text
    task = None
    try:
        async with j.sessions() as blocker:
            pid = await blocker.scalar(text('SELECT pg_backend_pid()'))
            await blocker.scalar(select(Business).where(Business.id == j.bid).with_for_update())
            task = asyncio.create_task(post(j, candidate, body))
            await wait_for_lock(blocker, pid)
            if revocation == 'role':
                await blocker.execute(update(Membership).where(Membership.business_id == j.bid).values(role='viewer'))
            else:
                await blocker.execute(update(UserSession).where(UserSession.user_id == j.uid).values(revoked_at=datetime.now(timezone.utc)))
            await blocker.commit()
        response = await asyncio.wait_for(task, 5)
        assert response.status_code == (403 if revocation == 'role' else 401), response.text
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert await private_counts(j) == [int(replay), 0]
