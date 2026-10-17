"""Actual Alembic/P01 checks, pending integrator's import migration registration.

No create_all, alternative database URL or synthetic schema is used. Without an
allocated disposable lane migrated_engine skips explicitly. With a lane, missing
registered import DDL is a failure, never silently replaced with model metadata.
"""
import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.imports_v1 import ImportAudit, ImportDraft, ImportJob
from app.models.identity import Business, Membership, User
from app.models.seller import Seller
from app.schemas.imports_v1 import CandidateReviewWrite, ImportJobCreate
from app.services import imports_v1 as service
from app.services.identity import Actor, ensure_legacy_owner_bridge, legacy_owner_id
from app.v1.imports import FactField
from app.v1.imports.fetching import FetchedSource


@pytest_asyncio.fixture
async def sessions(migrated_engine):
    yield async_sessionmaker(migrated_engine, expire_on_commit=False)


async def seed(sessions):
    business_id = uuid4()
    async with sessions.begin() as db:
        seller = Seller(id=business_id, email=f"{business_id}@example.invalid", password_hash="synthetic", business_name="Import fixture")
        db.add(seller)
        await db.flush()
        await ensure_legacy_owner_bridge(db, seller)
    return business_id, Actor(legacy_owner_id(business_id), "v1_user")


def write(key=None):
    return ImportJobCreate(idempotency_key=key or uuid4(), source_kind="website",
        source_url="https://shop.example.com/dress", source_authorized=True)


class FakeFetcher:
    async def fetch(self, *args, **kwargs):
        return FetchedSource("https://shop.example.com/dress", "application/ld+json",
            b'{"@type":"Product","sku":"dress","name":"Dress","offers":{"price":"1299","priceCurrency":"INR"}}')


@pytest.mark.asyncio
async def test_migrated_concurrent_job_idempotency_and_durable_recovery(sessions):
    business, actor = await seed(sessions)
    payload = write()
    async def create():
        async with sessions.begin() as db:
            return await service.create_job(db, actor, business, payload)
    first, second = await asyncio.gather(create(), create())
    assert first.job_id == second.job_id
    assert await service.run_job(sessions, business, first.job_id, fetcher=FakeFetcher())
    assert not await service.run_job(sessions, business, first.job_id, fetcher=FakeFetcher())
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ImportJob).where(ImportJob.business_id == business)) == 1
        rows = await service.list_candidates(db, actor, business)
        assert len(rows) == 1 and rows[0].candidate["extracted"]["stock"] is None
        assert rows[0].candidate["state"] == "review_required"


@pytest.mark.asyncio
async def test_migrated_review_revision_and_reimport_preserve_seller_overrides(sessions):
    business, actor = await seed(sessions)
    async with sessions.begin() as db:
        job = await service.create_job(db, actor, business, write())
    assert await service.run_job(sessions, business, job.job_id, fetcher=FakeFetcher())
    async with sessions.begin() as db:
        item = (await service.list_candidates(db, actor, business))[0]
        item = await service.review_candidate(db, actor, business, item.candidate_id,
            CandidateReviewWrite(expected_revision=item.revision, idempotency_key=uuid4(), action="edit",
                overrides=[{"field": "stock", "value": 3}, {"field": "options", "value": []}]))
        review = CandidateReviewWrite(expected_revision=item.revision, idempotency_key=uuid4(), action="approve", confirmed_fields=list(FactField))
    async def approve():
        try:
            async with sessions.begin() as db:
                await service.review_candidate(db, actor, business, item.candidate_id,
                    review.model_copy(update={"idempotency_key": uuid4()}))
            return "applied"
        except service.ImportConflict:
            return "conflict"
    assert sorted(await asyncio.gather(approve(), approve())) == ["applied", "conflict"]
    async with sessions.begin() as db:
        newer = await service.create_job(db, actor, business, write())
    assert await service.run_job(sessions, business, newer.job_id, fetcher=FakeFetcher())
    async with sessions() as db:
        row = await db.scalar(select(ImportDraft).where(ImportDraft.business_id == business))
        candidate = service.ImportCandidate.model_validate(row.document)
        assert candidate.effective_facts().stock == 3 and candidate.state == "approved"
        assert await db.scalar(select(func.count()).select_from(ImportAudit).where(ImportAudit.business_id == business)) >= 4


