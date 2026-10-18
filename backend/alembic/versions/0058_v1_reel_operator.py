"""Immutable one-source native reel review and canonical outbox authorization."""
from alembic import op
revision = '0058_v1_reel_operator'
down_revision = '0057_v1_whatsapp_self_service'
branch_labels = depends_on = None

DDL = (
"""CREATE TABLE whatsapp_reel_commands (
 id UUID PRIMARY KEY, business_id UUID NOT NULL REFERENCES businesses(id),
 actor_user_id UUID NOT NULL REFERENCES users(id), actor_session_id UUID NOT NULL REFERENCES user_sessions(id),
 actor_auth_version INTEGER NOT NULL, idempotency_key UUID NOT NULL, action VARCHAR(24) NOT NULL,
 request_hash VARCHAR(64) NOT NULL, inbound_message_id UUID NOT NULL, contact_id UUID NOT NULL,
 phone_number_id VARCHAR(40) NOT NULL, waba_id VARCHAR(40) NOT NULL, provider_mid VARCHAR(255) NOT NULL,
 source_classification VARCHAR(24) NOT NULL, source_fingerprint VARCHAR(64) NOT NULL,
 quoted_message_id UUID REFERENCES whatsapp_messages(id), quoted_fingerprint VARCHAR(64),
 shortcode VARCHAR(100) NOT NULL, source_url VARCHAR(300) NOT NULL, product_id UUID NOT NULL,
 connection_version INTEGER NOT NULL, credential_fingerprint VARCHAR(64) NOT NULL,
 expected_fingerprint VARCHAR(64) NOT NULL, expected_mapping_fingerprint VARCHAR(64) NOT NULL,
 accepted_mapping_fingerprint VARCHAR(64) NOT NULL, reply_context JSONB NOT NULL, result JSONB NOT NULL,
 created_at TIMESTAMPTZ DEFAULT clock_timestamp() NOT NULL,
 CONSTRAINT wa_reel_command_key UNIQUE(business_id,idempotency_key),
 CONSTRAINT wa_reel_command_tenant UNIQUE(business_id,id),
 CONSTRAINT wa_reel_command_member FOREIGN KEY(business_id,actor_user_id) REFERENCES memberships(business_id,user_id),
 CONSTRAINT wa_reel_command_source FOREIGN KEY(business_id,inbound_message_id,contact_id,phone_number_id)
 REFERENCES whatsapp_messages(seller_id,id,contact_id,phone_number_id),
 CONSTRAINT wa_reel_command_product FOREIGN KEY(business_id,product_id) REFERENCES products(seller_id,id),
 CONSTRAINT wa_reel_command_action CHECK(action IN ('link_only','link_and_resume')),
 CONSTRAINT wa_reel_command_class CHECK(source_classification IN ('message_link','referral_link','quoted_message','recent_message')),
 CONSTRAINT wa_reel_command_versions CHECK(actor_auth_version>=0 AND connection_version>=0),
 CONSTRAINT wa_reel_command_reference CHECK(shortcode ~ '^[A-Za-z0-9_-]{1,100}$' AND length(provider_mid) BETWEEN 1 AND 255),
 CONSTRAINT wa_reel_command_hashes CHECK(request_hash ~ '^[a-f0-9]{64}$' AND source_fingerprint ~ '^[a-f0-9]{64}$'
 AND credential_fingerprint ~ '^[a-f0-9]{64}$' AND expected_fingerprint ~ '^[a-f0-9]{64}$'
 AND expected_mapping_fingerprint ~ '^[a-f0-9]{64}$' AND accepted_mapping_fingerprint ~ '^[a-f0-9]{64}$'),
 CONSTRAINT wa_reel_command_quote CHECK((quoted_message_id IS NULL AND quoted_fingerprint IS NULL)
 OR (quoted_message_id IS NOT NULL AND quoted_fingerprint ~ '^[a-f0-9]{64}$')),
 CONSTRAINT wa_reel_command_context CHECK(jsonb_typeof(reply_context)='object' AND octet_length(reply_context::text)<=4096),
 CONSTRAINT wa_reel_command_result CHECK(coalesce(jsonb_typeof(result)='object' AND octet_length(result::text)<=2048
 AND result ?& ARRAY['mapping','resume','reason','outbound_id','mapping_fingerprint']
 AND result-ARRAY['mapping','resume','reason','outbound_id','mapping_fingerprint']='{}'::jsonb
 AND result->>'mapping'='saved' AND result->>'resume' IN ('queued','held','not_requested')
 AND ((result->>'resume'='queued' AND result->'reason'='null'::jsonb)
 OR (result->>'resume'<>'queued' AND result->>'reason' ~ '^[a-z_]{1,80}$'))
 AND result->>'mapping_fingerprint'=accepted_mapping_fingerprint
 AND ((result->>'resume'='queued' AND result->>'outbound_id' ~ '^[a-f0-9-]{36}$')
 OR (result->>'resume'<>'queued' AND result->'outbound_id'='null'::jsonb)),false))
)""",
"""CREATE TABLE whatsapp_reel_authorizations (
 command_id UUID PRIMARY KEY, business_id UUID NOT NULL, inbound_message_id UUID NOT NULL,
 contact_id UUID NOT NULL, phone_number_id VARCHAR(40) NOT NULL, outbound_message_id UUID NOT NULL,
 CONSTRAINT wa_reel_auth_command FOREIGN KEY(business_id,command_id) REFERENCES whatsapp_reel_commands(business_id,id),
 CONSTRAINT wa_reel_auth_source FOREIGN KEY(business_id,inbound_message_id,contact_id,phone_number_id)
 REFERENCES whatsapp_messages(seller_id,id,contact_id,phone_number_id),
 CONSTRAINT wa_reel_auth_outbound FOREIGN KEY(business_id,outbound_message_id,contact_id,phone_number_id)
 REFERENCES whatsapp_messages(seller_id,id,contact_id,phone_number_id),
 CONSTRAINT wa_reel_auth_outbound_once UNIQUE(business_id,outbound_message_id),
 CONSTRAINT wa_reel_auth_source_once UNIQUE(business_id,inbound_message_id)
)""",
"""CREATE FUNCTION wa_reel_source_fingerprint(payload jsonb, body text, kind text, stamp timestamptz,
 mid text, contact uuid, phone text) RETURNS text LANGUAGE sql STABLE AS $$
 SELECT encode(sha256(convert_to(jsonb_build_object('payload',payload,'text',body,'kind',kind,'created_at',to_char(stamp AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US'),
 'provider_mid',mid,'contact_id',contact,'phone_number_id',phone)::text,'UTF8')),'hex') $$""",
"""CREATE FUNCTION wa_reel_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'Native reel review history is immutable' USING ERRCODE='23514'; END; $$""",
"""CREATE FUNCTION wa_reel_command_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM user_sessions s JOIN users u ON u.id=s.user_id
 JOIN memberships m ON m.user_id=u.id AND m.business_id=NEW.business_id
 JOIN businesses b ON b.id=m.business_id JOIN sellers seller ON seller.id=b.id
 WHERE s.id=NEW.actor_session_id AND u.id=NEW.actor_user_id
 AND s.auth_version=NEW.actor_auth_version AND u.auth_version=NEW.actor_auth_version
 AND s.revoked_at IS NULL AND s.expires_at>clock_timestamp() AND u.is_active AND u.revoked_at IS NULL
 AND m.is_active AND m.revoked_at IS NULL AND m.role IN ('owner','manager') AND b.is_active AND seller.is_active) THEN
 RAISE EXCEPTION 'Current native reviewer session required' USING ERRCODE='23514'; END IF;
 IF NOT EXISTS (SELECT 1 FROM whatsapp_messages src JOIN whatsapp_accounts a ON a.seller_id=src.seller_id
 JOIN channel_connection_states control ON control.business_id=a.seller_id AND control.channel='whatsapp'
 JOIN products p ON p.seller_id=src.seller_id AND p.id=NEW.product_id
 WHERE src.id=NEW.inbound_message_id AND src.seller_id=NEW.business_id AND src.contact_id=NEW.contact_id
 AND src.phone_number_id=NEW.phone_number_id AND src.direction='inbound' AND src.provider_message_id=NEW.provider_mid
 AND src.payload->'reel_context'->>'source'=NEW.source_classification
 AND jsonb_array_length(src.payload->'reel_context'->'references')=1
 AND src.payload->'reel_context'->'references'->0->>'shortcode'=NEW.shortcode
 AND src.payload->'reel_context'->'references'->0->>'url'=NEW.source_url
 AND NEW.source_url ~ ('^https://www[.]instagram[.]com/(reel|p|tv)/' || NEW.shortcode || '/$')
 AND wa_reel_source_fingerprint(src.payload,src.text,src.kind,src.created_at,src.provider_message_id,src.contact_id,src.phone_number_id)=NEW.source_fingerprint
 AND a.phone_number_id=NEW.phone_number_id AND a.waba_id=NEW.waba_id AND control.version=NEW.connection_version
 AND encode(sha256(convert_to(a.access_token,'UTF8')),'hex')=NEW.credential_fingerprint
 AND p.active AND encode(sha256(convert_to(coalesce(p.reel_urls,'[]'::jsonb)::text,'UTF8')),'hex')=NEW.accepted_mapping_fingerprint
 AND NEW.created_at BETWEEN transaction_timestamp() AND clock_timestamp()) THEN
 RAISE EXCEPTION 'Exact reviewed source/account/product required' USING ERRCODE='23514'; END IF;
 RETURN NEW; END; $$""",
"""CREATE FUNCTION wa_reel_authorization_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM whatsapp_reel_commands c
 JOIN whatsapp_messages src ON src.seller_id=c.business_id AND src.id=c.inbound_message_id
 JOIN whatsapp_messages dst ON dst.seller_id=c.business_id AND dst.id=NEW.outbound_message_id
 WHERE c.id=NEW.command_id AND c.business_id=NEW.business_id AND c.action='link_and_resume'
 AND ROW(c.inbound_message_id,c.contact_id,c.phone_number_id)=ROW(NEW.inbound_message_id,NEW.contact_id,NEW.phone_number_id)
 AND c.source_classification IN ('message_link','referral_link','quoted_message')
 AND c.result->>'resume'='queued' AND c.result->>'outbound_id'=NEW.outbound_message_id::text
 AND dst.direction='outbound' AND dst.kind='text' AND dst.status='queued' AND dst.provider_message_id IS NULL
 AND dst.contact_id=c.contact_id AND dst.phone_number_id=c.phone_number_id
 AND dst.idempotency_key='auto:reel:' || c.provider_mid
 AND dst.payload=jsonb_build_object('reel_context',c.reply_context,'customer_text',src.text)
 AND dst.created_at>=c.created_at AND dst.xmin=pg_current_xact_id()::text::xid
 AND NOT EXISTS (SELECT 1 FROM whatsapp_messages previous WHERE previous.seller_id=c.business_id
 AND previous.contact_id=c.contact_id AND previous.direction='outbound' AND previous.id<>dst.id AND previous.created_at>=src.created_at)) THEN
 RAISE EXCEPTION 'Exact new canonical reviewed outbound required' USING ERRCODE='23514'; END IF;
 RETURN NEW; END; $$""",
"""CREATE FUNCTION wa_reel_message_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF EXISTS(SELECT 1 FROM whatsapp_reel_commands WHERE inbound_message_id=OLD.id OR quoted_message_id=OLD.id) THEN
 IF TG_OP='DELETE' OR (to_jsonb(NEW)-ARRAY['status','error','updated_at']) IS DISTINCT FROM
 (to_jsonb(OLD)-ARRAY['status','error','updated_at']) THEN
 RAISE EXCEPTION 'Reviewed inbound source is immutable' USING ERRCODE='23514'; END IF; END IF;
 IF EXISTS(SELECT 1 FROM whatsapp_reel_authorizations WHERE outbound_message_id=OLD.id) THEN
 IF TG_OP='DELETE' OR (to_jsonb(NEW)-ARRAY['text','provider_message_id','status','error','updated_at']) IS DISTINCT FROM
 (to_jsonb(OLD)-ARRAY['text','provider_message_id','status','error','updated_at']) THEN
 RAISE EXCEPTION 'Reviewed outbound association is immutable' USING ERRCODE='23514'; END IF;
 IF OLD.provider_message_id IS NOT NULL AND NEW.provider_message_id IS DISTINCT FROM OLD.provider_message_id THEN
 RAISE EXCEPTION 'Reviewed provider receipt is one way' USING ERRCODE='23514'; END IF; END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW; END; $$""",
)


