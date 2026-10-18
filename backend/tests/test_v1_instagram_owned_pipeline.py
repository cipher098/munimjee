"""Independent existing-seam QA. Fakes prove workflow, never Meta acceptance.

No provider module is imported here: its API/transport security has a separate
owner. Every runtime interaction uses injected synthetic values and the real
shared service/domain code. Actual PostgreSQL checks live in the companion file.
"""
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import ValidationError
import pytest
from sqlalchemy.dialects import postgresql

from app.models.imports_v1 import ImportAsset, ImportAudit, ImportDraft, ImportJob
from app.schemas.imports_v1 import ImportJobCreate
from app.services import imports_v1 as service
from app.services.identity import Actor
from app.v1.imports import DraftFacts, SellerOverride, apply_overrides, reimport_candidate
from app.v1.imports.runner import drain_jobs
from app.v1.imports import runner


BUSINESS = UUID("10000000-0000-0000-0000-000000000071")
ACTOR = Actor(UUID("20000000-0000-0000-0000-000000000071"), "v1_user")
ACCOUNT, MEDIA = "178400000000071", "180000000000071"


class TenantDB:
    """Predetermined results with independently checked SQL tenant binding."""
    def __init__(self, values):
        self.values = iter(values)
        self.added, self.queries = [], []
        self.flushes = 0

    async def scalar(self, query):
        compiled = query.compile(dialect=postgresql.dialect())
        assert BUSINESS in compiled.params.values()
        assert query._for_update_arg is not None or "v1_import_jobs" in str(compiled)
        self.queries.append(str(compiled))
        return next(self.values)

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        self.flushes += 1


def job(**updates):
    values = dict(id=uuid4(), business_id=BUSINESS, creator_id=ACTOR.user_id,
        idempotency_key=uuid4(), request_hash="a" * 64,
        source={"kind": "instagram", "account_id": ACCOUNT, "media_id": MEDIA},
        asset_id=None, state="pending", revision=1, attempts=0, candidate_count=0,
        error_code=None, lease_token=None, lease_expires_at=None,
        created_at=service.now(), available_at=service.now())
    values.update(updates)
    return ImportJob(**values)


def claim(row=None, **updates):
    row = row or job()
    return replace(service.JobClaim(row.id, BUSINESS, ACTOR.user_id,
        row.lease_token or uuid4(), dict(row.source), service.now()), **updates)


def provider(*, facts=None, products=None, **extra):
    result = SimpleNamespace(account_id=ACCOUNT, media_id=MEDIA,
        products=(("media-product", facts or DraftFacts()),) if products is None else products,
        **extra)
    return SimpleNamespace(fetch_owned_media=AsyncMock(return_value=result))


@pytest.fixture
def access(monkeypatch):
    callback = AsyncMock(return_value=SimpleNamespace(instagram_page_id=ACCOUNT))
    monkeypatch.setattr(service, "_access", callback)
    return callback


@pytest.mark.parametrize("field", ["business_id", "account_id", "actor_id", "creator_id",
    "access_token", "token", "credential", "connection_version", "published", "approved"])
def test_caller_cannot_choose_authority_credentials_or_decision(field):
    with pytest.raises(ValidationError):
        ImportJobCreate.model_validate(dict(idempotency_key=uuid4(), source_authorized=True,
            source_kind="instagram", media_id=MEDIA, **{field: "forged"}))


@pytest.mark.asyncio
async def test_create_binds_account_from_trusted_access_and_not_presentation_url(access):
    db = TenantDB([None])
    result = await service.create_job(db, ACTOR, BUSINESS, ImportJobCreate(
        idempotency_key=uuid4(), source_kind="instagram", media_id=MEDIA,
        source_url="https://www.instagram.com/reel/untrusted-presentation/", source_authorized=True))
    assert result.source == {"kind": "instagram", "account_id": ACCOUNT, "media_id": MEDIA,
        "url": "https://www.instagram.com/reel/untrusted-presentation/"}
    assert db.added[0].creator_id == ACTOR.user_id
    access.assert_awaited_once_with(db, ACTOR, BUSINESS, write=True, lock=True)


