"""Add last_shown_price to conversation_products

Customer-facing display ceiling per (conversation, product). Once any
negotiated price (counter/accept) has been shown to the customer for a
product, future replies must not quote a higher number — quoting higher
makes the bot look dishonest and erodes trust.

Distinct from last_counter_price (negotiation math) so the two concepts
can evolve independently. Nullable — only set once the bot has actually
quoted a price.

Revision ID: 0017
Revises: 0016
"""
from alembic import op
import sqlalchemy as sa

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('conversation_products',
        sa.Column('last_shown_price', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('conversation_products', 'last_shown_price')
