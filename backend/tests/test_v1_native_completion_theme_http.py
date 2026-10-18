"""Independent actual app mount + actual Alembic theme isolation/authority gates.

Fixtures are disposable synthetic tenants. No HTTP/domain projection is mocked.
The shared P01 fixture is the only connection/reset path.
"""
import asyncio
import json
from pathlib import Path
import re
from datetime import datetime, timezone
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import func, select, text, update

from app.models.commerce import Storefront
from app.models.identity import Business, Membership
from app.models.identity_auth import UserSession
from app.models.storefront_theme_v1 import StorefrontThemeCommand, StorefrontThemeSettings
from app.services.storefront_theme_v1 import view
from tests.test_v1_native_completion_import_http import native_import, wait_for_lock  # noqa: F401


def page_data(html):
    return json.loads(re.search(r'<script id="storefront-data" type="application/json">(.*?)</script>', html, re.S)[1])


def test_actual_theme_revision_is_registered_after_actual_parcel_revision():
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).parents[1] / 'alembic'))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_current_head() == '0050_v1_assistance'
    assert scripts.get_revision('0050_v1_assistance').down_revision == '0049_v1_storefront_settings'
    assert scripts.get_revision('0049_v1_storefront_settings').down_revision == '0048_v1_parcel_tracking'
    assert scripts.get_revision('0048_v1_parcel_tracking').down_revision == '0047_v1_import_catalogue_bridge'