@pytest.mark.asyncio
async def test_migrated_composite_tenant_fk_denies_cross_business_job(sessions):
    owner, actor = await seed(sessions)
    other, _ = await seed(sessions)
    async with sessions.begin() as db:
        job = await service.create_job(db, actor, owner, write())
    async with sessions() as db:
        db.add(ImportDraft(id=uuid4(), business_id=other, last_job_id=job.job_id, revision=1, document={}))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["user_revoked", "role_downgrade", "account_changed", "membership_revoked", "business_inactive", "seller_inactive"])
async def test_migrated_cached_authorization_is_fresh_after_tenant_lock_wait(sessions, monkeypatch, change):
    """Two real sessions plus strongly retained stale identity-map objects.

    This regression needs only existing identity DDL; import-table tests above
    remain gated on the integrator's additive import migration registration.
    """
    business_id, actor = await seed(sessions)
    async with sessions.begin() as setup:
        await setup.execute(update(Seller).where(Seller.id == business_id).values(instagram_page_id="old-account"))
    async with sessions() as cached:
        user = await cached.get(User, actor.user_id)
        membership = await cached.scalar(select(Membership).where(Membership.business_id == business_id, Membership.user_id == actor.user_id))
        business = await cached.get(Business, business_id)
        seller = await cached.get(Seller, business_id)
        await cached.commit()  # expire_on_commit=False deliberately retains stale objects.
        seller.business_name = "Unrelated dirty local edit must remain unflushed"
        waiting = asyncio.Event()
        original_scalar = cached.scalar

        async def observe_lock(query, *args, **kwargs):
            if query._for_update_arg is not None:
                waiting.set()
            return await original_scalar(query, *args, **kwargs)

        monkeypatch.setattr(cached, "scalar", observe_lock)
        task = None
        try:
            async with sessions.begin() as blocking:
                await blocking.scalar(select(Business).where(Business.id == business_id).with_for_update())
                task = asyncio.create_task(service._access(cached, actor, business_id, write=True, lock=True))
                await asyncio.wait_for(waiting.wait(), timeout=5)
                if change == "user_revoked":
                    await blocking.execute(update(User).where(User.id == actor.user_id).values(revoked_at=service.now()))
                elif change == "role_downgrade":
                    await blocking.execute(update(Membership).where(Membership.business_id == business_id).values(role="viewer"))
                elif change == "membership_revoked":
                    await blocking.execute(update(Membership).where(Membership.business_id == business_id).values(revoked_at=service.now()))
                elif change == "business_inactive":
                    await blocking.execute(update(Business).where(Business.id == business_id).values(is_active=False))
                elif change == "seller_inactive":
                    await blocking.execute(update(Seller).where(Seller.id == business_id).values(is_active=False))
                else:
                    await blocking.execute(update(Seller).where(Seller.id == business_id).values(instagram_page_id="new-account"))
            if change == "account_changed":
                snapshot = await asyncio.wait_for(task, timeout=5)
                assert snapshot.instagram_page_id == "new-account"
            else:
                with pytest.raises(service.HTTPException) as denied:
                    await asyncio.wait_for(task, timeout=5)
                assert denied.value.status_code in (403, 404)
            # Fresh scalar projection neither expires cached objects nor flushes
            # an unrelated dirty seller; these are intentionally stale values.
            assert user.revoked_at is None and membership.role == "owner"
            assert business.is_active and seller.instagram_page_id == "old-account"
            assert seller.business_name == "Unrelated dirty local edit must remain unflushed"
            stored_name = await cached.scalar(select(Seller.business_name).where(Seller.id == business_id).execution_options(autoflush=False))
            assert stored_name == "Import fixture"
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await cached.rollback()