@pytest.mark.asyncio
async def test_missing_account_does_not_create_a_job(access):
    access.return_value = SimpleNamespace(instagram_page_id=None)
    db = TenantDB([None])
    with pytest.raises(service.ImportConflict, match="Connected Instagram"):
        await service.create_job(db, ACTOR, BUSINESS, ImportJobCreate(idempotency_key=uuid4(),
            source_kind="instagram", media_id=MEDIA, source_authorized=True))
    assert not db.added


@pytest.mark.asyncio
async def test_provider_gets_only_committed_tenant_account_media_and_unknown_placeholder():
    item, fake = claim(), provider(caption="Two dresses Rs999 stock10 BUY NOW", media_type="VIDEO")
    candidates = await service.collect_claim(item, fetcher=None, instagram_provider=fake)
    fake.fetch_owned_media.assert_awaited_once_with(business_id=BUSINESS, account_id=ACCOUNT, media_id=MEDIA)
    assert len(candidates) == 1  # A media placeholder, never an inferred product count.
    candidate = candidates[0]
    assert candidate.state == "review_required" and candidate.review is None
    assert candidate.extracted.model_dump() == dict(title=None, description=None, price=None, stock=None, options=None)
    document = candidate.model_dump(mode="json")
    assert document["provenance"]["source"] == {"kind": "instagram", "media_id": MEDIA, "url": None}
    assert ACCOUNT not in str(document) and "BUY NOW" not in str(document)
    assert not any(key in document for key in ("published", "active", "catalogue_id"))


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("account_id", "foreign"), ("media_id", "foreign")])
async def test_mismatched_owned_result_is_rejected_before_candidate_creation(field, value):
    fake = provider()
    setattr(fake.fetch_owned_media.return_value, field, value)
    with pytest.raises(service.FetchError, match="provider_ownership_mismatch"):
        await service.collect_claim(claim(), fetcher=None, instagram_provider=fake)


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 201])
async def test_unbounded_or_empty_product_result_is_rejected(count):
    with pytest.raises(service.FetchError, match="invalid_provider_products"):
        await service.collect_claim(claim(), fetcher=None,
            instagram_provider=provider(products=tuple((str(i), DraftFacts()) for i in range(count))))


@pytest.mark.asyncio
async def test_duplicate_product_keys_fail_complete_collection():
    with pytest.raises(service.FetchError, match="duplicate_source_product_key"):
        await service.collect_claim(claim(), fetcher=None,
            instagram_provider=provider(products=(("same", DraftFacts()), ("same", DraftFacts()))))


@pytest.mark.asyncio
async def test_candidate_identity_survives_job_url_and_capture_changes_but_not_tenant_or_media():
    first = claim()
    changed = replace(first, job_id=uuid4(), captured_at=first.captured_at + timedelta(seconds=1),
        source={**first.source, "url": "https://www.instagram.com/reel/new-reference/"})
    a = (await service.collect_claim(first, fetcher=None, instagram_provider=provider()))[0]
    b = (await service.collect_claim(changed, fetcher=None, instagram_provider=provider()))[0]
    assert a.id == b.id and a.provenance.import_job_id != b.provenance.import_job_id
    other_tenant = replace(first, business_id=uuid4())
    c = (await service.collect_claim(other_tenant, fetcher=None, instagram_provider=provider()))[0]
    other_media = replace(first, source={**first.source, "media_id": "180000000000072"})
    fake = provider()
    fake.fetch_owned_media.return_value.media_id = other_media.source["media_id"]
    d = (await service.collect_claim(other_media, fetcher=None, instagram_provider=fake))[0]
    assert len({a.id, c.id, d.id}) == 3


@pytest.mark.asyncio
async def test_reimport_preserves_seller_override_and_requires_review():
    first = claim()
    old = (await service.collect_claim(first, fetcher=None, instagram_provider=provider()))[0]
    corrected = apply_overrides(old, (SellerOverride(field="title", value="Seller title",
        reviewer_id=ACTOR.user_id), SellerOverride(field="stock", value=0, reviewer_id=ACTOR.user_id)), business_id=BUSINESS)
    incoming = (await service.collect_claim(replace(first, job_id=uuid4(),
        captured_at=first.captured_at + timedelta(seconds=1)), fetcher=None,
        instagram_provider=provider(facts=DraftFacts(description="Literal untrusted source text"))))[0]
    reconciled = reimport_candidate(corrected, incoming, business_id=BUSINESS)
    assert reconciled.candidate.effective_facts().title == "Seller title"
    assert reconciled.candidate.effective_facts().stock == 0
    assert reconciled.candidate.extracted.price is None and reconciled.candidate.extracted.options is None
    assert reconciled.candidate.state == "review_required" and reconciled.candidate.review is None


