"""Durable, single-use account linking and unverified payment evidence."""
from uuid import uuid4
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from app.database import Base


class OAuthState(Base):
    __tablename__ = "oauth_states"
    nonce_hash = Column(String(64), primary_key=True)
    seller_id = Column(UUID(as_uuid=True), ForeignKey("sellers.id"), nullable=False)
    browser_hash = Column(String(64), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)


class PaymentReview(Base):
    __tablename__ = "payment_reviews"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    seller_id = Column(UUID(as_uuid=True), ForeignKey("sellers.id"), nullable=False, index=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)
    screenshot_url = Column(Text, nullable=False)
    extracted = Column(JSONB, nullable=False, default=dict)
    assessment = Column(String, nullable=True)
    reason = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="pending")
    confirmed_amount = Column(Integer, nullable=True)
    reference = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
