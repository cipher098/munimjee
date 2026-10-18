"""Immutable native reviews; no row here authorizes or queues a message."""
from uuid import uuid4
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from app.database import Base
from app.models.whatsapp import WhatsAppMessage


COMMAND_OPERATION = "operation IN ('rule_create','rule_update','rule_disable','comment_close','enquiry_close')"
COMMAND_RESULT = """coalesce(jsonb_typeof(result)='object' AND octet_length(result::text)<=32768
 AND result ?& ARRAY['resource_id','fingerprint'] AND result-ARRAY['resource_id','fingerprint']='{}'::jsonb
 AND jsonb_typeof(result->'resource_id')='string' AND result->>'resource_id' ~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
 AND jsonb_typeof(result->'fingerprint')='string' AND result->>'fingerprint' ~ '^[a-f0-9]{64}$',false)"""

# The new enquiry's receiving account is bound to the exact historical inbound,
# never the account currently configured when an operator opens the page.
WhatsAppMessage.__table__.append_constraint(UniqueConstraint(
    'seller_id', 'id', 'contact_id', 'phone_number_id', name='wa_message_review_source'))


class CommentOperatorCommand(Base):
    __tablename__ = 'comment_operator_commands'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey('businesses.id'), nullable=False)
    actor_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    idempotency_key = Column(UUID(as_uuid=True), nullable=False)
    operation = Column(String(24), nullable=False)
    request_hash = Column(String(64), nullable=False)
    result = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())
    __table_args__ = (
        UniqueConstraint('business_id', 'idempotency_key', name='comment_operator_command_once'),
        UniqueConstraint('business_id', 'id', name='comment_operator_command_tenant'),
        ForeignKeyConstraint(['business_id', 'actor_id'], ['memberships.business_id', 'memberships.user_id'], name='comment_operator_actor_tenant'),
        CheckConstraint(COMMAND_OPERATION, name='comment_operator_operation'),
        CheckConstraint("request_hash ~ '^[a-f0-9]{64}$'", name='comment_operator_request_hash'),
        CheckConstraint(COMMAND_RESULT, name='comment_operator_safe_result'),
        Index('ix_comment_operator_commands_business_created', 'business_id', 'created_at', 'id'),
    )


class CommentOperatorReview(Base):
    __tablename__ = 'comment_operator_reviews'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), nullable=False)
    event_id = Column(UUID(as_uuid=True), nullable=False)
    command_id = Column(UUID(as_uuid=True), nullable=False)
    reason = Column(String(1000), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())
    __table_args__ = (
        UniqueConstraint('business_id', 'event_id', name='comment_operator_review_once'),
        UniqueConstraint('business_id', 'command_id', name='comment_review_command_once'),
        ForeignKeyConstraint(['business_id', 'event_id'], ['comment_events.seller_id', 'comment_events.id'], name='comment_operator_review_event'),
        ForeignKeyConstraint(['business_id', 'command_id'], ['comment_operator_commands.business_id', 'comment_operator_commands.id'], name='comment_operator_review_command'),
        CheckConstraint('length(btrim(reason)) BETWEEN 10 AND 1000', name='comment_operator_review_reason'),
        Index('ix_comment_operator_reviews_business_created', 'business_id', 'created_at', 'id'),
    )


class WhatsAppEnquiryReview(Base):
    __tablename__ = 'whatsapp_enquiry_reviews'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey('businesses.id'), nullable=False)
    inbound_message_id = Column(UUID(as_uuid=True), nullable=False)
    contact_id = Column(UUID(as_uuid=True), nullable=False)
    phone_number_id = Column(String(40), nullable=False)
    reason = Column(String(40), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())
    __table_args__ = (
        UniqueConstraint('business_id', 'inbound_message_id', name='wa_enquiry_inbound_once'),
        UniqueConstraint('business_id', 'id', name='wa_enquiry_tenant'),
        ForeignKeyConstraint(['business_id', 'inbound_message_id', 'contact_id', 'phone_number_id'],
            ['whatsapp_messages.seller_id', 'whatsapp_messages.id', 'whatsapp_messages.contact_id', 'whatsapp_messages.phone_number_id'], name='wa_enquiry_exact_source'),
        ForeignKeyConstraint(['contact_id', 'business_id'], ['whatsapp_contacts.id', 'whatsapp_contacts.seller_id'], name='wa_enquiry_contact_tenant'),
        CheckConstraint("reason='activated_inferred_context'", name='wa_enquiry_reason'),
        Index('ix_whatsapp_enquiry_reviews_business_created', 'business_id', 'created_at', 'id'),
    )


class WhatsAppEnquiryClosure(Base):
    __tablename__ = 'whatsapp_enquiry_closures'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), nullable=False)
    enquiry_id = Column(UUID(as_uuid=True), nullable=False)
    command_id = Column(UUID(as_uuid=True), nullable=False)
    reason = Column(String(1000), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())
    __table_args__ = (
        UniqueConstraint('business_id', 'enquiry_id', name='wa_enquiry_close_once'),
        UniqueConstraint('business_id', 'command_id', name='wa_enquiry_close_command_once'),
        ForeignKeyConstraint(['business_id', 'enquiry_id'], ['whatsapp_enquiry_reviews.business_id', 'whatsapp_enquiry_reviews.id'], name='wa_enquiry_close_source'),
        ForeignKeyConstraint(['business_id', 'command_id'], ['comment_operator_commands.business_id', 'comment_operator_commands.id'], name='wa_enquiry_close_command'),
        CheckConstraint('length(btrim(reason)) BETWEEN 10 AND 1000', name='wa_enquiry_close_reason'),
        Index('ix_whatsapp_enquiry_closures_business_created', 'business_id', 'created_at', 'id'),
    )
