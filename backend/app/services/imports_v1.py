"""Tenant-authorized durable imports. Public services never commit caller work.

run_job owns short claim/result transactions; all network I/O is outside them.
The scheduler may replay run_job: leases and deterministic candidates fence it.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4, uuid5

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.models.identity import Business, Membership, User
from app.models.imports_v1 import ImportAsset, ImportAudit, ImportDraft, ImportJob
from app.models.seller import Seller
from app.schemas.imports_v1 import (
    CandidateReviewWrite, ImportCandidateRead, ImportJobCreate, ImportJobRead,
    JobMutation, UploadCreate, UploadRead,
)
from app.services.identity import Actor, capabilities_for, require_business_access
from app.v1.imports import (
    CandidateState, DraftFacts, ImportCandidate, ImportReviewError, ReviewDecision,
    SellerOverride, apply_overrides, approve, begin_review, confirm_facts,
    parse_candidate, reimport_candidate, reject,
)
from app.v1.imports.extraction import extract_website, validate_upload
from app.v1.imports.csv_source import CSVSourceError, parse_csv, validate_csv_upload
from app.v1.imports.fetching import FetchError, SafeFetcher


class ImportConflict(ValueError):
    pass


class ImportRevisionConflict(ImportConflict):
    """Receipt lookup succeeded with no match; stale check precedes all writes."""


class ImportNotFound(ValueError):
    pass


def now():
    return datetime.now(timezone.utc)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class AccessSnapshot:
    role: str
    instagram_page_id: str | None


async def _fresh_access(db, actor, business_id, capability):
    """Read authorization scalars from PostgreSQL, never ORM-cached objects.

    No autoflush/expire/populate operation may publish or overwrite unrelated
    dirty identity state while obtaining this committed authorization snapshot.
    Native-session validity remains the shared request dependency's authority.
    """
    query = select(Membership.role, Seller.instagram_page_id).select_from(User).join(
        Membership, Membership.user_id == User.id).join(
        Business, Business.id == Membership.business_id).join(
        Seller, Seller.id == Business.id).where(
        User.id == actor.user_id, User.is_active.is_(True), User.revoked_at.is_(None),
        Business.id == business_id, Business.is_active.is_(True), Seller.is_active.is_(True),
        Membership.is_active.is_(True), Membership.revoked_at.is_(None),
    ).execution_options(autoflush=False)
    row = (await db.execute(query)).one_or_none()
    if row is None:
        raise HTTPException(404, "Business not found")
    if capability not in capabilities_for(row.role):
        raise HTTPException(403, "Capability required")
    return AccessSnapshot(row.role, row.instagram_page_id)


async def _access(db, actor, business_id, *, write=False, lock=False):
    capability = "catalogue.write" if write else "catalogue.read"
    with db.no_autoflush:
        await require_business_access(db, actor, business_id, capability)
        if lock:
            await db.scalar(select(Business).where(Business.id == business_id).with_for_update())
        # A concurrent revocation, downgrade or linked-account change may have
        # committed while waiting; scalar projections bypass the identity map.
        return await _fresh_access(db, actor, business_id, capability)


async def _job(db, business_id, job_id, *, lock=False):
    query = select(ImportJob).where(ImportJob.business_id == business_id, ImportJob.id == job_id)
    job = await db.scalar(query.with_for_update() if lock else query)
    if job is None:
        raise ImportNotFound("Import job not found")
    return job


def job_view(job):
    return ImportJobRead(job_id=job.id, business_id=job.business_id, state=job.state,
        revision=job.revision, attempts=job.attempts, candidate_count=job.candidate_count,
        error_code=job.error_code, source=job.source, created_at=job.created_at)


def candidate_view(row):
    document = ImportCandidate.model_validate(row.document)
    if document.id != row.id or document.provenance.business_id != row.business_id:
        raise ImportReviewError("Stored candidate identity does not match tenant record")
    return ImportCandidateRead(candidate_id=row.id, revision=row.revision,
        candidate=document.model_dump(mode="json"), catalogue_bridge_status=(
            "pending_reviewed_allocation" if document.state == CandidateState.APPROVED else "not_requested"))


async def get_job(db, actor, business_id, job_id):
    await _access(db, actor, business_id)
    return job_view(await _job(db, business_id, job_id))


async def list_jobs(db, actor, business_id, *, after=None, limit=50):
    await _access(db, actor, business_id)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid page size")
    query = select(ImportJob).where(ImportJob.business_id == business_id)
    if after:
        query = query.where(ImportJob.id > after)
    return [job_view(job) for job in (await db.scalars(query.order_by(ImportJob.id).limit(limit))).all()]


async def list_candidates(db, actor, business_id, *, after=None, limit=50):
    await _access(db, actor, business_id)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid page size")
    query = select(ImportDraft).where(ImportDraft.business_id == business_id)
    if after:
        query = query.where(ImportDraft.id > after)
    return [candidate_view(row) for row in (await db.scalars(query.order_by(ImportDraft.id).limit(limit))).all()]


async def put_upload(db, actor, business_id, payload: UploadCreate, *, content: bytes):
    await _access(db, actor, business_id, write=True, lock=True)
    sha = validate_csv_upload(content) if payload.content_type == "text/csv" else validate_upload(content, payload.content_type)
    previous = await db.scalar(select(ImportAsset).where(
        ImportAsset.business_id == business_id, ImportAsset.idempotency_key == payload.idempotency_key))
    if previous:
        if previous.sha256 != sha or previous.content_type != payload.content_type:
            raise ImportConflict("Idempotency key reused for a different upload")
        asset = previous
    else:
        asset = ImportAsset(id=uuid4(), business_id=business_id, creator_id=actor.user_id,
            idempotency_key=payload.idempotency_key, content_type=payload.content_type,
            content=content, sha256=sha, size_bytes=len(content), authorized_at=now())
        db.add(asset)
        await db.flush()
    return UploadRead(asset_id=asset.id, sha256=asset.sha256, size_bytes=asset.size_bytes, content_type=asset.content_type)


async def create_job(db, actor, business_id, payload: ImportJobCreate):
    access = await _access(db, actor, business_id, write=True, lock=True)
    request_hash = digest(payload.model_dump(mode="json", exclude={"document_id", "document_label"} if payload.source_kind != "csv" else None))
    previous = await db.scalar(select(ImportJob).where(
        ImportJob.business_id == business_id, ImportJob.idempotency_key == payload.idempotency_key))
    if previous:
        if previous.request_hash != request_hash:
            raise ImportConflict("Idempotency key reused for a different import")
        return job_view(previous)
    source = {"kind": payload.source_kind}
    if payload.source_kind == "website":
        source["url"] = payload.source_url
    elif payload.source_kind == "instagram":
        account = access.instagram_page_id
        if not account:
            raise ImportConflict("Connected Instagram account required")
        source.update(media_id=payload.media_id, account_id=account)
        if payload.source_url:
            source["url"] = payload.source_url
    else:
        asset = await db.scalar(select(ImportAsset).where(
            ImportAsset.business_id == business_id, ImportAsset.id == payload.asset_id))
        if asset is None:
            raise ImportNotFound("Import asset not found")
        if payload.source_kind == "csv":
            if asset.content_type != "text/csv":
                raise ValueError("CSV source requires a CSV upload")
            source.update(document_id=str(payload.document_id), document_label=payload.document_label,
                media_id=f"csv-document:{payload.document_id}", upload_sha256=asset.sha256)
        else:
            if asset.content_type == "text/csv":
                raise ValueError("Media source cannot consume a CSV upload")
            source["media_id"] = asset.sha256  # Stable media identity across upload keys/blob UUIDs.
    timestamp = now()
    job = ImportJob(id=uuid4(), business_id=business_id, creator_id=actor.user_id,
        idempotency_key=payload.idempotency_key, request_hash=request_hash, source=source,
        asset_id=payload.asset_id, state="pending", revision=1, attempts=0,
        candidate_count=0, error_code=None, authorized_at=timestamp, created_at=timestamp, available_at=timestamp)
    db.add(job)
    await db.flush()
    return job_view(job)


async def _replay(db, business_id, key, request_hash):
    audit = await db.scalar(select(ImportAudit).where(
        ImportAudit.business_id == business_id, ImportAudit.idempotency_key == key))
    if audit and audit.request_hash != request_hash:
        raise ImportConflict("Idempotency key reused for a different action")
    return audit


def _audit(db, *, business_id, actor_id, key, request_hash, action, details, job_id=None, candidate_id=None):
    db.add(ImportAudit(id=uuid4(), business_id=business_id, actor_id=actor_id,
        idempotency_key=key, request_hash=request_hash, action=action, details=details,
        job_id=job_id, candidate_id=candidate_id))


async def mutate_job(db, actor, business_id, job_id, payload: JobMutation, *, action):
    await _access(db, actor, business_id, write=True, lock=True)
    if action not in ("cancel", "retry"):
        raise ValueError("Unsupported job action")
    request_hash = digest({"job_id": str(job_id), "action": action, **payload.model_dump(mode="json")})
    audit = await _replay(db, business_id, payload.idempotency_key, request_hash)
    if audit:
        return ImportJobRead.model_validate(audit.details["result"])
    job = await _job(db, business_id, job_id, lock=True)
    if job.revision != payload.expected_revision:
        raise ImportRevisionConflict("Import job revision changed")
    if action == "cancel":
        if job.state not in ("pending", "running", "failed"):
            raise ImportConflict("Import job cannot be cancelled")
        job.state = "cancelled"
    else:
        if job.state != "failed" or job.attempts >= 3 or job.error_code in ("authorization_revoked", "source_connection_changed"):
            raise ImportConflict("Import job is not retryable")
        job.state = "pending"
        job.available_at = now() + timedelta(seconds=min(5 * 2 ** job.attempts, 60))
    job.revision += 1
    job.error_code = None
    job.lease_token = job.lease_expires_at = None
    result = job_view(job)
    _audit(db, business_id=business_id, actor_id=actor.user_id, key=payload.idempotency_key,
        request_hash=request_hash, action=action, job_id=job.id, details={"result": result.model_dump(mode="json")})
    await db.flush()
    return result


async def review_candidate(db, actor, business_id, candidate_id, payload: CandidateReviewWrite):
    await _access(db, actor, business_id, write=True, lock=True)
    request_hash = digest({"candidate_id": str(candidate_id), **payload.model_dump(mode="json")})
    audit = await _replay(db, business_id, payload.idempotency_key, request_hash)
    if audit:
        return ImportCandidateRead.model_validate(audit.details["result"])
    row = await db.scalar(select(ImportDraft).where(
        ImportDraft.business_id == business_id, ImportDraft.id == candidate_id).with_for_update())
    if row is None:
        raise ImportNotFound("Import candidate not found")
    if row.revision != payload.expected_revision:
        raise ImportRevisionConflict("Import candidate revision changed")
    before = ImportCandidate.model_validate(row.document)
    updated = before
    if payload.action == "edit":
        if payload.confirmed_fields or payload.reason:
            raise ImportReviewError("Edit cannot confirm or reject facts")
        updates = tuple(SellerOverride(field=o.field, value=o.value, reviewer_id=actor.user_id) for o in payload.overrides)
        updated = apply_overrides(updated, updates, business_id=business_id)
    else:
        if payload.overrides:
            raise ImportReviewError("Edit factual overrides before a separate explicit decision")
        decision = ReviewDecision(reviewer_id=actor.user_id,
            confirmed_fields=tuple(payload.confirmed_fields), reason=payload.reason)
        if payload.action == "approve":
            updated = approve(confirm_facts(updated, decision, business_id=business_id), business_id=business_id)
        else:
            if payload.confirmed_fields:
                raise ImportReviewError("Rejection cannot confirm facts")
            updated = reject(updated, decision, business_id=business_id)
    row.document = updated.model_dump(mode="json")
    row.revision += 1
    result = candidate_view(row)
    _audit(db, business_id=business_id, actor_id=actor.user_id, key=payload.idempotency_key,
        request_hash=request_hash, action=payload.action, candidate_id=row.id, job_id=row.last_job_id,
        details={"before": before.model_dump(mode="json"), "result": result.model_dump(mode="json")})
    await db.flush()
    return result


@dataclass(frozen=True)
class JobClaim:
    job_id: UUID
    business_id: UUID
    actor_id: UUID
    lease_token: UUID
    source: dict
    captured_at: datetime
    upload_content: bytes | None = None
    upload_content_type: str | None = None


def _fail(job, code):
    job.state, job.error_code = "failed", code
    job.lease_token = job.lease_expires_at = None
    job.revision += 1


async def claim_job(db, business_id, job_id) -> JobClaim | None:
    # Tenant business lock also serializes candidate upserts across import jobs.
    await db.scalar(select(Business).where(Business.id == business_id).with_for_update())
    job = await _job(db, business_id, job_id, lock=True)
    timestamp = now()
    if job.state == "running" and job.lease_expires_at > timestamp:
        return None
    if job.state not in ("pending", "running"):
        return None
    if job.state == "pending" and job.available_at > timestamp:
        return None
    if job.attempts >= 3:
        _fail(job, "attempts_exhausted")
        await db.flush()
        return None
    try:
        access = await _access(db, Actor(job.creator_id, "import_job"), business_id, write=True)
    except HTTPException:
        _fail(job, "authorization_revoked")
        await db.flush()
        return None
    if job.source["kind"] == "instagram" and access.instagram_page_id != job.source["account_id"]:
        _fail(job, "source_connection_changed")
        await db.flush()
        return None
    content = content_type = None
    if job.asset_id:
        asset = await db.scalar(select(ImportAsset).where(
            ImportAsset.business_id == business_id, ImportAsset.id == job.asset_id))
        if asset is None:
            _fail(job, "upload_unavailable")
            await db.flush()
            return None
        content, content_type = bytes(asset.content), asset.content_type
    token = uuid4()
    job.state, job.error_code = "running", None
    job.lease_token, job.lease_expires_at = token, timestamp + timedelta(seconds=60)
    job.attempts += 1
    job.revision += 1
    await db.flush()
    # CSV bytes are immutable at acceptance: delayed execution must not make an
    # older file a newer document version. Other adapters capture fresh data.
    captured_at = job.created_at if job.source["kind"] == "csv" else timestamp
    return JobClaim(job.id, business_id, job.creator_id, token, dict(job.source), captured_at, content, content_type)


async def collect_claim(claim: JobClaim, *, fetcher: SafeFetcher, instagram_provider=None):
    source = {key: value for key, value in claim.source.items() if key != "account_id"}
    if source["kind"] == "website":
        fetched = await fetcher.fetch(source["url"], authorized_origin=source["url"])
        items = extract_website(fetched)
        evidence = f"Literal structured Product fields; fetched {fetched.final_url}"
    elif source["kind"] == "csv":
        if claim.upload_content_type != "text/csv":
            raise CSVSourceError("content_type")
        records = parse_csv(claim.upload_content)
        items = tuple((record.product_ref, record.facts) for record in records)
        evidence = f"Literal CSV facts; upload SHA256 {claim.source['upload_sha256']}; seller review required"
        source = {"kind": "csv", "media_id": source["media_id"]}
    elif source["kind"] == "uploaded_media":
        validate_upload(claim.upload_content, claim.upload_content_type)
        items = (("media-product", DraftFacts()),)
        evidence = "Seller-authorized uploaded media; facts unknown; no AI/media inference performed"
    else:
        # Existing InstagramClient has no owned-media retrieval/owner proof.
        # An integration-supplied adapter may use only that authorized provider,
        # return its verified account/media IDs and bounded structured facts.
        if instagram_provider is None:
            raise FetchError("provider_capability_pending")
        result = await asyncio.wait_for(instagram_provider.fetch_owned_media(
            business_id=claim.business_id, account_id=claim.source["account_id"], media_id=source["media_id"]), timeout=15)
        if result.account_id != claim.source["account_id"] or result.media_id != source["media_id"]:
            raise FetchError("provider_ownership_mismatch")
        items = result.products
        if not 1 <= len(items) <= 200:
            raise FetchError("invalid_provider_products")
        evidence = "Connected provider structured data; seller review required"
    candidates = []
    for index, (key, facts) in enumerate(items):
        candidate = parse_candidate({"provenance": {
            "business_id": claim.business_id, "import_job_id": claim.job_id,
            "captured_at": claim.captured_at, "source": source,
            "source_product_id": key, "evidence": evidence + (f"; source line {records[index].line}" if source["kind"] == "csv" else ""),
        }, "facts": facts.model_dump()}, business_id=claim.business_id)
        candidates.append(begin_review(candidate, business_id=claim.business_id))
    if len({candidate.id for candidate in candidates}) != len(candidates):
        raise FetchError("duplicate_source_product_key")
    return tuple(candidates)


async def check_claim(db, claim: JobClaim):
    """Cancellation/revocation checkpoint after committed claim, before fetch."""
    await db.scalar(select(Business).where(Business.id == claim.business_id).with_for_update())
    job = await _job(db, claim.business_id, claim.job_id, lock=True)
    if job.state != "running" or job.lease_token != claim.lease_token or job.lease_expires_at <= now():
        return False
    try:
        access = await _access(db, Actor(job.creator_id, "import_job"), claim.business_id, write=True)
    except HTTPException:
        _fail(job, "authorization_revoked")
        await db.flush()
        return False
    if job.source["kind"] == "instagram" and access.instagram_page_id != job.source["account_id"]:
        _fail(job, "source_connection_changed")
        await db.flush()
        return False
    return True


async def finish_claim(db, claim: JobClaim, *, candidates=(), error_code=None):
    await db.scalar(select(Business).where(Business.id == claim.business_id).with_for_update())
    job = await _job(db, claim.business_id, claim.job_id, lock=True)
    if job.state != "running" or job.lease_token != claim.lease_token or job.lease_expires_at <= now():
        return False  # Cancellation or a newer attempt fences late results.
    try:
        access = await _access(db, Actor(job.creator_id, "import_job"), claim.business_id, write=True)
        if job.source["kind"] == "instagram" and access.instagram_page_id != job.source["account_id"]:
            error_code = "source_connection_changed"
    except HTTPException:
        error_code = "authorization_revoked"
    if error_code:
        _fail(job, error_code)
        await db.flush()
        return False
    if not 1 <= len(candidates) <= 200:
        raise ImportReviewError("Expected bounded candidate results")
    for candidate in sorted(candidates, key=lambda item: str(item.id)):
        if candidate.provenance.business_id != claim.business_id or candidate.provenance.import_job_id != claim.job_id:
            raise ImportReviewError("Candidate provenance does not match claim")
        row = await db.scalar(select(ImportDraft).where(
            ImportDraft.business_id == claim.business_id, ImportDraft.id == candidate.id).with_for_update())
        details = {"incoming": candidate.model_dump(mode="json")}
        if row is None:
            row = ImportDraft(id=candidate.id, business_id=claim.business_id,
                last_job_id=claim.job_id, revision=1, document=candidate.model_dump(mode="json"))
            db.add(row)
        else:
            previous = ImportCandidate.model_validate(row.document)
            if previous.provenance.captured_at > candidate.provenance.captured_at:
                # A slower older job cannot overwrite a newer extraction/review.
                _audit(db, business_id=claim.business_id, actor_id=claim.actor_id,
                    key=uuid5(claim.lease_token, str(candidate.id)), request_hash=digest(details),
                    action="stale_capture_ignored", candidate_id=row.id, job_id=claim.job_id, details=details)
                continue
            result = reimport_candidate(previous, candidate, business_id=claim.business_id)
            details["before"] = previous.model_dump(mode="json")
            details["changed_fields"] = [change.field.value for change in result.changes]
            row.document, row.last_job_id = result.candidate.model_dump(mode="json"), claim.job_id
            row.revision += 1
        # Flush the draft first: its audit has a composite tenant FK.
        await db.flush()
        _audit(db, business_id=claim.business_id, actor_id=claim.actor_id,
            key=uuid5(claim.lease_token, str(candidate.id)), request_hash=digest(details),
            action="import_extraction", candidate_id=row.id, job_id=claim.job_id, details=details)
    job.state, job.error_code = "review_required", None
    job.candidate_count = len(candidates)
    job.lease_token = job.lease_expires_at = None
    job.revision += 1
    await db.flush()
    return True


async def run_job(sessions, business_id, job_id, *, fetcher=None, instagram_provider=None):
    """Scheduler entry point. No live transport is called by tests.

    A persisted pending job survives dispatch failure. Repeated deliveries while
    leased are no-ops; recovery may reclaim an expired lease at most three times.
    """
    async with sessions.begin() as db:
        claim = await claim_job(db, business_id, job_id)
    if claim is None:
        return False
    async with sessions.begin() as db:
        if not await check_claim(db, claim):
            return False
    try:
        candidates = await collect_claim(claim, fetcher=fetcher or SafeFetcher(), instagram_provider=instagram_provider)
        error_code = None
    except CSVSourceError as exc:
        candidates, error_code = (), exc.code
    except FetchError as exc:
        allowed_errors = {
            "invalid_url", "credential_url_forbidden", "too_many_query_fields", "encoded_query_key_forbidden", "invalid_dns_address", "non_public_address",
            "transition_address_forbidden", "too_many_dns_addresses", "invalid_dns_response",
            "transport_busy", "resolver_busy", "response_headers_too_large", "body_too_large",
            "encoded_body_forbidden", "fetch_timeout", "fetch_failed", "unauthorized_redirect_origin",
            "instagram_requires_connected_provider", "peer_address_mismatch", "too_many_redirects",
            "invalid_redirect", "source_http_error", "unsupported_content_type", "invalid_source_encoding",
            "too_many_structured_blocks", "ambiguous_structured_json", "structured_source_too_complex",
            "too_many_source_products", "stable_product_key_required", "invalid_source_product_key",
            "duplicate_source_product_key", "invalid_structured_facts", "structured_products_not_found",
            "invalid_upload_size", "unsupported_upload_type", "provider_capability_pending",
            "provider_ownership_mismatch", "invalid_provider_products",
        }
        candidates, error_code = (), exc.code if exc.code in allowed_errors else "source_adapter_failed"
    except TimeoutError:
        candidates, error_code = (), "fetch_timeout"
    except (ImportReviewError, ValidationError, ValueError, TypeError):
        candidates, error_code = (), "invalid_source_data"
    except Exception:
        # Never persist/log raw transport/provider exceptions or credentials.
        candidates, error_code = (), "source_adapter_failed"
    async with sessions.begin() as db:
        return await finish_claim(db, claim, candidates=candidates, error_code=error_code)
