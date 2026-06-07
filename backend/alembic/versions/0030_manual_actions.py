"""manual_actions — post-payment change requests needing seller action

Revision ID: 0030
Revises: 0029
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0030'
down_revision = '0029'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'manual_actions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('seller_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sellers.id'), nullable=False),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('conversations.id'), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('detail', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='open'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_manual_actions_conv_status', 'manual_actions', ['conversation_id', 'status'])
    op.create_index('ix_manual_actions_seller_status', 'manual_actions', ['seller_id', 'status'])


def downgrade() -> None:
    op.drop_index('ix_manual_actions_seller_status', table_name='manual_actions')
    op.drop_index('ix_manual_actions_conv_status', table_name='manual_actions')
    op.drop_table('manual_actions')
