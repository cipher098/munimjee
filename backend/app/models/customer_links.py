"""Tenant-local channel-control evidence; never a merge of historic records."""
from uuid import uuid4
from sqlalchemy import Column, DateTime, String, ForeignKey, ForeignKeyConstraint, UniqueConstraint, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.database import Base


class Customer(Base):
    __tablename__ = 'v1_customers'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey('businesses.id'), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint('business_id', 'id', name='v1_customer_tenant'),)


class CustomerLinkChallenge(Base):
    __tablename__ = 'v1_customer_link_challenges'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey('businesses.id'), nullable=False)
    created_by = Column(UUID(as_uuid=True), nullable=False)
    conversation_id = Column(UUID(as_uuid=True), nullable=False)
    contact_id = Column(UUID(as_uuid=True), nullable=False)
    instagram_account = Column(String(100), nullable=False)
    instagram_subject = Column(String(100), nullable=False)
    whatsapp_account = Column(String(40), nullable=False)
    whatsapp_subject = Column(String(20), nullable=False)
    binding_hash = Column(String(64), nullable=False)
    secret_digest = Column(String(64), nullable=False)
    state = Column(String(20), nullable=False, default='pending')
    customer_id = Column(UUID(as_uuid=True), nullable=True)
    issued_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint('business_id', 'id', name='v1_customer_challenge_tenant'),
        UniqueConstraint('business_id', 'secret_digest', name='v1_customer_challenge_secret'),
        ForeignKeyConstraint(['business_id', 'created_by'], ['memberships.business_id', 'memberships.user_id']),
        ForeignKeyConstraint(['conversation_id', 'business_id'], ['conversations.id', 'conversations.seller_id']),
        ForeignKeyConstraint(['contact_id', 'business_id'], ['whatsapp_contacts.id', 'whatsapp_contacts.seller_id']),
        ForeignKeyConstraint(['business_id', 'customer_id'], ['v1_customers.business_id', 'v1_customers.id']),
        CheckConstraint("state IN ('pending','verified','cancelled')", name='v1_customer_challenge_state'),
        CheckConstraint("expires_at > issued_at AND expires_at <= issued_at + interval '10 minutes'", name='v1_customer_challenge_expiry'),
        CheckConstraint("(state='verified')=(customer_id IS NOT NULL)", name='v1_customer_challenge_result'),
        CheckConstraint("binding_hash ~ '^[a-f0-9]{64}$' AND secret_digest ~ '^[a-f0-9]{64}$'", name='v1_customer_challenge_hashes'),
        Index('v1_customer_challenge_list', 'business_id', 'issued_at'),
    )


class CustomerLinkProof(Base):
    __tablename__ = 'v1_customer_link_proofs'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), nullable=False)
    challenge_id = Column(UUID(as_uuid=True), nullable=False)
    channel = Column(String(12), nullable=False)
    account_id = Column(String(100), nullable=False)
    subject_id = Column(String(100), nullable=False)
    provider_message_id = Column(String(255), nullable=False)
    provider_at = Column(DateTime(timezone=True), nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(['business_id', 'challenge_id'], ['v1_customer_link_challenges.business_id', 'v1_customer_link_challenges.id']),
        UniqueConstraint('business_id', 'challenge_id', 'channel', name='v1_customer_proof_side'),
        UniqueConstraint('business_id', 'channel', 'account_id', 'provider_message_id', name='v1_customer_proof_event'),
        CheckConstraint("channel IN ('instagram','whatsapp')", name='v1_customer_proof_channel'),
    )


class CustomerAssociation(Base):
    __tablename__ = 'v1_customer_associations'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), nullable=False)
    customer_id = Column(UUID(as_uuid=True), nullable=False)
    challenge_id = Column(UUID(as_uuid=True), nullable=False)
    channel = Column(String(12), nullable=False)
    account_id = Column(String(100), nullable=False)
    subject_id = Column(String(100), nullable=False)
    conversation_id = Column(UUID(as_uuid=True), nullable=True)
    contact_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint('business_id', 'id', name='v1_customer_association_tenant'),
        ForeignKeyConstraint(['business_id', 'customer_id'], ['v1_customers.business_id', 'v1_customers.id']),
        ForeignKeyConstraint(['business_id', 'challenge_id', 'channel'], ['v1_customer_link_proofs.business_id', 'v1_customer_link_proofs.challenge_id', 'v1_customer_link_proofs.channel']),
        ForeignKeyConstraint(['conversation_id', 'business_id'], ['conversations.id', 'conversations.seller_id']),
        ForeignKeyConstraint(['contact_id', 'business_id'], ['whatsapp_contacts.id', 'whatsapp_contacts.seller_id']),
        CheckConstraint("(channel='instagram' AND conversation_id IS NOT NULL AND contact_id IS NULL) OR (channel='whatsapp' AND contact_id IS NOT NULL AND conversation_id IS NULL)", name='v1_customer_association_source'),
        Index('v1_customer_active_endpoint', 'business_id', 'channel', 'account_id', 'subject_id', unique=True, postgresql_where=revoked_at.is_(None)),
        Index('v1_customer_active_conversation', 'business_id', 'conversation_id', unique=True, postgresql_where=revoked_at.is_(None)),
        Index('v1_customer_active_contact', 'business_id', 'contact_id', unique=True, postgresql_where=revoked_at.is_(None)),
    )


class CustomerLinkAudit(Base):
    __tablename__ = 'v1_customer_link_audits'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey('businesses.id'), nullable=False)
    actor_id = Column(UUID(as_uuid=True), nullable=False)
    idempotency_key = Column(UUID(as_uuid=True), nullable=False)
    request_hash = Column(String(64), nullable=False)
    action = Column(String(20), nullable=False)
    result = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(['business_id', 'actor_id'], ['memberships.business_id', 'memberships.user_id']),
        UniqueConstraint('business_id', 'idempotency_key', name='v1_customer_command_once'),
        CheckConstraint("action IN ('create','finalize','cancel','unlink')", name='v1_customer_audit_action'),
        CheckConstraint("jsonb_typeof(result)='object'", name='v1_customer_audit_result'),
        CheckConstraint("request_hash ~ '^[a-f0-9]{64}$'", name='v1_customer_audit_hash'),
    )


# Additive tenant key for the existing independently identified IG record.
from app.models.conversation import Conversation
if not any(item.name == 'v1_customer_conversation_tenant' for item in Conversation.__table__.constraints):
    Conversation.__table__.append_constraint(UniqueConstraint('id', 'seller_id', name='v1_customer_conversation_tenant'))
