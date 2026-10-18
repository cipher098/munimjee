"""Permit bounded CSV originals in the existing tenant-owned import asset store."""
from alembic import op

revision = '0053_v1_csv_import'
down_revision = '0052_v1_customer_links'
branch_labels = depends_on = None


def upgrade():
    op.drop_constraint('v1_import_asset_content', 'v1_import_assets', type_='check')
    op.create_check_constraint('v1_import_asset_content', 'v1_import_assets',
        "content_type IN ('image/jpeg','image/png','video/mp4','text/csv') AND sha256 ~ '^[a-f0-9]{64}$'")


def downgrade():
    # Retained original bytes/provenance must never be deleted to make rollback
    # succeed. PostgreSQL rejects this constraint if CSV originals remain.
    op.drop_constraint('v1_import_asset_content', 'v1_import_assets', type_='check')
    op.create_check_constraint('v1_import_asset_content', 'v1_import_assets',
        "content_type IN ('image/jpeg','image/png','video/mp4') AND sha256 ~ '^[a-f0-9]{64}$'")
