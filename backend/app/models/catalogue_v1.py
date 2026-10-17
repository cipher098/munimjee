"""Additive SKU snapshots. Legacy Product remains the live inventory writer."""
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from app.database import Base
from app.models.product import Product


# Mirror the migration's additive tenant key without editing the legacy model.
if not any(c.name == "products_seller_id_id" for c in Product.__table__.constraints):
    Product.__table__.append_constraint(UniqueConstraint("seller_id", "id", name="products_seller_id_id"))


class CatalogueSKU(Base):
    __tablename__ = "catalogue_skus"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # Business IDs equal Seller IDs during compatibility migration.
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False)
    product_id = Column(UUID(as_uuid=True), nullable=False)
    options = Column(JSONB, nullable=False)
    price_minor = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False)
    stock_available = Column(Integer, nullable=True)  # null = untracked, never on-hand
    active = Column(Boolean, nullable=False)
    legacy_variant_index = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(["business_id", "product_id"], ["products.seller_id", "products.id"], name="catalogue_sku_tenant_product"),
        UniqueConstraint("business_id", "product_id", "options", name="catalogue_sku_options"),
        CheckConstraint("jsonb_typeof(options) = 'object'", name="catalogue_sku_options_object"),
        CheckConstraint("price_minor >= 0 AND price_minor <= 2000000000", name="catalogue_sku_price"),
        CheckConstraint("stock_available IS NULL OR (stock_available >= 0 AND stock_available <= 2000000000)", name="catalogue_sku_available"),
        CheckConstraint("currency IN ('INR')", name="catalogue_sku_currency"),
        CheckConstraint("legacy_variant_index IS NULL OR legacy_variant_index >= 0", name="catalogue_sku_legacy_index"),
    )


class CatalogueProductMapping(Base):
    __tablename__ = "catalogue_product_mappings"
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), primary_key=True)
    product_id = Column(UUID(as_uuid=True), primary_key=True)
    state = Column(String(24), nullable=False)
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    legacy_fingerprint = Column(String(64), nullable=False)
    issues = Column(JSONB, nullable=False)
    legacy_variants = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        ForeignKeyConstraint(["business_id", "product_id"], ["products.seller_id", "products.id"], name="catalogue_mapping_tenant_product"),
        CheckConstraint("state IN ('needs_review','default_backfilled','reviewed')", name="catalogue_mapping_state"),
        CheckConstraint("revision >= 1", name="catalogue_mapping_revision"),
        CheckConstraint("legacy_fingerprint ~ '^[a-f0-9]{64}$'", name="catalogue_mapping_fingerprint"),
        CheckConstraint("jsonb_typeof(issues) = 'array' AND jsonb_typeof(legacy_variants) = 'array'", name="catalogue_mapping_lists"),
    )
