"""Add llm_call_logs — per-call LLM usage + cost ledger.

One row per LLM API call (decide / generate_reply / intent_classifier /
vision / catalog match / …) with full request + response, token usage
(incl. Anthropic prompt-cache buckets), resolved provider/model, and the
computed USD cost. Enables cost-per-conversation queries at any time.

Revision ID: 0025
Revises: 0024
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0025'
down_revision = '0024'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'llm_call_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('seller_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sellers.id'), nullable=True),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('conversations.id'), nullable=True),
        sa.Column('conversation_product_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('conversation_products.id'), nullable=True),
        sa.Column('product_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('products.id'), nullable=True),
        sa.Column('customer_message_mid', sa.String(), nullable=True),
        sa.Column('method', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='success'),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('cache_read_input_tokens', sa.Integer(), nullable=True),
        sa.Column('cache_creation_input_tokens', sa.Integer(), nullable=True),
        sa.Column('cost_usd', sa.Numeric(14, 8), nullable=True),
        sa.Column('request', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('response', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_llm_call_logs_seller_id', 'llm_call_logs', ['seller_id'])
    op.create_index('ix_llm_call_logs_conversation_id', 'llm_call_logs', ['conversation_id'])
    op.create_index('ix_llm_call_logs_customer_message_mid', 'llm_call_logs', ['customer_message_mid'])
    op.create_index('ix_llm_call_logs_created_at', 'llm_call_logs', ['created_at'])


def downgrade():
    op.drop_index('ix_llm_call_logs_created_at', table_name='llm_call_logs')
    op.drop_index('ix_llm_call_logs_customer_message_mid', table_name='llm_call_logs')
    op.drop_index('ix_llm_call_logs_conversation_id', table_name='llm_call_logs')
    op.drop_index('ix_llm_call_logs_seller_id', table_name='llm_call_logs')
    op.drop_table('llm_call_logs')
