"""Atomic approved import -> private canonical draft with immutable provenance.

Caller owns commit/rollback. Business then Storefront then candidate locking
serializes source review with creation; PostgreSQL supplies current authority.
"""
from itertools import product
import hmac
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update

from app.config import settings
from app.models.import_catalogue import ImportCatalogueBridge
from app.models.identity import Business
from app.models.imports_v1 import ImportAudit, ImportDraft
from app.models.commerce import Storefront
from app.schemas.catalogue_v1 import SKUWrite
from app.schemas.checkout_v1 import ProductCreate
from app.schemas.import_catalogue import ImportCatalogueRead, ImportCataloguePreview
from app.services import imports_v1 as imports
from app.services import checkout_v1 as catalogue
from app.v1.imports import CandidateState, ImportCandidate, ReviewDecision, approve, begin_review, confirm_facts
from app.v1.imports.contracts import FactField


def conflict(detail):
    raise HTTPException(409, detail)


def combinations(facts):
    if facts.title is None or facts.price is None or facts.stock is None or facts.options is None:
        raise ValueError('Resolve title, price, stock and options before creating a draft')
    if facts.price.currency != 'INR':
        raise ValueError('Canonical catalogue supports INR only; no currency conversion is inferred')
    price = facts.price.amount * 100
    if price != price.to_integral_value() or not 0 <= price <= 2_000_000_000:
        raise ValueError('Price is outside the canonical catalogue range')
    count = 1
    for option in facts.options:
        count *= len(option.values)
        if len(option.name) > 64:
            raise ValueError('Option name exceeds the canonical catalogue limit')
        if count > 500:
            raise ValueError('At most 500 explicit SKU combinations are supported')
    names = [option.name for option in facts.options]
    return [dict(zip(names, values)) for values in product(*(option.values for option in facts.options))]


def canonical_skus(facts, allocations):
    expected = combinations(facts)
    identity = lambda options: tuple(sorted(options.items()))
    wanted = {identity(options) for options in expected}
    supplied = [identity(row.options) for row in allocations]
    if len(supplied) != len(wanted) or set(supplied) != wanted:
        raise ValueError('Allocate each confirmed option combination exactly once')
    if sum(row.stock_available for row in allocations) != facts.stock:
        raise ValueError('Allocated stock must equal the explicitly confirmed source total')
    return [SKUWrite(options=row.options, stock_available=row.stock_available,
        active=row.active, price_minor=int(facts.price.amount * 100), currency='INR') for row in allocations]


def receipt_view(row, *, replayed):
    return ImportCatalogueRead(receipt_id=row.id, candidate_id=row.candidate_id,
        candidate_revision=row.candidate_revision, product_id=row.product_id,
        catalogue_url=f'/v1/businesses/{row.business_id}/catalogue', replayed=replayed)


async def candidate_row(db, business_id, candidate_id, *, lock=False):
    query = select(ImportDraft.id, ImportDraft.document, ImportDraft.revision, ImportDraft.last_job_id).where(
        ImportDraft.business_id == business_id, ImportDraft.id == candidate_id)
    row = (await db.execute((query.with_for_update() if lock else query).execution_options(autoflush=False))).one_or_none()
    if row is None:
        raise HTTPException(404, 'Import candidate not found')
    candidate = ImportCandidate.model_validate(row.document)
    if candidate.id != candidate_id or candidate.provenance.business_id != business_id:
        conflict('Stored candidate identity does not match tenant record')
    return row, candidate


async def preview(db, actor, business_id, candidate_id):
    await imports._access(db, actor, business_id)
    row, candidate = await candidate_row(db, business_id, candidate_id)
    existing = await db.scalar(select(ImportCatalogueBridge).where(
        ImportCatalogueBridge.business_id == business_id, ImportCatalogueBridge.candidate_id == candidate_id))
    facts = candidate.effective_facts()
    issues, allocations = [], []
    if not settings.V1_IMPORT_BRIDGE_ENABLED:
        issues.append('Import catalogue creation is not enabled')
    try:
        options = combinations(facts)
        allocations = [dict(options=item, stock_available=facts.stock if len(options) == 1 else None, active=True)
                       for item in options]
    except ValueError as exc:
        issues.append(str(exc))
    if not await db.scalar(select(Storefront.seller_id).where(Storefront.seller_id == business_id)):
        issues.append('Configure the storefront before creating a catalogue draft')
    if candidate.state == CandidateState.REJECTED:
        issues.append('Rejected source candidates cannot create catalogue drafts')
    state = 'already_created' if existing else 'unsupported' if issues else (
        'ready_for_allocation' if candidate.state == CandidateState.APPROVED else 'needs_review')
    return ImportCataloguePreview(candidate_id=candidate_id, candidate_revision=row.revision,
        state=state, facts=facts.model_dump(mode='json'), issues=issues, allocations=allocations,
        existing=receipt_view(existing, replayed=True) if existing else None)


