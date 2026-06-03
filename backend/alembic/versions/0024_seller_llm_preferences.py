"""Add llm_preferences JSONB to sellers for per-seller model overrides.

Sellers can pick which provider/model handles the bot's "thinking" call
(decide → action JSON) and the customer-facing "replying" call
(generate_reply → message text). Null = inherit app-level defaults
from agents.yaml. Subagent calls (vision, catalog, intent classifier)
are NOT per-seller configurable.

Shape:
    {
      "decide":  {"provider": "anthropic", "model": "claude-sonnet-4-20250514"},
      "reply":   {"provider": "sarvam",    "model": "sarvam-m"}
    }

Either key can be omitted to fall back to the agents.yaml app default.

Revision ID: 0024
Revises: 0023
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'sellers',
        sa.Column('llm_preferences', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade():
    op.drop_column('sellers', 'llm_preferences')
