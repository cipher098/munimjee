"""product category tags — categories, tags, tag values, seller alerts

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # product_categories
    op.create_table(
        "product_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_product_categories_seller", "product_categories", ["seller_id"])

    # category_tags
    op.create_table(
        "category_tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("value_type", sa.String(), nullable=False, server_default="text"),
        sa.Column("allowed_values", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["category_id"], ["product_categories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_category_tags_category", "category_tags", ["category_id"])

    # product_tag_values
    op.create_table(
        "product_tag_values",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["category_tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "tag_id", name="uq_product_tag"),
    )

    # seller_alerts
    op.create_table(
        "seller_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["seller_id"], ["sellers.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["tag_id"], ["category_tags.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_seller_alerts_seller_unresolved", "seller_alerts", ["seller_id", "resolved_at"])

    # Add category_id to products
    op.add_column("products", sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_products_category", "products", "product_categories", ["category_id"], ["id"])

    # Add pending_tag_id to conversations
    op.add_column("conversations", sa.Column("pending_tag_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_conversations_pending_tag", "conversations", "category_tags", ["pending_tag_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_conversations_pending_tag", "conversations", type_="foreignkey")
    op.drop_column("conversations", "pending_tag_id")
    op.drop_constraint("fk_products_category", "products", type_="foreignkey")
    op.drop_column("products", "category_id")
    op.drop_index("idx_seller_alerts_seller_unresolved", table_name="seller_alerts")
    op.drop_table("seller_alerts")
    op.drop_table("product_tag_values")
    op.drop_index("idx_category_tags_category", table_name="category_tags")
    op.drop_table("category_tags")
    op.drop_index("idx_product_categories_seller", table_name="product_categories")
    op.drop_table("product_categories")
