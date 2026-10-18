"""Append-only native comment reviews and exact inbound enquiry visibility."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = '0056_v1_comment_operator'
down_revision = '0055_v1_comment_binding'
branch_labels = depends_on = None

TABLES = ('comment_operator_commands', 'comment_operator_reviews', 'whatsapp_enquiry_reviews', 'whatsapp_enquiry_closures')
RESULT_CHECK = """coalesce(jsonb_typeof(result)='object' AND octet_length(result::text)<=32768
 AND result ?& ARRAY['resource_id','fingerprint'] AND result-ARRAY['resource_id','fingerprint']='{}'::jsonb
 AND jsonb_typeof(result->'resource_id')='string' AND result->>'resource_id' ~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
 AND jsonb_typeof(result->'fingerprint')='string' AND result->>'fingerprint' ~ '^[a-f0-9]{64}$',false)"""


def upgrade():
    op.create_unique_constraint('wa_message_review_source', 'whatsapp_messages', ['seller_id', 'id', 'contact_id', 'phone_number_id'])
    op.create_table('comment_operator_commands',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('business_id', pg.UUID(as_uuid=True), sa.ForeignKey('businesses.id'), nullable=False),
        sa.Column('actor_id', pg.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('idempotency_key', pg.UUID(as_uuid=True), nullable=False),
        sa.Column('operation', sa.String(24), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('result', pg.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.UniqueConstraint('business_id', 'idempotency_key', name='comment_operator_command_once'),
        sa.UniqueConstraint('business_id', 'id', name='comment_operator_command_tenant'),
        sa.ForeignKeyConstraint(['business_id', 'actor_id'], ['memberships.business_id', 'memberships.user_id'], name='comment_operator_actor_tenant'),
        sa.CheckConstraint("operation IN ('rule_create','rule_update','rule_disable','comment_close','enquiry_close')", name='comment_operator_operation'),
        sa.CheckConstraint("request_hash ~ '^[a-f0-9]{64}$'", name='comment_operator_request_hash'),
        sa.CheckConstraint(RESULT_CHECK, name='comment_operator_safe_result'))
    op.create_table('comment_operator_reviews',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('business_id', pg.UUID(as_uuid=True), nullable=False),
        sa.Column('event_id', pg.UUID(as_uuid=True), nullable=False),
        sa.Column('command_id', pg.UUID(as_uuid=True), nullable=False),
        sa.Column('reason', sa.String(1000), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.UniqueConstraint('business_id', 'event_id', name='comment_operator_review_once'),
        sa.UniqueConstraint('business_id', 'command_id', name='comment_review_command_once'),
        sa.ForeignKeyConstraint(['business_id', 'event_id'], ['comment_events.seller_id', 'comment_events.id'], name='comment_operator_review_event'),
        sa.ForeignKeyConstraint(['business_id', 'command_id'], ['comment_operator_commands.business_id', 'comment_operator_commands.id'], name='comment_operator_review_command'),
        sa.CheckConstraint('length(btrim(reason)) BETWEEN 10 AND 1000', name='comment_operator_review_reason'))
    op.create_table('whatsapp_enquiry_reviews',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('business_id', pg.UUID(as_uuid=True), sa.ForeignKey('businesses.id'), nullable=False),
        sa.Column('inbound_message_id', pg.UUID(as_uuid=True), nullable=False),
        sa.Column('contact_id', pg.UUID(as_uuid=True), nullable=False),
        sa.Column('phone_number_id', sa.String(40), nullable=False),
        sa.Column('reason', sa.String(40), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.UniqueConstraint('business_id', 'inbound_message_id', name='wa_enquiry_inbound_once'),
        sa.UniqueConstraint('business_id', 'id', name='wa_enquiry_tenant'),
        sa.ForeignKeyConstraint(['business_id', 'inbound_message_id', 'contact_id', 'phone_number_id'],
            ['whatsapp_messages.seller_id', 'whatsapp_messages.id', 'whatsapp_messages.contact_id', 'whatsapp_messages.phone_number_id'], name='wa_enquiry_exact_source'),
        sa.ForeignKeyConstraint(['contact_id', 'business_id'], ['whatsapp_contacts.id', 'whatsapp_contacts.seller_id'], name='wa_enquiry_contact_tenant'),
        sa.CheckConstraint("reason='activated_inferred_context'", name='wa_enquiry_reason'))
    op.create_table('whatsapp_enquiry_closures',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('business_id', pg.UUID(as_uuid=True), nullable=False),
        sa.Column('enquiry_id', pg.UUID(as_uuid=True), nullable=False),
        sa.Column('command_id', pg.UUID(as_uuid=True), nullable=False),
        sa.Column('reason', sa.String(1000), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.UniqueConstraint('business_id', 'enquiry_id', name='wa_enquiry_close_once'),
        sa.UniqueConstraint('business_id', 'command_id', name='wa_enquiry_close_command_once'),
        sa.ForeignKeyConstraint(['business_id', 'enquiry_id'], ['whatsapp_enquiry_reviews.business_id', 'whatsapp_enquiry_reviews.id'], name='wa_enquiry_close_source'),
        sa.ForeignKeyConstraint(['business_id', 'command_id'], ['comment_operator_commands.business_id', 'comment_operator_commands.id'], name='wa_enquiry_close_command'),
        sa.CheckConstraint('length(btrim(reason)) BETWEEN 10 AND 1000', name='wa_enquiry_close_reason'))
    for table in TABLES:
        op.create_index('ix_' + table + '_business_created', table, ['business_id', 'created_at', 'id'])
    op.execute("""CREATE FUNCTION v1_comment_operator_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN RAISE EXCEPTION 'Operator command and review history is immutable' USING ERRCODE='23514'; END; $$""")
    for table in TABLES:
        op.execute('CREATE TRIGGER v1_comment_operator_immutable BEFORE UPDATE OR DELETE ON ' + table + ' FOR EACH ROW EXECUTE FUNCTION v1_comment_operator_immutable()')


def downgrade():
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute('DROP FUNCTION v1_comment_operator_immutable()')
    op.drop_constraint('wa_message_review_source', 'whatsapp_messages', type_='unique')
