"""Move state machine to ConversationProduct; simplify Conversation to session shell

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-02
"""
from alembic import op
import sqlalchemy as sa

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade():
    # conversation_products — add state machine columns
    op.add_column('conversation_products', sa.Column('state', sa.String(), nullable=False, server_default='product_inquiry'))
    op.add_column('conversation_products', sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('conversation_products', sa.Column('pending_tag_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_conv_product_pending_tag', 'conversation_products', 'category_tags', ['pending_tag_id'], ['id'])

    # conversations — add status, drop state machine columns
    op.add_column('conversations', sa.Column('status', sa.String(), nullable=False, server_default='active'))
    op.drop_column('conversations', 'state')
    op.drop_column('conversations', 'agreed_price')
    op.drop_column('conversations', 'last_counter_price')
    op.drop_column('conversations', 'negotiation_round')
    op.drop_column('conversations', 'pending_tag_id')

    # Drop the old partial index that used conversation.state
    op.execute("DROP INDEX IF EXISTS uq_active_conversation")
    # New partial index using conversation.status
    op.execute("""
        CREATE UNIQUE INDEX uq_active_conversation
        ON conversations (seller_id, customer_instagram_id)
        WHERE status = 'active'
    """)

    # order_items table
    op.create_table(
        'order_items',
        sa.Column('id', sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('order_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('orders.id'), nullable=False),
        sa.Column('conversation_product_id', sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey('conversation_products.id'), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('unit_price', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )


def downgrade():
    op.drop_table('order_items')
    op.execute("DROP INDEX IF EXISTS uq_active_conversation")
    op.add_column('conversations', sa.Column('state', sa.String(), nullable=False, server_default='greeting'))
    op.add_column('conversations', sa.Column('agreed_price', sa.Integer(), nullable=True))
    op.add_column('conversations', sa.Column('last_counter_price', sa.Integer(), nullable=True))
    op.add_column('conversations', sa.Column('negotiation_round', sa.Integer(), server_default='0'))
    op.add_column('conversations', sa.Column('pending_tag_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))
    op.drop_column('conversations', 'status')
    op.drop_column('conversation_products', 'state')
    op.drop_column('conversation_products', 'quantity')
    op.drop_column('conversation_products', 'pending_tag_id')
    op.execute("""
        CREATE UNIQUE INDEX uq_active_conversation
        ON conversations (seller_id, customer_instagram_id)
        WHERE state NOT IN ('payment_confirmed', 'failed', 'dispatched_notified')
    """)
