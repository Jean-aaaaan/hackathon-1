"""Add missing columns to signals and drafts that exist in ORM models but not initial migration.

Revision ID: 0002_missing_columns
Revises: 0001_initial
Create Date: 2026-05-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_missing_columns"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── signals: columns in model missing from migration ──────────────────────
    op.add_column("signals", sa.Column("gold_confidence", sa.Float, nullable=True))
    op.add_column("signals", sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("signals", sa.Column("notification_sent", sa.Boolean, server_default="false", nullable=False))
    op.add_column("signals", sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True))

    # ── drafts: columns in model missing from migration ───────────────────────
    op.add_column("drafts", sa.Column("content_html", sa.Text, nullable=True))
    op.add_column("drafts", sa.Column("target_contact", sa.Text, nullable=True))
    op.add_column("drafts", sa.Column("subject_line", sa.Text, nullable=True))
    op.add_column("drafts", sa.Column(
        "reviewer_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("workspace_users.id"),
        nullable=True,
    ))
    op.add_column("drafts", sa.Column("final_content", sa.Text, nullable=True))
    op.add_column("drafts", sa.Column("pushed_to_crm", sa.Boolean, server_default="false", nullable=False))
    op.add_column("drafts", sa.Column("crm_draft_id", sa.Text, nullable=True))
    op.add_column("drafts", sa.Column("crm_pushed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("drafts", "crm_pushed_at")
    op.drop_column("drafts", "crm_draft_id")
    op.drop_column("drafts", "pushed_to_crm")
    op.drop_column("drafts", "final_content")
    op.drop_column("drafts", "reviewer_id")
    op.drop_column("drafts", "subject_line")
    op.drop_column("drafts", "target_contact")
    op.drop_column("drafts", "content_html")

    op.drop_column("signals", "detected_at")
    op.drop_column("signals", "notification_sent")
    op.drop_column("signals", "processed_at")
    op.drop_column("signals", "gold_confidence")
