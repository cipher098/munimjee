"""Theme boundaries and native HTTP/persistence checks on P01's real migration chain."""
from uuid import UUID, uuid4
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.v1.auth import router as auth_router
from app.api.v1.theme_settings import router, preview_html
from app.config import settings
from app.database import get_db
from app.models.identity import Membership
from app.models.storefront_theme_v1 import StorefrontThemeCommand, StorefrontThemeSettings
from app.schemas.storefront_theme_v1 import ThemeConfig, ThemeDraftWrite, ThemePublishWrite
from app.services.storefront_theme_v1 import published_theme


@pytest.mark.parametrize('extra', [{'business_id':str(uuid4())},{'actor_id':str(uuid4())},{'reviewed':True},{'css':'body{}'},{'html':'<b>hi</b>'},{'logo_url':'https://example.com/x'}])
def test_theme_config_rejects_extra_authority_and_executable_fields(extra):
    with pytest.raises(ValidationError):
        ThemeConfig.model_validate(extra)


@pytest.mark.parametrize('field,value',[('theme','unknown'),('palette','#ffffff'),('show_story','true'),('show_categories',1),('story_body','<script>bad</script>'),('hero_intro','bad\x00text'),('hero_headline','x'*101)])
def test_theme_config_rejects_invalid_values(field,value):
    with pytest.raises(ValidationError):
        ThemeConfig.model_validate({field:value})


@pytest.mark.parametrize('theme',['editorial','catalogue','video'])
def test_all_theme_previews_escape_and_disable_capabilities(theme):
    html=preview_html(ThemeConfig(theme=theme,hero_headline='A & B',story_body='Safe story').model_dump(),'"Synthetic & Boutique"')
    assert f'data-theme="{theme}"' in html
    assert 'A &amp; B' in html and '&quot;Synthetic &amp; Boutique&quot;' in html
    assert 'noindex,nofollow' in html and 'checkout unavailable' in html
    assert '<script' not in html and '<form' not in html and 'fetch(' not in html and '/api/' not in html
    hidden=preview_html(ThemeConfig(theme=theme,show_story=False,show_categories=False).model_dump(),'Boutique')
    assert 'class="story"' not in hidden and '<nav' not in hidden


@pytest.mark.parametrize('payload',[
    {'expected_version':True,'idempotency_key':str(uuid4()),'config':{}},
    {'expected_version':0,'idempotency_key':str(uuid4()),'config':{},'business_id':str(uuid4())},
    {'expected_version':0,'idempotency_key':'bad','config':{}},
])
def test_command_schema_is_strict(payload):
    with pytest.raises(ValidationError):ThemeDraftWrite.model_validate(payload)


def test_design_publish_requires_saved_version():
    with pytest.raises(ValidationError):ThemePublishWrite(expected_version=0,idempotency_key=uuid4())


@pytest.fixture
async def theme_client(migrated_engine, monkeypatch):
    async with migrated_engine.connect() as connection:
        tables=await connection.run_sync(lambda c: inspect(c).get_table_names())
    if not {'storefront_theme_settings_v1','storefront_theme_commands_v1'}.issubset(tables):
        pytest.skip('Theme DB gate pending: integrator-reserved migration and model registration are not applied')
    monkeypatch.setattr(settings,'V1_AUTH_ENABLED',True)
    monkeypatch.setattr(settings,'PUBLIC_BASE_URL','http://test')
    app=FastAPI();app.include_router(auth_router);app.include_router(router)
    factory=async_sessionmaker(migrated_engine,expire_on_commit=False)
    async def database():
        async with factory() as db:
            try:yield db;await db.commit()
            except Exception:await db.rollback();raise
    app.dependency_overrides[get_db]=database
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test',headers={'Origin':'http://test'}) as c:
        c.factory=factory
        yield c


async def signup(c):
    response=await c.post('/api/v1/auth/signup',json={'email':f'{uuid4().hex}@example.com','password':'synthetic-password-123','business_name':'Synthetic Theme Boutique'})
    assert response.status_code==201,response.text
    data=response.json()
    return data['businesses'][0]['id'],data['user_id']


def csrf(c):return {'X-CSRF-Token':c.cookies.get('v1_csrf','')}
def draft(version=0,**config):return {'expected_version':version,'idempotency_key':str(uuid4()),'config':config}


