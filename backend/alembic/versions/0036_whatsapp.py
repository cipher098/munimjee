"""Tenant-owned WhatsApp accounts, inbox, templates and durable outbox.

Revision ID: 0036
Revises: 0035
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '0036'
down_revision = '0035'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('whatsapp_accounts',
        sa.Column('seller_id',UUID(as_uuid=True),sa.ForeignKey('sellers.id'),primary_key=True),
        sa.Column('phone_number_id',sa.String(40),nullable=False,unique=True),
        sa.Column('waba_id',sa.String(40),nullable=False),
        sa.Column('display_phone_number',sa.String(50),nullable=False),
        sa.Column('access_token',sa.Text(),nullable=False),
        sa.Column('enabled',sa.Boolean(),nullable=False),
        sa.Column('automation_enabled',sa.Boolean(),nullable=False),
        sa.Column('welcome_message',sa.Text(),nullable=False),
        sa.Column('rules',JSONB(),nullable=False),
        sa.Column('order_templates',JSONB(),nullable=False),
        sa.Column('connected_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))
    op.create_table('whatsapp_contacts',
        sa.Column('id',UUID(as_uuid=True),primary_key=True),
        sa.Column('seller_id',UUID(as_uuid=True),sa.ForeignKey('sellers.id'),nullable=False),
        sa.Column('phone',sa.String(20),nullable=False),sa.Column('name',sa.String(200),nullable=False),
        sa.Column('last_inbound_at',sa.DateTime(timezone=True)),
        sa.Column('opted_out',sa.Boolean(),nullable=False),sa.Column('utility_opt_in',sa.Boolean(),nullable=False),sa.Column('marketing_opt_in',sa.Boolean(),nullable=False),
        sa.Column('consent_updated_at',sa.DateTime(timezone=True)),sa.Column('consent_history',JSONB(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.UniqueConstraint('seller_id','phone',name='wa_contact_phone'),sa.UniqueConstraint('id','seller_id',name='wa_contact_tenant'))
    op.create_index('ix_whatsapp_contacts_seller_id','whatsapp_contacts',['seller_id'])
    op.create_table('whatsapp_messages',
        sa.Column('id',UUID(as_uuid=True),primary_key=True),sa.Column('seller_id',UUID(as_uuid=True),sa.ForeignKey('sellers.id'),nullable=False),
        sa.Column('contact_id',UUID(as_uuid=True),nullable=False),sa.Column('phone_number_id',sa.String(40),nullable=False),
        sa.Column('provider_message_id',sa.String(255)),sa.Column('idempotency_key',sa.String(350),nullable=False),
        sa.Column('direction',sa.String(10),nullable=False),sa.Column('kind',sa.String(30),nullable=False),sa.Column('text',sa.Text(),nullable=False),sa.Column('payload',JSONB(),nullable=False),sa.Column('status',sa.String(30),nullable=False),sa.Column('error',sa.String(500)),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['contact_id','seller_id'],['whatsapp_contacts.id','whatsapp_contacts.seller_id']),
        sa.UniqueConstraint('seller_id','idempotency_key',name='wa_message_idempotency'),sa.UniqueConstraint('seller_id','provider_message_id',name='wa_provider_message'))
    for field in ('seller_id','contact_id','status'):
        op.create_index('ix_whatsapp_messages_'+field,'whatsapp_messages',[field])
    op.create_table('whatsapp_templates',
        sa.Column('id',UUID(as_uuid=True),primary_key=True),sa.Column('seller_id',UUID(as_uuid=True),sa.ForeignKey('sellers.id'),nullable=False),
        sa.Column('name',sa.String(512),nullable=False),sa.Column('language',sa.String(30),nullable=False),sa.Column('status',sa.String(50),nullable=False),sa.Column('category',sa.String(30),nullable=False),sa.Column('components',JSONB(),nullable=False),sa.Column('synced_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.UniqueConstraint('seller_id','name','language',name='wa_template_identity'))
    op.create_index('ix_whatsapp_templates_seller_id','whatsapp_templates',['seller_id'])


def downgrade():
    for table in ('whatsapp_templates','whatsapp_messages','whatsapp_contacts','whatsapp_accounts'):
        op.drop_table(table)
