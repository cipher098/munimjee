"""add multi photos to products and photos_sent_count to conversation_products

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('products', sa.Column('photo_urls', postgresql.JSONB(), nullable=True))
    op.add_column('conversation_products', sa.Column('photos_sent_count', sa.Integer(), nullable=True, server_default='0'))

def downgrade():
    op.drop_column('products', 'photo_urls')
    op.drop_column('conversation_products', 'photos_sent_count')
