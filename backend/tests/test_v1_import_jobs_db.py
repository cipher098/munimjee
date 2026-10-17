"""Actual Alembic/P01 checks, pending integrator's import migration registration.

No create_all, alternative database URL or synthetic schema is used. Without an
allocated disposable lane migrated_engine skips explicitly. With a lane, missing
registered import DDL is a failure, never silently replaced with model metadata.
"""
import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.imports_v1 import ImportAudit, ImportDraft, ImportJob
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
