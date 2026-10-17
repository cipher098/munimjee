"""Add preview SKU foundation; no data/checkout writer cutover.

Revision ID: 0041_v1_catalogue
Revises: 0040_v1_identity
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0041_v1_catalogue"
down_revision = "0040_v1_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("products_seller_id_id", "products", ["seller_id", "id"])
    op.create_table("catalogue_skus",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("business_id", pg.UUID(as_uuid=True), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("product_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("options", pg.JSONB, nullable=False),
        sa.Column("price_minor", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("stock_available", sa.Integer, nullable=True),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("legacy_variant_index", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["business_id", "product_id"], ["products.seller_id", "products.id"], name="catalogue_sku_tenant_product"),
        sa.UniqueConstraint("business_id", "product_id", "options", name="catalogue_sku_options"),
        sa.CheckConstraint("jsonb_typeof(options) = 'object'", name="catalogue_sku_options_object"),
        sa.CheckConstraint("price_minor >= 0 AND price_minor <= 2000000000", name="catalogue_sku_price"),
        sa.CheckConstraint("stock_available IS NULL OR (stock_available >= 0 AND stock_available <= 2000000000)", name="catalogue_sku_available"),
        sa.CheckConstraint("currency IN ('INR')", name="catalogue_sku_currency"),
        sa.CheckConstraint("legacy_variant_index IS NULL OR legacy_variant_index >= 0", name="catalogue_sku_legacy_index"))
    op.create_table("catalogue_product_mappings",
        sa.Column("business_id", pg.UUID(as_uuid=True), sa.ForeignKey("businesses.id"), primary_key=True),
        sa.Column("product_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("legacy_fingerprint", sa.String(64), nullable=False),
        sa.Column("issues", pg.JSONB, nullable=False),
        sa.Column("legacy_variants", pg.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["business_id", "product_id"], ["products.seller_id", "products.id"], name="catalogue_mapping_tenant_product"),
        sa.CheckConstraint("state IN ('needs_review','default_backfilled','reviewed')", name="catalogue_mapping_state"),
        sa.CheckConstraint("revision >= 1", name="catalogue_mapping_revision"),
        sa.CheckConstraint("legacy_fingerprint ~ '^[a-f0-9]{64}$'", name="catalogue_mapping_fingerprint"),
        sa.CheckConstraint("jsonb_typeof(issues) = 'array' AND jsonb_typeof(legacy_variants) = 'array'", name="catalogue_mapping_lists"))


def downgrade():
    # Development schema teardown only, not a transaction-preserving cutover rollback.
    op.drop_table("catalogue_product_mappings")
    op.drop_table("catalogue_skus")
    op.drop_constraint("products_seller_id_id", "products", type_="unique")
