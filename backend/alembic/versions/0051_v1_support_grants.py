"""Explicit read-only owner consent and immutable access/command receipts.

Revision ID: 0051_v1_support_grants
Revises: 0050_v1_assistance
"""
from alembic import op
revision = '0051_v1_support_grants'
down_revision = '0050_v1_assistance'
branch_labels = depends_on = None


def upgrade():
    op.execute('''CREATE TABLE v1_support_grants (
 id UUID PRIMARY KEY,
 business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE RESTRICT,
 subject_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 consented_by_user_id UUID NOT NULL,
 subject_auth_version INTEGER NOT NULL,
 owner_auth_version INTEGER NOT NULL,
 scope VARCHAR(40) NOT NULL,
 reason VARCHAR(200) NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 expires_at TIMESTAMPTZ NOT NULL,
 revoked_at TIMESTAMPTZ,
 revoked_by_user_id UUID,
 CONSTRAINT v1_support_grant_tenant UNIQUE(business_id,id),
 CONSTRAINT v1_support_grant_owner FOREIGN KEY(business_id,consented_by_user_id) REFERENCES memberships(business_id,user_id) ON DELETE RESTRICT,
 CONSTRAINT v1_support_grant_revoker FOREIGN KEY(business_id,revoked_by_user_id) REFERENCES memberships(business_id,user_id) ON DELETE RESTRICT,
 CONSTRAINT v1_support_grant_scope CHECK(scope='readiness.summary' AND char_length(reason) BETWEEN 1 AND 200),
 CONSTRAINT v1_support_grant_subject CHECK(subject_auth_version>=0 AND owner_auth_version>=0 AND subject_user_id<>consented_by_user_id),
 CONSTRAINT v1_support_grant_expiry CHECK(expires_at>=created_at+interval '5 minutes' AND expires_at<=created_at+interval '60 minutes'),
 CONSTRAINT v1_support_grant_revocation CHECK((revoked_at IS NULL)=(revoked_by_user_id IS NULL) AND (revoked_at IS NULL OR revoked_at>=created_at))
)''')
    op.execute('CREATE INDEX v1_support_grant_subject_lookup ON v1_support_grants(subject_user_id,business_id,expires_at)')
    op.execute('''CREATE TABLE v1_support_commands (
 business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE RESTRICT,
 idempotency_key UUID NOT NULL,
 grant_id UUID NOT NULL,
 actor_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
 operation VARCHAR(20) NOT NULL,
 request_hash VARCHAR(64) NOT NULL,
 result JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(business_id,idempotency_key),
 CONSTRAINT v1_support_command_grant FOREIGN KEY(business_id,grant_id) REFERENCES v1_support_grants(business_id,id) ON DELETE RESTRICT,
 CONSTRAINT v1_support_command_operation CHECK(operation IN ('create','revoke','open')),
 CONSTRAINT v1_support_command_result CHECK(request_hash ~ '^[a-f0-9]{64}$' AND jsonb_typeof(result)='object')
)''')
    op.execute('''CREATE FUNCTION v1_support_consent_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' AND OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL
 AND NEW.revoked_by_user_id IS NOT NULL
 AND (to_jsonb(NEW)-ARRAY['revoked_at','revoked_by_user_id'])=(to_jsonb(OLD)-ARRAY['revoked_at','revoked_by_user_id']) THEN
  RETURN NEW;
 END IF;
 RAISE EXCEPTION 'Support consent is immutable except irreversible revocation' USING ERRCODE='23514';
END; $$''')
    op.execute('''CREATE TRIGGER v1_support_consent_immutable BEFORE UPDATE OR DELETE ON v1_support_grants
 FOR EACH ROW EXECUTE FUNCTION v1_support_consent_immutable()''')
    op.execute('''CREATE FUNCTION v1_support_command_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Support access receipts are immutable' USING ERRCODE='23514'; END; $$''')
    op.execute('''CREATE TRIGGER v1_support_command_immutable BEFORE UPDATE OR DELETE ON v1_support_commands
 FOR EACH ROW EXECUTE FUNCTION v1_support_command_immutable()''')


def downgrade():
    op.drop_table('v1_support_commands')
    op.drop_table('v1_support_grants')
    op.execute('DROP FUNCTION v1_support_command_immutable()')
    op.execute('DROP FUNCTION v1_support_consent_immutable()')
