"""add timeline_actions table and response_velocity to account state

Revision ID: 20260530_0007
Revises: 20260528_0006
Create Date: 2026-05-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '20260530_0007'
down_revision = '20260528_0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'timeline_actions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('account_id', UUID(as_uuid=True),
                  sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('workspace_id', UUID(as_uuid=True), nullable=False),

        sa.Column('action_type', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('reasoning', sa.Text()),

        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('priority', sa.Float(), server_default='0.5'),

        sa.Column('status', sa.Text(), server_default='upcoming'),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('completed_notes', sa.Text()),
        sa.Column('skipped_at', sa.DateTime(timezone=True)),
        sa.Column('skip_count', sa.Integer(), server_default='0'),

        sa.Column('draft_id', UUID(as_uuid=True),
                  sa.ForeignKey('drafts.id', ondelete='SET NULL'), nullable=True),
        sa.Column('prepared_content', JSONB),

        sa.Column('source', sa.Text()),
        sa.Column('source_ref_id', sa.Text()),

        sa.Column('meddpicc_component', sa.Text()),
        sa.Column('deal_stage_at_creation', sa.Text()),

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

    op.create_index('idx_timeline_actions_account_due',
                    'timeline_actions', ['account_id', 'due_date'])
    op.create_index('idx_timeline_actions_workspace_status',
                    'timeline_actions', ['workspace_id', 'status', 'due_date'])


def downgrade() -> None:
    op.drop_index('idx_timeline_actions_workspace_status', 'timeline_actions')
    op.drop_index('idx_timeline_actions_account_due', 'timeline_actions')
    op.drop_table('timeline_actions')
