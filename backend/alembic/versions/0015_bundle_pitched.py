"""Add bundle_pitched to conversation_products

Revision ID: 0015
Revises: 0014
"""
from alembic import op
import sqlalchemy as sa

revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('conversation_products',
        sa.Column('bundle_pitched', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    op.drop_column('conversation_products', 'bundle_pitched')
