"""add forecast_snapshots table and icp_score column

Revision ID: 20260528_0006
Revises: 20260528_0005
Create Date: 2026-05-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '20260528_0006'
down_revision = '20260528_0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'forecast_snapshots',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', UUID(as_uuid=True), sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('workspace_id', UUID(as_uuid=True), nullable=False),
        sa.Column('run_date', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('pov_category', sa.Text()),
        sa.Column('pov_amount', sa.Float()),
        sa.Column('pov_close_date', sa.Date()),
        sa.Column('crm_amount', sa.Float()),
        sa.Column('crm_stage', sa.Text()),
        sa.Column('crm_close_date', sa.Date()),
    )
    op.create_index('idx_forecast_snapshots_workspace', 'forecast_snapshots', ['workspace_id', 'run_date'])
    op.add_column('accounts', sa.Column('icp_score', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('accounts', 'icp_score')
    op.drop_index('idx_forecast_snapshots_workspace', 'forecast_snapshots')
    op.drop_table('forecast_snapshots')
