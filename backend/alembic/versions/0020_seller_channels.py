"""Add channels JSONB to sellers for approved alternative-channel list.

Bot was improvising WhatsApp suggestions when customers said "I'm not on
Instagram much." We want the seller to explicitly list which channels the
bot is allowed to offer. Empty/null → bot keeps everything on Instagram.

Shape: [{"type": "whatsapp"|"phone"|"email", "value": "<contact>"}, ...]

Revision ID: 0020
Revises: 0019
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'sellers',
        sa.Column('channels', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade():
    op.drop_column('sellers', 'channels')
