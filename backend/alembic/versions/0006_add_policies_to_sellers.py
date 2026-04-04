"""add policies to sellers

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('sellers', sa.Column('policies', JSONB(), nullable=True))


def downgrade():
    op.drop_column('sellers', 'policies')
