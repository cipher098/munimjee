"""Seller-scoped comment rules and durable reply outbox.
Revision ID: 0037
Revises: 0036
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
revision = '0037'
down_revision = '0036'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('comment_rules',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('seller_id', pg.UUID(as_uuid=True), sa.ForeignKey('sellers.id'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('media_id', sa.String(100)),
        sa.Column('keywords', pg.JSONB(), nullable=False),
        sa.Column('product_id', pg.UUID(as_uuid=True), sa.ForeignKey('products.id'), nullable=False),
        sa.Column('private_reply', sa.String(700), nullable=False),
        sa.Column('public_reply', sa.String(500)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('ix_comment_rules_seller_id', 'comment_rules', ['seller_id'])
    op.create_table('comment_events',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('seller_id', pg.UUID(as_uuid=True), sa.ForeignKey('sellers.id'), nullable=False),
        sa.Column('comment_id', sa.String(100), nullable=False),
        sa.Column('media_id', sa.String(100), nullable=False),
        sa.Column('actor_id', sa.String(100), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('commented_at', sa.DateTime(timezone=True)),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('reason', sa.String(100)),
        sa.Column('rule_id', pg.UUID(as_uuid=True), sa.ForeignKey('comment_rules.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('seller_id','comment_id',name='comment_event_once'))
    op.create_index('ix_comment_events_seller_id', 'comment_events', ['seller_id'])
    op.create_table('comment_actions',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('seller_id', pg.UUID(as_uuid=True), sa.ForeignKey('sellers.id'), nullable=False),
        sa.Column('event_id', pg.UUID(as_uuid=True), sa.ForeignKey('comment_events.id'), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('error_code', sa.String(100)),
        sa.Column('provider_id', sa.String(200)),
        sa.Column('attempted_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('event_id','kind',name='comment_action_once'))
    op.create_index('ix_comment_actions_seller_id', 'comment_actions', ['seller_id'])
    op.create_index('ix_comment_actions_status', 'comment_actions', ['status'])


def downgrade():
    op.drop_table('comment_actions')
    op.drop_table('comment_events')
    op.drop_table('comment_rules')
