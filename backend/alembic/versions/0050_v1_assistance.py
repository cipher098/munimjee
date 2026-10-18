"""Membership-scoped assistance ownership and immutable command receipts.

Revision ID: 0050_v1_assistance
Revises: 0049_v1_storefront_settings
"""
from alembic import op
revision = '0050_v1_assistance'
down_revision = '0049_v1_storefront_settings'
branch_labels = depends_on = None


def upgrade():
    op.execute('''
CREATE TABLE v1_onboarding_assignments (
 business_id UUID PRIMARY KEY REFERENCES businesses(id) ON DELETE RESTRICT,
 assignee_user_id UUID,
 assigned_by_user_id UUID NOT NULL,
 version INTEGER NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT v1_assistance_assignee_member FOREIGN KEY(business_id,assignee_user_id) REFERENCES memberships(business_id,user_id) ON DELETE RESTRICT,
 CONSTRAINT v1_assistance_assigner_member FOREIGN KEY(business_id,assigned_by_user_id) REFERENCES memberships(business_id,user_id) ON DELETE RESTRICT,
 CONSTRAINT v1_assistance_assignment_version CHECK(version>0 AND version<=2000000000)
)
''')
    op.execute('''CREATE TABLE v1_assistance_commands (
 business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE RESTRICT,
 idempotency_key UUID NOT NULL,
 actor_user_id UUID NOT NULL,
 operation VARCHAR(20) NOT NULL,
 request_hash VARCHAR(64) NOT NULL,
 result JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(business_id,idempotency_key),
 CONSTRAINT v1_assistance_command_actor_member FOREIGN KEY(business_id,actor_user_id) REFERENCES memberships(business_id,user_id) ON DELETE RESTRICT,
 CONSTRAINT v1_assistance_command_operation CHECK(operation IN ('assignment','open')),
 CONSTRAINT v1_assistance_command_result CHECK(request_hash ~ '^[a-f0-9]{64}$' AND jsonb_typeof(result)='object')
)
''')
    op.execute('''CREATE FUNCTION v1_assistance_command_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'Assistance receipts are immutable' USING ERRCODE='23514';
END; $$
''')
    op.execute('''CREATE TRIGGER v1_assistance_command_immutable BEFORE UPDATE OR DELETE ON v1_assistance_commands
 FOR EACH ROW EXECUTE FUNCTION v1_assistance_command_immutable()
''')


def downgrade():
    op.drop_table('v1_assistance_commands')
    op.drop_table('v1_onboarding_assignments')
    op.execute('DROP FUNCTION v1_assistance_command_immutable()')
