"""seller gender — drives the bot's first-person verb forms

Revision ID: 0032
Revises: 0031
"""
from alembic import op
import sqlalchemy as sa


revision = '0032'
down_revision = '0031'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('sellers', sa.Column('gender', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('sellers', 'gender')
