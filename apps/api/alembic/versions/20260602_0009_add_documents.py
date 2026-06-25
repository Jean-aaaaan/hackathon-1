"""add documents table for generated sales collateral

Revision ID: 20260602_0009
Revises: 20260530_0008
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '20260602_0009'
down_revision = '20260530_0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'documents',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('workspace_id', UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', UUID(as_uuid=True),
                  sa.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False),

        sa.Column('doc_type', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False, server_default='generating'),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('file_name', sa.Text(), nullable=False),
        sa.Column('file_format', sa.Text(), nullable=False),
        sa.Column('file_size_bytes', sa.Integer()),
        sa.Column('file_data', sa.LargeBinary()),

        sa.Column('generated_by', sa.Text(), server_default='user_request'),
        sa.Column('generation_context', JSONB, server_default='{}'),
        sa.Column('grounding_confidence', sa.Float()),
        sa.Column('error_message', sa.Text()),

        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('deleted_at', sa.DateTime(timezone=True)),
    )
    op.create_index('ix_documents_account_id', 'documents', ['account_id'])
    op.create_index('ix_documents_workspace_id', 'documents', ['workspace_id'])


def downgrade() -> None:
    op.drop_index('ix_documents_workspace_id', table_name='documents')
    op.drop_index('ix_documents_account_id', table_name='documents')
    op.drop_table('documents')
