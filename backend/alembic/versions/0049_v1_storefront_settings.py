"""Tenant design drafts, explicit publication and durable theme command receipts."""
from alembic import op

revision = "0049_v1_storefront_settings"
down_revision = "0048_v1_parcel_tracking"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE storefront_theme_settings_v1 (
	business_id UUID NOT NULL,
	version INTEGER NOT NULL,
	draft_config JSONB NOT NULL,
	published_config JSONB,
	published_revision INTEGER DEFAULT '0' NOT NULL,
	updated_by UUID NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	published_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (business_id),
	CONSTRAINT theme_settings_versions CHECK (version >= 1 AND published_revision >= 0 AND published_revision <= version),
	CONSTRAINT theme_settings_publication CHECK ((published_config IS NULL AND published_revision = 0 AND published_at IS NULL) OR (published_config IS NOT NULL AND published_revision > 0 AND published_at IS NOT NULL)),
	FOREIGN KEY(business_id) REFERENCES businesses (id),
	FOREIGN KEY(updated_by) REFERENCES users (id)
)

;

CREATE TABLE storefront_theme_commands_v1 (
	business_id UUID NOT NULL,
	idempotency_key UUID NOT NULL,
	operation VARCHAR(16) NOT NULL,
	request_hash VARCHAR(64) NOT NULL,
	result JSONB NOT NULL,
	actor_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (business_id, idempotency_key),
	CONSTRAINT theme_command_operation CHECK (operation IN ('save','publish')),
	FOREIGN KEY(business_id) REFERENCES businesses (id),
	FOREIGN KEY(actor_id) REFERENCES users (id)
)

;
"""


def upgrade():
    for statement in DDL.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade():
    op.drop_table("storefront_theme_commands_v1")
    op.drop_table("storefront_theme_settings_v1")
