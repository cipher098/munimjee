"""Native V1 sessions, invitations and persisted business profile.

No email-based identity merge or password/contact backfill is performed.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0043_v1_auth"
down_revision = "0042_instagram_ingress"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("businesses", sa.Column("profile", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("businesses", sa.Column("profile_confirmed_at", sa.DateTime(timezone=True)))
    op.add_column("businesses", sa.Column("profile_version", sa.Integer(), nullable=False, server_default="0"))
    op.create_check_constraint("businesses_profile_object", "businesses", "jsonb_typeof(profile) = 'object'")
    op.create_check_constraint("businesses_profile_version", "businesses", "profile_version >= 0")
    op.add_column("users", sa.Column("auth_email", sa.String(320)))
    op.add_column("users", sa.Column("password_hash", sa.String()))
    op.add_column("users", sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("legacy_revoked_before", sa.DateTime(timezone=True)))
    op.create_unique_constraint("users_auth_email", "users", ["auth_email"])
    op.create_check_constraint("users_auth_version", "users", "auth_version >= 0")
    op.create_table("user_sessions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("csrf_digest", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_user_sessions_user", "user_sessions", ["user_id"])
    op.create_table("business_invitations",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("business_id", pg.UUID(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("auth_email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("accepted_by", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('manager','staff','viewer')", name="business_invitations_role"))
    op.create_index("ix_business_invitations_business", "business_invitations", ["business_id"])
    op.create_table("identity_audit_events",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("business_id", pg.UUID(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="RESTRICT")),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("subject_id", pg.UUID(as_uuid=True)),
        sa.Column("details", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_identity_audit_business", "identity_audit_events", ["business_id", "created_at"])


def downgrade():
    # Disposable development teardown; never an application rollback over transactions.
    op.drop_table("identity_audit_events")
    op.drop_table("business_invitations")
    op.drop_table("user_sessions")
    op.drop_constraint("users_auth_version", "users", type_="check")
    op.drop_constraint("users_auth_email", "users", type_="unique")
    for column in ("legacy_revoked_before", "auth_version", "password_hash", "auth_email"):
        op.drop_column("users", column)
    op.drop_constraint("businesses_profile_version", "businesses", type_="check")
    op.drop_constraint("businesses_profile_object", "businesses", type_="check")
    for column in ("profile_version", "profile_confirmed_at", "profile"):
        op.drop_column("businesses", column)
