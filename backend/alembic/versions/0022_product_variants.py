"""Add variants JSONB to products + active_variant_label to conversation_products.

Sellers can now register a product with multiple variants (color / size /
material — freeform label) where each variant has its own photo list. The
bot will list available variants when the customer asks, and the customer
can lock in a specific one ("blue dedo") so subsequent product-photo sends
only cycle through that variant's photos.

Shape for products.variants:
    [{"label": "Red", "photo_urls": ["https://...", ...]}, {"label": "Blue", ...}]
Empty/null = no variants (existing flat photo_url + photo_urls flow).

Revision ID: 0022
Revises: 0021
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'products',
        sa.Column('variants', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        'conversation_products',
        sa.Column('active_variant_label', sa.String(), nullable=True),
    )


def downgrade():
    op.drop_column('conversation_products', 'active_variant_label')
    op.drop_column('products', 'variants')
