"""Tenant-owned WhatsApp inbox and durable, conservatively retried outbox."""
from uuid import uuid4
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, UniqueConstraint, ForeignKeyConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.database import Base


class WhatsAppAccount(Base):
    __tablename__ = 'whatsapp_accounts'
    seller_id = Column(UUID(as_uuid=True), ForeignKey('sellers.id'), primary_key=True)
    phone_number_id = Column(String(40), nullable=False, unique=True)
    waba_id = Column(String(40), nullable=False)
    display_phone_number = Column(String(50), nullable=False, default='')
    access_token = Column(Text, nullable=False)  # Fernet ciphertext only
    enabled = Column(Boolean, nullable=False, default=True)
    automation_enabled = Column(Boolean, nullable=False, default=False)
    reel_replies_enabled = Column(Boolean, nullable=False, default=False, server_default='false')
    welcome_message = Column(Text, nullable=False, default='')
    rules = Column(JSONB, nullable=False, default=list)
    order_templates = Column(JSONB, nullable=False, default=dict)
    connected_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WhatsAppContact(Base):
    __tablename__ = 'whatsapp_contacts'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    seller_id = Column(UUID(as_uuid=True), ForeignKey('sellers.id'), nullable=False, index=True)
    phone = Column(String(20), nullable=False)
    name = Column(String(200), nullable=False, default='')
    last_inbound_at = Column(DateTime(timezone=True), nullable=True)
    opted_out = Column(Boolean, nullable=False, default=False)
    utility_opt_in = Column(Boolean, nullable=False, default=False)
    marketing_opt_in = Column(Boolean, nullable=False, default=False)
    consent_updated_at = Column(DateTime(timezone=True), nullable=True)
    consent_history = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint('seller_id', 'phone', name='wa_contact_phone'), UniqueConstraint('id', 'seller_id', name='wa_contact_tenant'))


class WhatsAppMessage(Base):
    __tablename__ = 'whatsapp_messages'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    seller_id = Column(UUID(as_uuid=True), ForeignKey('sellers.id'), nullable=False, index=True)
    contact_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    phone_number_id = Column(String(40), nullable=False)
    provider_message_id = Column(String(255), nullable=True)
    idempotency_key = Column(String(350), nullable=False)
    direction = Column(String(10), nullable=False)
    kind = Column(String(30), nullable=False, default='text')
    text = Column(Text, nullable=False, default='')
    payload = Column(JSONB, nullable=False, default=dict)
    status = Column(String(30), nullable=False, default='queued', index=True)
    error = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    __table_args__ = (ForeignKeyConstraint(['contact_id','seller_id'], ['whatsapp_contacts.id','whatsapp_contacts.seller_id']), UniqueConstraint('seller_id','idempotency_key',name='wa_message_idempotency'), UniqueConstraint('seller_id','provider_message_id',name='wa_provider_message'))


class WhatsAppTemplate(Base):
    __tablename__ = 'whatsapp_templates'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    seller_id = Column(UUID(as_uuid=True), ForeignKey('sellers.id'), nullable=False, index=True)
    name = Column(String(512), nullable=False)
    language = Column(String(30), nullable=False)
    status = Column(String(50), nullable=False)
    category = Column(String(30), nullable=False)
    components = Column(JSONB, nullable=False, default=list)
    synced_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint('seller_id','name','language',name='wa_template_identity'),)
