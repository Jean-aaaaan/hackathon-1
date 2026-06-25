"""
Drafts router — Draft review, approval, decline.
GET  /v1/drafts                 — list pending drafts (Agent Inbox view)
GET  /v1/drafts/{id}            — single draft with full source citations
PATCH /v1/drafts/{id}           — approve | approve_modified | decline
POST /v1/drafts/{id}/send       — save approved draft to Outlook Drafts folder
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field
import structlog

from app.db.database import get_db
from app.middleware.auth import get_current_user, require_scope, CurrentUser
from app.models.account import Draft, Account, Interaction, AuditLog
from app.models.workspace import Workspace

log = structlog.get_logger()
router = APIRouter()


def _actor_uuid(current_user: "CurrentUser") -> Optional[uuid.UUID]:
    """Return the actor UUID for DB columns that must be NULL for API-key actions."""
    return uuid.UUID(current_user.user_id) if not current_user.is_api_key else None


# ── Request/Response schemas ──────────────────────────────────────────────────

class DraftReviewRequest(BaseModel):
    action: str = Field(..., pattern="^(approved|approved_modified|declined)$")
    modified_content: Optional[str] = Field(None, max_length=50000)
    reviewer_notes: Optional[str] = Field(None, max_length=2000)
    training_category: Optional[str] = Field(None, pattern="^(wrong_tone|wrong_timing|wrong_content|hallucination|other)$")


# ── Endpoints ─────────────────────────────────────────────────────────────────

# Draft types handled entirely inside the platform (not sent to contacts).
# Used to drive the is_internal filter + the is_internal flag in list responses.
INTERNAL_DRAFT_TYPES = {
    "close_plan_proposal", "renewal_brief", "competitive_displacement", "meeting_brief"
}

# Exhaustive allow-list for the draft_type filter query param.
# Keeps unknown values from silently matching zero rows and confusing callers.
_ALLOWED_DRAFT_TYPES = {
    "follow_up", "outreach", "proposal", "close_plan_proposal", "renewal_brief",
    "competitive_displacement", "meeting_brief", "objection_response", "executive_summary",
}


@router.get("")
async def list_drafts(
    status: str = Query("pending", pattern="^(pending|queued|approved|approved_modified|declined|superseded|expired)$"),
    account_id: Optional[str] = None,
    draft_type: Optional[str] = None,
    is_internal: Optional[bool] = None,
    page: int = 1,
    limit: int = Query(default=20, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List drafts for the Agent Inbox.
    Defaults to pending — the morning review queue.
    """
    q = (
        select(Draft)
        .join(Account, Draft.account_id == Account.id)
        .where(
            Account.workspace_id == current_user.workspace_id,
            Account.deleted_at.is_(None),
        )
        .options(selectinload(Draft.account))
    )

    q = q.where(Draft.status == status)
    if status == "pending":
        # Expired pending drafts are stale intelligence — a week-old draft
        # superseded by newer signals must not be approvable from the queue.
        q = q.where(
            (Draft.expires_at.is_(None))
            | (Draft.expires_at > datetime.now(timezone.utc))
        )
    if account_id:
        try:
            _acct_uuid = uuid.UUID(account_id)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="Invalid account_id format")
        q = q.where(Draft.account_id == _acct_uuid)
    if draft_type:
        if draft_type not in _ALLOWED_DRAFT_TYPES:
            raise HTTPException(status_code=400, detail=f"Unknown draft_type: {draft_type}")
        q = q.where(Draft.type == draft_type)
    if is_internal is True:
        q = q.where(Draft.type.in_(INTERNAL_DRAFT_TYPES))
    elif is_internal is False:
        q = q.where(Draft.type.notin_(INTERNAL_DRAFT_TYPES))

    # Reps see only their accounts; managers see all
    if not current_user.is_manager():
        q = q.where(Account.owner_rep_id == current_user.workos_user_id)

    # Total count before pagination
    count_q = select(func.count()).select_from(q.subquery())
    total_result = await db.execute(count_q)
    total = total_result.scalar_one()

    # Order: highest urgency first
    q = q.order_by(Account.urgency_score.desc().nullslast(), Draft.created_at.desc())
    q = q.offset((page - 1) * limit).limit(limit)

    result = await db.execute(q)
    drafts = result.scalars().all()

    return {
        "data": [_format_draft(d) for d in drafts],
        "meta": {"status_filter": status},
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "returned": len(drafts),
            "has_more": (page * limit) < total,
        },
    }