@pytest.mark.asyncio
async def test_original_media_result_is_not_falsely_persisted_by_existing_seam(access):
    row = job(state="running", lease_token=uuid4(), lease_expires_at=service.now() + timedelta(seconds=30))
    synthetic_bytes = b"\x89PNG\r\n\x1a\noriginal-garment-fixture"
    fake = provider(assets=(SimpleNamespace(media_id=MEDIA, content=synthetic_bytes,
        content_type="image/png", source_url="https://cdn.example.invalid/signed?secret=synthetic"),))
    item = claim(row)
    candidates = await service.collect_claim(item, fetcher=None, instagram_provider=fake)
    db = TenantDB([None, row, None])
    assert await service.finish_claim(db, item, candidates=candidates)
    assert len([record for record in db.added if isinstance(record, ImportDraft)]) == 1
    assert not any(isinstance(record, ImportAsset) for record in db.added)
    assert row.asset_id is None
    assert "original-garment" not in str([record.document for record in db.added if isinstance(record, ImportDraft)])
    assert "signed?secret" not in str([record.details for record in db.added if isinstance(record, ImportAudit)])


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["cancelled", "expired", "replaced_lease", "revoked", "account_changed"])
@pytest.mark.parametrize("checkpoint", ["check_claim", "finish_claim"])
async def test_checkpoint_discards_cancelled_revoked_changed_or_late_results(access, change, checkpoint):
    row = job(state="running", lease_token=uuid4(), lease_expires_at=service.now() + timedelta(seconds=30))
    item = claim(row)
    candidates = await service.collect_claim(item, fetcher=None, instagram_provider=provider())
    if change == "cancelled":
        row.state, row.lease_token, row.lease_expires_at = "cancelled", None, None
    elif change == "expired":
        row.lease_expires_at = service.now() - timedelta(seconds=1)
    elif change == "replaced_lease":
        row.lease_token = uuid4()
    elif change == "revoked":
        access.side_effect = HTTPException(403, "synthetic revoked")
    else:
        access.return_value = SimpleNamespace(instagram_page_id="replacement-account")
    db = TenantDB([None, row])
    kwargs = dict(candidates=candidates) if checkpoint == "finish_claim" else {}
    assert not await getattr(service, checkpoint)(db, item, **kwargs)
    assert not db.added and len(db.queries) == 2
    if change in ("revoked", "account_changed"):
        assert row.state == "failed"
        assert row.error_code == ("authorization_revoked" if change == "revoked" else "source_connection_changed")


@pytest.mark.asyncio
async def test_stale_capture_keeps_newer_review_document_and_records_ignored_audit(access):
    row = job(state="running", lease_token=uuid4(), lease_expires_at=service.now() + timedelta(seconds=30))
    older_claim = claim(row)
    older = (await service.collect_claim(older_claim, fetcher=None, instagram_provider=provider()))[0]
    newer = (await service.collect_claim(replace(older_claim, job_id=uuid4(),
        captured_at=older_claim.captured_at + timedelta(seconds=10)), fetcher=None, instagram_provider=provider()))[0]
    newer = apply_overrides(newer, (SellerOverride(field="title", value="Newer correction", reviewer_id=ACTOR.user_id),), business_id=BUSINESS)
    stored = ImportDraft(id=newer.id, business_id=BUSINESS, last_job_id=newer.provenance.import_job_id,
        revision=7, document=newer.model_dump(mode="json"))
    before = dict(stored.document)
    db = TenantDB([None, row, stored])
    assert await service.finish_claim(db, older_claim, candidates=(older,))
    assert stored.document == before and stored.revision == 7
    assert [record.action for record in db.added] == ["stale_capture_ignored"]


