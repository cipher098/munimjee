"""Bounded native WhatsApp signup and exact test-message authority."""
from alembic import op

revision = "0057_v1_whatsapp_self_service"
down_revision = "0056_v1_comment_operator"
branch_labels = depends_on = None

TABLES = ('whatsapp_signup_attempts', 'whatsapp_signup_choices', 'whatsapp_authorization_provenance', 'whatsapp_connection_tests', 'whatsapp_test_authorizations')

DDL = (
    """CREATE TABLE whatsapp_signup_attempts (
	id UUID NOT NULL, 
	business_id UUID NOT NULL, 
	actor_user_id UUID NOT NULL, 
	actor_session_id UUID NOT NULL, 
	actor_auth_version INTEGER NOT NULL, 
	idempotency_key UUID NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	connection_version INTEGER NOT NULL, 
	nonce_digest VARCHAR(64) NOT NULL, 
	evidence_kind VARCHAR(30) DEFAULT 'provider' NOT NULL, 
	state VARCHAR(30) DEFAULT 'pending' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	exchange_consumed_at TIMESTAMP WITH TIME ZONE, 
	provisional_token_ciphertext TEXT, 
	token_delete_after TIMESTAMP WITH TIME ZONE NOT NULL, 
	token_expiry_kind VARCHAR(12) DEFAULT 'unknown' NOT NULL, 
	token_expires_at TIMESTAMP WITH TIME ZONE, 
	verified_app_id VARCHAR(40), 
	selected_choice_id UUID, 
	selected_key UUID, 
	selected_hash VARCHAR(64), 
	subscription_state VARCHAR(20) DEFAULT 'not_started' NOT NULL, 
	registration_state VARCHAR(20) DEFAULT 'not_started' NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT wa_signup_key UNIQUE (business_id, idempotency_key), 
	CONSTRAINT wa_signup_tenant UNIQUE (id, business_id), 
	CONSTRAINT wa_signup_versions CHECK (actor_auth_version >= 0 AND connection_version >= 0), 
	CONSTRAINT wa_signup_digests CHECK (request_hash ~ '^[0-9a-f]{64}$' AND nonce_digest ~ '^[0-9a-f]{64}$'), 
	CONSTRAINT wa_signup_expiry CHECK (expires_at = created_at + interval '10 minutes' AND token_delete_after = created_at + interval '15 minutes'), 
	CONSTRAINT wa_signup_evidence CHECK (evidence_kind IN ('provider','synthetic_fixture')), 
	CONSTRAINT wa_signup_state CHECK (state IN ('pending','exchanging','exchange_unknown','awaiting_assets','awaiting_selection','setting_up','setup_unknown','attached','failed','cancelled','expired','stale')), 
	CONSTRAINT wa_signup_steps CHECK (subscription_state IN ('not_started','requesting','unknown','confirmed','failed') AND registration_state IN ('not_started','requesting','unknown','confirmed','failed')), 
	CONSTRAINT wa_signup_token_expiry CHECK (token_expiry_kind IN ('unknown','at','permanent') AND ((token_expiry_kind = 'at' AND token_expires_at IS NOT NULL) OR (token_expiry_kind <> 'at' AND token_expires_at IS NULL))), 
	CONSTRAINT wa_signup_app_id CHECK (verified_app_id IS NULL OR verified_app_id ~ '^[0-9]{1,40}$'), 
	CONSTRAINT wa_signup_selection CHECK ((selected_key IS NULL AND selected_hash IS NULL AND selected_choice_id IS NULL) OR (selected_key IS NOT NULL AND selected_hash IS NOT NULL AND selected_hash ~ '^[0-9a-f]{64}$' AND selected_choice_id IS NOT NULL)), 
	FOREIGN KEY(business_id) REFERENCES businesses (id), 
	FOREIGN KEY(actor_user_id) REFERENCES users (id), 
	FOREIGN KEY(actor_session_id) REFERENCES user_sessions (id)
)""",
    """CREATE TABLE whatsapp_signup_choices (
	id UUID NOT NULL, 
	attempt_id UUID NOT NULL, 
	business_id UUID NOT NULL, 
	waba_id VARCHAR(40) NOT NULL, 
	phone_number_id VARCHAR(40) NOT NULL, 
	display_name VARCHAR(160) NOT NULL, 
	display_phone_number VARCHAR(50) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	verified_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	provider_registration_status VARCHAR(20) DEFAULT 'unknown' NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT wa_choice_attempt FOREIGN KEY(attempt_id, business_id) REFERENCES whatsapp_signup_attempts (id, business_id), 
	CONSTRAINT wa_choice_phone UNIQUE (attempt_id, waba_id, phone_number_id), 
	CONSTRAINT wa_choice_tenant UNIQUE (id, attempt_id, business_id), 
	CONSTRAINT wa_choice_ids CHECK (waba_id ~ '^[0-9]{1,40}$' AND phone_number_id ~ '^[0-9]{1,40}$'), 
	CONSTRAINT wa_choice_fingerprint CHECK (fingerprint ~ '^[0-9a-f]{64}$'), 
	CONSTRAINT wa_choice_registration CHECK (provider_registration_status IN ('unknown','registered','unregistered'))
)""",
    """CREATE TABLE whatsapp_authorization_provenance (
	business_id UUID NOT NULL, 
	connection_version INTEGER NOT NULL, 
	attempt_id UUID NOT NULL, 
	actor_user_id UUID NOT NULL, 
	actor_session_id UUID NOT NULL, 
	actor_auth_version INTEGER NOT NULL, 
	phone_number_id VARCHAR(40) NOT NULL, 
	waba_id VARCHAR(40) NOT NULL, 
	verified_app_id VARCHAR(40) NOT NULL, 
	grants JSONB NOT NULL, 
	token_expiry_kind VARCHAR(12) NOT NULL, 
	token_expires_at TIMESTAMP WITH TIME ZONE, 
	verified_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	evidence_kind VARCHAR(30) NOT NULL, 
	PRIMARY KEY (business_id, connection_version), 
	CONSTRAINT wa_provenance_attempt FOREIGN KEY(attempt_id, business_id) REFERENCES whatsapp_signup_attempts (id, business_id), 
	CONSTRAINT wa_provenance_versions CHECK (actor_auth_version >= 0 AND connection_version >= 0), 
	CONSTRAINT wa_provenance_ids CHECK (phone_number_id ~ '^[0-9]{1,40}$' AND waba_id ~ '^[0-9]{1,40}$' AND verified_app_id ~ '^[0-9]{1,40}$'), 
	CONSTRAINT wa_provenance_grants CHECK (jsonb_typeof(grants) = 'array' AND jsonb_array_length(grants) = 2 AND grants @> '["whatsapp_business_management","whatsapp_business_messaging"]'::jsonb), 
	CONSTRAINT wa_provenance_expiry CHECK ((token_expiry_kind = 'at' AND token_expires_at IS NOT NULL AND token_expires_at > verified_at) OR (token_expiry_kind = 'permanent' AND token_expires_at IS NULL)), 
	CONSTRAINT wa_provenance_evidence CHECK (evidence_kind IN ('provider','synthetic_fixture')), 
	FOREIGN KEY(business_id) REFERENCES businesses (id), 
	FOREIGN KEY(actor_user_id) REFERENCES users (id), 
	FOREIGN KEY(actor_session_id) REFERENCES user_sessions (id)
)""",
    """CREATE TABLE whatsapp_connection_tests (
	id UUID NOT NULL, 
	business_id UUID NOT NULL, 
	actor_user_id UUID NOT NULL, 
	actor_session_id UUID NOT NULL, 
	actor_auth_version INTEGER NOT NULL, 
	idempotency_key UUID NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	connection_version INTEGER NOT NULL, 
	phone_number_id VARCHAR(40) NOT NULL, 
	waba_id VARCHAR(40) NOT NULL, 
	challenge_digest VARCHAR(64) NOT NULL, 
	evidence_kind VARCHAR(30) NOT NULL, 
	issued_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	recipient_contact_id UUID, 
	inbound_message_id UUID, 
	inbound_provider_at TIMESTAMP WITH TIME ZONE, 
	received_at TIMESTAMP WITH TIME ZONE, 
	cancelled_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT wa_test_key UNIQUE (business_id, idempotency_key), 
	CONSTRAINT wa_test_tenant UNIQUE (id, business_id), 
	CONSTRAINT wa_test_contact FOREIGN KEY(recipient_contact_id, business_id) REFERENCES whatsapp_contacts (id, seller_id), 
	CONSTRAINT wa_test_inbound FOREIGN KEY(inbound_message_id, business_id) REFERENCES whatsapp_messages (id, seller_id), 
	CONSTRAINT wa_test_versions CHECK (actor_auth_version >= 0 AND connection_version >= 0), 
	CONSTRAINT wa_test_digests CHECK (request_hash ~ '^[0-9a-f]{64}$' AND challenge_digest ~ '^[0-9a-f]{64}$'), 
	CONSTRAINT wa_test_ids CHECK (phone_number_id ~ '^[0-9]{1,40}$' AND waba_id ~ '^[0-9]{1,40}$'), 
	CONSTRAINT wa_test_evidence CHECK (evidence_kind IN ('provider','synthetic_fixture')), 
	CONSTRAINT wa_test_expiry CHECK (expires_at = issued_at + interval '10 minutes'), 
	CONSTRAINT wa_test_inbound_times CHECK ((recipient_contact_id IS NULL AND inbound_message_id IS NULL AND inbound_provider_at IS NULL AND received_at IS NULL) OR (recipient_contact_id IS NOT NULL AND inbound_message_id IS NOT NULL AND inbound_provider_at IS NOT NULL AND received_at IS NOT NULL AND inbound_provider_at BETWEEN issued_at AND expires_at AND received_at BETWEEN inbound_provider_at - interval '30 seconds' AND expires_at + interval '30 seconds')), 
	FOREIGN KEY(business_id) REFERENCES businesses (id), 
	FOREIGN KEY(actor_user_id) REFERENCES users (id), 
	FOREIGN KEY(actor_session_id) REFERENCES user_sessions (id), 
	UNIQUE (challenge_digest)
)""",
    """CREATE TABLE whatsapp_test_authorizations (
	test_id UUID NOT NULL, 
	business_id UUID NOT NULL, 
	actor_user_id UUID NOT NULL, 
	actor_session_id UUID NOT NULL, 
	actor_auth_version INTEGER NOT NULL, 
	connection_version INTEGER NOT NULL, 
	phone_number_id VARCHAR(40) NOT NULL, 
	recipient_contact_id UUID NOT NULL, 
	inbound_message_id UUID NOT NULL, 
	outbound_message_id UUID NOT NULL, 
	idempotency_key UUID NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	fixed_text_version VARCHAR(40) NOT NULL, 
	authorized_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (test_id), 
	CONSTRAINT wa_test_auth_test FOREIGN KEY(test_id, business_id) REFERENCES whatsapp_connection_tests (id, business_id), 
	CONSTRAINT wa_test_auth_contact FOREIGN KEY(recipient_contact_id, business_id) REFERENCES whatsapp_contacts (id, seller_id), 
	CONSTRAINT wa_test_auth_inbound FOREIGN KEY(inbound_message_id, business_id) REFERENCES whatsapp_messages (id, seller_id), 
	CONSTRAINT wa_test_auth_outbound FOREIGN KEY(outbound_message_id, business_id) REFERENCES whatsapp_messages (id, seller_id), 
	CONSTRAINT wa_test_auth_key UNIQUE (business_id, idempotency_key), 
	CONSTRAINT wa_test_auth_versions CHECK (actor_auth_version >= 0 AND connection_version >= 0), 
	CONSTRAINT wa_test_auth_identity CHECK (phone_number_id ~ '^[0-9]{1,40}$' AND request_hash ~ '^[0-9a-f]{64}$'), 
	CONSTRAINT wa_test_auth_text CHECK (fixed_text_version = 'wa-connection-test.v1'), 
	CONSTRAINT wa_test_auth_expiry CHECK (expires_at > authorized_at AND expires_at <= authorized_at + interval '120 seconds'), 
	FOREIGN KEY(actor_user_id) REFERENCES users (id), 
	FOREIGN KEY(actor_session_id) REFERENCES user_sessions (id), 
	UNIQUE (outbound_message_id)
)""",
    """ALTER TABLE whatsapp_signup_attempts ADD CONSTRAINT wa_signup_selected_choice FOREIGN KEY(selected_choice_id, id, business_id) REFERENCES whatsapp_signup_choices (id, attempt_id, business_id)""",
    """CREATE INDEX ix_wa_signup_cleanup ON whatsapp_signup_attempts (token_delete_after)""",
    """CREATE INDEX ix_wa_test_created ON whatsapp_connection_tests (business_id, issued_at)""",
)

