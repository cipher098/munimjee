"""Optional P01 actual-migrated seam checks. No DB allocation or fallback.

The shared migrated_engine fixture skips before opening a socket unless an
operator has separately allocated a guarded disposable TEST_DATABASE_URL lane.
No create_all or direct provider request is used.
"""
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.channel_operator import ChannelConnectionState
from app.models.identity import Membership
from app.models.imports_v1 import ImportAsset, ImportDraft, ImportJob
from app.models.seller import Seller
from app.schemas.imports_v1 import CandidateReviewWrite, ImportJobCreate
from app.services import imports_v1 as service
from app.services.identity import Actor, ensure_legacy_owner_bridge, legacy_owner_id
from app.v1.imports import DraftFacts


ACCOUNT, MEDIA = "178400000000071", "180000000000071"


async def seed(sessions):
    business = uuid4()
    async with sessions.begin() as db:
        seller = Seller(id=business, email=f"{business}@example.invalid", password_hash="synthetic",
            business_name="Owned Instagram QA", instagram_page_id=ACCOUNT,
            instagram_token="synthetic-only-never-real", instagram_token_expires_at=service.now() + timedelta(hours=1))
        db.add(seller)
        await db.flush()
        await ensure_legacy_owner_bridge(db, seller)
        db.add(ChannelConnectionState(business_id=business, channel="instagram", version=7,
            provider_account_id=ACCOUNT, automation_enabled=False))
    return business, Actor(legacy_owner_id(business), "v1_user")


async def enqueue(sessions, business, actor):
    async with sessions.begin() as db:
        return await service.create_job(db, actor, business, ImportJobCreate(
            idempotency_key=uuid4(), source_kind="instagram", media_id=MEDIA, source_authorized=True))


class FakeProvider:
    def __init__(self, business, before_return=None):
        self.business, self.before_return = business, before_return
        self.calls = 0

    async def fetch_owned_media(self, *, business_id, account_id, media_id):
        assert (business_id, account_id, media_id) == (self.business, ACCOUNT, MEDIA)
        self.calls += 1
        if self.before_return:
            await self.before_return()
        return SimpleNamespace(account_id=account_id, media_id=media_id,
            products=(("media-product", DraftFacts()),))


@pytest.mark.asyncio
async def test_migrated_owned_import_reimport_preserves_unknowns_corrections_and_private_state(migrated_engine):
    sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)
    business, actor = await seed(sessions)
    first = await enqueue(sessions, business, actor)
    fake = FakeProvider(business)
    assert await service.run_job(sessions, business, first.job_id, instagram_provider=fake)
    assert not await service.run_job(sessions, business, first.job_id, instagram_provider=fake)
    assert fake.calls == 1
    async with sessions.begin() as db:
        original = (await service.list_candidates(db, actor, business))[0]
        assert original.candidate["state"] == "review_required"
        assert all(value is None for value in original.candidate["extracted"].values())
        edited = await service.review_candidate(db, actor, business, original.candidate_id,
            CandidateReviewWrite(idempotency_key=uuid4(), expected_revision=original.revision, action="edit",
                overrides=[{"field": "title", "value": "Seller correction"}, {"field": "stock", "value": 0}]))
        assert edited.candidate["review"] is None
    second = await enqueue(sessions, business, actor)
    assert await service.run_job(sessions, business, second.job_id, instagram_provider=fake)
    async with sessions() as db:
        rows = await service.list_candidates(db, actor, business)
        assert len(rows) == 1 and rows[0].candidate_id == original.candidate_id
        candidate = service.ImportCandidate.model_validate(rows[0].candidate)
        assert candidate.effective_facts().title == "Seller correction"
        assert candidate.effective_facts().stock == 0 and candidate.effective_facts().price is None
        assert candidate.state == "review_required"
        assert rows[0].catalogue_bridge_status == "not_requested"
        assert await db.scalar(select(func.count()).select_from(ImportAsset).where(ImportAsset.business_id == business)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["cancelled", "revoked", "expired_lease", "replaced_lease", "account_changed"])
async def test_migrated_final_guard_discards_result_after_network_gap(migrated_engine, change):
    sessions = async_sessionmaker(migrated_engine, expire_on_commit=False)
    business, actor = await seed(sessions)
    pending = await enqueue(sessions, business, actor)

    async def mutate_during_fetch():
        async with sessions.begin() as db:
            if change == "revoked":
                await db.execute(update(Membership).where(Membership.business_id == business,
                    Membership.user_id == actor.user_id).values(revoked_at=service.now()))
            elif change == "account_changed":
                await db.execute(update(Seller).where(Seller.id == business).values(instagram_page_id="178400000000072"))
            else:
                values = {"lease_expires_at": service.now() - timedelta(seconds=1)} if change == "expired_lease" else {
                    "lease_token": uuid4()} if change == "replaced_lease" else {
                    "state": "cancelled", "lease_token": None, "lease_expires_at": None}
                await db.execute(update(ImportJob).where(ImportJob.business_id == business,
                    ImportJob.id == pending.job_id).values(**values))

    assert not await service.run_job(sessions, business, pending.job_id,
        instagram_provider=FakeProvider(business, mutate_during_fetch))
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ImportDraft).where(ImportDraft.business_id == business)) == 0
        assert await db.scalar(select(func.count()).select_from(ImportAsset).where(ImportAsset.business_id == business)) == 0
        persisted = await db.scalar(select(ImportJob).where(ImportJob.business_id == business, ImportJob.id == pending.job_id))
        assert persisted.state != "review_required"
        if change in ("revoked", "account_changed"):
            assert persisted.error_code == ("authorization_revoked" if change == "revoked" else "source_connection_changed")
