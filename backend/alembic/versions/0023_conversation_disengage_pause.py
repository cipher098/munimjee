"""Add disengage_paused_until to conversations.

When the customer signals disengagement ("bye", "ok", "nahi chahiye") the
bot acks once and goes quiet — but we no longer close the conversation,
because the closed status caused the next customer message to spawn a
fresh conversation that greeted them from scratch (the very loop the
feature was supposed to prevent).

Instead we mute: a timestamp on the conversation past which the bot may
resume. The pause gate in the batch worker honours it; a re-engagement
signal (buying-intent keyword / number / question mark) clears it early.

Revision ID: 0023
Revises: 0022
"""
from alembic import op
import sqlalchemy as sa

revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'conversations',
        sa.Column('disengage_paused_until', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column('conversations', 'disengage_paused_until')
