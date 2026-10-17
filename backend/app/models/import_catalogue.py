"""Immutable tenant-bound receipt for explicit import approval/private creation."""
from uuid import uuid4

from sqlalchemy import (CheckConstraint, Column, DateTime, ForeignKey,
                        ForeignKeyConstraint, Integer, String, UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.database import Base


class ImportCatalogueBridge(Base):
    __tablename__ = "import_catalogue_bridges"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False)
    candidate_id = Column(UUID(as_uuid=True), nullable=False)
    candidate_revision = Column(Integer, nullable=False)
    product_id = Column(UUID(as_uuid=True), nullable=False)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    idempotency_key = Column(UUID(as_uuid=True), nullable=False)
    request_hash = Column(String(64), nullable=False)
    approved_snapshot = Column(JSONB, nullable=False)
    creation_snapshot = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("business_id", "candidate_id", name="import_bridge_one_candidate"),
        UniqueConstraint("business_id", "idempotency_key", name="import_bridge_idempotency"),
        ForeignKeyConstraint(["business_id", "candidate_id"], ["v1_import_drafts.business_id", "v1_import_drafts.id"],
                             name="import_bridge_candidate", ondelete="RESTRICT"),
        ForeignKeyConstraint(["business_id", "product_id"], ["products.seller_id", "products.id"],
                             name="import_bridge_product", ondelete="RESTRICT"),
        ForeignKeyConstraint(["business_id", "actor_user_id"], ["memberships.business_id", "memberships.user_id"],
                             name="import_bridge_member", ondelete="RESTRICT"),
        CheckConstraint("candidate_revision >= 1", name="import_bridge_revision"),
        CheckConstraint("request_hash ~ '^[a-f0-9]{64}$'", name="import_bridge_hash"),
        CheckConstraint("jsonb_typeof(approved_snapshot) = 'object' AND jsonb_typeof(creation_snapshot) = 'object'",
                        name="import_bridge_snapshots"),
    )
