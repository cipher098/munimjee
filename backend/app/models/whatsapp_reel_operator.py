"""Immutable native review receipt and exact outbound authorization; no sender."""
from uuid import uuid4
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from app.database import Base


RESULT_CHECK = """coalesce(jsonb_typeof(result)='object' AND octet_length(result::text)<=2048
 AND result ?& ARRAY['mapping','resume','reason','outbound_id','mapping_fingerprint']
 AND result-ARRAY['mapping','resume','reason','outbound_id','mapping_fingerprint']='{}'::jsonb
 AND result->>'mapping'='saved' AND result->>'resume' IN ('queued','held','not_requested')
 AND ((action='link_only' AND result->>'resume'='not_requested' AND result->>'reason'='resume_not_requested') OR (action='link_and_resume' AND result->>'resume' IN ('queued','held')))
 AND ((result->>'resume'='queued' AND result->'reason'='null'::jsonb)
 OR (result->>'resume'<>'queued' AND result->>'reason' ~ '^[a-z_]{1,80}$'))
 AND result->>'mapping_fingerprint'=accepted_mapping_fingerprint
 AND ((result->>'resume'='queued' AND result->>'outbound_id' ~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$')
 OR (result->>'resume'<>'queued' AND result->'outbound_id'='null'::jsonb)),false)"""


class WhatsAppReelCommand(Base):
    __tablename__ = 'whatsapp_reel_commands'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey('businesses.id'), nullable=False)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey('users.id'), nullable=False)
    actor_session_id = Column(UUID(as_uuid=True), ForeignKey('user_sessions.id'), nullable=False)
    actor_auth_version = Column(Integer, nullable=False)
    idempotency_key = Column(UUID(as_uuid=True), nullable=False)
    action = Column(String(24), nullable=False)
    request_hash = Column(String(64), nullable=False)
    inbound_message_id = Column(UUID(as_uuid=True), nullable=False)
    contact_id = Column(UUID(as_uuid=True), nullable=False)
    phone_number_id = Column(String(40), nullable=False)
    waba_id = Column(String(40), nullable=False)
    provider_mid = Column(String(255), nullable=False)
    source_classification = Column(String(24), nullable=False)
    source_fingerprint = Column(String(64), nullable=False)
    quoted_message_id = Column(UUID(as_uuid=True), ForeignKey('whatsapp_messages.id'))
    quoted_fingerprint = Column(String(64))
    shortcode = Column(String(100), nullable=False)
    source_url = Column(String(300), nullable=False)
    product_id = Column(UUID(as_uuid=True), nullable=False)
    connection_version = Column(Integer, nullable=False)
    credential_fingerprint = Column(String(64), nullable=False)
    expected_fingerprint = Column(String(64), nullable=False)
    expected_mapping_fingerprint = Column(String(64), nullable=False)
    accepted_mapping_fingerprint = Column(String(64), nullable=False)
    reply_context = Column(JSONB, nullable=False)
    result = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())
    __table_args__ = (
        UniqueConstraint('business_id','idempotency_key',name='wa_reel_command_key'),
        UniqueConstraint('business_id','id',name='wa_reel_command_tenant'),
        ForeignKeyConstraint(['business_id','actor_user_id'],['memberships.business_id','memberships.user_id'],name='wa_reel_command_member'),
        ForeignKeyConstraint(['business_id','inbound_message_id','contact_id','phone_number_id'],
            ['whatsapp_messages.seller_id','whatsapp_messages.id','whatsapp_messages.contact_id','whatsapp_messages.phone_number_id'],name='wa_reel_command_source'),
        ForeignKeyConstraint(['business_id','product_id'],['products.seller_id','products.id'],name='wa_reel_command_product'),
        CheckConstraint("action IN ('link_only','link_and_resume')",name='wa_reel_command_action'),
        CheckConstraint("source_classification IN ('message_link','referral_link','quoted_message','recent_message')",name='wa_reel_command_class'),
        CheckConstraint('actor_auth_version>=0 AND connection_version>=0',name='wa_reel_command_versions'),
        CheckConstraint("shortcode ~ '^[A-Za-z0-9_-]{1,100}$' AND length(provider_mid) BETWEEN 1 AND 255",name='wa_reel_command_reference'),
        CheckConstraint("request_hash ~ '^[a-f0-9]{64}$' AND source_fingerprint ~ '^[a-f0-9]{64}$' AND credential_fingerprint ~ '^[a-f0-9]{64}$' AND expected_fingerprint ~ '^[a-f0-9]{64}$' AND expected_mapping_fingerprint ~ '^[a-f0-9]{64}$' AND accepted_mapping_fingerprint ~ '^[a-f0-9]{64}$'",name='wa_reel_command_hashes'),
        CheckConstraint("(source_classification='quoted_message')=(quoted_message_id IS NOT NULL) AND ((quoted_message_id IS NULL AND quoted_fingerprint IS NULL) OR (quoted_message_id IS NOT NULL AND quoted_fingerprint IS NOT NULL AND quoted_fingerprint ~ '^[a-f0-9]{64}$'))",name='wa_reel_command_quote'),
        CheckConstraint("jsonb_typeof(reply_context)='object' AND octet_length(reply_context::text)<=4096",name='wa_reel_command_context'),
        CheckConstraint(RESULT_CHECK,name='wa_reel_command_result'),
    )


class WhatsAppReelAuthorization(Base):
    __tablename__ = 'whatsapp_reel_authorizations'
    command_id = Column(UUID(as_uuid=True), primary_key=True)
    business_id = Column(UUID(as_uuid=True), nullable=False)
    inbound_message_id = Column(UUID(as_uuid=True), nullable=False)
    contact_id = Column(UUID(as_uuid=True), nullable=False)
    phone_number_id = Column(String(40), nullable=False)
    outbound_message_id = Column(UUID(as_uuid=True), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(['business_id','command_id'],['whatsapp_reel_commands.business_id','whatsapp_reel_commands.id'],name='wa_reel_auth_command'),
        ForeignKeyConstraint(['business_id','inbound_message_id','contact_id','phone_number_id'],
            ['whatsapp_messages.seller_id','whatsapp_messages.id','whatsapp_messages.contact_id','whatsapp_messages.phone_number_id'],name='wa_reel_auth_source'),
        ForeignKeyConstraint(['business_id','outbound_message_id','contact_id','phone_number_id'],
            ['whatsapp_messages.seller_id','whatsapp_messages.id','whatsapp_messages.contact_id','whatsapp_messages.phone_number_id'],name='wa_reel_auth_outbound'),
        UniqueConstraint('business_id','outbound_message_id',name='wa_reel_auth_outbound_once'),
        UniqueConstraint('business_id','inbound_message_id',name='wa_reel_auth_source_once'),
    )
