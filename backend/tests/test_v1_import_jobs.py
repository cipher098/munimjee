"""SQL-shape/service/route tests; fake DB evidence is not migrated evidence."""
import asyncio
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.api.v1.imports import bounded_upload, create_router
from app.database import get_db
from app.models.imports_v1 import ImportAsset, ImportAudit, ImportDraft, ImportJob
from app.schemas.imports_v1 import CandidateReviewWrite, ImportJobCreate, JobMutation, UploadCreate
from app.services import imports_v1 as service
from app.services.identity import Actor
from app.v1.imports import FactField, SellerOverride, apply_overrides, begin_review, parse_candidate
from app.v1.imports.fetching import FetchError, FetchedSource


BUSINESS = UUID("10000000-0000-0000-0000-000000000001")
OTHER = UUID("20000000-0000-0000-0000-000000000002")
ACTOR = Actor(UUID("30000000-0000-0000-0000-000000000003"), "v1_user")
URL = "https://shop.example.com/item"


class FakeDB:
    no_autoflush = nullcontext()
    def __init__(self, values=()):
        self.values = iter(values)
        self.queries, self.added = [], []
        self.flushes = 0

    async def scalar(self, query):
        compiled = query.compile(dialect=postgresql.dialect())
        assert BUSINESS in compiled.params.values(), "Each lookup/lock must bind the authorized tenant"
        self.queries.append(str(compiled))
        return next(self.values)

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        self.flushes += 1


@pytest.fixture
def access(monkeypatch):
    authorize = AsyncMock(return_value=SimpleNamespace(instagram_page_id="linked-ig"))
    monkeypatch.setattr(service, "require_business_access", authorize)
    async def fresh(db, actor, business_id, capability):
        return await authorize(db, actor, business_id, capability)
    monkeypatch.setattr(service, "_fresh_access", fresh)
    return authorize


@pytest.mark.asyncio
@pytest.mark.parametrize("role,allowed", [("owner", True), ("manager", True), ("staff", False), ("viewer", False)])
async def test_fresh_authorization_uses_tenant_actor_scalar_columns_without_autoflush(role, allowed):
    class SnapshotDB:
        async def execute(self, query):
            compiled = query.compile(dialect=postgresql.dialect())
            assert BUSINESS in compiled.params.values() and ACTOR.user_id in compiled.params.values()
            assert query.get_execution_options()["autoflush"] is False
            assert [column.key for column in query.selected_columns] == ["role", "instagram_page_id"]
            text = str(compiled)
            for guard in ("users.is_active IS true", "users.revoked_at IS NULL", "memberships.is_active IS true",
                          "memberships.revoked_at IS NULL", "businesses.is_active IS true", "sellers.is_active IS true"):
                assert guard in text
            return SimpleNamespace(one_or_none=lambda: SimpleNamespace(role=role, instagram_page_id="fresh-account"))
    if allowed:
        snapshot = await service._fresh_access(SnapshotDB(), ACTOR, BUSINESS, "catalogue.write")
        assert snapshot.instagram_page_id == "fresh-account" and snapshot.role == role
    else:
        with pytest.raises(HTTPException) as caught:
            await service._fresh_access(SnapshotDB(), ACTOR, BUSINESS, "catalogue.write")
        assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_fresh_authorization_missing_or_revoked_snapshot_fails_closed():
    class SnapshotDB:
        async def execute(self, query):
            return SimpleNamespace(one_or_none=lambda: None)
    with pytest.raises(HTTPException) as caught:
        await service._fresh_access(SnapshotDB(), ACTOR, BUSINESS, "catalogue.read")
    assert caught.value.status_code == 404


def job(**updates):
    values = dict(id=uuid4(), business_id=BUSINESS, creator_id=ACTOR.user_id,
        idempotency_key=uuid4(), request_hash="a" * 64, source={"kind": "website", "url": URL},
        asset_id=None, state="pending", revision=1, attempts=0, candidate_count=0,
        error_code=None, lease_token=None, lease_expires_at=None,
        created_at=service.now(), available_at=service.now())
    values.update(updates)
    return ImportJob(**values)


