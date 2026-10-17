"""Add V1 businesses/users/memberships and deterministic legacy owner backfill."""
from uuid import NAMESPACE_URL, uuid5
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0040_v1_identity"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("businesses",
        sa.Column("id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sellers.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("legacy_seller_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sellers.id", ondelete="RESTRICT"), unique=True),
        sa.Column("display_name", sa.String()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("business_id", "user_id", name="uq_memberships_business_user"),
        sa.CheckConstraint("role IN ('owner', 'manager', 'staff', 'viewer')", name="ck_memberships_role"))
    op.create_index("ix_memberships_business_id", "memberships", ["business_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    backfill_legacy_owners(op.get_bind())


def backfill_legacy_owners(connection):
    """Batched inserts preserve all existing states when deliberately rerun."""
    rows = connection.execute(sa.text("SELECT id, business_name, email, is_active FROM sellers ORDER BY id"))
    for batch in rows.mappings().partitions(500):
        businesses, users, memberships = [], [], []
        for seller in batch:
            sid = seller["id"]
            uid = uuid5(NAMESPACE_URL, f"munimjee:v1:legacy-owner:{sid}")
            active = bool(seller["is_active"])
            businesses.append(dict(id=sid, name=seller["business_name"] or seller["email"], is_active=active))
            users.append(dict(id=uid, legacy_seller_id=sid, display_name=seller["business_name"], is_active=active))
            memberships.append(dict(id=uuid5(NAMESPACE_URL, f"munimjee:v1:legacy-owner-membership:{sid}"),
                                    business_id=sid, user_id=uid, role="owner", is_active=active))
        connection.execute(sa.text("INSERT INTO businesses (id,name,is_active) VALUES (:id,:name,:is_active) ON CONFLICT DO NOTHING"), businesses)
        connection.execute(sa.text("INSERT INTO users (id,legacy_seller_id,display_name,is_active) VALUES (:id,:legacy_seller_id,:display_name,:is_active) ON CONFLICT DO NOTHING"), users)
        connection.execute(sa.text("INSERT INTO memberships (id,business_id,user_id,role,is_active) VALUES (:id,:business_id,:user_id,:role,:is_active) ON CONFLICT DO NOTHING"), memberships)


def downgrade():
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("businesses")
