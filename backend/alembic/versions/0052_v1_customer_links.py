"""Channel-control proof and explicit consent, no historic record merge/backfill."""
from alembic import op
revision = '0052_v1_customer_links'
down_revision = '0051_v1_support_grants'
branch_labels = depends_on = None

DDL = (
    """ALTER TABLE conversations ADD CONSTRAINT v1_customer_conversation_tenant UNIQUE(id,seller_id)""",
    """CREATE TABLE v1_customers (
	id UUID NOT NULL, 
	business_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT v1_customer_tenant UNIQUE (business_id, id), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
)""",
    """CREATE TABLE v1_customer_link_challenges (
	id UUID NOT NULL, 
	business_id UUID NOT NULL, 
	created_by UUID NOT NULL, 
	conversation_id UUID NOT NULL, 
	contact_id UUID NOT NULL, 
	instagram_account VARCHAR(100) NOT NULL, 
	instagram_subject VARCHAR(100) NOT NULL, 
	whatsapp_account VARCHAR(40) NOT NULL, 
	whatsapp_subject VARCHAR(20) NOT NULL, 
	binding_hash VARCHAR(64) NOT NULL, 
	secret_digest VARCHAR(64) NOT NULL, 
	state VARCHAR(20) NOT NULL, 
	customer_id UUID, 
	issued_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT v1_customer_challenge_tenant UNIQUE (business_id, id), 
	CONSTRAINT v1_customer_challenge_secret UNIQUE (business_id, secret_digest), 
	FOREIGN KEY(business_id, created_by) REFERENCES memberships (business_id, user_id), 
	FOREIGN KEY(conversation_id, business_id) REFERENCES conversations (id, seller_id), 
	FOREIGN KEY(contact_id, business_id) REFERENCES whatsapp_contacts (id, seller_id), 
	FOREIGN KEY(business_id, customer_id) REFERENCES v1_customers (business_id, id), 
	CONSTRAINT v1_customer_challenge_state CHECK (state IN ('pending','verified','cancelled')), 
	CONSTRAINT v1_customer_challenge_expiry CHECK (expires_at > issued_at AND expires_at <= issued_at + interval '10 minutes'), 
	CONSTRAINT v1_customer_challenge_result CHECK ((state='verified')=(customer_id IS NOT NULL)), 
	CONSTRAINT v1_customer_challenge_hashes CHECK (binding_hash ~ '^[a-f0-9]{64}$' AND secret_digest ~ '^[a-f0-9]{64}$'), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
)""",
    """CREATE INDEX v1_customer_challenge_list ON v1_customer_link_challenges (business_id, issued_at)""",
    """CREATE TABLE v1_customer_link_proofs (
	id UUID NOT NULL, 
	business_id UUID NOT NULL, 
	challenge_id UUID NOT NULL, 
	channel VARCHAR(12) NOT NULL, 
	account_id VARCHAR(100) NOT NULL, 
	subject_id VARCHAR(100) NOT NULL, 
	provider_message_id VARCHAR(255) NOT NULL, 
	provider_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	received_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(business_id, challenge_id) REFERENCES v1_customer_link_challenges (business_id, id), 
	CONSTRAINT v1_customer_proof_side UNIQUE (business_id, challenge_id, channel), 
	CONSTRAINT v1_customer_proof_event UNIQUE (business_id, channel, account_id, provider_message_id), 
	CONSTRAINT v1_customer_proof_channel CHECK (channel IN ('instagram','whatsapp'))
)""",
    """CREATE TABLE v1_customer_associations (
	id UUID NOT NULL, 
	business_id UUID NOT NULL, 
	customer_id UUID NOT NULL, 
	challenge_id UUID NOT NULL, 
	channel VARCHAR(12) NOT NULL, 
	account_id VARCHAR(100) NOT NULL, 
	subject_id VARCHAR(100) NOT NULL, 
	conversation_id UUID, 
	contact_id UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT v1_customer_association_tenant UNIQUE (business_id, id), 
	FOREIGN KEY(business_id, customer_id) REFERENCES v1_customers (business_id, id), 
	FOREIGN KEY(business_id, challenge_id, channel) REFERENCES v1_customer_link_proofs (business_id, challenge_id, channel), 
	FOREIGN KEY(conversation_id, business_id) REFERENCES conversations (id, seller_id), 
	FOREIGN KEY(contact_id, business_id) REFERENCES whatsapp_contacts (id, seller_id), 
	CONSTRAINT v1_customer_association_source CHECK ((channel='instagram' AND conversation_id IS NOT NULL AND contact_id IS NULL) OR (channel='whatsapp' AND contact_id IS NOT NULL AND conversation_id IS NULL))
)""",
    """CREATE UNIQUE INDEX v1_customer_active_contact ON v1_customer_associations (business_id, contact_id) WHERE revoked_at IS NULL""",
    """CREATE UNIQUE INDEX v1_customer_active_conversation ON v1_customer_associations (business_id, conversation_id) WHERE revoked_at IS NULL""",
    """CREATE UNIQUE INDEX v1_customer_active_endpoint ON v1_customer_associations (business_id, channel, account_id, subject_id) WHERE revoked_at IS NULL""",
    """CREATE TABLE v1_customer_link_audits (
	id UUID NOT NULL, 
	business_id UUID NOT NULL, 
	actor_id UUID NOT NULL, 
	idempotency_key UUID NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	action VARCHAR(20) NOT NULL, 
	result JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(business_id, actor_id) REFERENCES memberships (business_id, user_id), 
	CONSTRAINT v1_customer_command_once UNIQUE (business_id, idempotency_key), 
	CONSTRAINT v1_customer_audit_action CHECK (action IN ('create','finalize','cancel','unlink')), 
	CONSTRAINT v1_customer_audit_result CHECK (jsonb_typeof(result)='object'), 
	CONSTRAINT v1_customer_audit_hash CHECK (request_hash ~ '^[a-f0-9]{64}$'), 
	FOREIGN KEY(business_id) REFERENCES businesses (id)
)""",
    """CREATE FUNCTION v1_customer_evidence_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Customer link evidence is append-only' USING ERRCODE='23514'; END; $$""",
    """CREATE TRIGGER v1_customer_proof_immutable BEFORE UPDATE OR DELETE ON v1_customer_link_proofs FOR EACH ROW EXECUTE FUNCTION v1_customer_evidence_immutable()""",
    """CREATE TRIGGER v1_customer_audit_immutable BEFORE UPDATE OR DELETE ON v1_customer_link_audits FOR EACH ROW EXECUTE FUNCTION v1_customer_evidence_immutable()""",
    """CREATE FUNCTION v1_customer_association_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='UPDATE' AND OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL
 AND (to_jsonb(NEW)-'revoked_at')=(to_jsonb(OLD)-'revoked_at') THEN RETURN NEW; END IF;
 RAISE EXCEPTION 'Customer association can only be irreversibly unlinked' USING ERRCODE='23514'; END; $$""",
    """CREATE TRIGGER v1_customer_association_immutable BEFORE UPDATE OR DELETE ON v1_customer_associations FOR EACH ROW EXECUTE FUNCTION v1_customer_association_immutable()""",
    """CREATE FUNCTION v1_customer_challenge_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP='UPDATE' AND OLD.state='pending' AND NEW.state IN ('verified','cancelled')
 AND (to_jsonb(NEW)-ARRAY['state','customer_id'])=(to_jsonb(OLD)-ARRAY['state','customer_id']) THEN RETURN NEW; END IF;
 RAISE EXCEPTION 'Customer challenge bindings and expiry are immutable' USING ERRCODE='23514'; END; $$""",
    """CREATE TRIGGER v1_customer_challenge_immutable BEFORE UPDATE OR DELETE ON v1_customer_link_challenges FOR EACH ROW EXECUTE FUNCTION v1_customer_challenge_immutable()""",
    """CREATE TRIGGER v1_customer_immutable BEFORE UPDATE OR DELETE ON v1_customers FOR EACH ROW EXECUTE FUNCTION v1_customer_evidence_immutable()""",
)

def upgrade():
    for statement in DDL:
        op.execute(statement)

def downgrade():
    for table in ('v1_customer_link_audits','v1_customer_associations','v1_customer_link_proofs','v1_customer_link_challenges','v1_customers'):
        op.drop_table(table)
    op.execute('DROP FUNCTION v1_customer_challenge_immutable()')
    op.execute('DROP FUNCTION v1_customer_association_immutable()')
    op.execute('DROP FUNCTION v1_customer_evidence_immutable()')
    op.drop_constraint('v1_customer_conversation_tenant','conversations',type_='unique')
