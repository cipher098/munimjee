"""Additive V1 tenant identity; legacy sellers remain the compatibility anchor."""
from uuid import uuid4
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.database import Base


class Business(Base):
    __tablename__ = "businesses"
    # Existing tenant-owned records continue to use this exact seller UUID.
    id = Column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="RESTRICT"), primary_key=True)
    name = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # The only legacy identity link. Email/phone never merge users.
    legacy_seller_id = Column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="RESTRICT"), unique=True)
    display_name = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("business_id", "user_id", name="uq_memberships_business_user"),
        CheckConstraint("role IN ('owner', 'manager', 'staff', 'viewer')", name="ck_memberships_role"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    role = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
