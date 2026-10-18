"""Native WA setup attempts and exact message-linked test authority.

Credentials remain in the incumbent account; no message delivery state is copied.
The migration additionally enforces one-way/immutable evidence and actor bindings.
"""
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Index,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.database import Base


class WhatsAppSignupAttempt(Base):
    __tablename__ = "whatsapp_signup_attempts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    actor_session_id = Column(UUID(as_uuid=True), ForeignKey("user_sessions.id"), nullable=False)
    actor_auth_version = Column(Integer, nullable=False)
    idempotency_key = Column(UUID(as_uuid=True), nullable=False)
    request_hash = Column(String(64), nullable=False)
    connection_version = Column(Integer, nullable=False)
    nonce_digest = Column(String(64), nullable=False)
    evidence_kind = Column(String(30), nullable=False, default="provider", server_default="provider")
    state = Column(String(30), nullable=False, default="pending", server_default="pending")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    exchange_consumed_at = Column(DateTime(timezone=True))
    provisional_token_ciphertext = Column(Text)
    token_delete_after = Column(DateTime(timezone=True), nullable=False)
    token_expiry_kind = Column(String(12), nullable=False, default="unknown", server_default="unknown")
    token_expires_at = Column(DateTime(timezone=True))
    verified_app_id = Column(String(40))
    selected_choice_id = Column(UUID(as_uuid=True))
    selected_key = Column(UUID(as_uuid=True))
    selected_hash = Column(String(64))
    subscription_state = Column(String(20), nullable=False, default="not_started", server_default="not_started")
    registration_state = Column(String(20), nullable=False, default="not_started", server_default="not_started")
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("business_id", "idempotency_key", name="wa_signup_key"),
        UniqueConstraint("id", "business_id", name="wa_signup_tenant"),
        ForeignKeyConstraint(["selected_choice_id", "id", "business_id"],
            ["whatsapp_signup_choices.id", "whatsapp_signup_choices.attempt_id", "whatsapp_signup_choices.business_id"],
            name="wa_signup_selected_choice", use_alter=True),
        CheckConstraint("actor_auth_version >= 0 AND connection_version >= 0", name="wa_signup_versions"),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$' AND nonce_digest ~ '^[0-9a-f]{64}$'", name="wa_signup_digests"),
        CheckConstraint("expires_at = created_at + interval '10 minutes' AND token_delete_after = created_at + interval '15 minutes'", name="wa_signup_expiry"),
        CheckConstraint("evidence_kind IN ('provider','synthetic_fixture')", name="wa_signup_evidence"),
        CheckConstraint("state IN ('pending','exchanging','exchange_unknown','awaiting_assets','awaiting_selection','setting_up','setup_unknown','attached','failed','cancelled','expired','stale')", name="wa_signup_state"),
        CheckConstraint("subscription_state IN ('not_started','requesting','unknown','confirmed','failed') AND registration_state IN ('not_started','requesting','unknown','confirmed','failed')", name="wa_signup_steps"),
        CheckConstraint("token_expiry_kind IN ('unknown','at','permanent') AND ((token_expiry_kind = 'at' AND token_expires_at IS NOT NULL) OR (token_expiry_kind <> 'at' AND token_expires_at IS NULL))", name="wa_signup_token_expiry"),
        CheckConstraint("verified_app_id IS NULL OR verified_app_id ~ '^[0-9]{1,40}$'", name="wa_signup_app_id"),
        CheckConstraint("(selected_key IS NULL AND selected_hash IS NULL AND selected_choice_id IS NULL) OR (selected_key IS NOT NULL AND selected_hash IS NOT NULL AND selected_hash ~ '^[0-9a-f]{64}$' AND selected_choice_id IS NOT NULL)", name="wa_signup_selection"),
        Index("ix_wa_signup_cleanup", "token_delete_after"),
    )


