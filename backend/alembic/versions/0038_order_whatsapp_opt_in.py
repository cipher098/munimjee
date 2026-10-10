"""Explicit per-order WhatsApp updates consent."""
from alembic import op
import sqlalchemy as sa
revision = '0038'
down_revision = '0037'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('commerce_orders', sa.Column('whatsapp_updates_opt_in', sa.Boolean(), nullable=False, server_default=sa.false()))

def downgrade():
    op.drop_column('commerce_orders', 'whatsapp_updates_opt_in')
