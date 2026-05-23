"""Loosen NOT NULL on Seller instagram fields + add onboarding columns

A new seller signs up (email/password) BEFORE connecting Instagram, so
instagram_id / instagram_token / instagram_page_id cannot be required at
row creation time. Make them nullable; the OAuth callback fills them in.

Also adds:
  - business_name (display name shown in the dashboard)
  - onboarding_state (signed_up | instagram_connected | active)

Revision ID: 0018
Revises: 0017
"""
from alembic import op
import sqlalchemy as sa

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('sellers', 'instagram_id', nullable=True)
    op.alter_column('sellers', 'instagram_token', nullable=True)
    op.alter_column('sellers', 'instagram_page_id', nullable=True)
    op.add_column('sellers', sa.Column('business_name', sa.String(), nullable=True))
    op.add_column('sellers',
        sa.Column('onboarding_state', sa.String(), nullable=False, server_default='signed_up'))


def downgrade():
    op.drop_column('sellers', 'onboarding_state')
    op.drop_column('sellers', 'business_name')
    # Note: cannot restore NOT NULL if rows have nulls — leave as-is.
