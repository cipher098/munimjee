"""Immutable accepted comment source bindings and once-only dispatch claims."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg
revision='0055_v1_comment_binding'
down_revision='0054_v1_activity'
branch_labels=depends_on=None

SOURCE_CHECK="(source_account_id IS NULL AND source_binding IS NULL AND source_verified_at IS NULL AND source_verification IS NULL) OR coalesce((\n source_account_id IS NOT NULL AND source_verified_at IS NOT NULL AND source_verification IN ('signed_webhook','provider_metadata')\n AND jsonb_typeof(source_binding)='object' AND octet_length(source_binding::text)<=2048\n AND source_binding ?& ARRAY['account_id','version','credential_hash','expires_at']\n AND source_binding-ARRAY['account_id','version','credential_hash','expires_at']='{}'::jsonb\n AND jsonb_typeof(source_binding->'account_id')='string' AND source_binding->>'account_id'=source_account_id\n AND length(source_account_id) BETWEEN 1 AND 100\n AND jsonb_typeof(source_binding->'version')='number' AND source_binding->>'version' ~ '^(0|[1-9][0-9]{0,8})$'\n AND jsonb_typeof(source_binding->'credential_hash')='string' AND source_binding->>'credential_hash' ~ '^[a-f0-9]{64}$'\n AND jsonb_typeof(source_binding->'expires_at')='string' AND length(source_binding->>'expires_at') BETWEEN 10 AND 80\n),false)"
CLAIM_CHECK="(accepted_claim IS NULL AND claim_hash IS NULL) OR coalesce((\n jsonb_typeof(accepted_claim)='object' AND octet_length(accepted_claim::text)<=4096\n AND claim_hash ~ '^[a-f0-9]{64}$'\n),false)"

CLAIM_STATE_CHECK="accepted_claim IS NULL OR (\n (claim_token IS NULL AND attempted_at IS NULL AND provider_id IS NULL AND status IN ('pending','review_required','cancelled'))\n OR (claim_token IS NOT NULL AND attempted_at IS NOT NULL AND status IN ('sending','sent','unknown','rejected','review_required','cancelled'))\n)"

GUARDS=(
    """CREATE FUNCTION comment_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Comment acceptance history is immutable' USING ERRCODE='23514'; END IF;
 IF (to_jsonb(NEW)-ARRAY['status','reason']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','reason']) THEN
 RAISE EXCEPTION 'Comment accepted source is immutable' USING ERRCODE='23514'; END IF;
 RETURN NEW; END; $$""",
    """CREATE TRIGGER comment_event_guard BEFORE UPDATE OR DELETE ON comment_events FOR EACH ROW EXECUTE FUNCTION comment_event_guard()""",
    """CREATE FUNCTION comment_action_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Comment action history is immutable' USING ERRCODE='23514'; END IF;
 IF TG_OP='INSERT' THEN
  IF NEW.accepted_claim IS NOT NULL AND (NEW.claim_token IS NOT NULL OR NEW.attempted_at IS NOT NULL OR NEW.provider_id IS NOT NULL OR NEW.finalized_at IS NOT NULL
   OR NEW.accepted_claim->'connection' IS DISTINCT FROM (SELECT source_binding FROM comment_events WHERE seller_id=NEW.seller_id AND id=NEW.event_id)) THEN
   RAISE EXCEPTION 'Comment action requires its accepted source' USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF (to_jsonb(NEW)-ARRAY['status','error_code','provider_id','attempted_at','claim_token','finalized_at']) IS DISTINCT FROM
    (to_jsonb(OLD)-ARRAY['status','error_code','provider_id','attempted_at','claim_token','finalized_at'])
  OR (OLD.claim_token IS NOT NULL AND NEW.claim_token IS DISTINCT FROM OLD.claim_token)
  OR (OLD.attempted_at IS NOT NULL AND NEW.attempted_at IS DISTINCT FROM OLD.attempted_at)
  OR (OLD.provider_id IS NOT NULL AND NEW.provider_id IS DISTINCT FROM OLD.provider_id)
  OR (OLD.finalized_at IS NOT NULL AND NEW.finalized_at IS DISTINCT FROM OLD.finalized_at)
  OR (OLD.status<>'pending' AND NEW.status='pending')
  OR (NEW.status='sending' AND OLD.status NOT IN ('pending','sending')) THEN
  RAISE EXCEPTION 'Comment accepted claim and outcome cannot be rebound' USING ERRCODE='23514'; END IF;
 IF OLD.provider_id IS NULL AND NEW.provider_id IS NOT NULL AND (OLD.status<>'sending' OR OLD.claim_token IS NULL OR NEW.status<>'sent') THEN
  RAISE EXCEPTION 'Comment receipt requires its original dispatch claim' USING ERRCODE='23514'; END IF;
 IF NEW.finalized_at IS NOT NULL AND NEW.status IN ('pending','sending') THEN
  RAISE EXCEPTION 'A finalized comment cannot run again' USING ERRCODE='23514'; END IF;
 IF OLD.claim_token IS NULL AND NEW.claim_token IS NOT NULL AND (OLD.status<>'pending' OR OLD.attempted_at IS NOT NULL OR OLD.provider_id IS NOT NULL OR NEW.status<>'sending' OR NEW.accepted_claim IS NULL OR NEW.attempted_at IS NULL) THEN
  RAISE EXCEPTION 'Comment claim requires never-attempted accepted work' USING ERRCODE='23514'; END IF;
 RETURN NEW; END; $$""",
    """CREATE TRIGGER comment_action_guard BEFORE INSERT OR UPDATE OR DELETE ON comment_actions FOR EACH ROW EXECUTE FUNCTION comment_action_guard()""",
    """CREATE FUNCTION comment_audit_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'Comment dispatch audits are append-only' USING ERRCODE='23514'; END; $$""",
    """CREATE TRIGGER comment_audit_guard BEFORE UPDATE OR DELETE ON comment_action_audits FOR EACH ROW EXECUTE FUNCTION comment_audit_guard()""",
)

def upgrade():
    for column in (sa.Column('source_account_id',sa.String(100)),sa.Column('source_binding',pg.JSONB()),
                   sa.Column('source_verified_at',sa.DateTime(timezone=True)),sa.Column('source_verification',sa.String(24))):
        op.add_column('comment_events',column)
    for column in (sa.Column('accepted_claim',pg.JSONB()),sa.Column('claim_hash',sa.String(64)),
                   sa.Column('claim_token',pg.UUID(as_uuid=True)),sa.Column('finalized_at',sa.DateTime(timezone=True))):
        op.add_column('comment_actions',column)
    op.create_unique_constraint('comment_event_tenant','comment_events',['seller_id','id'])
    op.create_unique_constraint('comment_action_tenant','comment_actions',['seller_id','event_id','id'])
    op.create_check_constraint('comment_source_complete','comment_events',SOURCE_CHECK)
    op.create_check_constraint('comment_claim_complete','comment_actions',CLAIM_CHECK)
    op.create_check_constraint('comment_claim_runtime','comment_actions',CLAIM_STATE_CHECK)
    # Preserve historical mismatches; every new/updated row is tenant-enforced.
    op.create_foreign_key('comment_action_event_tenant','comment_actions','comment_events',
        ['seller_id','event_id'],['seller_id','id'],postgresql_not_valid=True)
    op.create_table('comment_action_audits',
        sa.Column('id',pg.UUID(as_uuid=True),primary_key=True),
        sa.Column('seller_id',pg.UUID(as_uuid=True),nullable=False),
        sa.Column('event_id',pg.UUID(as_uuid=True),nullable=False),
        sa.Column('action_id',pg.UUID(as_uuid=True),nullable=False),
        sa.Column('claim_token',pg.UUID(as_uuid=True)),
        sa.Column('stage',sa.String(24),nullable=False),
        sa.Column('before_status',sa.String(30)),sa.Column('after_status',sa.String(30),nullable=False),
        sa.Column('reason',sa.String(100)),sa.Column('provider_id',sa.String(200)),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.clock_timestamp(),nullable=False),
        sa.ForeignKeyConstraint(['seller_id','event_id','action_id'],
            ['comment_actions.seller_id','comment_actions.event_id','comment_actions.id'],name='comment_audit_action_tenant'),
        sa.ForeignKeyConstraint(['seller_id','event_id'],['comment_events.seller_id','comment_events.id'],name='comment_audit_event_tenant'),
        sa.CheckConstraint("stage IN ('accepted','claim','withheld','provider_result','worker_recovered')",name='comment_audit_stage'))
    op.create_index('ix_comment_action_audits_seller_id','comment_action_audits',['seller_id'])
    for statement in GUARDS: op.execute(statement)


def downgrade():
    for table,function in (('comment_action_audits','comment_audit_guard'),('comment_actions','comment_action_guard'),('comment_events','comment_event_guard')):
        op.execute('DROP TRIGGER '+function+' ON '+table)
        op.execute('DROP FUNCTION '+function+'()')
    op.drop_table('comment_action_audits')
    op.drop_constraint('comment_action_event_tenant','comment_actions',type_='foreignkey')
    op.drop_constraint('comment_claim_runtime','comment_actions',type_='check')
    op.drop_constraint('comment_claim_complete','comment_actions',type_='check')
    op.drop_constraint('comment_source_complete','comment_events',type_='check')
    op.drop_constraint('comment_action_tenant','comment_actions',type_='unique')
    op.drop_constraint('comment_event_tenant','comment_events',type_='unique')
    for name in ('accepted_claim','claim_hash','claim_token','finalized_at'):op.drop_column('comment_actions',name)
    for name in ('source_account_id','source_binding','source_verified_at','source_verification'):op.drop_column('comment_events',name)
