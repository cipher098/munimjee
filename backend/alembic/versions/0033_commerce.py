"""Storefront profiles and channel-independent COD commerce.

Revision ID: 0033
Revises: 0032
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '0033'
down_revision = '0032'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('storefronts',
        sa.Column('seller_id', pg.UUID(as_uuid=True), sa.ForeignKey('sellers.id'), primary_key=True),
        sa.Column('slug', sa.String(63), nullable=False, unique=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text, nullable=False),
        sa.Column('logo_url', sa.String, nullable=True),
        sa.Column('contact_email', sa.String, nullable=False),
        sa.Column('contact_phone', sa.String, nullable=False),
        sa.Column('shipping_policy', sa.Text, nullable=False),
        sa.Column('return_policy', sa.Text, nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('shipping_fee', sa.Integer, nullable=False),
        sa.Column('cod_enabled', sa.Boolean, nullable=False),
        sa.Column('published', sa.Boolean, nullable=False),
        sa.CheckConstraint('shipping_fee >= 0', name='store_shipping_nonnegative'))
    op.create_table('commerce_customers',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('seller_id', pg.UUID(as_uuid=True), sa.ForeignKey('sellers.id'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('phone', sa.String(20), nullable=False),
        sa.Column('email', sa.String(254)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('seller_id', 'phone', name='commerce_customer_phone'))
    op.create_index('ix_commerce_customers_seller_id', 'commerce_customers', ['seller_id'])
    op.create_table('commerce_orders',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('seller_id', pg.UUID(as_uuid=True), sa.ForeignKey('sellers.id'), nullable=False),
        sa.Column('customer_id', pg.UUID(as_uuid=True), sa.ForeignKey('commerce_customers.id'), nullable=False),
        sa.Column('idempotency_key', pg.UUID(as_uuid=True), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('customer', pg.JSONB, nullable=False),
        sa.Column('address', pg.JSONB, nullable=False),
        sa.Column('items', pg.JSONB, nullable=False),
        sa.Column('note', sa.Text, nullable=False),
        sa.Column('subtotal', sa.Integer, nullable=False),
        sa.Column('shipping_fee', sa.Integer, nullable=False),
        sa.Column('total', sa.Integer, nullable=False),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('payment_method', sa.String(20), nullable=False),
        sa.Column('payment_status', sa.String(20), nullable=False),
        sa.Column('fulfillment_status', sa.String(20), nullable=False),
        sa.Column('stock_released', sa.Boolean, nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True)),
        sa.Column('gateway_order_id', sa.String(100), unique=True),
        sa.Column('gateway_payment_id', sa.String(100), unique=True),
        sa.Column('carrier', sa.String(100)),
        sa.Column('tracking_number', sa.String(200)),
        sa.Column('tracking_url', sa.String(2000)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('seller_id','idempotency_key', name='commerce_order_idempotency'),
        sa.CheckConstraint('subtotal >= 0 AND shipping_fee >= 0 AND total = subtotal + shipping_fee', name='commerce_order_totals'),
        sa.CheckConstraint("payment_status IN ('pending','collected','cancelled','paid','expired','review_required')", name='commerce_payment_status'),
        sa.CheckConstraint("fulfillment_status IN ('pending','confirmed','packed','shipped','delivered','cancelled')", name='commerce_fulfillment_status'))
    for col in ('seller_id','customer_id','fulfillment_status'):
        op.create_index('ix_commerce_orders_' + col, 'commerce_orders', [col])


def downgrade():
    op.drop_table('commerce_orders')
    op.drop_table('commerce_customers')
    op.drop_table('storefronts')
