"""unique partial index on active conversations to prevent race-condition duplicates

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-02
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE UNIQUE INDEX uq_active_conversation
        ON conversations (seller_id, customer_instagram_id)
        WHERE state NOT IN ('payment_confirmed', 'failed', 'dispatched_notified')
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_active_conversation")
