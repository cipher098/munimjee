"""add warranty_months to products

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-01
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('products', sa.Column('warranty_months', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('products', 'warranty_months')
