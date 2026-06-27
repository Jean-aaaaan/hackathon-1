"""
Accounts router — Core account state API.
GET /v1/accounts — list with pagination, filtering, urgency sort
GET /v1/accounts/{id}/state — full ASO JSON
GET /v1/accounts/{id}/next-actions — prioritised actions
GET /v1/accounts/{id}/pov — AI Point of View
POST /v1/accounts/search — semantic search via pgvector
POST /v1/accounts/{id}/feedback — log interaction (episodic memory)
POST /v1/accounts/batch-refresh — trigger agent run
"""
import json as _json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import desc as sql_desc, select, func, and_, update as _upd
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified
from pydantic import BaseModel, Field
import structlog

import jwt as _jwt
from app.config import get_settings
from app.db.database import AsyncSessionLocal, get_db
from app.middleware.auth import get_current_user, require_scope, CurrentUser, require_manager
from app.models.account import Account, Draft as _Draft, Interaction
from app.models.workspace import WorkspaceUser
from app.services.account_service import AccountService
from app.services.plays_engine import BUILT_IN_PLAYS

log = structlog.get_logger()
router = APIRouter()

# ── Module-level constants ────────────────────────────────────────────────────

# Default number of accounts the nightly worker processes when no explicit list is given
_WORKER_DEFAULT_BATCH = 20

# Maximum SSE payload in bytes; parse+re-serialize rejects non-JSON and normalizes encoding
_SSE_MAX_PAYLOAD_BYTES = 65536

# Human-readable labels for decline training categories (shared by training-insights + chat)
_DECLINE_CATEGORY_LABELS: dict[str, str] = {
    "wrong_tone": "Wrong tone for this contact",
    "wrong_timing": "Wrong timing — too early or late",
    "already_sent": "Already sent something similar",
    "wrong_content": "Missing key context",
    "not_relevant": "Not relevant to current situation",
    "hallucination": "Fact not supported by account data",
    "other": "Other reason",
}

# Human-readable labels for win/loss reasons
_WIN_LOSS_REASON_LABELS: dict[str, str] = {
    "price": "Price too high",
    "champion": "Champion left",
    "timing": "Wrong timing",
    "no_budget": "No budget",
    "product_gap": "Product gap",
    "no_business_case": "No business case",
    "other": "Other",
}


# ── Request/Response schemas ─────────────────────────────────────────────────

class AccountListItem(BaseModel):
    id: str
    name: str
    stage: Optional[str]
    deal_amount: Optional[float]
    close_date: Optional[str]
    health_score: Optional[float]
    urgency_score: Optional[float]
    health_trend: Optional[str] = None  # "up" | "down" | "stable"
    pov_forecast_cat: Optional[str]
    pov_confidence: Optional[float]
    icp_score: Optional[float] = None
    pending_drafts: int = 0
    last_agent_run_at: Optional[str]
    signals_summary: list[dict] = []
    next_step: Optional[dict] = None
    deal_narrative: Optional[str] = None  # Flowing story of this deal
    top_risk_summary: Optional[str] = None  # One-sentence top risk

class FeedbackRequest(BaseModel):
    interaction_type: str = Field(..., pattern="^(call|email_sent|email_received|meeting|note|api_feedback|draft_declined)$")
    notes: str = Field(..., max_length=10000)
    outcome: Optional[str] = Field(None, max_length=500)
    is_training_signal: bool = False
    training_category: Optional[str] = Field(
        None,
        pattern="^(wrong_tone|wrong_timing|wrong_content|already_sent|not_relevant|hallucination|other)$",
    )

class SearchRequest(BaseModel):
    query: str = Field(..., max_length=1000)
    limit: int = Field(10, ge=1, le=50)
    min_urgency: Optional[float] = None
    stage: Optional[str] = Field(None, max_length=200)

class BatchRefreshRequest(BaseModel):
    account_ids: Optional[list[str]] = None  # None = filtered by stage_filter or all
    stage_filter: Optional[str] = None       # e.g. "Proposal" — ignored when account_ids set

class NextStepRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    due_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")

class SmartFieldApplyRequest(BaseModel):
    field_name: str = Field(..., max_length=100)
    suggested_value: str = Field(..., max_length=1000)  # HubSpot field value — validated against field type server-side


