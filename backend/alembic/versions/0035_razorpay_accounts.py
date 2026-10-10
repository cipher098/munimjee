"""Encrypted seller Razorpay settings.

Revision ID: 0035
Revises: 0034
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "commerce_orders",
        sa.Column("gateway_credentials", postgresql.JSONB(), nullable=True),
    )
    op.create_table(
        "razorpay_accounts",
        sa.Column(
            "seller_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sellers.id"),
            primary_key=True,
        ),
        sa.Column("key_id", sa.String(100), nullable=False),
        sa.Column("key_secret", sa.Text(), nullable=False),
        sa.Column("webhook_secret", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(4), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_table("razorpay_accounts")
    op.drop_column("commerce_orders", "gateway_credentials")