def upgrade():
    for statement in DDL:
        op.execute(statement)
    for table in ('whatsapp_reel_commands','whatsapp_reel_authorizations'):
        op.execute('CREATE TRIGGER wa_reel_immutable BEFORE UPDATE OR DELETE ON '+table+' FOR EACH ROW EXECUTE FUNCTION wa_reel_immutable()')
    op.execute('CREATE TRIGGER wa_reel_command_guard BEFORE INSERT ON whatsapp_reel_commands FOR EACH ROW EXECUTE FUNCTION wa_reel_command_guard()')
    op.execute('CREATE TRIGGER wa_reel_authorization_guard BEFORE INSERT ON whatsapp_reel_authorizations FOR EACH ROW EXECUTE FUNCTION wa_reel_authorization_guard()')
    op.execute('CREATE TRIGGER wa_reel_message_guard BEFORE UPDATE OR DELETE ON whatsapp_messages FOR EACH ROW EXECUTE FUNCTION wa_reel_message_guard()')


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM whatsapp_reel_commands) OR EXISTS(SELECT 1 FROM whatsapp_reel_authorizations)
    THEN RAISE EXCEPTION 'Native review history requires a forward fix' USING ERRCODE='23514'; END IF; END; $$""")
    op.execute('DROP TRIGGER wa_reel_message_guard ON whatsapp_messages')
    op.drop_table('whatsapp_reel_authorizations')
    op.drop_table('whatsapp_reel_commands')
    for function in ('wa_reel_command_guard()','wa_reel_authorization_guard()','wa_reel_message_guard()','wa_reel_immutable()',
                     'wa_reel_source_fingerprint(jsonb,text,text,timestamptz,text,uuid,text)'):
        op.execute('DROP FUNCTION '+function)
