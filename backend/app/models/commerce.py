"""Channel-independent storefront orders; legacy Instagram orders remain separate."""
from uuid import uuid4
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func
from app.database import Base


class Storefront(Base):
    __tablename__ = 'storefronts'
    seller_id = Column(UUID(as_uuid=True), ForeignKey('sellers.id'), primary_key=True)
    slug = Column(String(63), nullable=False, unique=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=False, default='')
    logo_url = Column(String, nullable=True)
    contact_email = Column(String, nullable=False, default='')
    contact_phone = Column(String, nullable=False, default='')
    shipping_policy = Column(Text, nullable=False, default='')
    return_policy = Column(Text, nullable=False, default='')
    currency = Column(String(3), nullable=False, default='INR')
    shipping_fee = Column(Integer, nullable=False, default=0)
    cod_enabled = Column(Boolean, nullable=False, default=True)
    published = Column(Boolean, nullable=False, default=False)
    __table_args__ = (CheckConstraint('shipping_fee >= 0', name='store_shipping_nonnegative'),)


class CommerceCustomer(Base):
    __tablename__ = 'commerce_customers'
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    seller_id = Column(UUID(as_uuid=True), ForeignKey('sellers.id'), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False)
    email = Column(String(254), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (UniqueConstraint('seller_id', 'phone', name='commerce_customer_phone'),)


class CommerceOrder(Base):
    __tablename__ = 'commerce_orders'
    __mapper_args__ = {'eager_defaults': True}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    seller_id = Column(UUID(as_uuid=True), ForeignKey('sellers.id'), nullable=False, index=True)
    customer_id = Column(UUID(as_uuid=True), ForeignKey('commerce_customers.id'), nullable=False, index=True)
    idempotency_key = Column(UUID(as_uuid=True), nullable=False)
    request_hash = Column(String(64), nullable=False)
    customer = Column(JSONB, nullable=False)
    address = Column(JSONB, nullable=False)
    items = Column(JSONB, nullable=False)
    note = Column(Text, nullable=False, default='')
    subtotal = Column(Integer, nullable=False)
    shipping_fee = Column(Integer, nullable=False)
    total = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False, default='INR')
    payment_method = Column(String(20), nullable=False, default='cod')
    payment_status = Column(String(20), nullable=False, default='pending')
    fulfillment_status = Column(String(20), nullable=False, default='pending', index=True)
    stock_released = Column(Boolean, nullable=False, default=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    gateway_credentials = Column(JSONB, nullable=True)  # encrypted per-order key snapshot for safe account rotation
    gateway_order_id = Column(String(100), nullable=True, unique=True)
    gateway_payment_id = Column(String(100), nullable=True, unique=True)
    carrier = Column(String(100), nullable=True)
    tracking_number = Column(String(200), nullable=True)
    tracking_url = Column(String(2000), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        UniqueConstraint('seller_id', 'idempotency_key', name='commerce_order_idempotency'),
        CheckConstraint('subtotal >= 0 AND shipping_fee >= 0 AND total = subtotal + shipping_fee', name='commerce_order_totals'),
        CheckConstraint("payment_status IN ('pending','collected','cancelled','paid','expired','review_required')", name='commerce_payment_status'),
        CheckConstraint("fulfillment_status IN ('pending','confirmed','packed','shipped','delivered','cancelled')", name='commerce_fulfillment_status'),
    )
