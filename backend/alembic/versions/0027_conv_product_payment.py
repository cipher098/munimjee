"""Add payment-tracking columns to conversation_products.

amount_paid: cumulative verified payment (paise) — supports partial payments.
payment_method_id: which payment method we shared with this customer.
payment_requested_at: when we shared the QR — start of the verify time window.

Revision ID: 0027
Revises: 0026
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0027'
down_revision = '0026'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('conversation_products',
                  sa.Column('amount_paid', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('conversation_products',
                  sa.Column('payment_method_id', postgresql.UUID(as_uuid=True),
                            sa.ForeignKey('payment_methods.id'), nullable=True))
    op.add_column('conversation_products',
                  sa.Column('payment_requested_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('conversation_products', 'payment_requested_at')
    op.drop_column('conversation_products', 'payment_method_id')
    op.drop_column('conversation_products', 'amount_paid')
