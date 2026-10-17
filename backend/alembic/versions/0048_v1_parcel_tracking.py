"""Existing-parcel associations and immutable tracking observations; no backfill."""
from alembic import op
revision='0048_v1_parcel_tracking'
down_revision='0047_v1_import_catalogue_bridge'
branch_labels=None
depends_on=None
DDL="""
CREATE TABLE v1_parcel_connectors (
 id UUID PRIMARY KEY,business_id UUID NOT NULL UNIQUE REFERENCES businesses(id),
 instance_id UUID NOT NULL UNIQUE,origin VARCHAR(300) NOT NULL,credential_ref VARCHAR(64) NOT NULL,
 enabled BOOLEAN NOT NULL DEFAULT false,CONSTRAINT v1_parcel_connector_tenant UNIQUE(business_id,id)
);
CREATE TABLE v1_order_parcel_links (
 id UUID PRIMARY KEY,business_id UUID NOT NULL,order_id UUID NOT NULL,connector_id UUID NOT NULL,
 actor_id UUID NOT NULL REFERENCES users(id),idempotency_key UUID NOT NULL,
 request_hash VARCHAR(64) NOT NULL,order_fingerprint VARCHAR(64) NOT NULL,
 courier_id VARCHAR(40) NOT NULL,awb VARCHAR(35) NOT NULL,remote_id UUID,
 state VARCHAR(32) NOT NULL DEFAULT 'pending_enrollment',revision INTEGER NOT NULL DEFAULT 1,
 lease_token UUID,lease_until TIMESTAMPTZ,next_poll_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 snapshot_revision INTEGER NOT NULL DEFAULT 0,tracking_state VARCHAR(32) NOT NULL DEFAULT 'awaiting_update',
 raw_status VARCHAR(120) NOT NULL DEFAULT 'Awaiting update',checked_at TIMESTAMPTZ,
 attempted_at TIMESTAMPTZ,last_sync_at TIMESTAMPTZ,error_code VARCHAR(64),created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 CONSTRAINT v1_parcel_link_tenant UNIQUE(business_id,id),CONSTRAINT v1_parcel_command_key UNIQUE(business_id,idempotency_key),
 FOREIGN KEY(business_id,order_id) REFERENCES commerce_orders(seller_id,id),
 FOREIGN KEY(business_id,connector_id) REFERENCES v1_parcel_connectors(business_id,id),
 CONSTRAINT v1_parcel_link_actor_member FOREIGN KEY(business_id,actor_id) REFERENCES memberships(business_id,user_id),
 CONSTRAINT v1_parcel_link_state CHECK(state IN ('pending_enrollment','enrollment_unknown','linked','review_required','unlinked')),
 CONSTRAINT v1_parcel_link_counters CHECK(revision>0 AND snapshot_revision>=0),
 CONSTRAINT v1_parcel_link_lease CHECK((lease_token IS NULL)=(lease_until IS NULL)),
 CONSTRAINT v1_parcel_link_identity CHECK(awb ~ '^[A-Z0-9-]{6,35}$' AND request_hash ~ '^[a-f0-9]{64}$' AND order_fingerprint ~ '^[a-f0-9]{64}$')
);
CREATE UNIQUE INDEX v1_parcel_one_order ON v1_order_parcel_links(business_id,order_id) WHERE state <> 'unlinked';
CREATE UNIQUE INDEX v1_parcel_one_awb ON v1_order_parcel_links(connector_id,courier_id,awb) WHERE state <> 'unlinked';
CREATE UNIQUE INDEX v1_parcel_one_remote ON v1_order_parcel_links(connector_id,remote_id) WHERE state <> 'unlinked';
CREATE TABLE v1_parcel_observations (
 id UUID PRIMARY KEY,business_id UUID NOT NULL,link_id UUID NOT NULL,event_hash VARCHAR(64) NOT NULL,
 raw_time VARCHAR(100) NOT NULL DEFAULT '',event_at TIMESTAMPTZ,status VARCHAR(120) NOT NULL,
 description VARCHAR(500) NOT NULL DEFAULT '',location VARCHAR(200) NOT NULL DEFAULT '',
 observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),CONSTRAINT v1_parcel_event_hash CHECK(event_hash ~ '^[a-f0-9]{64}$'),CONSTRAINT v1_parcel_event_dedupe UNIQUE(link_id,event_hash),
 FOREIGN KEY(business_id,link_id) REFERENCES v1_order_parcel_links(business_id,id)
);
CREATE TABLE v1_parcel_notifications (
 id UUID PRIMARY KEY,business_id UUID NOT NULL,link_id UUID NOT NULL,milestone VARCHAR(32) NOT NULL,
 decision VARCHAR(32) NOT NULL,reason VARCHAR(64) NOT NULL,outbox_id UUID REFERENCES whatsapp_messages(id),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),CONSTRAINT v1_parcel_milestone_once UNIQUE(link_id,milestone),
 FOREIGN KEY(business_id,link_id) REFERENCES v1_order_parcel_links(business_id,id),
 CONSTRAINT v1_parcel_notification_decision CHECK(decision IN ('queued','skipped'))
);
CREATE TABLE v1_parcel_audits (
 id UUID PRIMARY KEY,business_id UUID NOT NULL,link_id UUID NOT NULL,actor_id UUID NOT NULL REFERENCES users(id),
 CONSTRAINT v1_parcel_audit_actor_member FOREIGN KEY(business_id,actor_id) REFERENCES memberships(business_id,user_id),
 CONSTRAINT v1_parcel_audit_details CHECK(jsonb_typeof(details)='object'),
 action VARCHAR(40) NOT NULL,idempotency_key UUID NOT NULL,CONSTRAINT v1_parcel_audit_key UNIQUE(business_id,idempotency_key),details JSONB NOT NULL,created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 FOREIGN KEY(business_id,link_id) REFERENCES v1_order_parcel_links(business_id,id)
);
CREATE FUNCTION v1_parcel_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Parcel history is append-only'; END $$;
CREATE TRIGGER v1_parcel_observation_immutable BEFORE UPDATE OR DELETE ON v1_parcel_observations FOR EACH ROW EXECUTE FUNCTION v1_parcel_immutable();
CREATE TRIGGER v1_parcel_audit_immutable BEFORE UPDATE OR DELETE ON v1_parcel_audits FOR EACH ROW EXECUTE FUNCTION v1_parcel_immutable();
"""
def upgrade():
    # Function body includes a semicolon, so execute statements with an explicit boundary.
    for statement in DDL.split(';\n'):
        if statement.strip():op.execute(statement)
def downgrade():
    for table in ('v1_parcel_audits','v1_parcel_notifications','v1_parcel_observations','v1_order_parcel_links','v1_parcel_connectors'):op.drop_table(table)
    op.execute('DROP FUNCTION v1_parcel_immutable()')