class WhatsAppSignupChoice(Base):
    __tablename__ = "whatsapp_signup_choices"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    attempt_id = Column(UUID(as_uuid=True), nullable=False)
    business_id = Column(UUID(as_uuid=True), nullable=False)
    waba_id = Column(String(40), nullable=False)
    phone_number_id = Column(String(40), nullable=False)
    display_name = Column(String(160), nullable=False)
    display_phone_number = Column(String(50), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    verified_at = Column(DateTime(timezone=True), nullable=False)
    provider_registration_status = Column(String(20), nullable=False, default="unknown", server_default="unknown")
    __table_args__ = (
        ForeignKeyConstraint(["attempt_id", "business_id"], ["whatsapp_signup_attempts.id", "whatsapp_signup_attempts.business_id"], name="wa_choice_attempt"),
        UniqueConstraint("attempt_id", "waba_id", "phone_number_id", name="wa_choice_phone"),
        UniqueConstraint("id", "attempt_id", "business_id", name="wa_choice_tenant"),
        CheckConstraint("waba_id ~ '^[0-9]{1,40}$' AND phone_number_id ~ '^[0-9]{1,40}$'", name="wa_choice_ids"),
        CheckConstraint("fingerprint ~ '^[0-9a-f]{64}$'", name="wa_choice_fingerprint"),
        CheckConstraint("provider_registration_status IN ('unknown','registered','unregistered')", name="wa_choice_registration"),
    )


class WhatsAppAuthorizationProvenance(Base):
    __tablename__ = "whatsapp_authorization_provenance"
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True)
    connection_version = Column(Integer, primary_key=True)
    attempt_id = Column(UUID(as_uuid=True), nullable=False)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    actor_session_id = Column(UUID(as_uuid=True), ForeignKey("user_sessions.id"), nullable=False)
    actor_auth_version = Column(Integer, nullable=False)
    phone_number_id = Column(String(40), nullable=False)
    waba_id = Column(String(40), nullable=False)
    verified_app_id = Column(String(40), nullable=False)
    grants = Column(JSONB, nullable=False)
    token_expiry_kind = Column(String(12), nullable=False)
    token_expires_at = Column(DateTime(timezone=True))
    verified_at = Column(DateTime(timezone=True), nullable=False)
    evidence_kind = Column(String(30), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["attempt_id", "business_id"], ["whatsapp_signup_attempts.id", "whatsapp_signup_attempts.business_id"], name="wa_provenance_attempt"),
        CheckConstraint("actor_auth_version >= 0 AND connection_version >= 0", name="wa_provenance_versions"),
        CheckConstraint("phone_number_id ~ '^[0-9]{1,40}$' AND waba_id ~ '^[0-9]{1,40}$' AND verified_app_id ~ '^[0-9]{1,40}$'", name="wa_provenance_ids"),
        CheckConstraint("jsonb_typeof(grants) = 'array' AND jsonb_array_length(grants) = 2 AND grants @> '[\"whatsapp_business_management\",\"whatsapp_business_messaging\"]'::jsonb", name="wa_provenance_grants"),
        CheckConstraint("(token_expiry_kind = 'at' AND token_expires_at IS NOT NULL AND token_expires_at > verified_at) OR (token_expiry_kind = 'permanent' AND token_expires_at IS NULL)", name="wa_provenance_expiry"),
        CheckConstraint("evidence_kind IN ('provider','synthetic_fixture')", name="wa_provenance_evidence"),
    )


