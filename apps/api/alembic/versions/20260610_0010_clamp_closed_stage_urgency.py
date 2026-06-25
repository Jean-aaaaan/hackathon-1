"""Clamp urgency_score on closed-stage accounts.

The nightly worker never re-runs Won / Closed lost / Partners accounts, so
urgency scored while the deal was open persists forever and pins closed deals
to the top of every triage surface (inbox "Needs attention", Deal Book,
urgent alerts). Clamp them to 0.1; hubspot_sync now does the same on stage
transition going forward.

Revision ID: 20260610_0010
Revises: 20260602_0009
Create Date: 2026-06-10
"""
from alembic import op

revision = '20260610_0010'
down_revision = '20260602_0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE accounts
        SET urgency_score = 0.1
        WHERE lower(trim(stage)) IN ('won', 'closed lost', 'closed-lost', 'partners')
          AND urgency_score > 0.1
        """
    )


def downgrade() -> None:
    # Data correction — original stale scores are not recoverable.
    pass
