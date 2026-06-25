"""
SQLAlchemy models — Account, Signal, Draft, Interaction, AgentRun
"""
from sqlalchemy import (
    Column, String, Text, DateTime, Boolean, Float, Integer,
    ForeignKey, func, CheckConstraint, Index, Numeric, Date
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
import uuid
from app.db.database import Base


class Account(Base):
    __tablename__ = "accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)

    # CRM identifiers
    hubspot_deal_id = Column(Text)
    hubspot_company_id = Column(Text)
    hubspot_last_modified = Column(DateTime(timezone=True))  # set when webhook fires

    # Core display fields (denormalised from ASO)
    name = Column(Text, nullable=False)
    stage = Column(Text)
    deal_amount = Column(Numeric(15, 2))
    close_date = Column(Date)
    owner_rep_id = Column(Text)            # HubSpot owner ID
    owner_user_id = Column(UUID(as_uuid=True), ForeignKey("workspace_users.id"))

    # Full Account State Object — the ASO
    state = Column(JSONB, default={})

    # Denormalised quick-access (for fast ORDER BY / WHERE)
    health_score = Column(Float, CheckConstraint("health_score BETWEEN 0 AND 1"))
    urgency_score = Column(Float, CheckConstraint("urgency_score BETWEEN 0 AND 1"))
    pov_forecast_cat = Column(Text)        # Pipeline | Forecast | Best Case | Commit
    pov_confidence = Column(Float)
    icp_score = Column(Float)              # ICP fit score 0-1 from ResearcherAgent

    # Agent tracking
    last_agent_run_at = Column(DateTime(timezone=True))
    agent_run_count = Column(Integer, default=0)

    # Vector embedding for semantic search
    embedding = Column(Vector(1536))

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True))

    # Relationships
    workspace = relationship("Workspace", back_populates="accounts")
    signals = relationship("Signal", back_populates="account", cascade="all, delete-orphan")
    drafts = relationship("Draft", back_populates="account", cascade="all, delete-orphan")
    interactions = relationship("Interaction", back_populates="account", cascade="all, delete-orphan")
    timeline_actions = relationship("TimelineAction", back_populates="account", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_accounts_workspace_urgency", "workspace_id", "urgency_score"),
        Index("idx_accounts_workspace_health", "workspace_id", "health_score"),
        Index("idx_accounts_hubspot", "workspace_id", "hubspot_deal_id", unique=True),
    )


class Signal(Base):
    __tablename__ = "signals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)

    # Classification
    type = Column(Text, nullable=False)
    # champion_activity | competitive_mention | champion_dark | deal_slip
    # | usage_drop | champion_role_change | leadership_change | funding_event
    # | product_launch | news_mention | gong_call | hubspot_change

    urgency = Column(Text, nullable=False)       # high | medium | low
    urgency_score = Column(Float, nullable=False)

    detail = Column(Text)
    source = Column(Text)
    source_url = Column(Text)
    confidence = Column(Float)

    # Gold Data Layer — full audit trail (our differentiator)
    gold_sources = Column(JSONB)
    # [{source, raw_value, confidence, updated_at, weight}, ...]
    gold_resolution = Column(Text)
    gold_confidence = Column(Float)

    # Processing
    processed = Column(Boolean, default=False)
    processed_at = Column(DateTime(timezone=True))
    pushed_to_inbox = Column(Boolean, default=False)
    notification_sent = Column(Boolean, default=False)
    acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(Text)

    agent_run_id = Column(UUID(as_uuid=True))
    detected_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    account = relationship("Account", back_populates="signals")

    __table_args__ = (
        Index("idx_signals_account_unprocessed", "account_id", postgresql_where="processed = FALSE"),
        Index("idx_signals_workspace_urgent", "workspace_id", "urgency_score"),
    )


class Draft(Base):
    __tablename__ = "drafts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)

    type = Column(Text, nullable=False)
    # email_followup | meeting_brief | outreach_sequence | risk_summary | forecasting_pov

    content = Column(Text, nullable=False)
    content_html = Column(Text)
    target_contact = Column(Text)
    subject_line = Column(Text)

    # Audit trail — every fact cited to source
    sources_cited = Column(JSONB, default=[])
    # [{fact, source, source_id, confidence, verified_by_grounding_agent}, ...]
    gold_data_used = Column(JSONB, default={})

    # Review outcome
    status = Column(Text, default="pending")
    # pending | approved | approved_modified | declined | expired | superseded

    content_modified = Column(Text)       # rep's edited version (if approved_modified)
    reviewer_id = Column(UUID(as_uuid=True), ForeignKey("workspace_users.id"))
    reviewed_by = Column(UUID(as_uuid=True))  # denorm for quick access
    reviewer_notes = Column(Text)          # Decline reason → episodic memory training
    final_content = Column(Text)
    reviewed_at = Column(DateTime(timezone=True))

    # CRM sync
    hubspot_email_id = Column(Text)       # HubSpot email object ID after push
    pushed_to_crm = Column(Boolean, default=False)
    crm_draft_id = Column(Text)
    crm_pushed_at = Column(DateTime(timezone=True))
    pushed_at = Column(DateTime(timezone=True))  # alias for push timestamp

    confidence = Column(Float)  # 0-1 from DrafterAgent

    agent_run_id = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True))

    account = relationship("Account", back_populates="drafts")

    __table_args__ = (
        Index("idx_drafts_account_pending", "account_id", postgresql_where="status = 'pending'"),
        Index("idx_drafts_workspace_pending", "workspace_id", postgresql_where="status = 'pending'"),
    )