class WhatsAppConnectionTest(Base):
    __tablename__ = "whatsapp_connection_tests"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    actor_session_id = Column(UUID(as_uuid=True), ForeignKey("user_sessions.id"), nullable=False)
    actor_auth_version = Column(Integer, nullable=False)
    idempotency_key = Column(UUID(as_uuid=True), nullable=False)
    request_hash = Column(String(64), nullable=False)
    connection_version = Column(Integer, nullable=False)
    phone_number_id = Column(String(40), nullable=False)
    waba_id = Column(String(40), nullable=False)
    challenge_digest = Column(String(64), nullable=False, unique=True)
    evidence_kind = Column(String(30), nullable=False)
    issued_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    recipient_contact_id = Column(UUID(as_uuid=True))
    inbound_message_id = Column(UUID(as_uuid=True))
    inbound_provider_at = Column(DateTime(timezone=True))
    received_at = Column(DateTime(timezone=True))
    cancelled_at = Column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("business_id", "idempotency_key", name="wa_test_key"),
        UniqueConstraint("id", "business_id", name="wa_test_tenant"),
        ForeignKeyConstraint(["recipient_contact_id", "business_id"], ["whatsapp_contacts.id", "whatsapp_contacts.seller_id"], name="wa_test_contact"),
        ForeignKeyConstraint(["inbound_message_id", "business_id"], ["whatsapp_messages.id", "whatsapp_messages.seller_id"], name="wa_test_inbound"),
        CheckConstraint("actor_auth_version >= 0 AND connection_version >= 0", name="wa_test_versions"),
        CheckConstraint("request_hash ~ '^[0-9a-f]{64}$' AND challenge_digest ~ '^[0-9a-f]{64}$'", name="wa_test_digests"),
        CheckConstraint("phone_number_id ~ '^[0-9]{1,40}$' AND waba_id ~ '^[0-9]{1,40}$'", name="wa_test_ids"),
        CheckConstraint("evidence_kind IN ('provider','synthetic_fixture')", name="wa_test_evidence"),
        CheckConstraint("expires_at = issued_at + interval '10 minutes'", name="wa_test_expiry"),
        CheckConstraint("(recipient_contact_id IS NULL AND inbound_message_id IS NULL AND inbound_provider_at IS NULL AND received_at IS NULL) OR (recipient_contact_id IS NOT NULL AND inbound_message_id IS NOT NULL AND inbound_provider_at IS NOT NULL AND received_at IS NOT NULL AND inbound_provider_at BETWEEN issued_at AND expires_at AND received_at BETWEEN inbound_provider_at - interval '30 seconds' AND expires_at + interval '30 seconds')", name="wa_test_inbound_times"),
        Index("ix_wa_test_created", "business_id", "issued_at"),
    )


class WhatsAppTestAuthorization(Base):
    __tablename__ = "whatsapp_test_authorizations"
    test_id = Column(UUID(as_uuid=True), primary_key=True)
    business_id = Column(UUID(as_uuid=True), nullable=False)
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    actor_session_id = Column(UUID(as_uuid=True), ForeignKey("user_sessions.id"), nullable=False)
    actor_auth_version = Column(Integer, nullable=False)
    connection_version = Column(Integer, nullable=False)
    phone_number_id = Column(String(40), nullable=False)
    recipient_contact_id = Column(UUID(as_uuid=True), nullable=False)
    inbound_message_id = Column(UUID(as_uuid=True), nullable=False)
    outbound_message_id = Column(UUID(as_uuid=True), nullable=False, unique=True)
    idempotency_key = Column(UUID(as_uuid=True), nullable=False)
    request_hash = Column(String(64), nullable=False)
    fixed_text_version = Column(String(40), nullable=False)
    authorized_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["test_id", "business_id"], ["whatsapp_connection_tests.id", "whatsapp_connection_tests.business_id"], name="wa_test_auth_test"),
        ForeignKeyConstraint(["recipient_contact_id", "business_id"], ["whatsapp_contacts.id", "whatsapp_contacts.seller_id"], name="wa_test_auth_contact"),
        ForeignKeyConstraint(["inbound_message_id", "business_id"], ["whatsapp_messages.id", "whatsapp_messages.seller_id"], name="wa_test_auth_inbound"),
        ForeignKeyConstraint(["outbound_message_id", "business_id"], ["whatsapp_messages.id", "whatsapp_messages.seller_id"], name="wa_test_auth_outbound"),
        UniqueConstraint("business_id", "idempotency_key", name="wa_test_auth_key"),
        CheckConstraint("actor_auth_version >= 0 AND connection_version >= 0", name="wa_test_auth_versions"),
        CheckConstraint("phone_number_id ~ '^[0-9]{1,40}$' AND request_hash ~ '^[0-9a-f]{64}$'", name="wa_test_auth_identity"),
        CheckConstraint("fixed_text_version = 'wa-connection-test.v1'", name="wa_test_auth_text"),
        CheckConstraint("expires_at > authorized_at AND expires_at <= authorized_at + interval '120 seconds'", name="wa_test_auth_expiry"),
    )
