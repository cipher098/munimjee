"""Tenant-safe immutable import approval and private catalogue creation receipt.

Revision ID: 0047_v1_import_catalogue_bridge
Revises: 0046_v1_import_jobs
"""
from alembic import op

revision = "0047_v1_import_catalogue_bridge"
down_revision = "0046_v1_import_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE import_catalogue_bridges (
            id UUID PRIMARY KEY,
            business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE RESTRICT,
            candidate_id UUID NOT NULL,
            candidate_revision INTEGER NOT NULL,
            product_id UUID NOT NULL,
            actor_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            idempotency_key UUID NOT NULL,
            request_hash VARCHAR(64) NOT NULL,
            approved_snapshot JSONB NOT NULL,
            creation_snapshot JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT import_bridge_one_candidate UNIQUE (business_id, candidate_id),
            CONSTRAINT import_bridge_idempotency UNIQUE (business_id, idempotency_key),
            CONSTRAINT import_bridge_candidate FOREIGN KEY (business_id, candidate_id)
                REFERENCES v1_import_drafts(business_id, id) ON DELETE RESTRICT,
            CONSTRAINT import_bridge_product FOREIGN KEY (business_id, product_id)
                REFERENCES products(seller_id, id) ON DELETE RESTRICT,
            CONSTRAINT import_bridge_member FOREIGN KEY (business_id, actor_user_id)
                REFERENCES memberships(business_id, user_id) ON DELETE RESTRICT,
            CONSTRAINT import_bridge_revision CHECK (candidate_revision >= 1),
            CONSTRAINT import_bridge_hash CHECK (request_hash ~ '^[a-f0-9]{64}$'),
            CONSTRAINT import_bridge_snapshots CHECK (
                jsonb_typeof(approved_snapshot) = 'object' AND jsonb_typeof(creation_snapshot) = 'object')
        )
    """)
    op.execute("""
        CREATE FUNCTION immutable_import_bridge() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Import approval receipts are immutable' USING ERRCODE = '23514';
        END $$
    """)
    op.execute("""
        CREATE TRIGGER import_bridge_immutable BEFORE UPDATE ON import_catalogue_bridges
        FOR EACH ROW EXECUTE FUNCTION immutable_import_bridge()
    """)


def downgrade():
    op.execute("DROP TABLE import_catalogue_bridges")
    op.execute("DROP FUNCTION immutable_import_bridge()")
