"""Owner-consented first-party activity and immutable order test provenance.

Raw measurement data is bounded to 90 days; lifetime order classification stays
separate. There is no customer/provider payload and no historical backfill.
"""
from alembic import op
revision='0054_v1_activity'
down_revision='0053_v1_csv_import'
branch_labels=depends_on=None

DDL=(
    "CREATE TABLE v1_activity_policies (\n\tbusiness_id UUID NOT NULL, \n\tmode VARCHAR(8) NOT NULL, \n\trevision INTEGER NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\tPRIMARY KEY (business_id), \n\tCONSTRAINT v1_activity_policy_value CHECK (mode IN ('off','test','live') AND revision>=1), \n\tFOREIGN KEY(business_id) REFERENCES businesses (id)\n)",
    "CREATE TABLE v1_activity_policy_commands (\n\tbusiness_id UUID NOT NULL, \n\tidempotency_key UUID NOT NULL, \n\tactor_user_id UUID NOT NULL, \n\trequest_hash VARCHAR(64) NOT NULL, \n\tmode VARCHAR(8) NOT NULL, \n\trevision INTEGER NOT NULL, \n\tnotice_version VARCHAR(30) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\tPRIMARY KEY (business_id, idempotency_key), \n\tCONSTRAINT v1_activity_command_value CHECK (mode IN ('off','test','live') AND revision>=1 AND notice_version='first-party.v1'), \n\tCONSTRAINT v1_activity_command_hash CHECK (request_hash ~ '^[a-f0-9]{64}$'), \n\tCONSTRAINT v1_activity_command_actor_tenant FOREIGN KEY(business_id, actor_user_id) REFERENCES memberships (business_id, user_id), \n\tCONSTRAINT v1_activity_policy_revision UNIQUE (business_id, revision), \n\tFOREIGN KEY(business_id) REFERENCES businesses (id), \n\tFOREIGN KEY(actor_user_id) REFERENCES users (id)\n)",
    'CREATE INDEX v1_activity_policy_history ON v1_activity_policy_commands (business_id, created_at)',
    "CREATE TABLE v1_activity_contexts (\n\tid UUID NOT NULL, \n\tbusiness_id UUID NOT NULL, \n\tidempotency_key UUID NOT NULL, \n\tclassification VARCHAR(8) NOT NULL, \n\treason VARCHAR(32) NOT NULL, \n\tpolicy_revision INTEGER NOT NULL, \n\tstarted_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tretained_until TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlossy BOOLEAN DEFAULT 'false' NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT v1_activity_context_tenant UNIQUE (business_id, id), \n\tCONSTRAINT v1_activity_context_once UNIQUE (business_id, idempotency_key), \n\tCONSTRAINT v1_activity_context_class CHECK (classification IN ('live','test','unknown')), \n\tCONSTRAINT v1_activity_context_policy FOREIGN KEY(business_id, policy_revision) REFERENCES v1_activity_policy_commands (business_id, revision), \n\tCONSTRAINT v1_activity_context_class_reason CHECK ((classification='live' AND reason='live_policy') OR (classification='test' AND reason IN ('policy_test','native_context','nonproduction')) OR (classification='unknown' AND reason='unproven')), \n\tCONSTRAINT v1_activity_context_reason CHECK (reason IN ('live_policy','policy_test','native_context','nonproduction','unproven') AND policy_revision>=1), \n\tCONSTRAINT v1_activity_context_window CHECK (expires_at=started_at+interval '30 minutes' AND retained_until=started_at+interval '2160 hours'), \n\tFOREIGN KEY(business_id) REFERENCES businesses (id)\n)",
    'CREATE INDEX v1_activity_context_cohort ON v1_activity_contexts (business_id, classification, started_at)',
    'CREATE INDEX v1_activity_context_retention ON v1_activity_contexts (retained_until)',
    "CREATE TABLE v1_activity_events (\n\tid UUID NOT NULL, \n\tbusiness_id UUID NOT NULL, \n\tcontext_id UUID NOT NULL, \n\tevent_kind VARCHAR(24) NOT NULL, \n\tproduct_id UUID, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT v1_activity_event_context FOREIGN KEY(business_id, context_id) REFERENCES v1_activity_contexts (business_id, id) ON DELETE CASCADE, \n\tCONSTRAINT v1_activity_event_product FOREIGN KEY(business_id, product_id) REFERENCES products (seller_id, id), \n\tCONSTRAINT v1_activity_event_shape CHECK ((event_kind='product_view' AND product_id IS NOT NULL) OR (event_kind='checkout_opened' AND product_id IS NULL)), \n\tCONSTRAINT v1_activity_event_once UNIQUE NULLS NOT DISTINCT (context_id, event_kind, product_id)\n)",
    'CREATE INDEX v1_activity_event_read ON v1_activity_events (business_id, context_id)',
    "CREATE TABLE v1_activity_gaps (\n\tbusiness_id UUID NOT NULL, \n\tclassification VARCHAR(8) NOT NULL, \n\tminute TIMESTAMP WITH TIME ZONE NOT NULL, \n\treason VARCHAR(24) NOT NULL, \n\tPRIMARY KEY (business_id, classification, minute, reason), \n\tCONSTRAINT v1_activity_gap_class CHECK (classification IN ('live','test','unknown')), \n\tCONSTRAINT v1_activity_gap_reason CHECK (reason IN ('context_capacity','event_capacity') AND date_trunc('minute',minute)=minute), \n\tFOREIGN KEY(business_id) REFERENCES businesses (id)\n)",
    'CREATE INDEX v1_activity_gap_retention ON v1_activity_gaps (minute)',
    "CREATE TABLE v1_order_activity (\n\torder_id UUID NOT NULL, \n\tbusiness_id UUID NOT NULL, \n\tclassification VARCHAR(8) NOT NULL, \n\treason VARCHAR(32) NOT NULL, \n\tcontext_id UUID, \n\taccepted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (order_id), \n\tCONSTRAINT v1_activity_order_tenant FOREIGN KEY(business_id, order_id) REFERENCES commerce_orders (seller_id, id), \n\tCONSTRAINT v1_activity_order_class CHECK (classification IN ('live','test','unknown')), \n\tCONSTRAINT v1_activity_order_reason CHECK (reason IN ('live_context','test_context','nonproduction','gateway_test','unproven_context','tracking_disabled')), \n\tCONSTRAINT v1_activity_order_class_reason CHECK ((classification='live' AND reason='live_context') OR (classification='test' AND reason IN ('test_context','nonproduction','gateway_test')) OR (classification='unknown' AND reason IN ('unproven_context','tracking_disabled'))), \n\tCONSTRAINT v1_activity_order_live_link CHECK ((reason IN ('live_context','test_context'))=(context_id IS NOT NULL))\n)",
    'CREATE INDEX v1_activity_order_cohort ON v1_order_activity (business_id, classification, accepted_at)',
    'CREATE INDEX v1_activity_order_context ON v1_order_activity (business_id, context_id)',
    "CREATE TABLE v1_activity_sources (\n\tbusiness_id UUID NOT NULL, \n\tsource_kind VARCHAR(24) NOT NULL, \n\tsource_id UUID NOT NULL, \n\tclassification VARCHAR(8) NOT NULL, \n\torigin VARCHAR(16) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, \n\tretained_until TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (business_id, source_kind, source_id), \n\tCONSTRAINT v1_activity_source_class CHECK (classification IN ('live','test','unknown')), \n\tCONSTRAINT v1_activity_source_kind CHECK (source_kind IN ('instagram_ingress','wa_inbound','wa_outbound','comment_action') AND origin IN ('inbound','automated','operator','unknown')), \n\tCONSTRAINT v1_activity_source_retention CHECK (retained_until=created_at+interval '2160 hours'), \n\tCONSTRAINT v1_activity_source_origin CHECK ((source_kind IN ('instagram_ingress','wa_inbound') AND origin IN ('inbound','unknown')) OR (source_kind IN ('wa_outbound','comment_action') AND origin IN ('automated','operator','unknown'))), \n\tCONSTRAINT v1_activity_source_unknown CHECK (origin<>'unknown' OR classification='unknown'), \n\tFOREIGN KEY(business_id) REFERENCES businesses (id)\n)",
    'CREATE INDEX v1_activity_source_cohort ON v1_activity_sources (business_id, classification, created_at)',
    'CREATE INDEX v1_activity_source_expiry ON v1_activity_sources (retained_until)',
)

