"""Opt-in catalogue replies for WhatsApp reel references."""
from alembic import op
import sqlalchemy as sa

revision = '0039'
down_revision = '0038'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('whatsapp_accounts', sa.Column('reel_replies_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('whatsapp_accounts', 'reel_replies_enabled')
