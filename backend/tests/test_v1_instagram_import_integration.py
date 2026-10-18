"""Actual migrated PG16 connection/original boundaries; synthetic provider only."""
from datetime import timedelta
from uuid import uuid4
from types import SimpleNamespace
import hashlib
import pytest
from fastapi import HTTPException
from sqlalchemy import select,func,update
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.config import settings
from app.models.seller import Seller
from app.models.channel_operator import ChannelConnectionState
from app.models.imports_v1 import ImportAsset,ImportAudit,ImportDraft,ImportJob
from app.services import imports_v1 as jobs, import_originals, instagram_credentials as credentials
from tests.test_v1_instagram_owned_pipeline_db import seed,enqueue,FakeProvider,ACCOUNT


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['token','version','disconnect','expiry','business'])
async def test_same_account_connection_change_after_download_cannot_retain_any_result(migrated_engine,change):
    from app.models.identity import Business
    sessions=async_sessionmaker(migrated_engine,expire_on_commit=False);bid,actor=await seed(sessions)
    job=await enqueue(sessions,bid,actor)
    async def changed():
        async with sessions.begin() as db:
            if change=='token':await db.execute(update(Seller).where(Seller.id==bid).values(instagram_token='different-synthetic'))
            elif change=='version':await db.execute(update(ChannelConnectionState).where(ChannelConnectionState.business_id==bid).values(version=8))
            elif change=='disconnect':await db.execute(update(Seller).where(Seller.id==bid).values(instagram_token=None,instagram_page_id=None))
            elif change=='business':await db.execute(update(Business).where(Business.id==bid).values(is_active=False))
            else:await db.execute(update(Seller).where(Seller.id==bid).values(instagram_token_expires_at=jobs.now()-timedelta(seconds=1)))
    assert not await jobs.run_job(sessions,bid,job.job_id,instagram_provider=FakeProvider(bid,changed))
    async with sessions() as db:
        for model in (ImportAsset,ImportDraft,ImportAudit):
            assert await db.scalar(select(func.count()).select_from(model).where(model.business_id==bid))==0


@pytest.mark.asyncio
async def test_original_bytes_manifest_exact_replay_foreign_access_and_tamper(migrated_engine):
    sessions=async_sessionmaker(migrated_engine,expire_on_commit=False);bid,actor=await seed(sessions)
    job=await enqueue(sessions,bid,actor)
    assert await jobs.run_job(sessions,bid,job.job_id,instagram_provider=FakeProvider(bid))
    assert not await jobs.run_job(sessions,bid,job.job_id,instagram_provider=FakeProvider(bid))
    async with sessions() as db:
        draft=await db.scalar(select(ImportDraft).where(ImportDraft.business_id==bid))
        manifest=await import_originals.originals(db,actor,bid,draft.id)
        assert len(manifest['items'])==1
        m=manifest['items'][0]
        metadata,content=await import_originals.originals(db,actor,bid,draft.id,asset_id=m['asset_id'])
        assert hashlib.sha256(content).hexdigest()==metadata['sha256']
        assert 'synthetic-retained-original' not in str(manifest)
        assert (await db.get(ImportJob,job.job_id)).asset_id is None
        assert await db.scalar(select(func.count()).select_from(ImportAsset).where(ImportAsset.business_id==bid))==1
    foreign,other=await seed(sessions)
    async with sessions() as db:
        with pytest.raises(HTTPException) as denied:await import_originals.originals(db,other,bid,draft.id)
        assert denied.value.status_code==404
    async with sessions.begin() as db:
        asset=await db.scalar(select(ImportAsset).where(ImportAsset.business_id==bid))
        asset.content=b'\x89PNG\r\n\x1a\n'+b'x'*(asset.size_bytes-8)
    async with sessions() as db:
        with pytest.raises(HTTPException) as invalid:await import_originals.originals(db,actor,bid,draft.id)
        assert invalid.value.status_code==409


@pytest.mark.asyncio
async def test_late_refresh_result_never_resurrects_disconnected_or_replaced_generation(migrated_engine):
    sessions=async_sessionmaker(migrated_engine,expire_on_commit=False);bid,_=await seed(sessions)
    async with sessions() as db:old=await credentials.snapshot(db,bid)
    async with sessions.begin() as db:
        await db.execute(update(Seller).where(Seller.id==bid).values(instagram_token=None,instagram_page_id=None))
        await db.execute(update(ChannelConnectionState).where(ChannelConnectionState.business_id==bid).values(version=8,automation_enabled=False))
    async with sessions.begin() as db:
        assert not await credentials.replace(db,bid,expected=old.proof(),account_id=ACCOUNT,token='must-not-restore',expires_at=jobs.now()+timedelta(days=60))
    async with sessions() as db:
        assert (await db.get(Seller,bid)).instagram_token is None
        assert (await db.get(ChannelConnectionState,(bid,'instagram'))).version==8


@pytest.mark.asyncio
async def test_default_closed_worker_composition_has_zero_network_and_no_retention(migrated_engine,monkeypatch):
    sessions=async_sessionmaker(migrated_engine,expire_on_commit=False);bid,actor=await seed(sessions)
    monkeypatch.setattr(settings,'V1_INSTAGRAM_OWNED_MEDIA_ENABLED',False)
    job=await enqueue(sessions,bid,actor)
    assert not await jobs.run_job(sessions,bid,job.job_id)
    async with sessions() as db:
        assert (await db.get(ImportJob,job.job_id)).error_code=='provider_capability_pending'
        assert await db.scalar(select(func.count()).select_from(ImportAsset).where(ImportAsset.business_id==bid))==0


