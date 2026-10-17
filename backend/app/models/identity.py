"""Additive V1 tenant identity; legacy sellers remain the compatibility anchor."""
from uuid import uuid4
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from app.database import Base


class Business(Base):
    __tablename__ = "businesses"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(profile) = 'object'", name="businesses_profile_object"),
        CheckConstraint("profile_version >= 0", name="businesses_profile_version"),
    )
    # Existing tenant-owned records continue to use this exact seller UUID.
    id = Column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="RESTRICT"), primary_key=True)
    name = Column(String, nullable=False)
    profile = Column(JSONB, nullable=False, default=dict, server_default="{}")
    profile_confirmed_at = Column(DateTime(timezone=True), nullable=True)
    profile_version = Column(Integer, nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("auth_email", name="users_auth_email"),
        CheckConstraint("auth_version >= 0", name="users_auth_version"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # The only legacy identity link. Email/phone never merge users.
    legacy_seller_id = Column(UUID(as_uuid=True), ForeignKey("sellers.id", ondelete="RESTRICT"), unique=True)
    display_name = Column(String, nullable=True)
    auth_email = Column(String(320), nullable=True)
    password_hash = Column(String, nullable=True)
    auth_version = Column(Integer, nullable=False, default=0, server_default="0")
    legacy_revoked_before = Column(DateTime(timezone=True), nullable=True)
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