@pytest.mark.asyncio
async def test_theme_persistence_save_publish_replay_and_public_draft_isolation(theme_client):
    c=theme_client;bid,uid=await signup(c);url=f'/api/v1/businesses/{bid}/theme-settings'
    initial=await c.get(url);assert initial.status_code==200
    assert initial.json()['version']==0 and initial.json()['published'] is None
    body=draft(theme='editorial',hero_headline='Saved first draft')
    saved=await c.put(url,json=body,headers=csrf(c));assert saved.status_code==200,saved.text
    assert saved.json()['version']==1 and saved.json()['published'] is None
    async with c.factory() as db:
        assert (await published_theme(db,UUID(bid)))['theme']=='catalogue'
    publish={'expected_version':1,'idempotency_key':str(uuid4())}
    live=await c.post(url+'/publish',json=publish,headers=csrf(c));assert live.status_code==200,live.text
    assert live.json()['published_revision']==2 and live.json()['published']['theme']=='editorial'
    newer=draft(2,theme='video',hero_headline='Private video draft')
    assert (await c.put(url,json=newer,headers=csrf(c))).json()['version']==3
    assert (await c.put(url,json=body,headers=csrf(c))).json()==saved.json()
    assert (await c.post(url+'/publish',json=publish,headers=csrf(c))).json()==live.json()
    assert (await c.get(url)).json()['version']==3
    async with c.factory() as db:
        assert (await published_theme(db,UUID(bid)))['theme']=='editorial'
        assert (await db.get(StorefrontThemeSettings,UUID(bid))).draft_config['theme']=='video'
        receipts=(await db.scalars(select(StorefrontThemeCommand).where(StorefrontThemeCommand.business_id==UUID(bid)))).all()
        assert len(receipts)==3


@pytest.mark.asyncio
async def test_theme_conflicts_reject_changed_key_body_and_stale_version(theme_client):
    c=theme_client;bid,_=await signup(c);url=f'/api/v1/businesses/{bid}/theme-settings';body=draft(theme='video')
    assert (await c.put(url,json=body,headers=csrf(c))).status_code==200
    changed={**body,'config':{'theme':'editorial'}}
    assert (await c.put(url,json=changed,headers=csrf(c))).status_code==409
    assert (await c.put(url,json=draft(0,theme='editorial'),headers=csrf(c))).status_code==409
    assert (await c.post(url+'/publish',json={'expected_version':2,'idempotency_key':str(uuid4())},headers=csrf(c))).status_code==409
    assert (await c.get(url)).json()['draft']['theme']=='video'


@pytest.mark.asyncio
@pytest.mark.parametrize('role',['viewer','staff','manager','owner'])
async def test_theme_current_roles_native_csrf_and_tenant_scope(theme_client,role):
    c=theme_client;bid,uid=await signup(c);url=f'/api/v1/businesses/{bid}/theme-settings'
    async with c.factory() as db:
        member=await db.scalar(select(Membership).where(Membership.user_id==UUID(uid),Membership.business_id==UUID(bid)))
        member.role=role;await db.commit()
    assert (await c.get(url)).status_code==200
    assert (await c.put(url,json=draft(theme='video'))).status_code==403
    response=await c.put(url,json=draft(theme='video'),headers=csrf(c))
    assert response.status_code==(200 if role in {'manager','owner'} else 403),response.text
    assert (await c.get(f'/api/v1/businesses/{uuid4()}/theme-settings')).status_code==404
    assert (await c.put(f'/api/v1/businesses/{uuid4()}/theme-settings',json=draft(),headers=csrf(c))).status_code==404
    assert (await c.post('/api/v1/auth/logout',headers=csrf(c))).status_code==200
    assert (await c.get(url)).status_code==401


@pytest.mark.asyncio
async def test_theme_preview_and_workspace_are_private_and_no_query_enables_checkout(theme_client):
    c=theme_client;bid,_=await signup(c);url=f'/api/v1/businesses/{bid}/theme-settings'
    for path in [f'/v1/businesses/{bid}/themes',url,url+'/preview?checkout=true&theme=video']:
        response=await c.get(path);assert response.status_code==200,response.text
        assert response.headers['cache-control']=='no-store'
        assert response.headers['x-robots-tag']=='noindex, nofollow'
    preview=await c.get(url+'/preview?checkout=true&theme=video')
    assert 'data-theme="catalogue"' in preview.text and '<script' not in preview.text
    assert "default-src 'none'" in preview.headers['content-security-policy']
    assert (await c.get(f'/api/v1/businesses/{uuid4()}/theme-settings/preview')).status_code==404


