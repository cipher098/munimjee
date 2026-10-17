"""Durable tenant import jobs and original media, following channel operations.

Revision ID: 0046_v1_import_jobs
Revises: 0045_v1_channel_operator

Static reviewed PostgreSQL DDL; no runtime model imports or data backfill.
"""
from alembic import op
revision = "0046_v1_import_jobs"
down_revision = "0045_v1_channel_operator"
branch_labels = None
depends_on = None

DDL = r"""
CREATE TABLE v1_import_assets (
	id UUID NOT NULL,
	business_id UUID NOT NULL,
	creator_id UUID NOT NULL,
	idempotency_key UUID NOT NULL,
	content_type VARCHAR(32) NOT NULL,
	sha256 VARCHAR(64) NOT NULL,
	size_bytes INTEGER NOT NULL,
	content BYTEA NOT NULL,
	authorized_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT v1_import_asset_tenant UNIQUE (business_id, id),
	CONSTRAINT v1_import_asset_idempotency UNIQUE (business_id, idempotency_key),
	CONSTRAINT v1_import_asset_size CHECK (size_bytes > 0 AND size_bytes <= 5000000 AND octet_length(content) = size_bytes),
	CONSTRAINT v1_import_asset_content CHECK (content_type IN ('image/jpeg','image/png','video/mp4') AND sha256 ~ '^[a-f0-9]{64}$'),
	FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE RESTRICT,
	FOREIGN KEY(creator_id) REFERENCES users (id) ON DELETE RESTRICT
);

CREATE TABLE v1_import_jobs (
	id UUID NOT NULL,
	business_id UUID NOT NULL,
	creator_id UUID NOT NULL,
	idempotency_key UUID NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	source JSONB NOT NULL,
	asset_id UUID,
	state VARCHAR(24) DEFAULT 'pending' NOT NULL,
	revision INTEGER DEFAULT '1' NOT NULL,
	attempts INTEGER DEFAULT '0' NOT NULL,
	lease_token UUID,
	lease_expires_at TIMESTAMP WITH TIME ZONE,
	candidate_count INTEGER DEFAULT '0' NOT NULL,
	error_code VARCHAR(64),
	authorized_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	available_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT v1_import_job_tenant UNIQUE (business_id, id),
	CONSTRAINT v1_import_job_idempotency UNIQUE (business_id, idempotency_key),
	CONSTRAINT v1_import_job_tenant_asset FOREIGN KEY(business_id, asset_id) REFERENCES v1_import_assets (business_id, id),
	CONSTRAINT v1_import_job_state CHECK (state IN ('pending','running','review_required','failed','cancelled')),
	CONSTRAINT v1_import_job_counters CHECK (revision >= 1 AND attempts >= 0 AND attempts <= 3 AND candidate_count >= 0 AND candidate_count <= 200),
	CONSTRAINT v1_import_job_lease CHECK ((state = 'running' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (state <> 'running' AND lease_token IS NULL AND lease_expires_at IS NULL)),
	CONSTRAINT v1_import_job_source CHECK (jsonb_typeof(source) = 'object' AND request_hash ~ '^[a-f0-9]{64}$'),
	FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE RESTRICT,
	FOREIGN KEY(creator_id) REFERENCES users (id) ON DELETE RESTRICT
);

CREATE TABLE v1_import_drafts (
	id UUID NOT NULL,
	business_id UUID NOT NULL,
	last_job_id UUID NOT NULL,
	revision INTEGER DEFAULT '1' NOT NULL,
	document JSONB NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT v1_import_draft_tenant UNIQUE (business_id, id),
	CONSTRAINT v1_import_draft_tenant_job FOREIGN KEY(business_id, last_job_id) REFERENCES v1_import_jobs (business_id, id),
	CONSTRAINT v1_import_draft_document CHECK (revision >= 1 AND jsonb_typeof(document) = 'object'),
	FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE RESTRICT
);

CREATE TABLE v1_import_audits (
	id UUID NOT NULL,
	business_id UUID NOT NULL,
	job_id UUID,
	candidate_id UUID,
	actor_id UUID NOT NULL,
	idempotency_key UUID NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	action VARCHAR(32) NOT NULL,
	details JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT v1_import_audit_idempotency UNIQUE (business_id, idempotency_key),
	CONSTRAINT v1_import_audit_tenant_job FOREIGN KEY(business_id, job_id) REFERENCES v1_import_jobs (business_id, id),
	CONSTRAINT v1_import_audit_tenant_candidate FOREIGN KEY(business_id, candidate_id) REFERENCES v1_import_drafts (business_id, id),
	CONSTRAINT v1_import_audit_details CHECK (jsonb_typeof(details) = 'object' AND request_hash ~ '^[a-f0-9]{64}$'),
	FOREIGN KEY(business_id) REFERENCES businesses (id) ON DELETE RESTRICT,
	FOREIGN KEY(actor_id) REFERENCES users (id) ON DELETE RESTRICT
);

"""


def upgrade():
    for statement in DDL.split(";"):
        if statement.strip():
            op.execute(statement)
    for table in ("v1_import_jobs", "v1_import_drafts", "v1_import_audits"):
        op.create_index("ix_" + table + "_business_id", table, ["business_id"])


def downgrade():
    # Disposable development only; production rollback must retain originals/audits.
    for table in ("v1_import_audits", "v1_import_drafts", "v1_import_jobs", "v1_import_assets"):
        op.drop_table(table)
