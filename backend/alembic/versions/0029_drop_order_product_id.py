"""Drop orders.product_id.

An order is now a deal of one-or-more products; the products live on its
OrderItems (conversation_product_id -> ConversationProduct.product_id). The
single Order.product_id was redundant and, for a bundle, wrong (it only held the
focused product). Queries that needed it now go through OrderItem.

Revision ID: 0029
Revises: 0028
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0029'
down_revision = '0028'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('orders', 'product_id')


def downgrade():
    op.add_column('orders',
                  sa.Column('product_id', postgresql.UUID(as_uuid=True),
                            sa.ForeignKey('products.id'), nullable=True))
