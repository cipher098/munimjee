"""Explicit SKU activation, reservation ledger and uncertain-payment guard.

Revision ID: 0044_v1_checkout
Revises: 0043_v1_auth
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0044_v1_checkout"
down_revision = "0043_v1_auth"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("catalogue_sku_tenant_id", "catalogue_skus", ["business_id", "product_id", "id"])
    op.create_unique_constraint("commerce_order_tenant_id", "commerce_orders", ["seller_id", "id"])
    op.create_table("catalogue_store_policies",
        sa.Column("business_id", pg.UUID(as_uuid=True), sa.ForeignKey("businesses.id"), primary_key=True),
        sa.Column("checkout_enabled", sa.Boolean, nullable=False, server_default="false"))
    op.create_table("catalogue_activations",
        sa.Column("business_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("product_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("reviewed_revision", sa.Integer, nullable=False),
        sa.Column("legacy_fingerprint", sa.String(64), nullable=False),
        sa.Column("actor_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["business_id", "product_id"], ["catalogue_product_mappings.business_id", "catalogue_product_mappings.product_id"], name="catalogue_activation_mapping"),
        sa.CheckConstraint("reviewed_revision >= 1", name="catalogue_activation_revision"))
    op.create_table("catalogue_creations",
        sa.Column("business_id", pg.UUID(as_uuid=True), sa.ForeignKey("businesses.id"), primary_key=True),
        sa.Column("idempotency_key", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("product_id", pg.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["business_id", "product_id"], ["products.seller_id", "products.id"], name="catalogue_creation_product"))
    op.create_table("sku_reservations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("business_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("sku_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("tracked", sa.Boolean, nullable=False),
        sa.Column("released", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["business_id", "order_id"], ["commerce_orders.seller_id", "commerce_orders.id"], name="sku_reservation_order"),
        sa.ForeignKeyConstraint(["business_id", "product_id", "sku_id"], ["catalogue_skus.business_id", "catalogue_skus.product_id", "catalogue_skus.id"], name="sku_reservation_tenant_sku"),
        sa.UniqueConstraint("business_id", "order_id", "sku_id", name="sku_reservation_once"),
        sa.CheckConstraint("quantity >= 1 AND quantity <= 20", name="sku_reservation_quantity"))
    op.create_table("sku_payment_attempts",
        sa.Column("order_id", pg.UUID(as_uuid=True), sa.ForeignKey("commerce_orders.id"), primary_key=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("state IN ('requesting','unknown','ready')", name="sku_payment_attempt_state"))
    op.execute("""CREATE FUNCTION catalogue_protect_legacy_inventory() RETURNS trigger AS $$
    BEGIN
      IF EXISTS (SELECT 1 FROM catalogue_activations WHERE business_id=OLD.seller_id AND product_id=OLD.id)
         AND (NEW.stock_quantity IS DISTINCT FROM OLD.stock_quantity
           OR NEW.listed_price IS DISTINCT FROM OLD.listed_price
           OR NEW.variants IS DISTINCT FROM OLD.variants) THEN
        RAISE EXCEPTION 'SKU inventory activated: legacy stock/price/variant edits are forbidden' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql""")
    op.execute("CREATE TRIGGER catalogue_legacy_inventory_guard BEFORE UPDATE ON products FOR EACH ROW EXECUTE FUNCTION catalogue_protect_legacy_inventory()")
    op.execute("""CREATE FUNCTION catalogue_protect_order_snapshot() RETURNS trigger AS $$
    BEGIN
      IF OLD.items @> '[{"_inventory_engine":"sku.v1"}]'::jsonb
         AND NEW.items IS DISTINCT FROM OLD.items THEN
        RAISE EXCEPTION 'SKU order line snapshots are immutable' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql""")
    op.execute("CREATE TRIGGER catalogue_order_snapshot_guard BEFORE UPDATE ON commerce_orders FOR EACH ROW EXECUTE FUNCTION catalogue_protect_order_snapshot()")


def downgrade():
    op.execute("DROP TRIGGER catalogue_order_snapshot_guard ON commerce_orders")
    op.execute("DROP FUNCTION catalogue_protect_order_snapshot()")
    op.execute("DROP TRIGGER catalogue_legacy_inventory_guard ON products")
    op.execute("DROP FUNCTION catalogue_protect_legacy_inventory()")
    for name in ("sku_payment_attempts", "sku_reservations", "catalogue_creations", "catalogue_activations", "catalogue_store_policies"):
        op.drop_table(name)
    op.drop_constraint("commerce_order_tenant_id", "commerce_orders", type_="unique")
    op.drop_constraint("catalogue_sku_tenant_id", "catalogue_skus", type_="unique")
