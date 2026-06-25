"""Expire stale pending drafts.

Drafts carry a 7-day expires_at that was never enforced, so hundreds of
stale pending drafts accumulated ("440 drafts waiting"). Mark every pending
draft past its expiry as status='expired'; the list endpoint and review
endpoint now enforce expiry going forward.

Revision ID: 20260610_0011
Revises: 20260610_0010
Create Date: 2026-06-10
"""
from alembic import op

revision = '20260610_0011'
down_revision = '20260610_0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE drafts
        SET status = 'expired'
        WHERE status = 'pending'
          AND expires_at IS NOT NULL
          AND expires_at < NOW()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE drafts
        SET status = 'pending'
        WHERE status = 'expired'
        """
    )