def candidate(job_id, stock=4, source=None):
    return begin_review(parse_candidate({"provenance": {"business_id": BUSINESS,
        "import_job_id": job_id, "captured_at": service.now(),
        "source": source or {"kind": "website", "url": URL}, "source_product_id": "dress"},
        "facts": {"title": "Dress", "price": {"amount": "1000", "currency": "INR"}, "stock": stock, "options": []},
    }, business_id=BUSINESS), business_id=BUSINESS)


def draft(item, revision=1):
    return ImportDraft(id=item.id, business_id=BUSINESS, last_job_id=item.provenance.import_job_id,
                       revision=revision, document=item.model_dump(mode="json"))


def claim(row):
    return service.JobClaim(row.id, BUSINESS, ACTOR.user_id, row.lease_token, row.source, service.now())


def test_models_define_tenant_composite_constraints_and_lease_integrity():
    ddl = "\n".join(str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
                    for model in (ImportAsset, ImportJob, ImportDraft, ImportAudit))
    assert "FOREIGN KEY(business_id, candidate_id)" in ddl
    assert "FOREIGN KEY(business_id, asset_id)" in ddl
    assert "lease_token IS NULL AND lease_expires_at IS NULL" in ddl
    assert "attempts <= 3" in ddl
    assert "octet_length(content) = size_bytes" in ddl


@pytest.mark.parametrize("field,value", [("business_id", str(OTHER)), ("reviewer_id", str(uuid4())), ("source_authorized", 1)])
def test_job_write_forbids_authority_in_body(field, value):
    with pytest.raises(ValidationError):
        ImportJobCreate.model_validate({"idempotency_key": str(uuid4()), "source_kind": "website", "source_url": URL,
                                       "source_authorized": True, field: value})


def test_instagram_reference_normalization_and_credential_denial():
    payload = ImportJobCreate(idempotency_key=uuid4(), source_kind="instagram", media_id=" 123 ",
        source_url="https://WWW.INSTAGRAM.COM:443/reel/a/#section", source_authorized=True)
    assert payload.source_url == "https://www.instagram.com/reel/a/"
    assert payload.media_id == "123"
    with pytest.raises(ValueError):
        ImportJobCreate(idempotency_key=uuid4(), source_kind="instagram", media_id="123",
            source_url="https://www.instagram.com/reel/a/?code=private", source_authorized=True)


@pytest.mark.asyncio
async def test_create_job_is_idempotent_and_does_not_dispatch(access):
    payload = ImportJobCreate(idempotency_key=uuid4(), source_kind="website", source_url=URL, source_authorized=True)
    db = FakeDB([None, None])
    first = await service.create_job(db, ACTOR, BUSINESS, payload)
    assert first.state == "pending" and first.attempts == 0
    assert len(db.added) == 1 and isinstance(db.added[0], ImportJob)
    existing = db.added[0]
    replay = await service.create_job(FakeDB([None, existing]), ACTOR, BUSINESS, payload)
    assert first == replay
    existing.request_hash = "different"
    with pytest.raises(service.ImportConflict):
        await service.create_job(FakeDB([None, existing]), ACTOR, BUSINESS, payload)
    assert all(call.args[3] == "catalogue.write" for call in access.await_args_list)


@pytest.mark.asyncio
async def test_revoked_access_fails_before_any_row_read(access):
    access.side_effect = HTTPException(404, "Business not found")
    db = FakeDB([])
    with pytest.raises(HTTPException):
        await service.get_job(db, ACTOR, BUSINESS, uuid4())
    assert not db.queries and not db.added


@pytest.mark.asyncio
async def test_revocation_while_waiting_for_tenant_lock_blocks_mutation(access):
    access.side_effect = [SimpleNamespace(), HTTPException(403, "revoked while waiting")]
    db = FakeDB([None])
    payload = ImportJobCreate(idempotency_key=uuid4(), source_kind="website", source_url=URL, source_authorized=True)
    with pytest.raises(HTTPException):
        await service.create_job(db, ACTOR, BUSINESS, payload)
    assert len(db.queries) == 1 and not db.added


