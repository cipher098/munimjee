"""Explicit source review and bounded canonical allocation, never activation."""
from typing import Literal
from uuid import UUID
from pydantic import Field, field_validator
from app.schemas.catalogue_v1 import Contract
from app.schemas.checkout_v1 import ExplicitReview
from app.v1.imports.contracts import FactField


class ImportAllocation(Contract):
    options: dict[str, str] = Field(default_factory=dict, max_length=8)
    stock_available: int = Field(strict=True, ge=0, le=1_000_000)
    active: bool = Field(strict=True)


class ImportCatalogueWrite(ExplicitReview):
    idempotency_key: UUID
    expected_revision: int = Field(strict=True, ge=1)
    confirmed_fields: list[FactField] = Field(min_length=5, max_length=5)
    allocations: list[ImportAllocation] = Field(min_length=1, max_length=500)
    photo_urls: list[str] = Field(default_factory=list, max_length=30)
    category_id: UUID | None = None

    @field_validator('confirmed_fields')
    @classmethod
    def all_facts(cls, value):
        if set(value) != set(FactField):
            raise ValueError('Explicit confirmation of every factual field required')
        return value


class ImportCatalogueRead(Contract):
    contract_version: Literal['import-catalogue.v1'] = 'import-catalogue.v1'
    receipt_id: UUID
    candidate_id: UUID
    candidate_revision: int
    product_id: UUID
    catalogue_url: str
    creation_mode: Literal['private_draft'] = 'private_draft'
    replayed: bool


class ImportCataloguePreview(Contract):
    contract_version: Literal['import-catalogue-preview.v1'] = 'import-catalogue-preview.v1'
    candidate_id: UUID
    candidate_revision: int
    state: Literal['needs_review', 'ready_for_allocation', 'already_created', 'unsupported']
    facts: dict
    issues: list[str]
    allocations: list[dict]
    existing: ImportCatalogueRead | None = None
