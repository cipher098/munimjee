"""Add payment_methods table — per-seller UPI payment destinations.

Each row is a payment method the bot can share with customers (UPI today:
upi_id + account/payee name + QR image). Exactly one is_primary per
(seller, category) — enforced in the API. Built to extend later with more
handles + per-handle txn limits + non-UPI categories.

Revision ID: 0026
Revises: 0025
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0026'
down_revision = '0025'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'payment_methods',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('seller_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sellers.id'), nullable=False),
        sa.Column('category', sa.String(), nullable=False, server_default='upi'),
        sa.Column('upi_id', sa.String(), nullable=True),
        sa.Column('account_name', sa.String(), nullable=True),
        sa.Column('qr_code_url', sa.String(), nullable=True),
        sa.Column('label', sa.String(), nullable=True),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
    )
    op.create_index('ix_payment_methods_seller_id', 'payment_methods', ['seller_id'])


def downgrade():
    op.drop_index('ix_payment_methods_seller_id', table_name='payment_methods')
    op.drop_table('payment_methods')
