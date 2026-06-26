"""Add remaining columns missing from models vs DB schema.

Revision ID: 0003_remaining_columns
Revises: 0002_missing_columns
Create Date: 2026-05-27

Adds:
- workspace_users.name (display name from WorkOS)
- api_keys.expires_at
- interactions.sentiment, sentiment_score, contact_name, contact_email
- agent_runs.started_at, error_summary, triggered_by_user
- audit_log.user_id
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003_remaining_columns"
down_revision: Union[str, None] = "0002_missing_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE workspace_users ADD COLUMN IF NOT EXISTS name TEXT"))
    conn.execute(sa.text("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ"))
    conn.execute(sa.text("ALTER TABLE interactions ADD COLUMN IF NOT EXISTS sentiment TEXT"))
    conn.execute(sa.text("ALTER TABLE interactions ADD COLUMN IF NOT EXISTS sentiment_score FLOAT"))
    conn.execute(sa.text("ALTER TABLE interactions ADD COLUMN IF NOT EXISTS contact_name TEXT"))
    conn.execute(sa.text("ALTER TABLE interactions ADD COLUMN IF NOT EXISTS contact_email TEXT"))
    conn.execute(sa.text("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ DEFAULT NOW()"))
    conn.execute(sa.text("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS error_summary JSONB"))
    conn.execute(sa.text("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS triggered_by_user UUID REFERENCES workspace_users(id)"))
    conn.execute(sa.text("ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS user_id UUID"))


def downgrade() -> None:
    op.drop_column("audit_log", "user_id")
    op.drop_column("agent_runs", "triggered_by_user")
    op.drop_column("agent_runs", "error_summary")
    op.drop_column("agent_runs", "started_at")
    op.drop_column("interactions", "contact_email")
    op.drop_column("interactions", "contact_name")
    op.drop_column("interactions", "sentiment_score")
    op.drop_column("interactions", "sentiment")
    op.drop_column("api_keys", "expires_at")
    op.drop_column("workspace_users", "name")
