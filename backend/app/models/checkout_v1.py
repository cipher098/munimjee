"""Opt-in writer activation and auditable SKU reservations on commerce_orders."""
from uuid import uuid4
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.database import Base
from app.models.catalogue_v1 import CatalogueSKU
from app.models.commerce import CommerceOrder

for table, name, fields in (
    (CatalogueSKU.__table__, "catalogue_sku_tenant_id", ("business_id", "product_id", "id")),
    (CommerceOrder.__table__, "commerce_order_tenant_id", ("seller_id", "id")),
):
    if not any(c.name == name for c in table.constraints):
        table.append_constraint(UniqueConstraint(*fields, name=name))


class CatalogueStorePolicy(Base):
    __tablename__ = "catalogue_store_policies"
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True)
    checkout_enabled = Column(Boolean, nullable=False, default=False, server_default="false")


class CatalogueActivation(Base):
    __tablename__ = "catalogue_activations"
    business_id = Column(UUID(as_uuid=True), primary_key=True)
    product_id = Column(UUID(as_uuid=True), primary_key=True)
    reviewed_revision = Column(Integer, nullable=False)
    legacy_fingerprint = Column(String(64), nullable=False)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    activated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(["business_id", "product_id"], ["catalogue_product_mappings.business_id", "catalogue_product_mappings.product_id"], name="catalogue_activation_mapping"),
        CheckConstraint("reviewed_revision >= 1", name="catalogue_activation_revision"),
    )


class CatalogueCreation(Base):
    __tablename__ = "catalogue_creations"
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True)
    idempotency_key = Column(UUID(as_uuid=True), primary_key=True)
    request_hash = Column(String(64), nullable=False)
    product_id = Column(UUID(as_uuid=True), nullable=False)
    __table_args__ = (ForeignKeyConstraint(["business_id", "product_id"], ["products.seller_id", "products.id"], name="catalogue_creation_product"),)


class SKUReservation(Base):
    __tablename__ = "sku_reservations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    business_id = Column(UUID(as_uuid=True), nullable=False)
    order_id = Column(UUID(as_uuid=True), nullable=False)
    product_id = Column(UUID(as_uuid=True), nullable=False)
    sku_id = Column(UUID(as_uuid=True), nullable=False)
    quantity = Column(Integer, nullable=False)
    tracked = Column(Boolean, nullable=False)
    released = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    released_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        ForeignKeyConstraint(["business_id", "order_id"], ["commerce_orders.seller_id", "commerce_orders.id"], name="sku_reservation_order"),
        ForeignKeyConstraint(["business_id", "product_id", "sku_id"], ["catalogue_skus.business_id", "catalogue_skus.product_id", "catalogue_skus.id"], name="sku_reservation_tenant_sku"),
        UniqueConstraint("business_id", "order_id", "sku_id", name="sku_reservation_once"),
        CheckConstraint("quantity >= 1 AND quantity <= 20", name="sku_reservation_quantity"),
    )


class SKUPaymentAttempt(Base):
    __tablename__ = "sku_payment_attempts"
    order_id = Column(UUID(as_uuid=True), ForeignKey("commerce_orders.id"), primary_key=True)
    state = Column(String(16), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    __table_args__ = (CheckConstraint("state IN ('requesting','unknown','ready')", name="sku_payment_attempt_state"),)