GUARDS=(
    """CREATE FUNCTION v1_activity_policy_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP='INSERT' AND NEW.revision=1 THEN RETURN NEW; END IF;
      IF TG_OP='UPDATE' AND NEW.business_id=OLD.business_id AND NEW.revision=OLD.revision+1 AND NEW.updated_at>=OLD.updated_at THEN RETURN NEW; END IF;
      RAISE EXCEPTION 'Activity policy history must be preserved' USING ERRCODE='23514'; END; $$""",
    """CREATE TRIGGER v1_activity_policy_guard BEFORE INSERT OR UPDATE OR DELETE ON v1_activity_policies FOR EACH ROW EXECUTE FUNCTION v1_activity_policy_guard()""",
    """CREATE FUNCTION v1_activity_command_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      RAISE EXCEPTION 'Activity policy receipts are immutable' USING ERRCODE='23514'; END; $$""",
    """CREATE TRIGGER v1_activity_command_guard BEFORE UPDATE OR DELETE ON v1_activity_policy_commands FOR EACH ROW EXECUTE FUNCTION v1_activity_command_guard()""",
    """CREATE FUNCTION v1_activity_context_guard() RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE policy_mode text; policy_at timestamptz; BEGIN
      IF TG_OP='INSERT' THEN
        SELECT mode,created_at INTO policy_mode,policy_at FROM v1_activity_policy_commands WHERE business_id=NEW.business_id AND revision=NEW.policy_revision;
        IF policy_mode IN ('test','live') AND NEW.started_at>=policy_at AND NEW.started_at<=clock_timestamp() AND (NEW.classification<>'live' OR policy_mode='live') THEN RETURN NEW; END IF;
      ELSIF TG_OP='DELETE' THEN
        IF OLD.retained_until<=clock_timestamp() THEN RETURN OLD; END IF;
      ELSIF TG_OP='UPDATE' AND OLD.lossy=false AND NEW.lossy=true AND (to_jsonb(NEW)-'lossy')=(to_jsonb(OLD)-'lossy') THEN RETURN NEW;
      END IF;
      RAISE EXCEPTION 'Activity context classification is immutable until retention expiry' USING ERRCODE='23514'; END; $$""",
    """CREATE TRIGGER v1_activity_context_guard BEFORE INSERT OR UPDATE OR DELETE ON v1_activity_contexts FOR EACH ROW EXECUTE FUNCTION v1_activity_context_guard()""",
    """CREATE FUNCTION v1_activity_event_guard() RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE until_at timestamptz; start_at timestamptz; expire_at timestamptz; BEGIN
      IF TG_OP='INSERT' THEN
        SELECT started_at,expires_at INTO start_at,expire_at FROM v1_activity_contexts WHERE id=NEW.context_id AND business_id=NEW.business_id FOR UPDATE;
        IF start_at IS NOT NULL AND NEW.created_at>=start_at AND NEW.created_at<expire_at AND NEW.created_at<=clock_timestamp() THEN RETURN NEW; END IF;
      ELSIF TG_OP='DELETE' THEN
        SELECT retained_until INTO until_at FROM v1_activity_contexts WHERE id=OLD.context_id AND business_id=OLD.business_id;
        IF until_at IS NULL OR until_at<=clock_timestamp() THEN RETURN OLD; END IF;
      END IF;
      RAISE EXCEPTION 'Activity events are immutable until retention expiry' USING ERRCODE='23514'; END; $$""",
    """CREATE TRIGGER v1_activity_event_guard BEFORE INSERT OR UPDATE OR DELETE ON v1_activity_events FOR EACH ROW EXECUTE FUNCTION v1_activity_event_guard()""",
    """CREATE FUNCTION v1_activity_order_guard() RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE context_class text; BEGIN
      IF TG_OP='INSERT' THEN
        IF NOT EXISTS(SELECT 1 FROM commerce_orders WHERE id=NEW.order_id AND seller_id=NEW.business_id AND created_at=NEW.accepted_at) THEN
          RAISE EXCEPTION 'Activity order tenant/time mismatch' USING ERRCODE='23514'; END IF;
        IF NEW.context_id IS NULL THEN RETURN NEW; END IF;
        SELECT classification INTO context_class FROM v1_activity_contexts WHERE id=NEW.context_id AND business_id=NEW.business_id AND started_at<=NEW.accepted_at AND expires_at>NEW.accepted_at;
        IF context_class=NEW.classification THEN RETURN NEW; END IF;
      END IF;
      RAISE EXCEPTION 'Order activity provenance is immutable and tenant bound' USING ERRCODE='23514'; END; $$""",
    """CREATE TRIGGER v1_activity_order_guard BEFORE INSERT OR UPDATE OR DELETE ON v1_order_activity FOR EACH ROW EXECUTE FUNCTION v1_activity_order_guard()""",
    """CREATE FUNCTION v1_activity_source_guard() RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE source_time timestamptz; BEGIN
      IF TG_OP='DELETE' AND OLD.retained_until<=clock_timestamp() THEN RETURN OLD; END IF;
      IF TG_OP='INSERT' THEN
        CASE NEW.source_kind
          WHEN 'instagram_ingress' THEN SELECT created_at INTO source_time FROM instagram_ingress WHERE id=NEW.source_id AND seller_id=NEW.business_id AND NULLIF(provider_message_id,'') IS NOT NULL;
          WHEN 'wa_inbound' THEN SELECT created_at INTO source_time FROM whatsapp_messages WHERE id=NEW.source_id AND seller_id=NEW.business_id AND direction='inbound' AND NULLIF(provider_message_id,'') IS NOT NULL;
          WHEN 'wa_outbound' THEN SELECT created_at INTO source_time FROM whatsapp_messages WHERE id=NEW.source_id AND seller_id=NEW.business_id AND direction='outbound';
          WHEN 'comment_action' THEN SELECT a.created_at INTO source_time FROM comment_actions a JOIN comment_events e ON e.id=a.event_id AND e.seller_id=a.seller_id WHERE a.id=NEW.source_id AND a.seller_id=NEW.business_id;
          ELSE source_time:=NULL;
        END CASE;
        IF source_time IS NOT NULL AND source_time=NEW.created_at THEN RETURN NEW; END IF;
      END IF;
      RAISE EXCEPTION 'Activity source provenance is immutable and tenant bound' USING ERRCODE='23514'; END; $$""",
    """CREATE TRIGGER v1_activity_source_guard BEFORE INSERT OR UPDATE OR DELETE ON v1_activity_sources FOR EACH ROW EXECUTE FUNCTION v1_activity_source_guard()""",
    """CREATE FUNCTION v1_activity_gap_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      IF TG_OP='DELETE' AND OLD.minute+interval '2160 hours'<=clock_timestamp() THEN RETURN OLD; END IF;
      RAISE EXCEPTION 'Activity gap evidence must survive its retention window' USING ERRCODE='23514'; END; $$""",
    """CREATE TRIGGER v1_activity_gap_guard BEFORE UPDATE OR DELETE ON v1_activity_gaps FOR EACH ROW EXECUTE FUNCTION v1_activity_gap_guard()""",
)


def upgrade():
    for statement in (*DDL,*GUARDS):op.execute(statement)


def downgrade():
    # Routine application rollback does not erase post-cutover measurement or
    # lifetime order provenance. Empty pre-use rollback only, no forced cleanup.
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM v1_activity_policy_commands)
      OR EXISTS(SELECT 1 FROM v1_order_activity) OR EXISTS(SELECT 1 FROM v1_activity_contexts)
      OR EXISTS(SELECT 1 FROM v1_activity_sources) OR EXISTS(SELECT 1 FROM v1_activity_gaps)
      OR EXISTS(SELECT 1 FROM v1_activity_policies) THEN
      RAISE EXCEPTION 'Activity data requires a forward-compatible repair' USING ERRCODE='23514'; END IF; END; $$""")
    for name in ('v1_activity_sources','v1_order_activity','v1_activity_gaps','v1_activity_events','v1_activity_contexts','v1_activity_policy_commands','v1_activity_policies'):
        op.drop_table(name)
    for name in ('policy','command','context','event','order','source','gap'):
        op.execute(f'DROP FUNCTION v1_activity_{name}_guard()')
