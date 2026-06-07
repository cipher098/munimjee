"""Add nudge_state JSONB to conversations for two-nudge customer follow-up.

When a customer goes silent mid-conversation, the bot sends two nudges
(default 24h + 48h after last customer message) then drops it. State is
stored as a single JSONB:
    {"count": 0|1|2, "last_nudged_at": "<iso8601>" | null}
Eligibility (last customer message age, status, conv_product state) is
checked at scan / send time, not stored.

Revision ID: 0021
Revises: 0020
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'conversations',
        sa.Column('nudge_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade():
    op.drop_column('conversations', 'nudge_state')