class Interaction(Base):
    __tablename__ = "interactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)

    type = Column(Text, nullable=False)
    # call | email_sent | email_received | meeting | note
    # | agent_draft_approved | agent_draft_declined | chat_query | api_feedback

    source = Column(Text)    # hubspot | gong | manual | agent | mcp | api
    notes = Column(Text)
    outcome = Column(Text)

    sentiment = Column(Text)
    sentiment_score = Column(Float)

    rep_id = Column(UUID(as_uuid=True), ForeignKey("workspace_users.id"))
    contact_name = Column(Text)
    contact_email = Column(Text)

    # Training signal (from declined drafts → agent learning)
    is_training_signal = Column(Boolean, default=False)
    training_category = Column(Text)
    # wrong_tone | wrong_timing | wrong_content | hallucination | other

    occurred_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    account = relationship("Account", back_populates="interactions")

    __table_args__ = (
        Index("idx_interactions_account_time", "account_id", "occurred_at"),
        Index("idx_interactions_training", "workspace_id", postgresql_where="is_training_signal = TRUE"),
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False)

    trigger = Column(Text, nullable=False)
    # nightly_cron | webhook_deal_change | manual_refresh | signal_threshold | api_batch_refresh

    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))
    status = Column(Text, default="running")
    # running | completed | failed | partial | cancelled

    accounts_total = Column(Integer, default=0)
    accounts_processed = Column(Integer, default=0)
    accounts_failed = Column(Integer, default=0)
    signals_detected = Column(Integer, default=0)
    drafts_created = Column(Integer, default=0)

    # LLM cost tracking
    total_prompt_tokens = Column(Integer, default=0)
    total_completion_tokens = Column(Integer, default=0)
    total_cost_usd = Column(Numeric(10, 6), default=0)

    error_summary = Column(JSONB)
    triggered_by_user = Column(UUID(as_uuid=True), ForeignKey("workspace_users.id"))

    __table_args__ = (
        Index("idx_agent_runs_workspace", "workspace_id", "started_at"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True))
    user_id = Column(UUID(as_uuid=True))

    action = Column(Text, nullable=False)
    resource_type = Column(Text)
    resource_id = Column(Text)  # String ID (not UUID — supports external IDs)

    changes = Column(JSONB)
    extra_data = Column(JSONB)  # renamed from 'metadata' (reserved by SQLAlchemy)

    actor_id = Column(Text)  # user_id string or "hubspot_sync", "nightly_worker"
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_audit_log_workspace", "workspace_id", "created_at"),
        Index("idx_audit_log_user", "workspace_id", "actor_id"),
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)

    name = Column(Text, nullable=False)
    key_prefix = Column(Text, nullable=False)
    key_hash = Column(Text, nullable=False, unique=True)

    scopes = Column(ARRAY(Text), default=["read"])

    last_used_at = Column(DateTime(timezone=True))
    expires_at = Column(DateTime(timezone=True))

    created_by = Column(UUID(as_uuid=True), ForeignKey("workspace_users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    revoked_at = Column(DateTime(timezone=True))


class TimelineAction(Base):
    """
    One atomic action the agent has planned for a deal.
    The agent owns the sequence; the rep executes it.
    """
    __tablename__ = "timeline_actions"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id   = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), nullable=False)

    action_type = Column(Text, nullable=False)
    title       = Column(Text, nullable=False)
    reasoning   = Column(Text)

    due_date = Column(Date, nullable=False)
    priority = Column(Float, default=0.5)

    status          = Column(Text, default="upcoming")
    completed_at    = Column(DateTime(timezone=True))
    completed_notes = Column(Text)
    skipped_at      = Column(DateTime(timezone=True))
    skip_count      = Column(Integer, default=0)

    draft_id         = Column(UUID(as_uuid=True), ForeignKey("drafts.id", ondelete="SET NULL"), nullable=True)
    prepared_content = Column(JSONB)

    source        = Column(Text)
    source_ref_id = Column(Text)

    meddpicc_component     = Column(Text)
    deal_stage_at_creation = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    account = relationship("Account", back_populates="timeline_actions")

    __table_args__ = (
        Index("idx_timeline_actions_account_due", "account_id", "due_date"),
        Index("idx_timeline_actions_workspace_status", "workspace_id", "status", "due_date"),
    )


class ForecastSnapshot(Base):
    """
    Point-in-time snapshot of AI forecast vs CRM actuals.
    Used to measure forecast accuracy over time (F3 analytics).
    """
    __tablename__ = "forecast_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(UUID(as_uuid=True), nullable=False)
    run_date = Column(DateTime(timezone=True), server_default=func.now())
    pov_category = Column(Text)           # AI forecast: Commit/Best Case/Pipeline/Omit
    pov_amount = Column(Float)
    pov_close_date = Column(Date)
    crm_amount = Column(Float)
    crm_stage = Column(Text)
    crm_close_date = Column(Date)

    __table_args__ = (
        Index("idx_forecast_snapshots_workspace", "workspace_id", "run_date"),
    )
