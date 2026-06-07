"""Add last_seller_manual_reply_at to conversations for seller manual takeover

When a seller replies to a customer manually from the IG inbox, we want the
bot to pause so it doesn't talk over them. We detect that via the echo
webhook event (echo mid doesn't match anything we sent), and stamp this
column. The batch worker then skips reply generation while the stamp is
within BOT_AUTO_RESUME_AFTER_HOURS of now.

Revision ID: 0019
Revises: 0018
"""
from alembic import op
import sqlalchemy as sa

revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'conversations',
        sa.Column('last_seller_manual_reply_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column('conversations', 'last_seller_manual_reply_at')