@pytest.mark.asyncio
@pytest.mark.parametrize('theme', ['editorial', 'catalogue', 'video'])
async def test_actual_main_draft_preview_publish_public_ssr_and_query_authority(native_import, theme):
    j = native_import
    url = f'/api/v1/businesses/{j.bid}/theme-settings'
    async with j.sessions() as db:
        slug = (await db.get(Storefront, j.bid)).slug
        assert await db.scalar(text('SELECT version_num FROM alembic_version')) == '0050_v1_assistance'
    body = {'expected_version': 0, 'idempotency_key': str(uuid4()), 'config': {
        'theme': theme, 'palette': 'indigo', 'hero_headline': f'Published & {theme}',
        'story_body': 'Published seller story', 'show_story': True, 'show_categories': False}}
    saved = await j.client.put(url, headers=j.csrf, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()['version'] == 1 and saved.json()['published'] is None
    preview = await j.client.get(url+'/preview?theme=other&checkout=true')
    assert preview.status_code == 200 and f'Published &amp; {theme}' in preview.text
    assert preview.headers['cache-control'] == 'no-store' and '<script' not in preview.text
    public_path = f'/stores/{slug}'
    assert (await j.client.get(public_path+'?theme=video&preview=true&checkout=true')).status_code == 404
    published = await j.client.post(url+'/publish', headers=j.csrf, json={
        'expected_version': 1, 'idempotency_key': str(uuid4())})
    assert published.status_code == 200 and published.json()['published_revision'] == 2
    async with j.sessions.begin() as db:
        storefront = await db.get(Storefront, j.bid)
        assert storefront.published is False  # Design publication cannot publish the store.
        storefront.published = True  # Explicit synthetic fixture setup, separate authority.
    public = await j.client.get(public_path)
    assert public.status_code == 200, public.text
    data = page_data(public.text)
    assert data['store']['theme'] == theme and data['store']['design'] == published.json()['published']
    assert data['capabilities']['sku_checkout'] is False
    assert '<nav aria-label="Categories">' not in public.text
    assert 'Published &amp;' in public.text and 'Published seller story' in public.text
    private = await j.client.put(url, headers=j.csrf, json={'expected_version': 2,
        'idempotency_key': str(uuid4()), 'config': {'theme': 'video', 'hero_headline': 'NEVER_PUBLIC_PRIVATE_DRAFT'}})
    assert private.status_code == 200 and private.json()['version'] == 3
    for suffix in ('', '?theme=catalogue&preview=true&checkout=true'):
        current = await j.client.get(public_path+suffix)
        assert current.status_code == 200 and page_data(current.text) == data
        for secret in ('NEVER_PUBLIC_PRIVATE_DRAFT', 'draft_config', 'idempotency_key', 'actor_id', 'business_id', 'request_hash'):
            assert secret not in current.text
    assert (await j.client.put(url, headers=j.csrf, json=body)).json() == saved.json()
    async with j.sessions() as db:
        assert (await db.get(StorefrontThemeSettings, j.bid)).version == 3
        assert await db.scalar(select(func.count()).select_from(StorefrontThemeCommand).where(StorefrontThemeCommand.business_id == j.bid)) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('revocation', ['role', 'session'])
@pytest.mark.parametrize('operation', ['save', 'publish', 'replay_save', 'replay_publish'])
async def test_actual_main_observed_business_lock_wait_denies_theme_mutation_and_replay(native_import, revocation, operation):
    j = native_import
    url = f'/api/v1/businesses/{j.bid}/theme-settings'
    save = {'expected_version': 0, 'idempotency_key': str(uuid4()), 'config': {'theme': 'editorial'}}
    publish = {'expected_version': 1, 'idempotency_key': str(uuid4())}
    if operation != 'save':
        assert (await j.client.put(url, headers=j.csrf, json=save)).status_code == 200
    if operation == 'replay_publish':
        assert (await j.client.post(url+'/publish', headers=j.csrf, json=publish)).status_code == 200
    before = (await j.client.get(url)).json()
    async with j.sessions() as db:
        receipts = await db.scalar(select(func.count()).select_from(StorefrontThemeCommand).where(StorefrontThemeCommand.business_id == j.bid))
    task = None
    try:
        async with j.sessions() as blocker:
            pid = await blocker.scalar(text('SELECT pg_backend_pid()'))
            await blocker.scalar(select(Business).where(Business.id == j.bid).with_for_update())
            is_publish = 'publish' in operation
            task = asyncio.create_task(j.client.request('POST' if is_publish else 'PUT',
                url+('/publish' if is_publish else ''), headers=j.csrf, json=publish if is_publish else save))
            await wait_for_lock(blocker, pid)
            if revocation == 'role':
                await blocker.execute(update(Membership).where(Membership.business_id == j.bid).values(role='viewer'))
            else:
                await blocker.execute(update(UserSession).where(UserSession.user_id == j.uid).values(revoked_at=datetime.now(timezone.utc)))
            await blocker.commit()
        denied = await asyncio.wait_for(task, 5)
        assert denied.status_code == (403 if revocation == 'role' else 401), denied.text
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    async with j.sessions() as db:
        assert view(await db.get(StorefrontThemeSettings, j.bid)) == before
        assert await db.scalar(select(func.count()).select_from(StorefrontThemeCommand).where(StorefrontThemeCommand.business_id == j.bid)) == receipts


@pytest.mark.asyncio
async def test_actual_main_private_theme_mounts_require_native_session_before_db(monkeypatch):
    from app.main import app
    from app.config import settings
    from app.database import get_db
    from httpx import ASGITransport, AsyncClient
    monkeypatch.setattr(settings, 'V1_AUTH_ENABLED', True)
    async def opaque_database():
        yield object()  # An accidental query raises; session denial must precede DB access.
    app.dependency_overrides[get_db] = opaque_database
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            bid = uuid4()
            for path in (f'/v1/businesses/{bid}/themes', f'/api/v1/businesses/{bid}/theme-settings', f'/api/v1/businesses/{bid}/theme-settings/preview'):
                response = await client.get(path)
                assert response.status_code == 401, response.text
            assert (await client.put(f'/api/v1/businesses/{bid}/theme-settings', json={'expected_version': 0, 'idempotency_key': str(uuid4()), 'config': {}})).status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)
