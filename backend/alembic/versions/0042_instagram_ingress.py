"""Durable Instagram inbound message receipts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "instagram_ingress",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sellers.id"), nullable=False),
        sa.Column("account_id", sa.String(100), nullable=False),
        sa.Column("customer_id", sa.String(100), nullable=False),
        sa.Column("event_key", sa.String(64), nullable=False),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("events", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "event_key", name="instagram_ingress_event_once"),
    )
    op.create_index("ix_instagram_ingress_due", "instagram_ingress", ["status", "available_at"])
    op.create_index("ix_instagram_ingress_thread", "instagram_ingress", ["seller_id", "account_id", "customer_id", "status"])


def downgrade():
    op.drop_table("instagram_ingress")