@router.get("/{draft_id}")
async def get_draft(
    draft_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a single draft with full source citations and Gold Data."""
    draft = await _get_draft_or_404(draft_id, current_user, db)
    # gold_data_used is omitted from list responses (expensive); include here for Audit Panel
    gold_data = draft.gold_data_used or {}
    return {
        "data": {**_format_draft(draft), "gold_data_used": gold_data},
        "meta": {"draft_id": draft_id},
    }


@router.patch("/{draft_id}")
async def review_draft(
    draft_id: str,
    body: DraftReviewRequest,
    current_user: CurrentUser = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    """
    Approve, approve with modifications, or decline a draft.
    Declined drafts with training_category become training signals
    that improve future agent output.
    """
    draft = await _get_draft_or_404(draft_id, current_user, db)

    if draft.status in ("superseded", "expired"):
        raise HTTPException(
            status_code=409,
            detail=f"Draft cannot be changed (status: {draft.status})"
        )

    if (
        body.action in ("approved", "approved_modified")
        and draft.expires_at is not None
        and draft.expires_at <= datetime.now(timezone.utc)
    ):
        raise HTTPException(
            status_code=409,
            detail="Draft has expired — re-run the agent for fresh intelligence before sending",
        )

    # Apply review
    previous_status = draft.status
    draft.status = body.action
    draft.reviewer_notes = body.reviewer_notes
    draft.reviewed_at = datetime.now(timezone.utc)
    draft.reviewed_by = _actor_uuid(current_user)

    if body.action == "approved_modified" and body.modified_content:
        draft.content_modified = body.modified_content

    # Training signal only when a category is supplied — uncategorised declines
    # are user noise (accidental clicks) and shouldn't pollute the training set.
    is_training = body.action == "declined" and body.training_category is not None
    if is_training:
        interaction = Interaction(
            account_id=draft.account_id,
            workspace_id=uuid.UUID(current_user.workspace_id),
            type="draft_declined",
            source="agent_inbox",
            notes=body.reviewer_notes or "",
            outcome=body.action,
            is_training_signal=True,
            training_category=body.training_category,
            rep_id=_actor_uuid(current_user),
            occurred_at=datetime.now(timezone.utc),
        )
        db.add(interaction)

    db.add(_make_draft_audit(
        f"draft_{body.action}",
        draft,
        current_user,
        {"status": {"before": previous_status, "after": body.action}, "training_category": body.training_category},
    ))
    await db.commit()

    log.info(
        "draft_reviewed",
        draft_id=draft_id,
        action=body.action,
        training=is_training,
        account_id=str(draft.account_id),
    )

    return {
        "data": {
            "draft_id": draft_id,
            "status": body.action,
            "training_signal_logged": is_training,
        },
        "meta": {},
    }


_EMAIL_PATTERN = r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$"

class SendDraftRequest(BaseModel):
    to: str = Field(..., max_length=254, pattern=_EMAIL_PATTERN)
    subject: str = Field(..., min_length=1, max_length=500)
    cc: Optional[str] = Field(None, max_length=254, pattern=_EMAIL_PATTERN)


@router.post("/{draft_id}/send")
async def save_draft_to_outlook(
    draft_id: str,
    body: SendDraftRequest,
    current_user: CurrentUser = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    """
    Save a Vantage draft to the rep's Outlook Drafts folder (does NOT send).
    The rep reviews and sends from Outlook themselves — human always in the loop.
    Requires Outlook to be connected in Settings.
    Marks draft status as 'approved' (not 'sent' — rep still needs to send).
    """
    # Deferred: outlook is optional — not all workspaces connect it, so importing
    # here avoids a hard startup failure when the integration is unconfigured.
    from app.integrations.outlook import OutlookClient
    from app.config import get_settings as _get_settings
    _settings = _get_settings()
    if not _settings.allow_outbound_email:
        raise HTTPException(
            status_code=403,
            detail="Outbound email is disabled. Set ALLOW_OUTBOUND_EMAIL=true in .env to enable.",
        )

    draft = await _get_draft_or_404(draft_id, current_user, db)
    if draft.status not in ("pending", "approved"):
        raise HTTPException(status_code=422, detail=f"Cannot save draft with status '{draft.status}'")
    # Idempotency: hubspot_email_id is reused as the Outlook message-id store; a
    # non-null value means this draft was already pushed — return 409 to prevent
    # duplicate Outlook drafts rather than silently creating a second copy.
    if draft.hubspot_email_id:
        raise HTTPException(
            status_code=409,
            detail="Draft already saved to Outlook. Open your Drafts folder to send it.",
        )

    # Check Outlook is connected
    ws_result = await db.execute(select(Workspace).where(Workspace.id == current_user.workspace_id))
    ws = ws_result.scalar_one_or_none()
    if not ws or not ws.outlook_access_token:
        raise HTTPException(status_code=422, detail="Outlook not connected. Go to Settings → Integrations to connect.")

    await _maybe_refresh_outlook_token(ws, db)

    # Create draft in Outlook Drafts folder (does NOT send)
    ol = OutlookClient(ws.outlook_access_token)
    content = draft.content_modified or draft.content
    result_data = await ol.create_draft(to=body.to, subject=body.subject, body=content, cc=body.cc)

    # Mark as approved (rep still needs to open Outlook and send)
    draft.status = "approved"
    draft.reviewed_at = datetime.now(timezone.utc)
    draft.reviewed_by = _actor_uuid(current_user)

    db.add(_make_draft_audit(
        "draft_saved_to_outlook",
        draft,
        current_user,
        {"to": body.to, "subject": body.subject, "outlook_message_id": result_data.get("message_id")},
    ))
    await db.commit()

    log.info("draft_saved_to_outlook", draft_id=draft_id, to=body.to, subject=body.subject[:60])
    return {
        "data": {
            "draft_id": draft_id,
            "status": "approved",
            "outlook_draft_created": True,
            "outlook_web_link": result_data.get("web_link"),
            "to": body.to,
            "subject": body.subject,
        },
        "meta": {},
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_draft_audit(action: str, draft: "Draft", current_user: "CurrentUser", changes: dict) -> AuditLog:
    """Build an AuditLog entry for a draft action (approve / decline / save)."""
    return AuditLog(
        workspace_id=uuid.UUID(current_user.workspace_id),
        action=action,
        resource_type="draft",
        resource_id=str(draft.id),
        actor_id=current_user.user_id,
        changes=changes,
    )

async def _maybe_refresh_outlook_token(ws: Workspace, db: AsyncSession) -> None:
    """
    Refresh the Outlook access token if expired.
    Raises 422 if the token is expired and no refresh token is available —
    silently proceeding would send a request that Outlook rejects with 401.
    Flushes token updates before returning so a crash between refresh and the
    final commit doesn't strand consumed (non-replayable) refresh tokens.
    """
    from app.integrations.outlook import refresh_access_token  # optional import

    # No expiry set → token is still valid; expiry in the future → also still valid
    if not ws.outlook_token_expires_at or ws.outlook_token_expires_at > datetime.now(timezone.utc):
        return

    if not ws.outlook_refresh_token:
        raise HTTPException(
            status_code=422,
            detail="Outlook token expired and no refresh token available. Reconnect in Settings → Integrations.",
        )

    try:
        tokens = await refresh_access_token(ws.outlook_refresh_token)
        ws.outlook_access_token = tokens["access_token"]
        if tokens.get("refresh_token"):
            ws.outlook_refresh_token = tokens["refresh_token"]
        ws.outlook_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))
        # Commit immediately — refresh tokens are consumed (non-replayable). A crash
        # between flush() and the later commit() would lose the new tokens permanently.
        await db.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Outlook token refresh failed: {e}")


async def _get_draft_or_404(
    draft_id: str,
    current_user: CurrentUser,
    db: AsyncSession,
) -> Draft:
    """
    Fetch a workspace-scoped draft, enforcing rep ownership for non-managers.
    Raises 404 on bad UUID or missing/out-of-scope draft — callers get a uniform
    error surface regardless of whether the draft exists but belongs to another rep.
    """
    try:
        _draft_uuid = uuid.UUID(draft_id)
    except (ValueError, AttributeError):
        # 404, not 400: callers get a uniform error surface whether the UUID is
        # malformed or belongs to another workspace — prevents enumeration.
        raise HTTPException(status_code=404, detail="Draft not found")

    q = (
        select(Draft)
        .join(Account, Draft.account_id == Account.id)
        .where(
            Draft.id == _draft_uuid,
            Account.workspace_id == current_user.workspace_id,
            Account.deleted_at.is_(None),
        )
        .options(selectinload(Draft.account))
    )
    if not current_user.is_manager():
        q = q.where(Account.owner_rep_id == current_user.workos_user_id)

    result = await db.execute(q)
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


def _format_draft(draft: Draft) -> dict:
    """Format a draft for list/detail responses."""
    # account is always eager-loaded via selectinload; None guard covers edge cases only
    account = draft.account
    gold = draft.gold_data_used or {}
    return {
        "id": str(draft.id),
        "type": draft.type,
        "status": draft.status,
        "content": draft.content,
        "subject_line": draft.subject_line,
        "target_contact": draft.target_contact,
        "account": {
            "id": str(draft.account_id),
            "name": account.name if account else None,
            "stage": account.stage if account else None,
            "urgency_score": account.urgency_score if account else None,
        },
        "expires_at": draft.expires_at.isoformat() if draft.expires_at else None,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "reviewed_at": draft.reviewed_at.isoformat() if draft.reviewed_at else None,
        "reviewer_notes": draft.reviewer_notes,
        "hubspot_email_id": draft.hubspot_email_id,
        # Confidence + sources (B1, B3)
        "confidence": draft.confidence,
        "sources_cited": draft.sources_cited or [],
        "is_internal": draft.type in INTERNAL_DRAFT_TYPES,
        # Play metadata — present when draft was auto-queued by PlaysEngine
        "play_triggered": bool(gold.get("play_triggered")),
        "play_name": gold.get("play_name"),
        "play_reason": gold.get("play_reason"),
    }