# ── Helpers ──────────────────────────────────────────────────────────────────

def _require_jwt_signing_key(detail: str = "Feature not configured. Set JWT_SIGNING_KEY in .env.") -> str:
    """Return the JWT signing key or raise 503. Centralises the guard used across share/stream endpoints."""
    settings = get_settings()
    if not settings.jwt_signing_key:
        raise HTTPException(status_code=503, detail=detail)
    return settings.jwt_signing_key


async def _get_account_or_404(
    account_id: str,
    current_user: CurrentUser,
    db: AsyncSession,
) -> Account:
    """Resolve account_id string → Account row, enforcing workspace + ownership scope."""
    service = AccountService(db)
    account = await service.get_account(
        account_id,
        current_user.workspace_id,
        owner_rep_id=None if current_user.is_manager() else current_user.workos_user_id,
    )
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


def _build_interaction(
    account_id_str: str,
    current_user: CurrentUser,
    interaction_type: str,
    source: str,
    notes: str,
    outcome: Optional[str] = None,
    is_training_signal: bool = False,
    training_category: Optional[str] = None,
    contact_name: Optional[str] = None,
    contact_email: Optional[str] = None,
) -> Interaction:
    """Construct an Interaction row; caller is responsible for db.add + commit."""
    return Interaction(
        account_id=uuid.UUID(account_id_str),
        workspace_id=uuid.UUID(current_user.workspace_id),
        type=interaction_type,
        source=source,
        notes=notes,
        outcome=outcome,
        is_training_signal=is_training_signal,
        training_category=training_category,
        rep_id=uuid.UUID(current_user.user_id) if not current_user.is_api_key else None,
        contact_name=contact_name,
        contact_email=contact_email,
        occurred_at=datetime.now(timezone.utc),
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
async def list_accounts(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort_by: str = Query("urgency_score", regex="^(urgency_score|health_score|deal_amount|close_date|name|updated_at)$"),
    sort_dir: str = Query("desc", regex="^(asc|desc)$"),
    stage: Optional[str] = None,
    owner_id: Optional[str] = None,
    min_urgency: Optional[float] = None,
    min_amount: Optional[float] = None,
    close_before: Optional[str] = None,       # YYYY-MM-DD — returns deals closing on/before this date
    has_pending_drafts: Optional[bool] = None,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List accounts sorted by urgency score (for Agent Inbox)."""
    service = AccountService(db)
    accounts, total = await service.list_accounts(
        workspace_id=current_user.workspace_id,
        page=page,
        limit=limit,
        sort_by=sort_by,
        sort_dir=sort_dir,
        stage=stage,
        # API keys have workos_user_id="" — skip the owner filter so they see all workspace accounts.
        owner_id=owner_id or (None if current_user.is_api_key else (current_user.workos_user_id if not current_user.is_manager() else None)),
        min_urgency=min_urgency,
        min_amount=min_amount,
        close_before=close_before,
        has_pending_drafts=has_pending_drafts,
    )

    # Return available stages for filter dropdown (unfiltered, across all workspace accounts)
    stages_result = await db.execute(
        select(Account.stage).where(
            Account.workspace_id == current_user.workspace_id,
            Account.deleted_at.is_(None),
            Account.stage.is_not(None),
        ).distinct().order_by(Account.stage)
    )
    available_stages = [r[0] for r in stages_result.fetchall() if r[0]]

    items = []
    for acc in accounts:
        state = acc.state or {}
        signals = state.get("signals", [])[:3]  # Top 3 signals for list view

        items.append(AccountListItem(
            id=str(acc.id),
            name=acc.name,
            stage=acc.stage,
            deal_amount=float(acc.deal_amount) if acc.deal_amount else None,
            close_date=str(acc.close_date) if acc.close_date else None,
            health_score=acc.health_score,
            urgency_score=acc.urgency_score,
            health_trend=(acc.state or {}).get("health_trend"),
            pov_forecast_cat=acc.pov_forecast_cat,
            pov_confidence=acc.pov_confidence,
            icp_score=acc.icp_score,
            pending_drafts=len([
                d for d in acc.drafts
                if d.status == "pending"
                and (d.expires_at is None or d.expires_at > datetime.now(timezone.utc))
            ]) if acc.drafts else 0,
            last_agent_run_at=acc.last_agent_run_at.isoformat() if acc.last_agent_run_at else None,
            signals_summary=[{
                "type": s.get("type"),
                "urgency": s.get("urgency"),
                "detail": s.get("detail", "")[:100],
            } for s in signals],
            next_step=(acc.state or {}).get("next_step"),
            deal_narrative=(acc.state or {}).get("pov", {}).get("deal_narrative"),
            top_risk_summary=(acc.state or {}).get("pov", {}).get("top_risk_summary"),
        ))

    return {
        "data": [i.model_dump() for i in items],
        "meta": {
            "workspace_id": current_user.workspace_id,
            "available_stages": available_stages,
        },
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "has_more": (page * limit) < total,
        },
    }


@router.get("/{account_id}/meeting-brief")
async def get_meeting_brief(
    account_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return pre-built meeting brief (generated nightly for top 5 urgent accounts).
    Returns 204 if no prebuilt brief exists — client should generate on demand.
    """
    account = await _get_account_or_404(account_id, current_user, db)

    brief = (account.state or {}).get("prebuilt_meeting_brief")
    if not brief:
        return Response(status_code=204)

    return {
        "data": brief,
        "meta": {
            "account_id": account_id,
            "source": "prebuilt",
            "generated_at": brief.get("generated_at") if isinstance(brief, dict) else None,
        },
    }


@router.get("/{account_id}/state")
async def get_account_state(
    account_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the full Account State Object (ASO) for an account."""
    # Redis cache-first: serve pre-computed ASO at <50ms
    from app.services.cache import get_cached_aso, cache_aso
    cached = await get_cached_aso(account_id, workspace_id=current_user.workspace_id)
    if cached:
        return {
            "data": cached,
            "meta": {
                "account_id": account_id,
                "workspace_id": current_user.workspace_id,
                "cached": True,
            },
        }

    account = await _get_account_or_404(account_id, current_user, db)

    # Populate cache for next request
    if account.state:
        await cache_aso(account_id, account.state, workspace_id=current_user.workspace_id)

    return {
        "data": account.state,
        "meta": {
            "account_id": account_id,
            "name": account.name,
            "last_agent_run_at": account.last_agent_run_at.isoformat() if account.last_agent_run_at else None,
            "workspace_id": current_user.workspace_id,
            "cached": False,
        },
    }


@router.get("/{account_id}/pov")
async def get_account_pov(
    account_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the AI Point of View for an account — forecast, risks, signals."""
    account = await _get_account_or_404(account_id, current_user, db)

    state = account.state or {}
    pov = state.get("pov", {})

    return {
        "data": {
            "pov": pov,
            "health_score": account.health_score,
            "urgency_score": account.urgency_score,
            "crm_stage": account.stage,
            "crm_close_date": str(account.close_date) if account.close_date else None,
            "crm_amount": float(account.deal_amount) if account.deal_amount else None,
            # Show delta between AI and CRM (our differentiator)
            "delta": {
                "ai_category": pov.get("forecast_category"),
                "crm_category": state.get("crm_forecast_category"),
                "ai_vs_crm": _compute_delta(pov, state),
            },
            # Gold Data Layer — fully auditable (shown in Audit Panel)
            "gold_data": state.get("gold_data", {}),
            "grounding_confidence": state.get("grounding_confidence"),
            "grounding_summary": state.get("grounding_summary"),
        },
        "meta": {"account_id": account_id, "workspace_id": current_user.workspace_id},
    }


@router.get("/{account_id}/next-actions")
async def get_next_actions(
    account_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return prioritised next actions for an account."""
    account = await _get_account_or_404(account_id, current_user, db)

    state = account.state or {}
    return {
        "data": {
            "next_actions": state.get("next_actions", []),
            "urgency_score": account.urgency_score,
        },
        "meta": {"account_id": account_id},
    }


@router.post("/search")
async def search_accounts(
    body: SearchRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Semantic search across all accounts via pgvector.
    Our key differentiator — Actively AI doesn't have this in public API.
    "find all accounts with competitive risk" → ranked by similarity.
    """
    service = AccountService(db)
    results = await service.semantic_search(
        workspace_id=current_user.workspace_id,
        query=body.query,
        limit=body.limit,
        min_urgency=body.min_urgency,
        stage=body.stage,
    )

    return {
        "data": results,
        "meta": {"query": body.query, "count": len(results)},
    }


@router.post("/{account_id}/feedback")
async def log_feedback(
    account_id: str,
    body: FeedbackRequest,
    current_user: CurrentUser = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    """
    Log an interaction to update the account's episodic memory.
    Training signals (from declined drafts) improve future agent output.
    """
    await _get_account_or_404(account_id, current_user, db)

    interaction = _build_interaction(
        account_id_str=account_id,
        current_user=current_user,
        interaction_type=body.interaction_type,
        source="api",
        notes=body.notes,
        outcome=body.outcome,
        is_training_signal=body.is_training_signal,
        training_category=body.training_category,
    )
    db.add(interaction)
    await db.commit()

    log.info("interaction_logged", account_id=account_id, type=body.interaction_type, training=body.is_training_signal)
    return {"data": {"interaction_id": str(interaction.id)}, "meta": {}}


@router.get("/{account_id}/notes")
async def get_account_notes(
    account_id: str,
    limit: int = Query(50, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return all interactions/notes for an account, newest first.
    Used by the War Room Notes tab.
    """
    await _get_account_or_404(account_id, current_user, db)

    result = await db.execute(
        select(Interaction)
        .where(
            Interaction.account_id == uuid.UUID(account_id),
            Interaction.workspace_id == uuid.UUID(current_user.workspace_id),
        )
        .order_by(sql_desc(Interaction.occurred_at))
        .limit(limit)
    )
    interactions = result.scalars().all()

    return {
        "data": [
            {
                "id": str(i.id),
                "type": i.type,
                "notes": i.notes,
                "outcome": i.outcome,
                "source": i.source,
                "occurred_at": i.occurred_at.isoformat() if i.occurred_at else None,
            }
            for i in interactions
        ],
        "meta": {"account_id": account_id, "count": len(interactions)},
    }


@router.get("/{account_id}/smart-fields")
async def get_smart_fields(
    account_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return pending Smart Field suggestions for an account.
    These are AI-suggested HubSpot field updates generated by the SmartFieldsAgent.
    """
    account = await _get_account_or_404(account_id, current_user, db)

    state = account.state or {}
    all_suggestions = state.get("smart_fields", [])
    pending = [s for s in all_suggestions if s.get("status", "pending") == "pending"]

    return {
        "data": {
            "suggestions": pending,
            "total": len(all_suggestions),
            "pending": len(pending),
        },
        "meta": {"account_id": account_id},
    }


@router.post("/{account_id}/smart-fields/dismiss")
async def dismiss_smart_field(
    account_id: str,
    body: SmartFieldApplyRequest,
    current_user: CurrentUser = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    """Dismiss a Smart Field suggestion without applying it to HubSpot."""
    account = await _get_account_or_404(account_id, current_user, db)

    state = account.state or {}
    suggestions = state.get("smart_fields", [])
    for s in suggestions:
        if s.get("field_name") == body.field_name and s.get("status") == "pending":
            s["status"] = "dismissed"
            s["dismissed_at"] = datetime.now(timezone.utc).isoformat()
            s["dismissed_by"] = current_user.user_id
            break

    account.state = {**state, "smart_fields": suggestions}
    # SQLAlchemy cannot detect in-place mutations to JSONB; flag_modified forces a dirty-mark
    flag_modified(account, "state")
    await db.commit()

    log.info("smart_field_dismissed", account_id=account_id, field=body.field_name)
    return {
        "data": {"dismissed": True, "field_name": body.field_name},
        "meta": {"account_id": account_id},
    }


@router.post("/{account_id}/next-step")
async def set_next_step(
    account_id: str,
    body: NextStepRequest,
    current_user: CurrentUser = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    """Set or override the rep-defined next step for an account."""
    account = await _get_account_or_404(account_id, current_user, db)

    state = dict(account.state or {})
    state["next_step"] = {
        "text": body.text.strip(),
        "due_date": body.due_date,
        "source": "rep",
        "set_by": current_user.user_id,
        "set_at": datetime.now(timezone.utc).isoformat(),
    }
    account.state = state
    # SQLAlchemy cannot detect in-place mutations to JSONB; flag_modified forces a dirty-mark
    flag_modified(account, "state")
    await db.commit()

    log.info("next_step_set", account_id=account_id, user=current_user.user_id)
    return {"data": {"next_step": state["next_step"]}, "meta": {"account_id": account_id}}


@router.post("/batch-refresh")
async def batch_refresh(
    body: BatchRefreshRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger immediate agent run for specified accounts (or all).
    Uses FastAPI BackgroundTasks (not asyncio.create_task) for proper anyio compatibility.
    """
    run_id = str(uuid.uuid4())
    ws_id = current_user.workspace_id

    # Server-side cap — prevent resource exhaustion via large batch requests
    MAX_BATCH = 50
    if body.account_ids and len(body.account_ids) > MAX_BATCH:
        raise HTTPException(
            status_code=422,
            detail=f"Batch refresh limit is {MAX_BATCH} accounts per request. Received {len(body.account_ids)}."
        )
    acct_ids: Optional[list[str]] = list(body.account_ids) if body.account_ids else None
    stage_filter: Optional[str] = body.stage_filter if not acct_ids else None

    async def _run_agents():
        """Runs in background after response is sent. Uses own DB session."""
        async with AsyncSessionLocal() as bg_db:
            try:
                from app.services.nightly_worker import NightlyWorker
                worker = NightlyWorker(bg_db)
                await worker._run_immediate_sync(
                    run_id=run_id,
                    workspace_id=ws_id,
                    account_ids=acct_ids,
                    stage_filter=stage_filter,
                )
                log.info("batch_refresh_complete", run_id=run_id)
            except Exception as e:
                log.error("batch_refresh_bg_failed", run_id=run_id, error=str(e))

    background_tasks.add_task(_run_agents)
    # When no explicit IDs given, worker defaults to _WORKER_DEFAULT_BATCH accounts; reflect that here
    account_count = len(acct_ids) if acct_ids else _WORKER_DEFAULT_BATCH
    log.info("batch_refresh_started", run_id=run_id, workspace_id=ws_id, count=account_count, stage_filter=stage_filter)
    return {"data": {"run_id": run_id, "status": "queued", "account_count": account_count}, "meta": {}}


@router.get("/{account_id}/plays")
async def get_plays(
    account_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return fired plays (play-triggered drafts) + available plays (unfired conditions)
    for an account. Used in the War Room Plays tab.
    """
    account = await _get_account_or_404(account_id, current_user, db)

    # Fired plays: drafts where play_triggered=true in gold_data_used
    result = await db.execute(
        select(_Draft)
        .where(
            _Draft.account_id == uuid.UUID(account_id),
            _Draft.gold_data_used["play_triggered"].astext == "true",
        )
        .order_by(sql_desc(_Draft.created_at))
        .limit(20)
    )
    play_drafts = result.scalars().all()

    fired = [
        {
            "draft_id": str(d.id),
            "play_name": (d.gold_data_used or {}).get("play_name", d.type),
            "play_reason": (d.gold_data_used or {}).get("play_reason", ""),
            "play_description": (d.gold_data_used or {}).get("play_description", ""),
            "draft_type": d.type,
            "status": d.status,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in play_drafts
    ]

    # Available plays: evaluate conditions against current ASO without firing
    state = account.state or {}
    available = []
    for play in BUILT_IN_PLAYS:
        try:
            should_fire, reason = play.should_fire(state)
            if should_fire:
                available.append({
                    "play_name": play.name,
                    "draft_type": play.draft_type,
                    "reason": reason,
                    "description": play.description,
                    "cooldown_hours": play.cooldown_hours,
                })
        except Exception:
            pass

    return {
        "data": {"fired": fired, "available": available},
        "meta": {"account_id": account_id},
    }


@router.get("/{account_id}/transcripts")
async def get_transcripts(
    account_id: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return Fireflies transcripts stored in account ASO."""
    account = await _get_account_or_404(account_id, current_user, db)

    state = account.state or {}
    transcripts = state.get("transcripts", [])
    start = (page - 1) * limit

    # Conversation rollup + freshness-derived fields (never stored stale)
    intel = dict(state.get("conversation_intel") or {})
    last_call_ms = intel.get("last_call_date")
    if last_call_ms:
        try:
            last_call = datetime.fromtimestamp(last_call_ms / 1000, tz=timezone.utc)
            intel["days_since_last_call"] = (datetime.now(timezone.utc) - last_call).days
        except (TypeError, ValueError, OSError):
            intel["days_since_last_call"] = None
    else:
        intel["days_since_last_call"] = None

    return {
        "data": transcripts[start:start + limit],
        "intel": intel,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": len(transcripts),
            "has_more": start + limit < len(transcripts),
        },
        "meta": {"account_id": account_id},
    }


@router.post("/{account_id}/share")
async def create_share_link(
    account_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a 7-day read-only share token for an account brief."""
    await _get_account_or_404(account_id, current_user, db)

    secret = _require_jwt_signing_key("Share links are not configured. Set JWT_SIGNING_KEY in .env.")
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    token = _jwt.encode(
        {
            "account_id": account_id,
            "workspace_id": current_user.workspace_id,
            "exp": expires_at,
            "iat": datetime.now(timezone.utc),
            "aud": "share_link",
        },
        secret,
        algorithm="HS256",
    )

    share_url = f"{settings.frontend_url}/share/{token}"
    return {
        "data": {
            "share_url": share_url,
            "expires_at": expires_at.isoformat(),
        },
        "meta": {"account_id": account_id},
    }


@router.get("/share/{token}")
async def get_shared_brief(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Public read-only endpoint for shared account brief. No auth required."""
    secret = _require_jwt_signing_key("Share links not configured")

    try:
        payload = _jwt.decode(token, secret, algorithms=["HS256"], audience="share_link")
        account_id = payload["account_id"]
        workspace_id = payload["workspace_id"]
        # UUID parse inside the same block so both failure modes raise the same 401
        _share_acct_uuid = uuid.UUID(account_id)
        _share_ws_uuid = uuid.UUID(workspace_id)
    except _jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Share link has expired")
    except Exception as e:
        log.warning("share_link_invalid", error=type(e).__name__)
        raise HTTPException(status_code=401, detail="Invalid share link")

    result = await db.execute(
        select(Account).where(
            Account.id == _share_acct_uuid,
            Account.workspace_id == _share_ws_uuid,
            Account.deleted_at.is_(None),
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    state = account.state or {}
    pov = state.get("pov", {})

    # Scrub internal-only fields — share links are external-facing, strip strategy/stakeholder data
    _safe_signals = [
        {"summary": s.get("summary", ""), "severity": s.get("severity")}
        for s in (state.get("signals") or [])[:3]
        if s.get("summary")
    ]
    return {
        "data": {
            "account_name": account.name,
            "stage": account.stage,
            "deal_amount": float(account.deal_amount) if account.deal_amount else None,
            "health_score": account.health_score,
            "ai_forecast": pov.get("forecast_category"),
            "ai_confidence": pov.get("forecast_confidence"),
            "top_signals": _safe_signals,
            "meddpicc_overall": (pov.get("meddpicc") or {}).get("overall_score"),
        },
        "meta": {"account_id": account_id, "expires_in_days": 7},
    }


@router.get("/{account_id}/stream-token")
async def get_stream_token(
    account_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Issue a short-lived (90s) token for the SSE stream endpoint.
    Required because EventSource (browser API) cannot send Authorization headers.
    Frontend: fetch this token, then open EventSource with ?t=<token> in the URL.
    """
    secret = _require_jwt_signing_key("Streaming not configured")

    # Verify the account belongs to this workspace before issuing the token
    result = await db.execute(
        select(Account.id).where(
            Account.id == uuid.UUID(account_id),
            Account.workspace_id == uuid.UUID(current_user.workspace_id),
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Account not found")

    expires_at = datetime.now(timezone.utc) + timedelta(seconds=90)
    # user_id intentionally omitted — SSE tokens appear in access logs (?t=...) and
    # stripping user_id prevents PII exposure via log-level attackers
    token = _jwt.encode(
        {
            "account_id": account_id,
            "workspace_id": current_user.workspace_id,
            "exp": expires_at,
            "iat": datetime.now(timezone.utc),
            "aud": "sse_stream",
        },
        secret,
        algorithm="HS256",
    )
    return {"data": {"token": token, "expires_in": 90}, "meta": {}}


@router.get("/{account_id}/stream")
async def stream_account_updates(
    account_id: str,
    t: Optional[str] = None,  # short-lived SSE token from /stream-token (required)
    db: AsyncSession = Depends(get_db),
):
    """
    SSE stream for real-time account updates.
    Auth: pass a short-lived token via ?t= (obtained from GET /stream-token).
    EventSource cannot send Authorization headers, so Bearer auth is not used here.
    """
    secret = _require_jwt_signing_key("Streaming not available: server not configured")

    # Validate the short-lived SSE token (required — no fallback to Bearer here)
    if not t:
        raise HTTPException(status_code=401, detail="Stream token required. Fetch from /stream-token first.")
    try:
        payload = _jwt.decode(t, secret, algorithms=["HS256"], audience="sse_stream")
        if payload.get("account_id") != account_id:
            raise ValueError("account mismatch")
        workspace_id = payload["workspace_id"]
    except _jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Stream token expired. Refresh and reconnect.")
    except Exception as e:
        log.warning("sse_token_invalid", error=type(e).__name__)
        raise HTTPException(status_code=401, detail="Invalid stream token")

    result = await db.execute(
        select(Account.id).where(
            Account.id == uuid.UUID(account_id),
            Account.workspace_id == uuid.UUID(workspace_id),
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Account not found")

    channel = f"account:{workspace_id}:{account_id}"

    async def event_generator():
        pubsub = None
        try:
            from app.services.cache import get_redis
            redis_client = await get_redis()
            if not redis_client:
                yield "data: {\"type\": \"connected\"}\n\n"
                return

            pubsub = redis_client.pubsub()
            await pubsub.subscribe(channel)
            yield "data: {\"type\": \"connected\"}\n\n"

            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode()
                    if not isinstance(data, str) or len(data) > _SSE_MAX_PAYLOAD_BYTES:
                        continue
                    try:
                        yield f"data: {_json.dumps(_json.loads(data))}\n\n"
                    except Exception:
                        pass
        except Exception as e:
            log.warning("sse_stream_error", account_id=account_id, error=str(e))
            yield "data: {\"type\": \"error\"}\n\n"
        finally:
            if pubsub:
                try:
                    await pubsub.unsubscribe(channel)
                except Exception:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{account_id}/notes")
async def post_note(
    account_id: str,
    body: FeedbackRequest,
    current_user: CurrentUser = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    """
    Post a note to an account. Stores with author attribution.
    Alias for feedback endpoint with note type — convenience for War Room Notes tab.
    """
    await _get_account_or_404(account_id, current_user, db)

    # Get author name from workspace users
    author_name = None
    author_email = None
    if not current_user.is_api_key:
        try:
            wu_result = await db.execute(
                select(WorkspaceUser).where(
                    WorkspaceUser.id == uuid.UUID(current_user.user_id),
                    WorkspaceUser.workspace_id == uuid.UUID(current_user.workspace_id),
                ).limit(1)
            )
            wu = wu_result.scalar_one_or_none()
            if wu:
                author_name = wu.name or wu.email
                author_email = wu.email
        except Exception:
            pass

    interaction = _build_interaction(
        account_id_str=account_id,
        current_user=current_user,
        interaction_type="note",
        source="rep",
        notes=body.notes,
        outcome=body.outcome,
        is_training_signal=body.is_training_signal,
        training_category=body.training_category,
        contact_name=author_name,
        contact_email=author_email,
    )
    db.add(interaction)
    await db.commit()

    log.info("note_posted", account_id=account_id, author=author_name or current_user.user_id)
    return {
        "data": {
            "interaction_id": str(interaction.id),
            "author_name": author_name,
            "author_id": current_user.user_id,
        },
        "meta": {},
    }


@router.get("/{account_id}/training-insights")
async def get_training_insights(
    account_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return what the AI agent has learned from feedback for this account.
    Shows decline patterns, most common reasons, and draft improvement status.
    """
    await _get_account_or_404(account_id, current_user, db)

    # Decline patterns by category (last 90 days)
    pattern_result = await db.execute(
        select(
            Interaction.training_category,
            func.count().label("count"),
        )
        .where(
            Interaction.account_id == uuid.UUID(account_id),
            Interaction.workspace_id == uuid.UUID(current_user.workspace_id),
            Interaction.is_training_signal == True,
            Interaction.training_category.is_not(None),
            Interaction.occurred_at >= datetime.now(timezone.utc) - timedelta(days=90),
        )
        .group_by(Interaction.training_category)
        .order_by(sql_desc("count"))
    )
    patterns = [{"category": r.training_category, "count": r.count} for r in pattern_result.fetchall()]

    # Recent decline details (last 10)
    recent_result = await db.execute(
        select(Interaction)
        .where(
            Interaction.account_id == uuid.UUID(account_id),
            Interaction.workspace_id == uuid.UUID(current_user.workspace_id),
            Interaction.type == "draft_declined",
        )
        .order_by(sql_desc(Interaction.occurred_at))
        .limit(10)
    )
    recent_declines = [
        {
            "date": i.occurred_at.strftime("%Y-%m-%d") if i.occurred_at else None,
            "category": i.training_category or "other",
            "notes": i.notes or "",
        }
        for i in recent_result.scalars().all()
    ]

    # Total declines — used to show volume trend to the rep
    totals_result = await db.execute(
        select(
            func.count().filter(Interaction.type == "draft_declined").label("declined"),
        )
        .where(
            Interaction.account_id == uuid.UUID(account_id),
            Interaction.workspace_id == uuid.UUID(current_user.workspace_id),
        )
    )
    totals = totals_result.fetchone()
    total_declines = totals.declined if totals else 0

    # Top decline category = what the agent is currently learning from
    top_category = patterns[0]["category"] if patterns else None

    summary = (
        f"Agent has learned {top_category} is the main issue ({patterns[0]['count']} times). "
        f"Future drafts are adjusted to avoid this pattern."
    ) if (patterns and top_category) else None

    return {
        "data": {
            "total_declines": total_declines,
            "top_category": top_category,
            "top_category_label": _DECLINE_CATEGORY_LABELS.get(top_category, top_category) if top_category else None,
            "patterns": patterns,
            "recent_declines": recent_declines,
            "learning_summary": summary,
            "category_labels": _DECLINE_CATEGORY_LABELS,
        },
        "meta": {"account_id": account_id},
    }


class WinLossRequest(BaseModel):
    outcome: str = Field(..., pattern="^(won|lost)$")
    reason: str = Field(..., pattern="^(price|champion|timing|competition|no_budget|product_gap|no_business_case|other)$")
    competitor: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = Field(None, max_length=2000)


@router.post("/{account_id}/win-loss")
async def capture_win_loss(
    account_id: str,
    body: WinLossRequest,
    current_user: CurrentUser = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    """Capture why a deal was won or lost. Stored for agent learning."""
    account = await _get_account_or_404(account_id, current_user, db)

    state = dict(account.state or {})
    state["win_loss"] = {
        "outcome": body.outcome,
        "reason": body.reason,
        "competitor": body.competitor,
        "notes": body.notes,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    # Raw UPDATE bypasses ORM identity map — avoids flag_modified + avoids a second SELECT on already-loaded account
    await db.execute(_upd(Account).where(Account.id == account.id).values(state=state))

    # competition label includes dynamic competitor name; build it separately
    competition_label = f"Lost to competitor{': ' + body.competitor if body.competitor else ''}"
    reason_label = competition_label if body.reason == "competition" else _WIN_LOSS_REASON_LABELS.get(body.reason, body.reason)
    interaction = Interaction(
        account_id=account.id,
        workspace_id=account.workspace_id,
        type=f"deal_{body.outcome}",
        source="rep",
        notes=f"Deal {body.outcome}: {reason_label}. {body.notes or ''}".strip(),
        outcome=body.reason,
        occurred_at=datetime.now(timezone.utc),
        is_training_signal=True,
    )
    db.add(interaction)
    await db.commit()
    return {"data": {"captured": True, "outcome": body.outcome}, "meta": {}}


def _compute_delta(pov: dict, state: dict) -> Optional[str]:
    """Return a human-readable disagreement string between AI and CRM.

    String comparison is intentional — both fields are categorical labels
    (e.g. "Commit", "Best Case") not numbers, so equality is the right test.
    """
    ai_cat = pov.get("forecast_category")
    crm_cat = state.get("crm_forecast_category")
    if not ai_cat or not crm_cat:
        return None
    if ai_cat == crm_cat:
        return "AI agrees with CRM"
    return f"AI says '{ai_cat}', CRM says '{crm_cat}'"
