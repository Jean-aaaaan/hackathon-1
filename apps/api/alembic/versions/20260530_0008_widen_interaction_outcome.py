"""widen interaction outcome column from VARCHAR(255) to Text

Revision ID: 20260530_0008
Revises: 20260530_0007
Create Date: 2026-05-30
"""
from alembic import op
import sqlalchemy as sa

revision = "20260530_0008"
down_revision = "20260530_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "interactions",
        "outcome",
        type_=sa.Text(),
        existing_type=sa.String(255),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "interactions",
        "outcome",
        type_=sa.String(255),
        existing_type=sa.Text(),
        existing_nullable=True,
    )