@pytest.mark.asyncio
async def test_same_upload_different_upload_keys_have_stable_candidate_source_identity(access):
    content = b"\x89PNG\r\n\x1a\nsynthetic"
    assets = []
    for _ in range(2):
        db = FakeDB([None, None])
        await service.put_upload(db, ACTOR, BUSINESS,
            UploadCreate(idempotency_key=uuid4(), content_type="image/png", source_authorized=True), content=content)
        assets.append(db.added[0])
    assert assets[0].id != assets[1].id
    assert assets[0].sha256 == assets[1].sha256
    jobs = []
    for asset in assets:
        db = FakeDB([None, None, asset])
        await service.create_job(db, ACTOR, BUSINESS, ImportJobCreate(idempotency_key=uuid4(),
            source_kind="uploaded_media", asset_id=asset.id, source_authorized=True))
        jobs.append(db.added[0])
    assert jobs[0].source == jobs[1].source
    claims = [service.JobClaim(row.id, BUSINESS, ACTOR.user_id, uuid4(), row.source, service.now(), content, "image/png") for row in jobs]
    candidates = [(await service.collect_claim(item, fetcher=None))[0] for item in claims]
    assert candidates[0].id == candidates[1].id
    assert candidates[0].extracted.stock is None


@pytest.mark.asyncio
async def test_claim_is_leased_and_redelivery_is_noop(access):
    row = job()
    result = await service.claim_job(FakeDB([None, row]), BUSINESS, row.id)
    assert result.lease_token == row.lease_token and row.attempts == 1 and row.state == "running"
    assert await service.claim_job(FakeDB([None, row]), BUSINESS, row.id) is None
    row.lease_expires_at = service.now() - timedelta(seconds=1)
    second = await service.claim_job(FakeDB([None, row]), BUSINESS, row.id)
    assert second.lease_token != result.lease_token and row.attempts == 2


@pytest.mark.asyncio
async def test_recovery_caps_attempts_and_checks_membership(access):
    exhausted = job(attempts=3)
    assert await service.claim_job(FakeDB([None, exhausted]), BUSINESS, exhausted.id) is None
    assert exhausted.error_code == "attempts_exhausted"
    access.side_effect = HTTPException(403, "revoked")
    revoked = job()
    assert await service.claim_job(FakeDB([None, revoked]), BUSINESS, revoked.id) is None
    assert revoked.error_code == "authorization_revoked" and revoked.state == "failed"


@pytest.mark.asyncio
async def test_cancel_fences_pre_fetch_and_results_and_replays(access):
    row = job(state="running", lease_token=uuid4(), lease_expires_at=service.now() + timedelta(seconds=60))
    token = claim(row)
    payload = JobMutation(expected_revision=1, idempotency_key=uuid4())
    db = FakeDB([None, None, row])
    cancelled = await service.mutate_job(db, ACTOR, BUSINESS, row.id, payload, action="cancel")
    assert cancelled.state == "cancelled" and row.lease_token is None
    replay = await service.mutate_job(FakeDB([None, db.added[0]]), ACTOR, BUSINESS, row.id, payload, action="cancel")
    assert replay == cancelled
    assert not await service.check_claim(FakeDB([None, row]), token)
    assert not await service.finish_claim(FakeDB([None, row]), token, candidates=(candidate(row.id),))


@pytest.mark.asyncio
async def test_manual_retry_backoff_and_revision_conflict(access):
    row = job(state="failed", attempts=1, revision=4, error_code="fetch_timeout")
    with pytest.raises(service.ImportConflict):
        await service.mutate_job(FakeDB([None, None, row]), ACTOR, BUSINESS, row.id,
            JobMutation(expected_revision=3, idempotency_key=uuid4()), action="retry")
    await service.mutate_job(FakeDB([None, None, row]), ACTOR, BUSINESS, row.id,
        JobMutation(expected_revision=4, idempotency_key=uuid4()), action="retry")
    assert row.state == "pending" and row.available_at > service.now()
    assert await service.claim_job(FakeDB([None, row]), BUSINESS, row.id) is None