async def create_draft(db, actor, business_id, candidate_id, payload, *, reauthorize=None):
    if not settings.V1_IMPORT_BRIDGE_ENABLED:
        raise HTTPException(404, 'Import catalogue bridge is disabled')
    await imports._access(db, actor, business_id, write=True)
    # Serialize import decisions without blocking the Business FK KEY SHARE
    # acquired by canonical catalogue writers holding the Storefront lock.
    await db.scalar(select(Business.id).where(Business.id == business_id)
        .with_for_update(key_share=True).execution_options(autoflush=False))
    await imports._fresh_access(db, actor, business_id, 'catalogue.write')
    if reauthorize is not None:
        await reauthorize()
    request_hash = imports.digest({'candidate_id':str(candidate_id), **payload.model_dump(mode='json')})
    previous = await db.scalar(select(ImportCatalogueBridge).where(
        ImportCatalogueBridge.business_id == business_id,
        ImportCatalogueBridge.idempotency_key == payload.idempotency_key))
    if previous:
        if previous.candidate_id != candidate_id or not hmac.compare_digest(previous.request_hash, request_hash):
            conflict('This import approval key was used for different facts')
        return receipt_view(previous, replayed=True)
    if await db.scalar(select(ImportAudit.id).where(ImportAudit.business_id == business_id,
            ImportAudit.idempotency_key == payload.idempotency_key)):
        conflict('This key already belongs to another import command')
    existing = await db.scalar(select(ImportCatalogueBridge).where(
        ImportCatalogueBridge.business_id == business_id, ImportCatalogueBridge.candidate_id == candidate_id))
    if existing:
        conflict({'code':'candidate_already_created', 'product_id':str(existing.product_id),
                  'message':'This source already created a private draft; review the existing catalogue product'})
    await catalogue.lock_store(db, business_id)
    row, before = await candidate_row(db, business_id, candidate_id, lock=True)
    if reauthorize is not None:
        await reauthorize()
    await imports._fresh_access(db, actor, business_id, 'catalogue.write')
    if row.revision != payload.expected_revision:
        conflict({'code':'import_revision_stale','message':'Import candidate revision changed before this action was accepted. Review current facts.'})
    candidate = before
    if candidate.state == CandidateState.PENDING:
        candidate = begin_review(candidate, business_id=business_id)
    if candidate.state == CandidateState.REVIEW_REQUIRED:
        candidate = approve(confirm_facts(candidate, ReviewDecision(reviewer_id=actor.user_id,
            confirmed_fields=tuple(payload.confirmed_fields)), business_id=business_id), business_id=business_id)
    if candidate.state != CandidateState.APPROVED:
        conflict('Explicit current source approval is required')
    facts = candidate.effective_facts()
    product_input = ProductCreate(idempotency_key=uuid4(), seller_reviewed=True,
        name=facts.title, description=facts.description or '', category_id=payload.category_id,
        photo_urls=payload.photo_urls, skus=canonical_skus(facts, payload.allocations))
    product_id, unexpected_replay = await catalogue.create_reviewed_product(db, business_id, product_input)
    if unexpected_replay:
        conflict('Unexpected internal catalogue command collision')
    revision = row.revision + (candidate != before)
    if candidate != before:
        await db.execute(update(ImportDraft).where(ImportDraft.business_id == business_id,
            ImportDraft.id == candidate_id, ImportDraft.revision == row.revision).values(
            document=candidate.model_dump(mode='json'), revision=revision).execution_options(synchronize_session=False))
    receipt = ImportCatalogueBridge(id=uuid4(), business_id=business_id, candidate_id=candidate_id,
        candidate_revision=revision, product_id=product_id, actor_user_id=actor.user_id,
        idempotency_key=payload.idempotency_key, request_hash=request_hash,
        approved_snapshot=candidate.model_dump(mode='json'), creation_snapshot={'catalogue':product_input.model_dump(mode='json'),
            'review':payload.model_dump(mode='json'), 'reviewer_user_id':str(actor.user_id)})
    db.add(receipt)
    result = receipt_view(receipt, replayed=False)
    imports._audit(db, business_id=business_id, actor_id=actor.user_id, key=payload.idempotency_key,
        request_hash=request_hash, action='catalogue_draft', candidate_id=candidate_id,
        job_id=row.last_job_id, details={'result':result.model_dump(mode='json')})
    await db.flush()
    return result
