"""Side-effect-free parsing, matching and review. Callers persist and authorize."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid5

from .contracts import (
    CandidateInput, CandidateState, FactField, ImportCandidate, Provenance,
    ReviewDecision, SellerOverride,
)

MAX_BATCH_SIZE = 200
MAX_PAYLOAD_BYTES = 2_000_000


class ImportReviewError(ValueError):
    """A requested domain transition is invalid."""


def _assert_owner(candidate: ImportCandidate, business_id: UUID) -> None:
    if candidate.provenance.business_id != business_id:
        raise ImportReviewError("candidate does not belong to business")


def parse_candidate(payload: Mapping[str, Any], *, business_id: UUID) -> ImportCandidate:
    """Parse structured, seller-supplied data only; captions are never executed."""
    source = CandidateInput.model_validate(payload)
    if source.provenance.business_id != business_id:
        raise ImportReviewError("source does not belong to business")
    identity = json.dumps(
        [source.provenance.source.identity(), source.provenance.source_product_id],
        ensure_ascii=True, separators=(",", ":"),
    )
    return ImportCandidate(
        id=uuid5(business_id, identity), provenance=source.provenance,
        extracted=source.facts, seller_product_ref=source.seller_product_ref,
    )


def parse_batch(payload: str, *, business_id: UUID) -> tuple[ImportCandidate, ...]:
    """Bounded JSON array parser. Repeated identities in one batch require correction."""
    if not isinstance(payload, str) or len(payload) > MAX_PAYLOAD_BYTES:
        raise ImportReviewError("batch exceeds payload limit")
    try:
        if len(payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ImportReviewError("batch exceeds payload limit")
    except UnicodeEncodeError as exc:
        raise ImportReviewError("batch contains invalid Unicode") from exc

    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ImportReviewError("duplicate JSON keys")
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise ImportReviewError("nonfinite JSON values forbidden")

    try:
        items = json.loads(payload, object_pairs_hook=unique_keys, parse_constant=invalid_constant)
    except (ValueError, RecursionError) as exc:
        raise ImportReviewError("invalid structured JSON batch") from exc
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_BATCH_SIZE:
        raise ImportReviewError("expected between 1 and 200 candidates")
    candidates = tuple(parse_candidate(item, business_id=business_id) for item in items)
    if len({candidate.id for candidate in candidates}) != len(candidates):
        raise ImportReviewError("duplicate source/product identity within batch")
    return candidates


@dataclass(frozen=True)
class DuplicateMatch:
    candidate_id: UUID
    reason: str
    exact_identity: bool = False


def duplicate_matches(candidate: ImportCandidate, existing: Iterable[ImportCandidate]) -> tuple[DuplicateMatch, ...]:
    """Suggest matches without merging; one media item may show several products."""
    result: list[DuplicateMatch] = []
    for index, previous in enumerate(existing):
        if index >= MAX_BATCH_SIZE:
            raise ImportReviewError("matching window exceeds 200 candidates")
        if previous.provenance.business_id != candidate.provenance.business_id:
            continue
        if previous.id == candidate.id:
            result.append(DuplicateMatch(previous.id, "same_source_product", True))
        elif candidate.seller_product_ref and candidate.seller_product_ref == previous.seller_product_ref:
            result.append(DuplicateMatch(previous.id, "same_seller_product_ref"))
        elif (
            candidate.extracted.title and previous.extracted.title
            and candidate.extracted.title.casefold() == previous.extracted.title.casefold()
        ):
            result.append(DuplicateMatch(previous.id, "same_title_requires_review"))
    return tuple(sorted(result, key=lambda match: (str(match.candidate_id), match.reason)))


def begin_review(candidate: ImportCandidate, *, business_id: UUID) -> ImportCandidate:
    _assert_owner(candidate, business_id)
    if candidate.state != CandidateState.PENDING:
        raise ImportReviewError("only pending candidates can begin review")
    return candidate.model_copy(update={"state": CandidateState.REVIEW_REQUIRED})


def apply_overrides(
    candidate: ImportCandidate, overrides: tuple[SellerOverride, ...], *, business_id: UUID,
) -> ImportCandidate:
    _assert_owner(candidate, business_id)
    if candidate.state not in (CandidateState.REVIEW_REQUIRED, CandidateState.APPROVED):
        raise ImportReviewError("candidate must be under review or approved before editing")
    if not overrides or len(overrides) > len(FactField) or len({o.field for o in overrides}) != len(overrides):
        raise ImportReviewError("expected distinct bounded factual overrides")
    merged = {override.field: override for override in candidate.overrides}
    merged.update({override.field: override for override in overrides})
    return candidate.model_copy(update={
        "overrides": tuple(merged[field] for field in FactField if field in merged),
        "state": CandidateState.REVIEW_REQUIRED, "review": None,
    })


def confirm_facts(
    candidate: ImportCandidate, decision: ReviewDecision, *, business_id: UUID,
) -> ImportCandidate:
    _assert_owner(candidate, business_id)
    if candidate.state != CandidateState.REVIEW_REQUIRED:
        raise ImportReviewError("candidate is not awaiting review")
    if set(decision.confirmed_fields) != set(FactField) or len(decision.confirmed_fields) != len(FactField):
        raise ImportReviewError("seller must explicitly confirm every factual field")
    return candidate.model_copy(update={"review": decision})


def approve(candidate: ImportCandidate, *, business_id: UUID) -> ImportCandidate:
    _assert_owner(candidate, business_id)
    if (
        candidate.state != CandidateState.REVIEW_REQUIRED or candidate.review is None
        or set(candidate.review.confirmed_fields) != set(FactField)
        or len(candidate.review.confirmed_fields) != len(FactField)
    ):
        raise ImportReviewError("explicit seller confirmation required")
    facts = candidate.effective_facts()
    if any(getattr(facts, field) is None for field in ("title", "price", "stock", "options")):
        raise ImportReviewError("title, price, stock and options must be explicitly resolved")
    return candidate.model_copy(update={"state": CandidateState.APPROVED})


def reject(candidate: ImportCandidate, decision: ReviewDecision, *, business_id: UUID) -> ImportCandidate:
    _assert_owner(candidate, business_id)
    if candidate.state not in (CandidateState.PENDING, CandidateState.REVIEW_REQUIRED) or not decision.reason:
        raise ImportReviewError("reject requires pending/review candidate and reason")
    return candidate.model_copy(update={"state": CandidateState.REJECTED, "review": decision})


@dataclass(frozen=True)
class ProposedChange:
    field: FactField
    previous_extracted: Any
    incoming_extracted: Any
    effective_value: Any
    seller_override_preserved: bool


@dataclass(frozen=True)
class ReimportResult:
    candidate: ImportCandidate
    changes: tuple[ProposedChange, ...]
    previous_provenance: Provenance


def reimport_candidate(
    existing: ImportCandidate, incoming: ImportCandidate, *, business_id: UUID,
) -> ReimportResult:
    _assert_owner(existing, business_id)
    _assert_owner(incoming, business_id)
    if existing.id != incoming.id:
        raise ImportReviewError("reimport requires exact source/product identity")
    if incoming.provenance.captured_at < existing.provenance.captured_at:
        raise ImportReviewError("stale source capture cannot replace newer extraction")
    effective = existing.effective_facts()
    overrides = {override.field for override in existing.overrides}
    changes = tuple(
        ProposedChange(field, getattr(existing.extracted, field.value), getattr(incoming.extracted, field.value),
                       getattr(effective, field.value), field in overrides)
        for field in FactField
        if getattr(existing.extracted, field.value) != getattr(incoming.extracted, field.value)
    )
    # Rejected data stays rejected. Any factual change invalidates prior approval.
    state = existing.state
    if changes and state != CandidateState.REJECTED:
        state = CandidateState.REVIEW_REQUIRED
    updated = existing.model_copy(update={
        "provenance": incoming.provenance, "extracted": incoming.extracted,
        "state": state, "review": existing.review if not changes or state == CandidateState.REJECTED else None,
    })
    return ReimportResult(updated, changes, existing.provenance)
