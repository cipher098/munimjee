"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # sellers
    op.create_table(
        "sellers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("instagram_id", sa.String(), nullable=False),
        sa.Column("instagram_token", sa.String(), nullable=False),
        sa.Column("instagram_page_id", sa.String(), nullable=False),
        sa.Column("whatsapp_number", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("persona", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("negotiation_style", sa.String(), nullable=True, server_default="medium"),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("instagram_id"),
        sa.UniqueConstraint("email"),
    )

    # delivery_members
    op.create_table(
        "delivery_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )

    # products
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("listed_price", sa.Integer(), nullable=False),
        sa.Column("floor_price", sa.Integer(), nullable=False),
        sa.Column("photo_url", sa.String(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # conversations
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_instagram_id", sa.String(), nullable=False),
        sa.Column("customer_name", sa.String(), nullable=True),
        sa.Column("state", sa.String(), nullable=False, server_default="greeting"),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agreed_price", sa.Integer(), nullable=True),
        sa.Column("negotiation_round", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("messages", postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_conversations_seller_customer", "conversations", ["seller_id", "customer_instagram_id"])

    # orders
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_name", sa.String(), nullable=False),
        sa.Column("customer_instagram_id", sa.String(), nullable=False),
        sa.Column("customer_address", sa.Text(), nullable=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="payment_confirmed"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_orders_seller_status", "orders", ["seller_id", "status"])

    # delivery_updates
    op.create_table(
        "delivery_updates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("courier_name", sa.String(), nullable=True),
        sa.Column("tracking_id", sa.String(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["delivery_members.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # transactions
    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("utr_number", sa.String(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("sender_name", sa.String(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_by", sa.String(), nullable=False),
        sa.Column("screenshot_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # CRITICAL: unique index prevents duplicate UTR fraud, cross-seller
    op.create_index("idx_transactions_utr", "transactions", ["utr_number"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_transactions_utr", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("delivery_updates")
    op.drop_index("idx_orders_seller_status", table_name="orders")
    op.drop_table("orders")
    op.drop_index("idx_conversations_seller_customer", table_name="conversations")
    op.drop_table("conversations")
    op.drop_table("products")
    op.drop_table("delivery_members")
    op.drop_table("sellers")