class Sessions:
    def __init__(self, databases):
        self.databases = iter(databases)
        self.active = 0

    @asynccontextmanager
    async def begin(self):
        self.active += 1
        try:
            yield next(self.databases)
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_run_job_commits_private_review_candidate_and_redelivery_does_not_fetch(access):
    row = job()
    dbs = [TenantDB([None, row]), TenantDB([None, row]), TenantDB([None, row, None])]
    sessions = Sessions(dbs)
    fake = provider()
    async def fetch(**kwargs):
        assert sessions.active == 0
        return fake.fetch_owned_media.return_value
    fake.fetch_owned_media.side_effect = fetch
    assert await service.run_job(sessions, BUSINESS, row.id, instagram_provider=fake)
    assert row.state == "review_required" and row.candidate_count == 1
    drafts = [record for record in dbs[-1].added if isinstance(record, ImportDraft)]
    assert len(drafts) == 1 and drafts[0].document["state"] == "review_required"
    assert not any(isinstance(record, ImportAsset) for db in dbs for record in db.added)
    assert not await service.run_job(Sessions([TenantDB([None, row])]), BUSINESS, row.id, instagram_provider=fake)
    assert fake.fetch_owned_media.await_count == 1


@pytest.mark.asyncio
async def test_real_run_job_has_no_transaction_during_provider_and_fences_late_cancel(access):
    row = job()
    dbs = [TenantDB([None, row]), TenantDB([None, row]), TenantDB([None, row])]
    sessions = Sessions(dbs)
    fake = provider()
    async def fetch(**kwargs):
        assert sessions.active == 0
        row.state, row.lease_token, row.lease_expires_at = "cancelled", None, None
        return fake.fetch_owned_media.return_value
    fake.fetch_owned_media.side_effect = fetch
    assert not await service.run_job(sessions, BUSINESS, row.id, instagram_provider=fake)
    assert not any(db.added for db in dbs)


@pytest.mark.asyncio
@pytest.mark.parametrize("error,code", [(RuntimeError("synthetic-token-do-not-persist"), "source_adapter_failed"),
    (service.FetchError("synthetic-token-do-not-persist"), "source_adapter_failed"),
    (TimeoutError("synthetic-token-do-not-persist"), "fetch_timeout"),
    (ValueError("synthetic-token-do-not-persist"), "invalid_source_data")])
async def test_run_job_persists_only_bounded_redacted_failure_code(access, caplog, error, code):
    row = job()
    dbs = [TenantDB([None, row]), TenantDB([None, row]), TenantDB([None, row])]
    fake = provider()
    fake.fetch_owned_media.side_effect = error
    assert not await service.run_job(Sessions(dbs), BUSINESS, row.id, instagram_provider=fake)
    assert row.state == "failed" and row.error_code == code
    assert not any(db.added for db in dbs)
    assert "synthetic-token-do-not-persist" not in caplog.text


@pytest.mark.asyncio
async def test_recovery_reclaims_expired_attempt_and_old_claim_cannot_finish(access):
    row = job(state="running", attempts=1, lease_token=uuid4(),
        lease_expires_at=service.now() - timedelta(seconds=1))
    old_claim = claim(row)
    fresh_claim = await service.claim_job(TenantDB([None, row]), BUSINESS, row.id)
    assert fresh_claim.lease_token != old_claim.lease_token and row.attempts == 2
    assert not await service.finish_claim(TenantDB([None, row]), old_claim)
    assert row.state == "running" and row.lease_token == fresh_claim.lease_token


@pytest.mark.asyncio
async def test_runner_forwards_the_explicit_provider_and_preserves_bounded_recovery(monkeypatch):
    fake = provider()
    ids = [(BUSINESS, uuid4()), (BUSINESS, uuid4())]
    class QueueDB:
        async def execute(self, query):
            compiled = query.compile(dialect=postgresql.dialect())
            assert "pending" in compiled.params.values() and "running" in compiled.params.values()
            assert 2 in compiled.params.values()
            return SimpleNamespace(all=lambda: ids)
    callback = AsyncMock(side_effect=[True, False])
    monkeypatch.setattr(runner, "run_job", callback)
    sessions = Sessions([QueueDB()])
    assert await drain_jobs(sessions, limit=2, instagram_provider=fake) == 1
    assert callback.await_count == 2
    assert [call.args[1:] for call in callback.await_args_list] == ids
    assert all(call.kwargs["instagram_provider"] is fake for call in callback.await_args_list)
