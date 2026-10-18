"""Import write bodies never carry authorization tenant or reviewer identity."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.v1.imports import FactField, SourceReference
from app.v1.imports.contracts import clean_text
from app.v1.imports.fetching import source_url


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Authorized(Contract):
    source_authorized: Literal[True]

    @field_validator("source_authorized", mode="before")
    @classmethod
    def explicit_authorization(cls, value):
        if value is not True:
            raise ValueError("Explicit permission to import this source is required")
        return value


class ImportJobCreate(Authorized):
    idempotency_key: UUID
    source_kind: Literal["website", "instagram", "uploaded_media", "csv"]
    source_url: str | None = Field(default=None, max_length=2048)
    media_id: str | None = Field(default=None, max_length=200)
    asset_id: UUID | None = None
    document_id: UUID | None = None
    document_label: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def source_shape(self):
        if self.source_kind == "csv":
            if not self.asset_id or not self.document_id or not self.document_label or self.source_url is not None or self.media_id is not None:
                raise ValueError("CSV requires only a tenant-owned asset and explicit document identity/label")
            self.document_label = clean_text(self.document_label, limit=100)
            return self
        if self.document_id is not None or self.document_label is not None:
            raise ValueError("Document fields are only supported for CSV")
        if self.source_kind == "website":
            if not self.source_url or self.asset_id or self.media_id:
                raise ValueError("Website import requires only source_url")
            self.source_url = source_url(self.source_url)
        elif self.source_kind == "instagram":
            if self.asset_id:
                raise ValueError("Instagram import cannot refer to uploads")
            reference = SourceReference(kind="instagram", url=self.source_url, media_id=self.media_id)
            self.source_url = source_url(reference.url) if reference.url else None
            self.media_id = reference.media_id
        elif not self.asset_id or self.source_url or self.media_id:
            raise ValueError("Uploaded-media import requires only a tenant-owned asset_id")
        return self


class UploadCreate(Authorized):
    idempotency_key: UUID
    content_type: Literal["image/jpeg", "image/png", "video/mp4", "text/csv"]


class UploadRead(Contract):
    asset_id: UUID
    content_type: str
    size_bytes: int
    sha256: str


class JobMutation(Contract):
    expected_revision: int = Field(strict=True, ge=1)
    idempotency_key: UUID


class OverrideWrite(Contract):
    field: FactField
    value: Any


class CandidateReviewWrite(JobMutation):
    action: Literal["edit", "approve", "reject"]
    overrides: list[OverrideWrite] = Field(default_factory=list, max_length=5)
    confirmed_fields: list[FactField] = Field(default_factory=list, max_length=5)
    reason: str | None = Field(default=None, max_length=1000)


class ImportJobRead(Contract):
    contract_version: Literal["imports.v1"] = "imports.v1"
    job_id: UUID
    business_id: UUID
    state: Literal["pending", "running", "review_required", "failed", "cancelled"]
    revision: int
    attempts: int
    candidate_count: int
    error_code: str | None
    source: dict
    created_at: datetime


class ImportCandidateRead(Contract):
    candidate_id: UUID
    revision: int
    candidate: dict
    catalogue_bridge_status: Literal["not_requested", "pending_reviewed_allocation"]


class CandidatePage(Contract):
    items: list[ImportCandidateRead]
    next_after: UUID | None = None