@pytest.mark.asyncio
async def test_theme_writes_do_not_create_or_publish_commerce_rows(theme_client):
    from app.models.commerce import Storefront
    from app.models.checkout_v1 import CatalogueActivation,CatalogueStorePolicy
    c=theme_client;bid,_=await signup(c);url=f'/api/v1/businesses/{bid}/theme-settings'
    assert (await c.put(url,json=draft(theme='editorial'),headers=csrf(c))).status_code==200
    assert (await c.post(url+'/publish',json={'expected_version':1,'idempotency_key':str(uuid4())},headers=csrf(c))).status_code==200
    async with c.factory() as db:
        assert await db.scalar(select(Storefront).where(Storefront.seller_id==UUID(bid))) is None
        assert await db.get(CatalogueStorePolicy,UUID(bid)) is None
        assert await db.scalar(select(CatalogueActivation).where(CatalogueActivation.business_id==UUID(bid))) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('same_key',[False,True])
async def test_theme_concurrent_first_saves_are_serialized(theme_client,same_key):
    import asyncio
    c=theme_client;bid,_=await signup(c);url=f'/api/v1/businesses/{bid}/theme-settings'
    first=draft(theme='editorial');second=first if same_key else draft(theme='video')
    responses=await asyncio.gather(c.put(url,json=first,headers=csrf(c)),c.put(url,json=second,headers=csrf(c)))
    assert sorted(r.status_code for r in responses)==([200,200] if same_key else [200,409])
    if same_key:assert responses[0].json()==responses[1].json()
    async with c.factory() as db:
        assert (await db.get(StorefrontThemeSettings,UUID(bid))).version==1
        receipts=(await db.scalars(select(StorefrontThemeCommand).where(StorefrontThemeCommand.business_id==UUID(bid)))).all()
        assert len(receipts)==1


@pytest.mark.asyncio
async def test_theme_rechecks_downgrade_while_waiting_on_business_lock(theme_client,monkeypatch):
    import asyncio
    from app.models.identity import Business
    from app.services import storefront_theme_v1 as domain
    c=theme_client;bid,uid=await signup(c);url=f'/api/v1/businesses/{bid}/theme-settings'
    authorized=asyncio.Event();original=domain.authorize
    async def checked(*args,**kwargs):
        result=await original(*args,**kwargs);authorized.set();return result
    monkeypatch.setattr(domain,'authorize',checked)
    async with c.factory() as holder:
        await holder.scalar(select(Business.id).where(Business.id==UUID(bid)).with_for_update())
        request=asyncio.create_task(c.put(url,json=draft(theme='video'),headers=csrf(c)))
        try:
            await asyncio.wait_for(authorized.wait(),3)
            membership=await holder.scalar(select(Membership).where(Membership.user_id==UUID(uid),Membership.business_id==UUID(bid)))
            membership.role='viewer';await holder.commit()
            response=await asyncio.wait_for(request,3)
        finally:
            if not request.done():request.cancel()
    assert response.status_code==403,response.text
    async with c.factory() as db:
        assert await db.get(StorefrontThemeSettings,UUID(bid)) is None


@pytest.mark.asyncio
async def test_theme_routes_deny_missing_native_session_without_database(monkeypatch):
    monkeypatch.setattr(settings,'V1_AUTH_ENABLED',True)
    app=FastAPI();app.include_router(router)
    async def no_database():yield object()
    app.dependency_overrides[get_db]=no_database
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as c:
        bid=uuid4()
        for url in [f'/v1/businesses/{bid}/themes',f'/api/v1/businesses/{bid}/theme-settings',f'/api/v1/businesses/{bid}/theme-settings/preview']:
            assert (await c.get(url)).status_code==401
        monkeypatch.setattr(settings,'V1_AUTH_ENABLED',False)
        assert (await c.get(f'/v1/businesses/{bid}/themes')).status_code==404


