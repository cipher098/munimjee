"""Single-use OAuth state and explicit screenshot payment reviews.
Revision ID: 0034
Revises: 0033
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = '0034'
down_revision = '0033'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('oauth_states',
        sa.Column('nonce_hash', sa.String(64), primary_key=True),
        sa.Column('seller_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sellers.id'), nullable=False),
        sa.Column('browser_hash', sa.String(64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True)))
    op.create_table('payment_reviews',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('seller_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sellers.id'), nullable=False),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('conversations.id'), nullable=False),
        sa.Column('order_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('orders.id')),
        sa.Column('screenshot_url', sa.Text(), nullable=False),
        sa.Column('extracted', postgresql.JSONB(), nullable=False),
        sa.Column('assessment', sa.String()), sa.Column('reason', sa.Text()),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('confirmed_amount', sa.Integer()), sa.Column('reference', sa.String()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('reviewed_at', sa.DateTime(timezone=True)))
    op.create_index('ix_payment_reviews_seller_id', 'payment_reviews', ['seller_id'])


def downgrade():
    op.drop_table('payment_reviews')
    op.drop_table('oauth_states')
