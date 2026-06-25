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
    # ── workspace_users ───────────────────────────────────────────────────────
    op.add_column("workspace_users", sa.Column("name", sa.Text, nullable=True))

    # ── api_keys ──────────────────────────────────────────────────────────────
    op.add_column("api_keys", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))

    # ── interactions ──────────────────────────────────────────────────────────
    op.add_column("interactions", sa.Column("sentiment", sa.Text, nullable=True))
    op.add_column("interactions", sa.Column("sentiment_score", sa.Float, nullable=True))
    op.add_column("interactions", sa.Column("contact_name", sa.Text, nullable=True))
    op.add_column("interactions", sa.Column("contact_email", sa.Text, nullable=True))

    # ── agent_runs ────────────────────────────────────────────────────────────
    # Add started_at (model uses this; DB has 'created_at' from initial migration).
    # Both columns coexist — started_at is used by the ORM, created_at is orphaned but harmless.
    op.add_column(
        "agent_runs",
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=True,
        ),
    )
    op.add_column("agent_runs", sa.Column("error_summary", postgresql.JSONB, nullable=True))
    op.add_column(
        "agent_runs",
        sa.Column(
            "triggered_by_user",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspace_users.id"),
            nullable=True,
        ),
    )

    # ── audit_log ─────────────────────────────────────────────────────────────
    op.add_column("audit_log", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))


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