@pytest.mark.asyncio
@pytest.mark.parametrize('revocation',['role','session'])
@pytest.mark.parametrize('command',['save','publish','replay_save','replay_publish'])
async def test_theme_mutation_guard_rejects_revocation_during_lock_wait_including_replay(theme_client,monkeypatch,revocation,command):
    """Actual Alembic DB/HTTP: no successful receipt escapes revoked authority."""
    import asyncio
    from datetime import datetime,timezone
    from app.models.identity import Business
    from app.models.identity_auth import UserSession
    from app.services import storefront_theme_v1 as domain
    c=theme_client;bid,uid=await signup(c);url=f'/api/v1/businesses/{bid}/theme-settings'
    saved_body=draft(theme='editorial');publish_body={'expected_version':1,'idempotency_key':str(uuid4())}
    if command!='save':assert (await c.put(url,json=saved_body,headers=csrf(c))).status_code==200
    if command=='replay_publish':assert (await c.post(url+'/publish',json=publish_body,headers=csrf(c))).status_code==200
    before=(await c.get(url)).json()
    async with c.factory() as db:
        before_receipts=len((await db.scalars(select(StorefrontThemeCommand))).all())
    operation='publish' if 'publish' in command else 'save'
    body=publish_body if operation=='publish' else saved_body
    authorized=asyncio.Event();original=domain.authorize
    async def checked(*args,**kwargs):
        result=await original(*args,**kwargs);authorized.set();return result
    monkeypatch.setattr(domain,'authorize',checked)
    async with c.factory() as holder:
        await holder.scalar(select(Business.id).where(Business.id==UUID(bid)).with_for_update())
        request=asyncio.create_task(c.request('POST' if operation=='publish' else 'PUT',url+('/publish' if operation=='publish' else ''),json=body,headers=csrf(c)))
        try:
            await asyncio.wait_for(authorized.wait(),5)
            if revocation=='role':
                member=await holder.scalar(select(Membership).where(Membership.user_id==UUID(uid),Membership.business_id==UUID(bid)));member.role='viewer'
            else:
                sessions=(await holder.scalars(select(UserSession).where(UserSession.user_id==UUID(uid)))).all()
                for session in sessions:session.revoked_at=datetime.now(timezone.utc)
            await holder.commit()
            response=await asyncio.wait_for(request,5)
        finally:
            if not request.done():request.cancel()
    assert response.status_code==(403 if revocation=='role' else 401),response.text
    async with c.factory() as db:
        from app.services.storefront_theme_v1 import view
        assert view(await db.get(StorefrontThemeSettings,UUID(bid)))==before
        assert len((await db.scalars(select(StorefrontThemeCommand))).all())==before_receipts


@pytest.mark.asyncio
@pytest.mark.parametrize('revocation',['role','session'])
@pytest.mark.parametrize('replay',[False,True])
async def test_theme_guard_rechecks_after_staging_before_caller_commit(theme_client,monkeypatch,revocation,replay):
    import asyncio
    from datetime import datetime,timezone
    from app.models.identity_auth import UserSession
    from app.services import storefront_theme_v1 as domain
    c=theme_client;bid,uid=await signup(c);url=f'/api/v1/businesses/{bid}/theme-settings';body=draft(theme='video')
    if replay:assert (await c.put(url,json=body,headers=csrf(c))).status_code==200
    before=(await c.get(url)).json();staged=asyncio.Event();release=asyncio.Event();original=domain.apply_command
    async def pause_after_staging(*args,**kwargs):
        result=await original(*args,**kwargs);staged.set();await release.wait();return result
    monkeypatch.setattr(domain,'apply_command',pause_after_staging)
    request=asyncio.create_task(c.put(url,json=body,headers=csrf(c)))
    try:
        await asyncio.wait_for(staged.wait(),5)
        async with c.factory() as other:
            if revocation=='role':
                member=await other.scalar(select(Membership).where(Membership.user_id==UUID(uid),Membership.business_id==UUID(bid)));member.role='viewer'
            else:
                for session in (await other.scalars(select(UserSession).where(UserSession.user_id==UUID(uid)))).all():session.revoked_at=datetime.now(timezone.utc)
            await other.commit()
        release.set();response=await asyncio.wait_for(request,5)
    finally:
        release.set()
        if not request.done():request.cancel()
    assert response.status_code==(403 if revocation=='role' else 401),response.text
    async with c.factory() as db:
        assert domain.view(await db.get(StorefrontThemeSettings,UUID(bid)))==before
        assert len((await db.scalars(select(StorefrontThemeCommand))).all())==(1 if replay else 0)