def upgrade():
    op.create_unique_constraint("wa_message_tenant_identity", "whatsapp_messages", ["id", "seller_id"])
    for statement in DDL:
        op.execute(statement)
    install_guards()

def downgrade():
    op.execute("DROP TRIGGER wa_test_message_guard ON whatsapp_messages")
    op.drop_constraint("wa_signup_selected_choice", "whatsapp_signup_attempts", type_="foreignkey")
    for table in reversed(TABLES):
        op.drop_table(table)
    for function in ("wa_self_initial_guard", "wa_self_actor_guard", "wa_self_immutable", "wa_signup_guard", "wa_test_guard", "wa_test_authorization_guard", "wa_provenance_guard", "wa_choice_guard", "wa_test_message_guard"):
        op.execute("DROP FUNCTION " + function + "()")
    op.drop_constraint("wa_message_tenant_identity", "whatsapp_messages", type_="unique")


def install_guards():
    op.execute("""CREATE FUNCTION wa_self_actor_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM user_sessions s JOIN users u ON u.id=s.user_id
 JOIN memberships m ON m.user_id=u.id AND m.business_id=NEW.business_id
 JOIN businesses b ON b.id=m.business_id JOIN sellers seller ON seller.id=b.id
 WHERE s.id=NEW.actor_session_id AND s.user_id=NEW.actor_user_id
 AND s.auth_version=NEW.actor_auth_version AND u.auth_version=s.auth_version
 AND s.revoked_at IS NULL AND s.expires_at>clock_timestamp()
 AND u.is_active AND u.revoked_at IS NULL AND m.is_active AND m.revoked_at IS NULL
 AND m.role='owner' AND b.is_active AND seller.is_active) THEN
 RAISE EXCEPTION 'Current native owner session required' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END; $$""")
    op.execute("""CREATE FUNCTION wa_self_initial_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='whatsapp_signup_attempts' AND (
 to_jsonb(NEW)->>'state'<>'pending' OR to_jsonb(NEW)->>'exchange_consumed_at' IS NOT NULL OR to_jsonb(NEW)->>'provisional_token_ciphertext' IS NOT NULL
 OR to_jsonb(NEW)->>'token_expiry_kind'<>'unknown' OR to_jsonb(NEW)->>'token_expires_at' IS NOT NULL OR to_jsonb(NEW)->>'verified_app_id' IS NOT NULL
 OR to_jsonb(NEW)->>'selected_choice_id' IS NOT NULL OR to_jsonb(NEW)->>'subscription_state'<>'not_started' OR to_jsonb(NEW)->>'registration_state'<>'not_started') THEN
 RAISE EXCEPTION 'Signup must start without provider effects' USING ERRCODE='23514'; END IF;
 IF TG_TABLE_NAME='whatsapp_connection_tests' AND (to_jsonb(NEW)->>'inbound_message_id' IS NOT NULL OR to_jsonb(NEW)->>'cancelled_at' IS NOT NULL) THEN
 RAISE EXCEPTION 'Test must start without recipient proof' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END; $$""")
    op.execute("""CREATE FUNCTION wa_self_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'WhatsApp authorization evidence is immutable' USING ERRCODE='23514'; END; $$""")
    op.execute("""CREATE FUNCTION wa_signup_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Signup history is retained' USING ERRCODE='23514'; END IF;
 IF (to_jsonb(NEW)-ARRAY['state','exchange_consumed_at','provisional_token_ciphertext','token_expiry_kind','token_expires_at','verified_app_id','selected_choice_id','selected_key','selected_hash','subscription_state','registration_state','updated_at'])
 IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','exchange_consumed_at','provisional_token_ciphertext','token_expiry_kind','token_expires_at','verified_app_id','selected_choice_id','selected_key','selected_hash','subscription_state','registration_state','updated_at']) THEN
 RAISE EXCEPTION 'Signup identity is immutable' USING ERRCODE='23514'; END IF;
 IF OLD.exchange_consumed_at IS NOT NULL AND NEW.exchange_consumed_at IS DISTINCT FROM OLD.exchange_consumed_at
 OR OLD.exchange_consumed_at IS NULL AND NEW.exchange_consumed_at IS NOT NULL AND (OLD.state<>'pending' OR NEW.state<>'exchanging' OR NEW.exchange_consumed_at<OLD.created_at OR NEW.exchange_consumed_at>OLD.expires_at)
 OR NEW.state='exchanging' AND NEW.exchange_consumed_at IS NULL THEN
 RAISE EXCEPTION 'Code exchange is one way' USING ERRCODE='23514'; END IF;
 IF NEW.state IS DISTINCT FROM OLD.state AND NOT (
 NEW.state IN ('cancelled','expired','stale') AND OLD.state IN ('pending','awaiting_assets','awaiting_selection')
 OR OLD.state='pending' AND NEW.state='exchanging'
 OR OLD.state='exchanging' AND NEW.state IN ('exchange_unknown','awaiting_assets','failed')
 OR OLD.state='awaiting_assets' AND NEW.state IN ('awaiting_selection','failed')
 OR OLD.state='awaiting_selection' AND NEW.state IN ('setting_up','failed')
 OR OLD.state='setting_up' AND NEW.state IN ('setup_unknown','attached','failed')) THEN
 RAISE EXCEPTION 'Invalid signup transition' USING ERRCODE='23514'; END IF;
 IF OLD.selected_key IS NOT NULL AND ROW(NEW.selected_choice_id,NEW.selected_key,NEW.selected_hash) IS DISTINCT FROM ROW(OLD.selected_choice_id,OLD.selected_key,OLD.selected_hash)
 OR OLD.selected_key IS NULL AND NEW.selected_key IS NOT NULL AND (OLD.state<>'awaiting_selection' OR NEW.state<>'setting_up') THEN
 RAISE EXCEPTION 'Selected account is immutable' USING ERRCODE='23514'; END IF;
 IF NEW.provisional_token_ciphertext IS DISTINCT FROM OLD.provisional_token_ciphertext AND NEW.provisional_token_ciphertext IS NOT NULL
 AND NOT (OLD.state='exchanging' AND NEW.state='awaiting_assets' AND OLD.provisional_token_ciphertext IS NULL) THEN
 RAISE EXCEPTION 'Provisional token cannot be restored or replaced' USING ERRCODE='23514'; END IF;
 IF ROW(NEW.token_expiry_kind,NEW.token_expires_at,NEW.verified_app_id) IS DISTINCT FROM ROW(OLD.token_expiry_kind,OLD.token_expires_at,OLD.verified_app_id)
 AND NOT (OLD.state='exchanging' AND NEW.state='awaiting_assets' AND OLD.verified_app_id IS NULL) THEN
 RAISE EXCEPTION 'Verified token evidence is immutable' USING ERRCODE='23514'; END IF;
 IF NEW.subscription_state IS DISTINCT FROM OLD.subscription_state AND NOT (
 OLD.subscription_state='not_started' AND NEW.subscription_state='requesting' AND NEW.state='setting_up'
 OR OLD.subscription_state='requesting' AND NEW.subscription_state IN ('unknown','confirmed','failed'))
 OR NEW.registration_state IS DISTINCT FROM OLD.registration_state AND NOT (
 OLD.registration_state='not_started' AND NEW.registration_state='requesting' AND NEW.state='setting_up'
 OR OLD.registration_state='requesting' AND NEW.registration_state IN ('unknown','confirmed','failed')) THEN
 RAISE EXCEPTION 'Provider step claim cannot be retried' USING ERRCODE='23514'; END IF;
 IF NEW.state IN ('attached','failed','cancelled','expired','stale','exchange_unknown','setup_unknown') AND NEW.provisional_token_ciphertext IS NOT NULL THEN
 RAISE EXCEPTION 'Terminal or unknown attempt cannot retain credentials' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END; $$""")
    op.execute("""CREATE FUNCTION wa_test_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE inbound whatsapp_messages%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Test history is retained' USING ERRCODE='23514'; END IF;
 IF (to_jsonb(NEW)-ARRAY['recipient_contact_id','inbound_message_id','inbound_provider_at','received_at','cancelled_at'])
 IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['recipient_contact_id','inbound_message_id','inbound_provider_at','received_at','cancelled_at']) THEN
 RAISE EXCEPTION 'Test identity is immutable' USING ERRCODE='23514'; END IF;
 IF OLD.cancelled_at IS NOT NULL AND NEW.cancelled_at IS DISTINCT FROM OLD.cancelled_at THEN
 RAISE EXCEPTION 'Test cancellation is one way' USING ERRCODE='23514'; END IF;
 IF OLD.inbound_message_id IS NOT NULL AND ROW(NEW.recipient_contact_id,NEW.inbound_message_id,NEW.inbound_provider_at,NEW.received_at)
 IS DISTINCT FROM ROW(OLD.recipient_contact_id,OLD.inbound_message_id,OLD.inbound_provider_at,OLD.received_at) THEN
 RAISE EXCEPTION 'Test recipient proof is immutable' USING ERRCODE='23514'; END IF;
 IF OLD.inbound_message_id IS NULL AND NEW.inbound_message_id IS NOT NULL THEN
 IF NEW.cancelled_at IS NOT NULL THEN RAISE EXCEPTION 'Cancelled test cannot receive proof' USING ERRCODE='23514'; END IF;
 SELECT * INTO inbound FROM whatsapp_messages WHERE id=NEW.inbound_message_id AND seller_id=NEW.business_id;
 IF NOT FOUND OR inbound.direction<>'inbound' OR inbound.kind<>'text'
 OR inbound.contact_id<>NEW.recipient_contact_id OR inbound.phone_number_id<>NEW.phone_number_id
 OR coalesce(inbound.provider_message_id,'')='' OR inbound.text<>'WhatsApp connection-test command (redacted)'
 OR inbound.payload<>'{}'::jsonb OR inbound.created_at<>NEW.inbound_provider_at THEN
 RAISE EXCEPTION 'Canonical redacted inbound proof required' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END; $$""")
    op.execute("""CREATE FUNCTION wa_test_authorization_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE test whatsapp_connection_tests%ROWTYPE; message whatsapp_messages%ROWTYPE;
BEGIN
 SELECT * INTO test FROM whatsapp_connection_tests WHERE id=NEW.test_id AND business_id=NEW.business_id;
 IF NOT FOUND OR test.cancelled_at IS NOT NULL OR NEW.authorized_at<test.received_at OR NEW.authorized_at>test.expires_at
 OR ROW(NEW.actor_user_id,NEW.actor_session_id,NEW.actor_auth_version,NEW.connection_version,NEW.phone_number_id,NEW.recipient_contact_id,NEW.inbound_message_id)
 IS DISTINCT FROM ROW(test.actor_user_id,test.actor_session_id,test.actor_auth_version,test.connection_version,test.phone_number_id,test.recipient_contact_id,test.inbound_message_id)
 OR test.inbound_message_id IS NULL THEN
 RAISE EXCEPTION 'Exact owner and recipient proof required' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS (SELECT 1 FROM channel_connection_states c JOIN whatsapp_accounts a ON a.seller_id=c.business_id
 JOIN whatsapp_authorization_provenance p ON p.business_id=c.business_id AND p.connection_version=c.version
 WHERE c.business_id=NEW.business_id AND c.channel='whatsapp' AND c.version=NEW.connection_version
 AND a.phone_number_id=NEW.phone_number_id AND p.phone_number_id=a.phone_number_id AND p.waba_id=a.waba_id
 AND (p.token_expiry_kind='permanent' OR p.token_expiry_kind='at' AND p.token_expires_at>NEW.authorized_at)) THEN
 RAISE EXCEPTION 'Current verified account authorization required' USING ERRCODE='23514'; END IF;
 SELECT * INTO message FROM whatsapp_messages WHERE id=NEW.outbound_message_id AND seller_id=NEW.business_id;
 IF NOT FOUND OR message.direction<>'outbound' OR message.kind<>'text' OR message.status<>'queued'
 OR message.contact_id<>NEW.recipient_contact_id OR message.phone_number_id<>NEW.phone_number_id
 OR message.text<>'This is a WhatsApp connection test from your business. No reply is required.'
 OR message.payload<>'{}'::jsonb OR message.provider_message_id IS NOT NULL THEN
 RAISE EXCEPTION 'Exact fixed canonical outbound required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END; $$""")
    op.execute("""CREATE FUNCTION wa_test_message_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS (SELECT 1 FROM whatsapp_test_authorizations WHERE outbound_message_id=OLD.id)
 OR EXISTS (SELECT 1 FROM whatsapp_connection_tests WHERE inbound_message_id=OLD.id) THEN
 IF TG_OP='DELETE' OR (to_jsonb(NEW)-ARRAY['provider_message_id','status','error','updated_at'])
 IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['provider_message_id','status','error','updated_at']) THEN
 RAISE EXCEPTION 'Bound test message identity is immutable' USING ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END; $$""")
    op.execute("""CREATE FUNCTION wa_choice_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM whatsapp_signup_attempts a WHERE a.id=NEW.attempt_id AND a.business_id=NEW.business_id
 AND a.state='awaiting_assets' AND a.verified_app_id IS NOT NULL AND a.provisional_token_ciphertext IS NOT NULL
 AND NEW.verified_at BETWEEN a.created_at AND a.expires_at) THEN
 RAISE EXCEPTION 'Choice requires current verified signup' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END; $$""")
    op.execute("""CREATE FUNCTION wa_provenance_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM whatsapp_signup_attempts a JOIN whatsapp_signup_choices choice ON choice.id=a.selected_choice_id
 JOIN whatsapp_accounts account ON account.seller_id=a.business_id
 JOIN channel_connection_states control ON control.business_id=a.business_id AND control.channel='whatsapp'
 WHERE a.id=NEW.attempt_id AND a.business_id=NEW.business_id AND a.state='setting_up'
 AND a.subscription_state='confirmed' AND a.registration_state='confirmed'
 AND ROW(a.actor_user_id,a.actor_session_id,a.actor_auth_version,a.verified_app_id,a.token_expiry_kind,a.token_expires_at,a.evidence_kind)
 IS NOT DISTINCT FROM ROW(NEW.actor_user_id,NEW.actor_session_id,NEW.actor_auth_version,NEW.verified_app_id,NEW.token_expiry_kind,NEW.token_expires_at,NEW.evidence_kind)
 AND NEW.connection_version=a.connection_version+1 AND control.version=NEW.connection_version
 AND NEW.phone_number_id=choice.phone_number_id AND NEW.waba_id=choice.waba_id
 AND account.phone_number_id=choice.phone_number_id AND account.waba_id=choice.waba_id
 AND NOT account.enabled AND NOT account.automation_enabled AND NEW.verified_at BETWEEN choice.verified_at AND a.expires_at) THEN
 RAISE EXCEPTION 'Exact paused signup attachment required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END; $$""")
    for table in ('whatsapp_signup_attempts','whatsapp_connection_tests'):
        op.execute('CREATE TRIGGER wa_self_initial BEFORE INSERT ON '+table+' FOR EACH ROW EXECUTE FUNCTION wa_self_initial_guard()')
    op.execute('CREATE TRIGGER wa_choice_guard BEFORE INSERT ON whatsapp_signup_choices FOR EACH ROW EXECUTE FUNCTION wa_choice_guard()')
    op.execute('CREATE TRIGGER wa_provenance_guard BEFORE INSERT ON whatsapp_authorization_provenance FOR EACH ROW EXECUTE FUNCTION wa_provenance_guard()')
    for table in ('whatsapp_signup_attempts','whatsapp_authorization_provenance' ,'whatsapp_connection_tests','whatsapp_test_authorizations'):
        op.execute('CREATE TRIGGER wa_self_actor BEFORE INSERT ON '+table+' FOR EACH ROW EXECUTE FUNCTION wa_self_actor_guard()')
    for table in ('whatsapp_signup_choices','whatsapp_authorization_provenance','whatsapp_test_authorizations'):
        op.execute('CREATE TRIGGER wa_self_immutable BEFORE UPDATE OR DELETE ON '+table+' FOR EACH ROW EXECUTE FUNCTION wa_self_immutable()')
    op.execute('CREATE TRIGGER wa_signup_guard BEFORE UPDATE OR DELETE ON whatsapp_signup_attempts FOR EACH ROW EXECUTE FUNCTION wa_signup_guard()')
    op.execute('CREATE TRIGGER wa_test_guard BEFORE UPDATE OR DELETE ON whatsapp_connection_tests FOR EACH ROW EXECUTE FUNCTION wa_test_guard()')
    op.execute('CREATE TRIGGER wa_test_authorization_guard BEFORE INSERT ON whatsapp_test_authorizations FOR EACH ROW EXECUTE FUNCTION wa_test_authorization_guard()')
    op.execute('CREATE TRIGGER wa_test_message_guard BEFORE UPDATE OR DELETE ON whatsapp_messages FOR EACH ROW EXECUTE FUNCTION wa_test_message_guard()')
