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
    conn = op.get_bind()
    # ── signals ───────────────────────────────────────────────────────────────
    conn.execute(sa.text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS gold_confidence FLOAT"))
    conn.execute(sa.text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ"))
    conn.execute(sa.text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS notification_sent BOOLEAN NOT NULL DEFAULT false"))
    conn.execute(sa.text("ALTER TABLE signals ADD COLUMN IF NOT EXISTS detected_at TIMESTAMPTZ DEFAULT NOW()"))
    # ── drafts ────────────────────────────────────────────────────────────────
    conn.execute(sa.text("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS content_html TEXT"))
    conn.execute(sa.text("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS target_contact TEXT"))
    conn.execute(sa.text("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS subject_line TEXT"))
    conn.execute(sa.text("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS reviewer_id UUID REFERENCES workspace_users(id)"))
    conn.execute(sa.text("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS final_content TEXT"))
    conn.execute(sa.text("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS pushed_to_crm BOOLEAN NOT NULL DEFAULT false"))
    conn.execute(sa.text("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS crm_draft_id TEXT"))
    conn.execute(sa.text("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS crm_pushed_at TIMESTAMPTZ"))


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
