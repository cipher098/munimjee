"""Durable draft imports; integrator must register additive DDL after 0045."""
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint,
    Integer, LargeBinary, String, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.database import Base


class ImportAsset(Base):
    __tablename__ = "v1_import_assets"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False)
    creator_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    idempotency_key = Column(UUID(as_uuid=True), nullable=False)
    content_type = Column(String(32), nullable=False)
    sha256 = Column(String(64), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    content = Column(LargeBinary, nullable=False)
    authorized_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("business_id", "id", name="v1_import_asset_tenant"),
        UniqueConstraint("business_id", "idempotency_key", name="v1_import_asset_idempotency"),
        CheckConstraint("size_bytes > 0 AND size_bytes <= 5000000 AND octet_length(content) = size_bytes", name="v1_import_asset_size"),
        CheckConstraint("content_type IN ('image/jpeg','image/png','video/mp4','text/csv') AND sha256 ~ '^[a-f0-9]{64}$'", name="v1_import_asset_content"),
    )


class ImportJob(Base):
    __tablename__ = "v1_import_jobs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True)
    creator_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    idempotency_key = Column(UUID(as_uuid=True), nullable=False)
    request_hash = Column(String(64), nullable=False)
    source = Column(JSONB, nullable=False)
    asset_id = Column(UUID(as_uuid=True), nullable=True)
    state = Column(String(24), nullable=False, default="pending", server_default="pending")
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    lease_token = Column(UUID(as_uuid=True), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    candidate_count = Column(Integer, nullable=False, default=0, server_default="0")
    error_code = Column(String(64), nullable=True)
    authorized_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    available_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("business_id", "id", name="v1_import_job_tenant"),
        UniqueConstraint("business_id", "idempotency_key", name="v1_import_job_idempotency"),
        ForeignKeyConstraint(["business_id", "asset_id"], ["v1_import_assets.business_id", "v1_import_assets.id"], name="v1_import_job_tenant_asset"),
        CheckConstraint("state IN ('pending','running','review_required','failed','cancelled')", name="v1_import_job_state"),
        CheckConstraint("revision >= 1 AND attempts >= 0 AND attempts <= 3 AND candidate_count >= 0 AND candidate_count <= 200", name="v1_import_job_counters"),
        CheckConstraint("(state = 'running' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (state <> 'running' AND lease_token IS NULL AND lease_expires_at IS NULL)", name="v1_import_job_lease"),
        CheckConstraint("jsonb_typeof(source) = 'object' AND request_hash ~ '^[a-f0-9]{64}$'", name="v1_import_job_source"),
    )


class ImportDraft(Base):
    __tablename__ = "v1_import_drafts"
    id = Column(UUID(as_uuid=True), primary_key=True)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True)
    last_job_id = Column(UUID(as_uuid=True), nullable=False)
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    document = Column(JSONB, nullable=False)
    __table_args__ = (
        UniqueConstraint("business_id", "id", name="v1_import_draft_tenant"),
        ForeignKeyConstraint(["business_id", "last_job_id"], ["v1_import_jobs.business_id", "v1_import_jobs.id"], name="v1_import_draft_tenant_job"),
        CheckConstraint("revision >= 1 AND jsonb_typeof(document) = 'object'", name="v1_import_draft_document"),
    )


class ImportAudit(Base):
    __tablename__ = "v1_import_audits"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True)
    job_id = Column(UUID(as_uuid=True), nullable=True)
    candidate_id = Column(UUID(as_uuid=True), nullable=True)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    idempotency_key = Column(UUID(as_uuid=True), nullable=False)
    request_hash = Column(String(64), nullable=False)
    action = Column(String(32), nullable=False)
    details = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("business_id", "idempotency_key", name="v1_import_audit_idempotency"),
        ForeignKeyConstraint(["business_id", "job_id"], ["v1_import_jobs.business_id", "v1_import_jobs.id"], name="v1_import_audit_tenant_job"),
        ForeignKeyConstraint(["business_id", "candidate_id"], ["v1_import_drafts.business_id", "v1_import_drafts.id"], name="v1_import_audit_tenant_candidate"),
        CheckConstraint("jsonb_typeof(details) = 'object' AND request_hash ~ '^[a-f0-9]{64}$'", name="v1_import_audit_details"),
    )
