"""Persistent per-customer conversation + per-cycle orders.

- Drop Conversation.status (the thread is now permanent; purchase finality lives
  on Order.status / ConversationProduct.state). Replace the partial unique index
  uq_active_conversation (... WHERE status='active') with an UNCONDITIONAL unique
  index on (seller_id, customer_instagram_id).
- Drop uq_conv_product so a customer can buy the same product more than once
  (each purchase cycle is its own ConversationProduct row).
- Move payment fields (amount_paid, payment_method_id, payment_requested_at)
  from conversation_products to orders.

Testing phase: conversation data is wiped before this runs, so no backfill.

Revision ID: 0028
Revises: 0027
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0028'
down_revision = '0027'
branch_labels = None
depends_on = None


def upgrade():
    # --- Order gains the payment fields ---
    op.add_column('orders',
                  sa.Column('amount_paid', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('orders',
                  sa.Column('payment_method_id', postgresql.UUID(as_uuid=True),
                            sa.ForeignKey('payment_methods.id'), nullable=True))
    op.add_column('orders',
                  sa.Column('payment_requested_at', sa.DateTime(timezone=True), nullable=True))

    # --- ConversationProduct loses the payment fields + the per-product uniqueness ---
    op.drop_constraint('uq_conv_product', 'conversation_products', type_='unique')
    op.drop_column('conversation_products', 'payment_requested_at')
    op.drop_column('conversation_products', 'payment_method_id')
    op.drop_column('conversation_products', 'amount_paid')

    # --- Conversation loses status; index becomes unconditional ---
    op.execute("DROP INDEX IF EXISTS uq_active_conversation")
    op.create_index(
        'uq_conversation_customer', 'conversations',
        ['seller_id', 'customer_instagram_id'], unique=True,
    )
    op.drop_column('conversations', 'status')


def downgrade():
    op.add_column('conversations',
                  sa.Column('status', sa.String(), nullable=False, server_default='active'))
    op.drop_index('uq_conversation_customer', table_name='conversations')
    op.execute(
        "CREATE UNIQUE INDEX uq_active_conversation "
        "ON conversations (seller_id, customer_instagram_id) WHERE status = 'active'"
    )

    op.add_column('conversation_products',
                  sa.Column('amount_paid', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('conversation_products',
                  sa.Column('payment_method_id', postgresql.UUID(as_uuid=True),
                            sa.ForeignKey('payment_methods.id'), nullable=True))
    op.add_column('conversation_products',
                  sa.Column('payment_requested_at', sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint(
        'uq_conv_product', 'conversation_products', ['conversation_id', 'product_id'],
    )

    op.drop_column('orders', 'payment_requested_at')
    op.drop_column('orders', 'payment_method_id')
    op.drop_column('orders', 'amount_paid')
