"""add conversation_products table

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'conversation_products',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'conversation_id',
            UUID(as_uuid=True),
            sa.ForeignKey('conversations.id'),
            nullable=False,
        ),
        sa.Column(
            'product_id',
            UUID(as_uuid=True),
            sa.ForeignKey('products.id'),
            nullable=False,
        ),
        sa.Column('negotiation_round', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_counter_price', sa.Integer(), nullable=True),
        sa.Column('agreed_price', sa.Integer(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('conversation_id', 'product_id', name='uq_conv_product'),
    )


def downgrade():
    op.drop_table('conversation_products')
