"""add fb_page_id to sellers

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-31
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sellers", sa.Column("fb_page_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("sellers", "fb_page_id")
