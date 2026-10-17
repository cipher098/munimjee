"""Seller-authorized channel operations; audit outcomes never contain credentials."""
from uuid import uuid4
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from app.database import Base


class ChannelOperation(Base):
    __tablename__ = "channel_operations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    idempotency_key = Column(UUID(as_uuid=True), nullable=False)
    action = Column(String(40), nullable=False)
    resource_id = Column(UUID(as_uuid=True), nullable=True)
    request_hash = Column(String(64), nullable=False)
    reason = Column(Text, nullable=False, default="")
    before_status = Column(String(40), nullable=True)
    after_status = Column(String(40), nullable=True)
    outcome = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint("business_id", "idempotency_key", name="channel_operation_idempotency"),)


class ChannelConnectionState(Base):
    __tablename__ = "channel_connection_states"
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True)
    channel = Column(String(15), primary_key=True)
    version = Column(Integer, nullable=False, default=0, server_default="0")
    provider_account_id = Column(String(100), nullable=True)
    automation_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    checked_at = Column(DateTime(timezone=True), nullable=True)
    check_status = Column(String(40), nullable=False, default="not_checked", server_default="not_checked")
    error_code = Column(String(80), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ChannelOAuthAttempt(Base):
    __tablename__ = "channel_oauth_attempts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    operation_id = Column(UUID(as_uuid=True), ForeignKey("channel_operations.id"), nullable=False)
    credential_hash = Column(String(64), nullable=False)
    connection_version = Column(Integer, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    result = Column(String(40), nullable=False, default="pending")
