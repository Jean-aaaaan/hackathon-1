"""Add Outlook OAuth columns to workspaces + next_step to accounts state

Revision ID: 20260528_0004
Revises: 20260527_0003
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa

revision = "20260528_0004"
down_revision = "0003_remaining_columns"
branch_labels = None
depends_on = None


def upgrade():
    # Outlook / Microsoft Graph OAuth columns on workspaces
    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.add_column(sa.Column("outlook_access_token", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("outlook_refresh_token", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("outlook_token_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("outlook_user_email", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.drop_column("outlook_user_email")
        batch_op.drop_column("outlook_token_expires_at")
        batch_op.drop_column("outlook_refresh_token")
        batch_op.drop_column("outlook_access_token")
