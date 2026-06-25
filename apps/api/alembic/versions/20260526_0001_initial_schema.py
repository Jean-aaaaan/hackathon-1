"""Initial schema — all tables for Vantage v1.0

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-26 00:00:00 UTC

Tables created:
- workspaces
- workspace_users
- accounts (with pgvector embedding)
- signals
- drafts
- interactions
- agent_runs
- audit_log
- api_keys
- conversations (thread history for Assistant)

pgvector extension must be installed:
  CREATE EXTENSION IF NOT EXISTS vector;
  CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')

    # ── workspaces ────────────────────────────────────────────────────────────
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), unique=True, nullable=False),
        sa.Column("plan", sa.String(50), nullable=False, server_default="internal"),
        # HubSpot OAuth
        sa.Column("hubspot_access_token", sa.Text),
        sa.Column("hubspot_refresh_token", sa.Text),
        sa.Column("hubspot_portal_id", sa.String(50)),
        sa.Column("hubspot_token_expires_at", sa.DateTime(timezone=True)),
        sa.Column("hubspot_last_modified", sa.DateTime(timezone=True)),
        # Gong
        sa.Column("gong_workspace_id", sa.Text),
        sa.Column("gong_api_key", sa.Text),
        sa.Column("gong_access_token", sa.Text),
        # Enrichment
        sa.Column("perplexity_api_key", sa.Text),
        # Notifications
        sa.Column("slack_webhook_url", sa.Text),
        sa.Column("teams_webhook_url", sa.Text),
        # Billing (for future SaaS)
        sa.Column("stripe_customer_id", sa.Text),
        # Settings (JSON: push_threshold, urgency_threshold, webhooks, etc.)
        sa.Column("settings", postgresql.JSONB, server_default="{}"),
        # Soft delete
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), onupdate=sa.text("NOW()")),
    )
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"])

    # ── workspace_users ───────────────────────────────────────────────────────
    op.create_table(
        "workspace_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workos_user_id", sa.String(255), nullable=False, unique=True),
        sa.Column("email", sa.String(255)),
        sa.Column("name", sa.Text),  # display name from WorkOS profile
        sa.Column("role", sa.String(50), nullable=False, server_default="rep"),  # rep|manager|admin|owner
        sa.Column("hubspot_owner_id", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_workspace_users_workspace", "workspace_users", ["workspace_id"])
    op.create_index("ix_workspace_users_workos", "workspace_users", ["workos_user_id"])

    # ── accounts ──────────────────────────────────────────────────────────────
    op.create_table(
        "accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("hubspot_deal_id", sa.String(100)),
        sa.Column("hubspot_company_id", sa.String(100)),
        sa.Column("hubspot_last_modified", sa.DateTime(timezone=True)),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("stage", sa.String(100)),
        sa.Column("deal_amount", sa.Numeric(18, 2)),
        sa.Column("close_date", sa.Date),
        sa.Column("owner_rep_id", sa.String(100)),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspace_users.id")),
        # ASO — full Account State Object
        sa.Column("state", postgresql.JSONB, server_default="{}"),
        # Indexed scores (sourced from state for fast sorting)
        sa.Column("health_score", sa.Float),
        sa.Column("urgency_score", sa.Float),
        sa.Column("pov_forecast_cat", sa.String(100)),
        sa.Column("pov_confidence", sa.Float),
        # Agent metadata
        sa.Column("last_agent_run_at", sa.DateTime(timezone=True)),
        sa.Column("agent_run_count", sa.Integer, server_default="0"),
        # pgvector embedding (1536-dim, voyage-3-lite)
        sa.Column("embedding", sa.String),  # Will be cast to vector(1536)
        # Soft delete
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    # Alter embedding column to proper vector type
    op.execute("ALTER TABLE accounts ALTER COLUMN embedding TYPE vector(1536) USING NULL")
    op.create_index("ix_accounts_workspace", "accounts", ["workspace_id"])
    op.create_index("ix_accounts_urgency", "accounts", ["workspace_id", "urgency_score"])
    op.create_index("ix_accounts_hubspot", "accounts", ["hubspot_deal_id"])
    op.create_index("ix_accounts_owner", "accounts", ["workspace_id", "owner_rep_id"])
    # IVFFlat index for ANN search — build after loading data for best performance
    # Using hnsw instead for empty-table safety (no minimum row requirement)
    op.execute("""
        CREATE INDEX ix_accounts_embedding ON accounts
        USING hnsw (embedding vector_cosine_ops)
        WHERE embedding IS NOT NULL;
    """)

    # ── signals ───────────────────────────────────────────────────────────────
    op.create_table(
        "signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("urgency", sa.String(20)),  # low|medium|high|critical
        sa.Column("urgency_score", sa.Float),
        sa.Column("detail", sa.Text),
        sa.Column("source", sa.String(100)),
        sa.Column("source_url", sa.Text),
        sa.Column("confidence", sa.Float),
        # Gold Data Layer
        sa.Column("gold_sources", postgresql.JSONB, server_default="[]"),
        sa.Column("gold_resolution", sa.Text),
        sa.Column("gold_confidence", sa.Float),   # ← was missing
        # Processing state
        sa.Column("processed", sa.Boolean, server_default="false"),
        sa.Column("processed_at", sa.DateTime(timezone=True)),       # ← was missing
        sa.Column("pushed_to_inbox", sa.Boolean, server_default="false"),
        sa.Column("notification_sent", sa.Boolean, server_default="false"),  # ← was missing
        sa.Column("acknowledged", sa.Boolean, server_default="false"),
        sa.Column("acknowledged_by", sa.String(255)),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),  # ← was missing
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_signals_account", "signals", ["account_id"])
    op.create_index("ix_signals_urgency", "signals", ["workspace_id", "urgency_score"])
    op.create_index("ix_signals_inbox", "signals", ["workspace_id", "pushed_to_inbox"])

    # ── drafts ────────────────────────────────────────────────────────────────
    op.create_table(
        "drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("type", sa.String(100), nullable=False),      # email_followup|meeting_brief|...
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_html", sa.Text),                      # ← was missing
        sa.Column("content_modified", sa.Text),                  # rep's edited version
        sa.Column("target_contact", sa.Text),                    # ← was missing
        sa.Column("subject_line", sa.Text),                      # ← was missing
        sa.Column("sources_cited", postgresql.JSONB, server_default="[]"),
        sa.Column("gold_data_used", postgresql.JSONB, server_default="{}"),
        sa.Column("status", sa.String(50), server_default="pending"),
        sa.Column("reviewer_notes", sa.Text),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspace_users.id")),  # ← was missing
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("final_content", sa.Text),                     # ← was missing
        sa.Column("hubspot_email_id", sa.String(100)),
        sa.Column("pushed_to_crm", sa.Boolean, server_default="false"),    # ← was missing
        sa.Column("crm_draft_id", sa.Text),                      # ← was missing
        sa.Column("crm_pushed_at", sa.DateTime(timezone=True)),  # ← was missing
        sa.Column("pushed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_drafts_account", "drafts", ["account_id"])
    op.create_index("ix_drafts_inbox", "drafts", ["workspace_id", "status"])
    op.create_index("ix_drafts_expires", "drafts", ["expires_at"])

    # ── interactions ──────────────────────────────────────────────────────────
    op.create_table(
        "interactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rep_id", postgresql.UUID(as_uuid=True)),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("source", sa.String(100)),
        sa.Column("notes", sa.Text),
        sa.Column("outcome", sa.String(255)),
        sa.Column("sentiment", sa.Text),                         # ← was missing
        sa.Column("sentiment_score", sa.Float),                  # ← was missing
        sa.Column("contact_name", sa.Text),                      # ← was missing
        sa.Column("contact_email", sa.Text),                     # ← was missing
        sa.Column("is_training_signal", sa.Boolean, server_default="false"),
        sa.Column("training_category", sa.String(100)),
        sa.Column("occurred_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_interactions_account", "interactions", ["account_id"])
    op.create_index("ix_interactions_training", "interactions", ["workspace_id", "is_training_signal"])

    # ── agent_runs ────────────────────────────────────────────────────────────
    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.String(50), nullable=False),     # nightly|manual|webhook
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),   # ← was 'created_at'
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(50), nullable=False),      # queued|running|completed|failed
        sa.Column("accounts_total", sa.Integer, server_default="0"),
        sa.Column("accounts_processed", sa.Integer, server_default="0"),
        sa.Column("accounts_failed", sa.Integer, server_default="0"),
        sa.Column("signals_detected", sa.Integer, server_default="0"),
        sa.Column("drafts_created", sa.Integer, server_default="0"),
        sa.Column("total_prompt_tokens", sa.BigInteger, server_default="0"),
        sa.Column("total_completion_tokens", sa.BigInteger, server_default="0"),
        sa.Column("total_cost_usd", sa.Numeric(10, 6), server_default="0"),
        sa.Column("error_summary", postgresql.JSONB),             # ← was missing
        sa.Column("triggered_by_user", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspace_users.id")),  # ← was missing
    )
    op.create_index("ix_agent_runs_workspace", "agent_runs", ["workspace_id"])
    op.create_index("ix_agent_runs_started", "agent_runs", ["started_at"])

    # ── audit_log ─────────────────────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True)),      # ← was missing
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(100)),
        sa.Column("resource_id", sa.String(255)),
        sa.Column("actor_id", sa.String(255)),
        sa.Column("changes", postgresql.JSONB, server_default="{}"),
        sa.Column("extra_data", postgresql.JSONB, server_default="{}"),
        sa.Column("ip_address", sa.String(50)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_audit_log_workspace", "audit_log", ["workspace_id", "created_at"])
    op.create_index("ix_audit_log_resource", "audit_log", ["resource_type", "resource_id"])
    # Append-only: revoke DELETE on audit_log for application role
    op.execute("REVOKE DELETE ON audit_log FROM PUBLIC;")

    # ── api_keys ──────────────────────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("key_prefix", sa.String(50), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("scopes", postgresql.ARRAY(sa.Text), server_default="{}"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_api_keys_hash", "api_keys", ["key_hash"])
    op.create_index("ix_api_keys_workspace", "api_keys", ["workspace_id"])

    # ── conversations (Assistant thread storage) ──────────────────────────────
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),  # UUID string — client-generated
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("account_id", sa.String(36)),
        sa.Column("messages", postgresql.JSONB, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_conversations_user", "conversations", ["user_id", "workspace_id"])
    op.create_index("ix_conversations_account", "conversations", ["account_id"])
    op.create_index("ix_conversations_updated", "conversations", ["updated_at"])

    # ── seed: default workspace for Invigilo internal use ─────────────────────
    op.execute("""
        INSERT INTO workspaces (id, name, slug, plan, settings)
        VALUES (
            '00000000-0000-0000-0000-000000000001',
            'Invigilo AI',
            'invigilo',
            'internal',
            '{"push_threshold": 0.85, "urgency_threshold": 0.7, "digest_hour_utc": 6}'::jsonb
        )
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.drop_table("conversations")
    op.drop_table("api_keys")
    op.drop_table("audit_log")
    op.drop_table("agent_runs")
    op.drop_table("interactions")
    op.drop_table("drafts")
    op.drop_table("signals")
    op.drop_table("accounts")
    op.drop_table("workspace_users")
    op.drop_table("workspaces")
    op.execute("DROP EXTENSION IF EXISTS vector;")