@pytest.mark.asyncio
async def test_original_asset_and_manifest_roll_back_with_candidate_and_job(migrated_engine,monkeypatch):
    sessions=async_sessionmaker(migrated_engine,expire_on_commit=False);bid,actor=await seed(sessions)
    job=await enqueue(sessions,bid,actor)
    original=import_originals.retain
    async def fail_after_flush(*args):
        await original(*args)
        await args[0].flush()
        raise RuntimeError('synthetic transaction boundary failure')
    monkeypatch.setattr(import_originals,'retain',fail_after_flush)
    with pytest.raises(RuntimeError):await jobs.run_job(sessions,bid,job.job_id,instagram_provider=FakeProvider(bid))
    async with sessions() as db:
        for model in (ImportAsset,ImportDraft,ImportAudit):
            assert await db.scalar(select(func.count()).select_from(model).where(model.business_id==bid))==0
        assert (await db.get(ImportJob,job.job_id)).state=='running' # committed lease remains recoverable


@pytest.mark.asyncio
async def test_actual_native_original_reader_fences_session_revoked_after_content_read(migrated_engine,monkeypatch):
    from app.main import app
    from app.database import get_db
    from app.services.auth_sessions import issue_session
    from app.models.identity import User
    from app.models.identity_auth import UserSession
    from httpx import AsyncClient,ASGITransport
    sessions=async_sessionmaker(migrated_engine,expire_on_commit=False);bid,actor=await seed(sessions)
    job=await enqueue(sessions,bid,actor)
    assert await jobs.run_job(sessions,bid,job.job_id,instagram_provider=FakeProvider(bid))
    async with sessions.begin() as db:
        token,csrf,session=await issue_session(db,await db.get(User,actor.user_id))
        draft=await db.scalar(select(ImportDraft).where(ImportDraft.business_id==bid));asset=await db.scalar(select(ImportAsset).where(ImportAsset.business_id==bid))
        sid=session.id;cid=draft.id;aid=asset.id
    async def database():
        async with sessions() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    prior=dict(app.dependency_overrides);app.dependency_overrides[get_db]=database
    monkeypatch.setattr(settings,'V1_AUTH_ENABLED',True)
    original=import_originals.originals
    async def revoked(*args,**kwargs):
        result=await original(*args,**kwargs)
        async with sessions.begin() as writer:await writer.execute(update(UserSession).where(UserSession.id==sid).values(revoked_at=jobs.now()))
        return result
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test',headers={'Authorization':'Bearer '+token}) as client:
            url=f'/api/v1/businesses/{bid}/imports/candidates/{cid}/originals/{aid}'
            valid=await client.get(url);assert valid.status_code==200 and valid.content.startswith(b'\x89PNG')
            monkeypatch.setattr(import_originals,'originals',revoked)
            denied=await client.get(url);assert denied.status_code==401 and b'synthetic-retained-original' not in denied.content
    finally:app.dependency_overrides.clear();app.dependency_overrides.update(prior)


@pytest.mark.asyncio
async def test_legacy_connect_result_cannot_restore_after_disconnect_during_exchange(migrated_engine,monkeypatch):
    from app.main import app
    from app.database import get_db
    from app.api.routes import auth
    from httpx import AsyncClient,ASGITransport
    sessions=async_sessionmaker(migrated_engine,expire_on_commit=False);bid,actor=await seed(sessions)
    async def database():
        async with sessions() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    prior=dict(app.dependency_overrides);app.dependency_overrides[get_db]=database
    async def exchange(_):
        async with sessions.begin() as writer:
            await writer.execute(update(Seller).where(Seller.id==bid).values(instagram_token=None,instagram_page_id=None))
            await writer.execute(update(ChannelConnectionState).where(ChannelConnectionState.business_id==bid).values(version=8,automation_enabled=False))
        return 'new-must-not-save'
    async def profile(_):return {'user_id':ACCOUNT}
    monkeypatch.setattr(auth,'exchange_for_long_lived_token',exchange);monkeypatch.setattr(auth,'fetch_ig_user',profile)
    token=auth._create_token({'sub':str(bid),'role':'seller'})
    try:
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
            response=await client.post('/auth/seller/connect-instagram',headers={'Authorization':'Bearer '+token},json={'short_lived_token':'synthetic-input'})
            assert response.status_code==409,response.text
        async with sessions() as db:assert (await db.get(Seller,bid)).instagram_token is None
    finally:app.dependency_overrides.clear();app.dependency_overrides.update(prior)


@pytest.mark.asyncio
async def test_actual_refresh_worker_discards_delayed_token_generation(migrated_engine,monkeypatch):
    from app.workers import refresh_tokens
    sessions=async_sessionmaker(migrated_engine,expire_on_commit=False);bid,actor=await seed(sessions)
    monkeypatch.setattr(refresh_tokens,'AsyncSessionLocal',sessions)
    async def exchange(_):
        async with sessions.begin() as db:
            await db.execute(update(Seller).where(Seller.id==bid).values(instagram_token=None,instagram_page_id=None))
            await db.execute(update(ChannelConnectionState).where(ChannelConnectionState.business_id==bid).values(version=8,automation_enabled=False))
        return 'new-must-not-save'
    monkeypatch.setattr(refresh_tokens,'exchange_for_long_lived_token',exchange)
    await refresh_tokens._refresh()
    async with sessions() as db:assert (await db.get(Seller,bid)).instagram_token is None
