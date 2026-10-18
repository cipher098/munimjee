"""Durable, seller-scoped Instagram comment rules and outbound actions."""
from uuid import uuid4
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, ForeignKeyConstraint, CheckConstraint, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from app.database import Base
from app.schemas.comment_binding import SOURCE_CHECK, CLAIM_CHECK, CLAIM_STATE_CHECK


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
    source_account_id = Column(String(100), nullable=True)
    source_binding = Column(JSONB(none_as_null=True), nullable=True)
    source_verified_at = Column(DateTime(timezone=True), nullable=True)
    source_verification = Column(String(24), nullable=True)
    __table_args__ = (UniqueConstraint('seller_id', 'comment_id', name='comment_event_once'),
        UniqueConstraint('seller_id','id',name='comment_event_tenant'),
        CheckConstraint(SOURCE_CHECK,name='comment_source_complete'))


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
    accepted_claim = Column(JSONB(none_as_null=True), nullable=True)
    claim_hash = Column(String(64), nullable=True)
    claim_token = Column(UUID(as_uuid=True), nullable=True)
    finalized_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint('event_id', 'kind', name='comment_action_once'),
        UniqueConstraint('seller_id','event_id','id',name='comment_action_tenant'),
        ForeignKeyConstraint(['seller_id','event_id'],['comment_events.seller_id','comment_events.id'],
            name='comment_action_event_tenant',postgresql_not_valid=True),
        CheckConstraint(CLAIM_CHECK,name='comment_claim_complete'),
        CheckConstraint(CLAIM_STATE_CHECK,name='comment_claim_runtime'))


class CommentActionAudit(Base):
    __tablename__ = 'comment_action_audits'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    seller_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    event_id = Column(UUID(as_uuid=True), nullable=False)
    action_id = Column(UUID(as_uuid=True), nullable=False)
    claim_token = Column(UUID(as_uuid=True), nullable=True)
    stage = Column(String(24), nullable=False)
    before_status = Column(String(30), nullable=True)
    after_status = Column(String(30), nullable=False)
    reason = Column(String(100), nullable=True)
    provider_id = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())
    __table_args__ = (
        ForeignKeyConstraint(['seller_id','event_id','action_id'],
            ['comment_actions.seller_id','comment_actions.event_id','comment_actions.id'],name='comment_audit_action_tenant'),
        ForeignKeyConstraint(['seller_id','event_id'],['comment_events.seller_id','comment_events.id'],name='comment_audit_event_tenant'),
        CheckConstraint("stage IN ('accepted','claim','withheld','provider_result','worker_recovered')",name='comment_audit_stage'))
