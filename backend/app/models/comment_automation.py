"""Durable, seller-scoped Instagram comment rules and outbound actions."""
from uuid import uuid4
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from app.database import Base


class CommentRule(Base):
    __tablename__ = 'comment_rules'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    seller_id = Column(UUID(as_uuid=True), ForeignKey('sellers.id'), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    enabled = Column(Boolean, nullable=False, default=False)
    media_id = Column(String(100), nullable=True)
    keywords = Column(JSONB, nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey('products.id'), nullable=False)
    private_reply = Column(String(700), nullable=False)
    public_reply = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CommentEvent(Base):
    __tablename__ = 'comment_events'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    seller_id = Column(UUID(as_uuid=True), ForeignKey('sellers.id'), nullable=False, index=True)
    comment_id = Column(String(100), nullable=False)
    media_id = Column(String(100), nullable=False)
    actor_id = Column(String(100), nullable=False)
    text = Column(Text, nullable=False)
    commented_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(30), nullable=False)
    reason = Column(String(100), nullable=True)
    rule_id = Column(UUID(as_uuid=True), ForeignKey('comment_rules.id', ondelete='SET NULL'), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint('seller_id', 'comment_id', name='comment_event_once'),)


class CommentAction(Base):
    __tablename__ = 'comment_actions'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    seller_id = Column(UUID(as_uuid=True), ForeignKey('sellers.id'), nullable=False, index=True)
    event_id = Column(UUID(as_uuid=True), ForeignKey('comment_events.id'), nullable=False)
    kind = Column(String(20), nullable=False)
    body = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, default='pending', index=True)
    error_code = Column(String(100), nullable=True)
    provider_id = Column(String(200), nullable=True)
    attempted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint('event_id', 'kind', name='comment_action_once'),)
