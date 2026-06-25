"""add fireflies_api_key to workspaces

Revision ID: 0002_fireflies_key
Revises: 0001_initial
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision: str = "0002_fireflies_key"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("fireflies_api_key", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("workspaces", "fireflies_api_key")