@pytest.mark.asyncio
async def test_reimport_persists_override_history_and_invalidates_stale_review(access):
    row = job(state="running", lease_token=uuid4(), lease_expires_at=service.now() + timedelta(seconds=60))
    first = candidate(row.id)
    corrected = apply_overrides(first, (SellerOverride(field="stock", value=2, reviewer_id=ACTOR.user_id),), business_id=BUSINESS)
    stored = draft(corrected, revision=3)
    incoming = candidate(row.id, stock=99)
    db = FakeDB([None, row, stored])
    assert await service.finish_claim(db, claim(row), candidates=(incoming,))
    assert stored.revision == 4
    assert service.ImportCandidate.model_validate(stored.document).effective_facts().stock == 2
    assert row.state == "review_required"
    assert isinstance(db.added[0], ImportAudit) and "before" in db.added[0].details
    with pytest.raises(service.ImportConflict):
        await service.review_candidate(FakeDB([None, None, stored]), ACTOR, BUSINESS, stored.id,
            CandidateReviewWrite(expected_revision=3, idempotency_key=uuid4(), action="approve", confirmed_fields=list(FactField)))


@pytest.mark.asyncio
async def test_approval_records_actor_and_replays_without_publication(access):
    item = candidate(uuid4())
    stored = draft(item)
    payload = CandidateReviewWrite(expected_revision=1, idempotency_key=uuid4(), action="approve", confirmed_fields=list(FactField))
    db = FakeDB([None, None, stored])
    result = await service.review_candidate(db, ACTOR, BUSINESS, item.id, payload)
    assert result.candidate["state"] == "approved"
    assert result.candidate["review"]["reviewer_id"] == str(ACTOR.user_id)
    assert result.catalogue_bridge_status == "pending_reviewed_allocation"
    assert len(db.added) == 1 and isinstance(db.added[0], ImportAudit)
    replay = await service.review_candidate(FakeDB([None, db.added[0]]), ACTOR, BUSINESS, item.id, payload)
    assert result == replay


@pytest.mark.asyncio
async def test_ig_connection_is_rechecked_and_provider_gate_truthful(access):
    row = job(source={"kind": "instagram", "media_id": "123", "account_id": "old-ig"})
    assert await service.claim_job(FakeDB([None, row]), BUSINESS, row.id) is None
    assert row.error_code == "source_connection_changed"
    with pytest.raises(FetchError, match="provider_capability_pending"):
        await service.collect_claim(service.JobClaim(uuid4(), BUSINESS, ACTOR.user_id, uuid4(),
            {"kind": "instagram", "media_id": "123", "account_id": "linked-ig"}, service.now()), fetcher=None)


@pytest.mark.asyncio
async def test_late_results_recheck_revoked_actor_and_do_not_write_drafts(access):
    row = job(state="running", lease_token=uuid4(), lease_expires_at=service.now() + timedelta(seconds=60))
    access.side_effect = HTTPException(403, "revoked")
    db = FakeDB([None, row])
    assert not await service.finish_claim(db, claim(row), candidates=(candidate(row.id),))
    assert row.error_code == "authorization_revoked" and not db.added


def test_router_requires_explicit_native_mutation_protection():
    with pytest.raises(TypeError):
        create_router(None)
    async def denied():
        raise HTTPException(403, "Mutation protection required")
    app = FastAPI()
    app.include_router(create_router(denied))
    async def no_db():
        yield FakeDB([])
    app.dependency_overrides[get_db] = no_db
    with TestClient(app) as client:
        for path in ("jobs", "jobs/00000000-0000-0000-0000-000000000001/cancel", "candidates/00000000-0000-0000-0000-000000000001/review", "uploads?idempotency_key=00000000-0000-0000-0000-000000000001&source_authorized=true"):
            assert client.post(f"/api/v1/businesses/{BUSINESS}/imports/{path}", json={}).status_code == 403


@pytest.mark.asyncio
async def test_upload_stream_is_bounded_without_trusting_content_length():
    class Request:
        headers = {}
        async def stream(self):
            yield b"x" * 3_000_000
            yield b"x" * 3_000_000
    with pytest.raises(HTTPException) as caught:
        await bounded_upload(Request())
    assert caught.value.status_code == 413
