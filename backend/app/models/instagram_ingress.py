"""Durable inbox for actionable Instagram customer messages (no credentials)."""
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.database import Base


class InstagramIngress(Base):
    __tablename__ = "instagram_ingress"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    seller_id = Column(UUID(as_uuid=True), ForeignKey("sellers.id"), nullable=False)
    account_id = Column(String(100), nullable=False)
    customer_id = Column(String(100), nullable=False)
    event_key = Column(String(64), nullable=False)
    provider_message_id = Column(String(255), nullable=True)
    events = Column(JSONB, nullable=False)
    status = Column(String(20), nullable=False, default="pending", server_default="pending")
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    error_code = Column(String(80), nullable=True)
    available_at = Column(DateTime(timezone=True), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("account_id", "event_key", name="instagram_ingress_event_once"),
        Index("ix_instagram_ingress_due", "status", "available_at"),
        Index("ix_instagram_ingress_thread", "seller_id", "account_id", "customer_id", "status"),
    )
