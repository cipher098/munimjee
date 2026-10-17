"""Audited channel review and connection operations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "0045_v1_channel_operator"
down_revision = "0044_v1_checkout"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("instagram_ingress", sa.Column("occurred_at", sa.DateTime(timezone=True)))
    op.add_column("instagram_ingress", sa.Column("operator_replay_pending", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table("channel_operations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("business_id", UUID(as_uuid=True), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("actor_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(40), nullable=False), sa.Column("resource_id", UUID(as_uuid=True)),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False), sa.Column("before_status", sa.String(40)),
        sa.Column("after_status", sa.String(40)), sa.Column("outcome", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("business_id", "idempotency_key", name="channel_operation_idempotency"))
    op.create_index("ix_channel_operations_business_id", "channel_operations", ["business_id"])
    op.create_table("channel_connection_states",
        sa.Column("business_id", UUID(as_uuid=True), sa.ForeignKey("businesses.id"), primary_key=True),
        sa.Column("channel", sa.String(15), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_account_id", sa.String(100)),
        sa.Column("automation_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checked_at", sa.DateTime(timezone=True)), sa.Column("check_status", sa.String(40), nullable=False, server_default="not_checked"),
        sa.Column("error_code", sa.String(80)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("channel_oauth_attempts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("business_id", UUID(as_uuid=True), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("actor_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("operation_id", UUID(as_uuid=True), sa.ForeignKey("channel_operations.id"), nullable=False),
        sa.Column("credential_hash", sa.String(64), nullable=False),
        sa.Column("connection_version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)), sa.Column("result", sa.String(40), nullable=False))


def downgrade():
    op.drop_table("channel_oauth_attempts")
    op.drop_table("channel_connection_states")
    op.drop_table("channel_operations")
    op.drop_column("instagram_ingress", "operator_replay_pending")
    op.drop_column("instagram_ingress", "occurred_at")
