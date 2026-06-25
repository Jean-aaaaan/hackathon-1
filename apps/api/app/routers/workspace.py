"""
Workspace router — Workspace settings, integrations, team management, usage.
GET  /v1/workspace              — workspace info + integration status
GET  /v1/workspace/usage        — LLM costs, DAR, account coverage
PATCH /v1/workspace/settings    — update settings (thresholds, Slack webhook)
GET  /v1/workspace/team         — list workspace users
POST /v1/workspace/team/invite  — invite user (WorkOS)
GET  /v1/workspace/integrations/hubspot — HubSpot connection status
POST /v1/workspace/integrations/hubspot/connect — initiate OAuth
POST /v1/workspace/integrations/hubspot/disconnect — revoke
POST /v1/workspace/integrations/hubspot/sync — re-pull all deals (resolves stage labels, etc.)
GET  /v1/workspace/api-keys     — list API keys (hashes only)
POST /v1/workspace/api-keys     — create new key
DELETE /v1/workspace/api-keys/{id} — revoke
"""
import asyncio
import uuid
import secrets
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import json as _json
from pydantic import BaseModel, Field, field_validator
import structlog

from app.db.database import get_db
from app.middleware.auth import get_current_user, CurrentUser, require_manager
from app.models.workspace import Workspace, WorkspaceUser
from app.models.account import Account, AgentRun, Draft, ApiKey, Interaction
from app.config import get_settings

log = structlog.get_logger()
router = APIRouter()

# Keys blocked from being written via settings API (tokens stored via dedicated columns)
_SETTINGS_SENSITIVE_KEYS = frozenset({
    "hubspot_access_token", "hubspot_refresh_token",
    "outlook_access_token", "outlook_refresh_token",
    "gong_access_token", "perplexity_api_key",
    "fireflies_api_key", "teams_webhook_url_secret",
    "workos_api_key", "anthropic_api_key",
    "jwt_signing_key", "encryption_key",
})

# Additional keys stripped from GET responses (webhook URLs contain bearer secrets)
_SETTINGS_RESPONSE_REDACTED = _SETTINGS_SENSITIVE_KEYS | {"teams_webhook_url", "slack_webhook_url"}

def _safe_settings(settings: dict) -> dict:
    """Strip sensitive keys before returning settings to the client."""
    return {k: v for k, v in settings.items() if k not in _SETTINGS_RESPONSE_REDACTED}


# ── Request/Response schemas ──────────────────────────────────────────────────

_SECRET_KEY_PATTERNS = ("_token", "_secret", "_key", "_password", "_credential")


class WorkspaceSettingsUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    @classmethod
    def model_validate(cls, obj, **kw):
        if isinstance(obj, dict):
            blocked = _SETTINGS_SENSITIVE_KEYS & set(obj.keys())
            if blocked:
                from fastapi import HTTPException as _HTTPException
                raise _HTTPException(status_code=422, detail=f"Cannot store sensitive keys in settings: {blocked}")
            # Reject keys that look like secrets even if not in the explicit blocklist
            suspicious = [
                k for k in obj.keys()
                if any(k.lower().endswith(p) for p in _SECRET_KEY_PATTERNS)
                and k not in {
                    "slack_webhook_url", "teams_webhook_url",
                    "auto_apply_smart_fields_threshold", "auto_push_to_hubspot",
                }
            ]
            if suspicious:
                from fastapi import HTTPException as _HTTPException
                raise _HTTPException(status_code=422, detail=f"Rejected keys with secret-like names: {suspicious}")
        return super().model_validate(obj, **kw)

    push_threshold: Optional[float] = Field(None, ge=0.5, le=1.0)
    urgency_threshold: Optional[float] = Field(None, ge=0.5, le=1.0)
    slack_webhook_url: Optional[str] = None
    teams_webhook_url: Optional[str] = None
    digest_hour_utc: Optional[int] = Field(None, ge=0, le=23)
    auto_push_to_hubspot: Optional[bool] = None
    # Sender identity (used by DrafterAgent to sign emails)
    sender_name: Optional[str] = None
    sender_title: Optional[str] = None
    sender_company: Optional[str] = None
    product_description: Optional[str] = None
    # Self-driving CRM settings
    hubspot_writeback_enabled: Optional[bool] = None
    auto_apply_smart_fields_threshold: Optional[float] = Field(None, ge=0.65, le=1.0)
    # AI customisation
    ai_fields: Optional[list[dict]] = Field(None, max_length=50)
    automation_rules: Optional[list[dict]] = Field(None, max_length=50)
    webhook_subscriptions: Optional[list[dict]] = Field(None, max_length=20)
    voice_profile: Optional[dict] = None  # Writing voice fingerprint for DrafterAgent
    icp_profile: Optional[dict] = None   # ICP scoring profile for ResearcherAgent

    @field_validator("voice_profile", "icp_profile", mode="before")
    @classmethod
    def _cap_profile_size(cls, v):
        if v is not None and len(_json.dumps(v)) > 51200:
            raise ValueError("Profile exceeds maximum allowed size (50KB)")
        return v


async def _validate_webhook_url(url: str) -> None:
    """
    Reject internal/private URLs to prevent SSRF via outbound webhook registration.
    Azure IMDS (169.254.169.254) and all RFC-1918 ranges are blocked.
    DNS resolution runs in a thread executor (non-blocking).
    """
    import asyncio
    import ipaddress
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(status_code=422, detail="Webhook URL must use HTTPS")
    if not parsed.hostname:
        raise HTTPException(status_code=422, detail="Webhook URL must have a valid hostname")

    try:
        loop = asyncio.get_event_loop()
        infos = await loop.run_in_executor(None, socket.getaddrinfo, parsed.hostname, None)
    except socket.gaierror:
        raise HTTPException(status_code=422, detail="Webhook URL hostname does not resolve")

    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast:
            raise HTTPException(
                status_code=422,
                detail="Webhook URL cannot point to a private, loopback, or link-local address"
            )


_ALLOWED_WEBHOOK_EVENTS = frozenset({
    "all", "signal.critical", "signal.high", "draft.created", "draft.approved",
    "draft.declined", "health.dropped", "agent.run_complete", "account.stage_changed", "play.fired",
})

class WebhookSubscriptionRequest(BaseModel):
    url: str = Field(..., max_length=2000)
    events: list[str] = Field(default_factory=lambda: ["all"], max_length=20)
    secret: Optional[str] = Field(None, min_length=32, max_length=256)

    @classmethod
    def model_validate(cls, obj, **kw):
        validated = super().model_validate(obj, **kw)
        bad_events = set(validated.events) - _ALLOWED_WEBHOOK_EVENTS
        if bad_events:
            from fastapi import HTTPException as _HTTPException
            raise _HTTPException(status_code=422, detail=f"Unknown webhook events: {bad_events}")
        return validated

_EMAIL_RE = r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$"

class InviteRequest(BaseModel):
    email: str = Field(..., max_length=254, pattern=_EMAIL_RE)
    role: str = Field("rep", pattern="^(rep|manager)$")

class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    scopes: list[str] = Field(default_factory=lambda: ["read"])

    @classmethod
    def model_validate(cls, obj, **kw):
        validated = super().model_validate(obj, **kw)
        allowed = {"read", "write"}
        bad = set(validated.scopes) - allowed
        if bad:
            from fastapi import HTTPException as _HTTPException
            raise _HTTPException(status_code=422, detail=f"Invalid scopes: {bad}. Allowed: {allowed}")
        return validated


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
async def get_workspace(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return workspace info and integration status."""
    result = await db.execute(
        select(Workspace).where(Workspace.id == current_user.workspace_id)
    )
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    return {
        "data": {
            "id": str(ws.id),
            "name": ws.name,
            "slug": ws.slug,
            "plan": ws.plan,
            "settings": _safe_settings(ws.settings or {}),
            "integrations": {
                "hubspot": {
                    "connected": bool(ws.hubspot_access_token),
                    "portal_id": ws.hubspot_portal_id,
                },
                "outlook": {
                    "connected": bool(ws.outlook_access_token),
                    "user_email": ws.outlook_user_email,
                },
                "gong": {
                    "connected": bool(ws.gong_access_token),
                },
                "perplexity": {
                    # Connected via workspace key OR the env-level key — the
                    # settings UI showed "Not connected" while research was
                    # actively running off the env key.
                    "connected": bool(ws.perplexity_api_key or get_settings().perplexity_api_key),
                },
            },
            "created_at": ws.created_at.isoformat() if ws.created_at else None,
        },
        "meta": {"workspace_id": current_user.workspace_id},
    }


@router.get("/usage")
async def get_usage(
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """
    Return LLM cost breakdown, DAR, and account coverage.
    Managers and above only.
    """

    # Account coverage
    account_count = await db.execute(
        select(func.count()).where(
            Account.workspace_id == current_user.workspace_id,
            Account.deleted_at.is_(None),
        )
    )
    total_accounts = account_count.scalar_one()

    accounts_with_runs = await db.execute(
        select(func.count()).where(
            Account.workspace_id == current_user.workspace_id,
            Account.deleted_at.is_(None),
            Account.last_agent_run_at.is_not(None),
        )
    )
    covered_accounts = accounts_with_runs.scalar_one()

    # Draft Acceptance Rate (DAR) — North Star KPI
    all_drafts = await db.execute(
        select(func.count(Draft.id))
        .join(Account, Draft.account_id == Account.id)
        .where(Account.workspace_id == current_user.workspace_id)
    )
    total_drafts = all_drafts.scalar_one()

    approved_drafts = await db.execute(
        select(func.count(Draft.id))
        .join(Account, Draft.account_id == Account.id)
        .where(
            Account.workspace_id == current_user.workspace_id,
            Draft.status.in_(["approved", "approved_modified"]),
        )
    )
    total_approved = approved_drafts.scalar_one()

    reviewed_drafts = await db.execute(
        select(func.count(Draft.id))
        .join(Account, Draft.account_id == Account.id)
        .where(
            Account.workspace_id == current_user.workspace_id,
            Draft.status.in_(["approved", "approved_modified", "declined"]),
        )
    )
    total_reviewed = reviewed_drafts.scalar_one()

    # DAR = approved ÷ reviewed — pending/superseded/expired are not decisions.
    # Must match the definition in analytics.py get_overview.
    dar = round(total_approved / total_reviewed, 4) if total_reviewed > 0 else 0.0

    # LLM cost (last 30 days)
    from sqlalchemy import text as sql_text
    cost_result = await db.execute(
        sql_text("""
            SELECT
                COALESCE(SUM(total_cost_usd), 0) AS total_cost,
                COALESCE(SUM(total_prompt_tokens), 0) AS prompt_tokens,
                COALESCE(SUM(total_completion_tokens), 0) AS completion_tokens,
                COUNT(*) AS run_count
            FROM agent_runs
            WHERE workspace_id = :ws_id
              AND created_at >= NOW() - INTERVAL '30 days'
        """),
        {"ws_id": current_user.workspace_id},
    )
    cost_row = cost_result.fetchone()

    return {
        "data": {
            "accounts": {
                "total": total_accounts,
                "covered": covered_accounts,
                "coverage_pct": round(covered_accounts / total_accounts, 4) if total_accounts > 0 else 0.0,
            },
            "drafts": {
                "total": total_drafts,
                "approved": total_approved,
                "dar": dar,
                "dar_target": 0.60,
                "dar_status": "on_track" if dar >= 0.50 else "needs_attention",
            },
            "llm_costs_30d": {
                "total_usd": round(float(cost_row.total_cost), 4),
                "prompt_tokens": int(cost_row.prompt_tokens),
                "completion_tokens": int(cost_row.completion_tokens),
                "run_count": int(cost_row.run_count),
                "cost_per_run": round(float(cost_row.total_cost) / max(cost_row.run_count, 1), 4),
            },
        },
        "meta": {"workspace_id": current_user.workspace_id},
    }


@router.patch("/settings")
async def update_settings(
    body: WorkspaceSettingsUpdate,
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """Update workspace settings (thresholds, webhooks, etc.)."""
    result = await db.execute(
        select(Workspace).where(Workspace.id == current_user.workspace_id)
    )
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    settings = dict(ws.settings or {})
    update = body.model_dump(exclude_none=True)

    # SSRF: validate webhook URLs before storing — they are used for outbound HTTP requests
    for _url_field in ("slack_webhook_url", "teams_webhook_url"):
        if _url_field in update and update[_url_field]:
            await _validate_webhook_url(update[_url_field])

    settings.update(update)
    ws.settings = settings
    await db.commit()

    log.info("workspace_settings_updated", workspace_id=current_user.workspace_id, keys=list(update.keys()))
    return {"data": {"settings": _safe_settings(settings)}, "meta": {}}


class WorkspaceSetupRequest(BaseModel):
    sender_name: str
    sender_title: str = "Account Executive"
    sender_company: str
    product_name: str
    product_description: str
    seller_domains: list[str] = []
    icp_industries: list[str] = []
    icp_regions: list[str] = []
    typical_deal_size: str = ""
    sales_cycle_months: str = ""
    differentiators: list[str] = []
    competitors: list[str] = []
    pain_points: list[str] = []


class WorkspaceCreateRequest(BaseModel):
    company_name: str
    slug: str
    sender_name: str = ""
    sender_title: str = "Account Executive"
    seller_domains: list[str] = []


@router.post("/setup")
async def setup_workspace_context(
    body: WorkspaceSetupRequest,
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """
    Populate workspace agent context from onboarding or settings UI.
    Idempotent — safe to call repeatedly; merges into existing settings.
    """
    result = await db.execute(select(Workspace).where(Workspace.id == current_user.workspace_id))
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    existing = dict(ws.settings or {})
    existing.update({
        "sender_name": body.sender_name,
        "sender_title": body.sender_title,
        "sender_company": body.sender_company,
        "seller_domains": body.seller_domains,
        "product_description": f"{body.product_name}: {body.product_description}",
        "icp_profile": {
            "product_name": body.product_name,
            "ideal_customer": ", ".join(body.icp_industries),
            "differentiators": body.differentiators,
            "competitors": body.competitors,
            "pain_points": body.pain_points,
            "icp_industries": body.icp_industries,
            "icp_regions": body.icp_regions,
            "typical_deal_size": body.typical_deal_size,
            "sales_cycle_months": body.sales_cycle_months,
        },
    })
    ws.settings = existing
    db.add(ws)
    await db.commit()
    log.info("workspace_setup_saved", workspace_id=str(ws.id))
    return {"status": "ok", "workspace_id": str(ws.id)}


@router.post("/create", status_code=201)
async def create_workspace(
    body: WorkspaceCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new workspace during onboarding."""
    ws = Workspace(
        name=body.company_name,
        slug=body.slug,
        plan="free",
        settings={
            "push_threshold": 0.85,
            "urgency_threshold": 0.7,
            "digest_hour_utc": 6,
            "sender_name": body.sender_name,
            "sender_title": body.sender_title,
            "sender_company": body.company_name,
            "seller_domains": body.seller_domains,
        },
    )
    db.add(ws)
    await db.flush()
    wu = WorkspaceUser(workspace_id=ws.id, workos_user_id=current_user.workos_user_id, email=current_user.email, role="admin")
    db.add(wu)
    await db.commit()
    await db.refresh(ws)
    return {"id": str(ws.id), "name": ws.name, "slug": ws.slug}


@router.get("/team")
async def get_team(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all workspace users."""
    result = await db.execute(
        select(WorkspaceUser).where(WorkspaceUser.workspace_id == current_user.workspace_id)
    )
    users = result.scalars().all()

    return {
        "data": [
            {
                "id": str(u.id),
                "email": u.email,
                "role": u.role,
                "hubspot_owner_id": u.hubspot_owner_id,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ],
        "meta": {"count": len(users)},
    }


@router.post("/team/invite")
async def invite_user(
    body: InviteRequest,
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """Invite a user to the workspace via WorkOS."""
    import workos
    settings = get_settings()

    # Domain restriction — enforced if ALLOWED_EMAIL_DOMAINS is configured
    if settings.allowed_email_domains:
        domain = body.email.split("@")[-1].lower() if "@" in body.email else ""
        if domain not in [d.lower() for d in settings.allowed_email_domains]:
            raise HTTPException(
                status_code=422,
                detail=f"Email domain '{domain}' is not allowed for this workspace."
            )

    try:
        client = workos.WorkOS(api_key=settings.workos_api_key)
        # Send magic link invite
        invitation = client.user_management.send_invitation(
            email=body.email,
            organization_id=current_user.workspace_id,
        )
        log.info("user_invited", email=body.email, role=body.role)
        return {"data": {"invitation_id": invitation.id, "email": body.email}, "meta": {}}
    except Exception as e:
        log.error("invite_failed", email=body.email, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to send invitation. Please try again.")


# ── Outlook OAuth ─────────────────────────────────────────────────────────────

@router.get("/integrations/outlook")
async def outlook_status(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Outlook / Microsoft Graph connection status."""
    result = await db.execute(select(Workspace).where(Workspace.id == current_user.workspace_id))
    ws = result.scalar_one_or_none()
    connected = bool(ws and ws.outlook_access_token)
    return {
        "data": {
            "connected": connected,
            "user_email": ws.outlook_user_email if ws else None,
        },
        "meta": {},
    }


@router.get("/integrations/outlook/connect")
async def outlook_connect(
    current_user: CurrentUser = Depends(require_manager()),
):
    """Return Microsoft OAuth authorization URL with HMAC-signed CSRF state."""
    from app.integrations.outlook import get_auth_url
    import secrets as _sec, hashlib as _hl, hmac as _hm
    settings = get_settings()
    if not settings.jwt_signing_key:
        raise HTTPException(status_code=503, detail="OAuth not configured — JWT_SIGNING_KEY missing")
    nonce = _sec.token_urlsafe(16)
    state_payload = f"{current_user.workspace_id}:{nonce}"
    sig = _hm.new(
        settings.jwt_signing_key.encode(),
        state_payload.encode(),
        _hl.sha256,
    ).hexdigest()
    state = f"{state_payload}:{sig}"
    auth_url = get_auth_url(state)
    return {"data": {"auth_url": auth_url}, "meta": {}}


class OutlookCallbackRequest(BaseModel):
    code: str
    state: str  # HMAC-signed CSRF state from Microsoft redirect — required, validated server-side
    # redirect_uri is validated server-side from settings — never trust client-supplied value


@router.post("/integrations/outlook/callback")
async def outlook_callback(
    body: OutlookCallbackRequest,
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """Exchange OAuth code for tokens. Called by frontend after Microsoft redirect."""
    from app.integrations.outlook import exchange_code, OutlookClient
    import hashlib as _hl_ol, hmac as _hm_ol
    settings = get_settings()

    # CSRF: validate HMAC-signed state (workspace_id:nonce:sig) — always required
    parts = body.state.rsplit(":", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid OAuth state parameter")
    state_payload, sig = parts
    if not settings.jwt_signing_key:
        raise HTTPException(status_code=503, detail="OAuth not configured — JWT_SIGNING_KEY missing")
    expected_sig = _hm_ol.new(
        settings.jwt_signing_key.encode(),
        state_payload.encode(),
        _hl_ol.sha256,
    ).hexdigest()
    if not _hm_ol.compare_digest(sig, expected_sig):
        log.warning("outlook_oauth_state_invalid", workspace_id=current_user.workspace_id)
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    ws_id_from_state = state_payload.split(":")[0]
    if ws_id_from_state != current_user.workspace_id:
        log.warning("outlook_oauth_workspace_mismatch", workspace_id=current_user.workspace_id)
        raise HTTPException(status_code=403, detail="OAuth state workspace mismatch")

    tokens = await exchange_code(body.code, settings.outlook_redirect_uri)
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in", 3600)

    if not access_token:
        raise HTTPException(status_code=400, detail="OAuth exchange failed — no access token returned")

    # Fetch user profile to confirm mailbox email
    client = OutlookClient(access_token)
    profile = await client.get_user_profile()
    user_email = profile.get("mail") or profile.get("userPrincipalName")

    result = await db.execute(select(Workspace).where(Workspace.id == current_user.workspace_id))
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    from datetime import timezone as tz
    ws.outlook_access_token = access_token
    ws.outlook_refresh_token = refresh_token
    ws.outlook_token_expires_at = datetime.now(tz.utc) + timedelta(seconds=expires_in)
    ws.outlook_user_email = user_email
    await db.commit()

    log.info("outlook_connected", workspace_id=current_user.workspace_id, email=user_email)
    return {
        "data": {"connected": True, "user_email": user_email},
        "meta": {},
    }


@router.post("/integrations/outlook/disconnect")
async def outlook_disconnect(
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """Revoke Outlook integration."""
    result = await db.execute(select(Workspace).where(Workspace.id == current_user.workspace_id))
    ws = result.scalar_one_or_none()
    if ws:
        ws.outlook_access_token = None
        ws.outlook_refresh_token = None
        ws.outlook_token_expires_at = None
        ws.outlook_user_email = None
        await db.commit()
    log.info("outlook_disconnected", workspace_id=current_user.workspace_id)
    return {"data": {"disconnected": True}, "meta": {}}


@router.post("/integrations/outlook/sync-calendar")
async def outlook_sync_calendar(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Sync Outlook calendar events for the next 7 days into account Interactions.
    Matches events to HubSpot accounts by attendee email domain.
    Returns count of upcoming meetings found.
    """
    from fastapi import BackgroundTasks as _BT
    from app.integrations.outlook import OutlookClient, refresh_access_token
    from sqlalchemy import text as sql_text

    result = await db.execute(select(Workspace).where(Workspace.id == current_user.workspace_id))
    ws = result.scalar_one_or_none()
    if not ws or not ws.outlook_access_token:
        raise HTTPException(status_code=422, detail="Outlook not connected. Go to Settings to connect.")

    # Refresh token if near expiry
    if ws.outlook_token_expires_at and ws.outlook_token_expires_at < datetime.now(timezone.utc) + timedelta(minutes=5):
        if ws.outlook_refresh_token:
            try:
                tokens = await refresh_access_token(ws.outlook_refresh_token)
                ws.outlook_access_token = tokens["access_token"]
                if tokens.get("refresh_token"):
                    ws.outlook_refresh_token = tokens["refresh_token"]
                ws.outlook_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))
                await db.commit()
            except Exception as e:
                log.warning("outlook_token_refresh_failed", error=str(e))

    ol = OutlookClient(ws.outlook_access_token)
    # Fetch 90 days back + 30 days ahead for full historical Fireflies matching
    events = await ol.get_calendar_events(days_back=90, days_ahead=30)

    if not events:
        return {"data": {"meetings_found": 0, "matched": 0}, "meta": {}}

    # Load all accounts for domain matching
    accs_result = await db.execute(
        select(Account).where(
            Account.workspace_id == current_user.workspace_id,
            Account.deleted_at.is_(None),
        )
    )
    accounts = accs_result.scalars().all()

    import re
    from app.integrations.fireflies import _domain_root, _GENERIC_WORDS, _SELLER_DOMAINS

    _GENERIC_SUBDOMAIN_PREFIXES = {
        "partner", "partners", "mail", "email", "info", "contact", "support",
        "portal", "app", "api", "help", "sales", "marketing", "hr", "admin",
        "noreply", "no-reply", "service", "services", "staff", "corp",
    }

    def _clean_name_words(name: str) -> set:
        cleaned = re.sub(r"\s*[-–]\s*(New Deal|Pilot|Phase \d+|POC|Demo|Renewal|Partner|Expansion|Follow.?up).*$",
                         "", name, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*\(.*?\)", "", cleaned).strip()
        words = {w.lower() for w in cleaned.split() if len(w) >= 5}  # 5+ chars only
        return words - _GENERIC_WORDS  # only specific, non-generic words

    matched_count = 0
    for event in events:
        attendee_emails = event.get("attendees", [])
        if not attendee_emails:
            continue

        # Extract the real company domain root from each external attendee email
        # Uses _domain_root() which skips generic subdomain prefixes like "partner.*"
        seller_domains = set((ws.settings or {}).get("seller_domains", []))
        ext_domains = set()
        for email in attendee_emails:
            parts_e = email.split("@")
            if len(parts_e) != 2 or parts_e[1] in seller_domains:
                continue
            root = _domain_root(email)
            if root and root not in _SELLER_DOMAINS and root not in _GENERIC_SUBDOMAIN_PREFIXES:
                ext_domains.add(root)

        if not ext_domains:
            continue

        # Match accounts: specific name words must overlap with external domain roots
        matched_account: Account | None = None
        best_score = 0
        for acc in accounts:
            name_words = _clean_name_words(acc.name)
            if not name_words:
                continue
            overlap = name_words & ext_domains
            if len(overlap) > best_score:
                best_score = len(overlap)
                matched_account = acc

        if not matched_account or best_score == 0:
            continue

        # Parse start time — always produce a UTC-aware datetime
        start_raw = event.get("start") or ""
        try:
            from datetime import timezone as _tz
            _parsed = datetime.fromisoformat(start_raw.replace("Z", "+00:00")) if start_raw else None
            if _parsed is None:
                start_dt = datetime.now(_tz.utc)
            elif _parsed.tzinfo is None:
                start_dt = _parsed.replace(tzinfo=_tz.utc)
            else:
                start_dt = _parsed.astimezone(_tz.utc)
        except (ValueError, AttributeError):
            from datetime import timezone as _tz
            start_dt = datetime.now(_tz.utc)

        # Dedup: skip if we already have this event (same account + same start time)
        existing = await db.execute(
            select(func.count()).where(
                Interaction.account_id == matched_account.id,
                Interaction.source == "outlook_calendar",
                Interaction.occurred_at == start_dt,
            )
        )
        if existing.scalar_one() > 0:
            continue

        # Store as an Interaction
        notes = (
            f"Upcoming meeting: {event.get('subject', 'Meeting')}\n"
            f"Attendees: {', '.join(attendee_emails[:5])}\n"
            f"{event.get('body_preview', '')[:200]}"
        )
        interaction = Interaction(
            account_id=matched_account.id,
            workspace_id=uuid.UUID(current_user.workspace_id),
            type="meeting_scheduled",
            source="outlook_calendar",
            notes=notes,
            outcome=event.get("online_meeting_url"),
            occurred_at=start_dt,
            is_training_signal=False,
        )
        db.add(interaction)

        # Store upcoming_meeting in account state for quick access
        from sqlalchemy.orm.attributes import flag_modified
        state = matched_account.state or {}
        upcoming = state.get("upcoming_meetings", [])
        upcoming = [u for u in upcoming if u.get("start") != start_raw]  # dedup
        upcoming.insert(0, {
            "subject": event.get("subject", ""),
            "start": start_raw,
            "end": event.get("end", ""),
            "attendees": attendee_emails[:5],
            "online_meeting_url": event.get("online_meeting_url"),
        })
        state["upcoming_meetings"] = upcoming[:5]
        matched_account.state = state
        flag_modified(matched_account, "state")
        matched_count += 1

    if matched_count:
        await db.commit()

    log.info("outlook_calendar_synced", workspace_id=current_user.workspace_id,
             events=len(events), matched=matched_count)
    return {
        "data": {"meetings_found": len(events), "matched": matched_count},
        "meta": {},
    }


@router.get("/status")
async def workspace_status(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Comprehensive pipeline status — what's connected, when was last run,
    how many deals need attention. Used by the frontend status bar.
    """
    from sqlalchemy import text as sql_text

    result = await db.execute(select(Workspace).where(Workspace.id == current_user.workspace_id))
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    settings = get_settings()

    # Last nightly run
    run_result = await db.execute(sql_text("""
        SELECT completed_at, accounts_processed, drafts_created, signals_detected
        FROM agent_runs
        WHERE workspace_id = :ws
          AND trigger = 'nightly'
          AND status = 'completed'
        ORDER BY completed_at DESC NULLS LAST
        LIMIT 1
    """), {"ws": current_user.workspace_id})
    last_run = run_result.fetchone()

    # Pipeline health
    counts = await db.execute(sql_text("""
        SELECT
            COUNT(*) FILTER (WHERE deleted_at IS NULL) AS total_accounts,
            COUNT(*) FILTER (WHERE deleted_at IS NULL AND urgency_score >= 0.85) AS critical_accounts,
            COUNT(*) FILTER (WHERE deleted_at IS NULL AND urgency_score >= 0.7) AS at_risk_accounts,
            COUNT(*) FILTER (WHERE deleted_at IS NULL AND last_agent_run_at >= NOW() - INTERVAL '24 hours') AS synced_24h
        FROM accounts WHERE workspace_id = :ws
    """), {"ws": current_user.workspace_id})
    c = counts.fetchone()

    pending_drafts = await db.execute(sql_text("""
        SELECT COUNT(*) FROM drafts d
        JOIN accounts a ON d.account_id = a.id
        WHERE a.workspace_id = :ws AND d.status = 'pending'
    """), {"ws": current_user.workspace_id})
    pending = pending_drafts.scalar_one()

    # DAR (30d)
    dar_result = await db.execute(sql_text("""
        SELECT ROUND(
            COUNT(*) FILTER (WHERE d.status IN ('approved','approved_modified'))::numeric
            / NULLIF(COUNT(*), 0) * 100, 1
        ) AS dar_pct
        FROM drafts d JOIN accounts a ON d.account_id = a.id
        WHERE a.workspace_id = :ws
          AND d.created_at >= NOW() - INTERVAL '30 days'
    """), {"ws": current_user.workspace_id})
    dar_row = dar_result.fetchone()

    return {
        "data": {
            "integrations": {
                "hubspot": {
                    "connected": bool(ws.hubspot_access_token),
                    "portal_id": ws.hubspot_portal_id,
                },
                "outlook": {
                    "connected": bool(ws.outlook_access_token),
                    "user_email": ws.outlook_user_email,
                },
                "fireflies": {
                    "configured": bool(settings.fireflies_api_key),
                },
                "teams": {
                    "configured": bool(settings.teams_webhook_url),
                },
                "perplexity": {
                    "configured": bool(settings.perplexity_api_key or
                                       (ws.settings or {}).get("perplexity_api_key")),
                },
            },
            "last_nightly_run": {
                "completed_at": last_run.completed_at.isoformat() if last_run and last_run.completed_at else None,
                "accounts_processed": last_run.accounts_processed if last_run else 0,
                "drafts_created": last_run.drafts_created if last_run else 0,
                "signals_detected": last_run.signals_detected if last_run else 0,
            },
            "pipeline": {
                "total_accounts": c.total_accounts if c else 0,
                "critical_accounts": c.critical_accounts if c else 0,
                "at_risk_accounts": c.at_risk_accounts if c else 0,
                "synced_last_24h": c.synced_24h if c else 0,
                "pending_drafts": int(pending),
                "dar_pct_30d": float(dar_row.dar_pct or 0) if dar_row else 0.0,
            },
        },
        "meta": {"workspace_id": current_user.workspace_id},
    }


# HubSpot private token endpoint removed — use OAuth flow only (/integrations/hubspot/connect).


# ── HubSpot OAuth ─────────────────────────────────────────────────────────────

@router.get("/integrations/hubspot")
async def hubspot_status(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """HubSpot connection status."""
    result = await db.execute(
        select(Workspace).where(Workspace.id == current_user.workspace_id)
    )
    ws = result.scalar_one_or_none()
    connected = bool(ws and ws.hubspot_access_token)

    return {
        "data": {
            "connected": connected,
            "portal_id": ws.hubspot_portal_id if ws else None,
            "token_expires_at": ws.hubspot_token_expires_at.isoformat() if ws and ws.hubspot_token_expires_at else None,
        },
        "meta": {},
    }


@router.post("/integrations/hubspot/connect")
async def hubspot_connect(
    current_user: CurrentUser = Depends(require_manager()),
):
    """Return the HubSpot OAuth authorization URL with CSRF state."""
    import secrets as _sec, hashlib as _hl, hmac as _hm
    settings = get_settings()
    if not settings.jwt_signing_key:
        raise HTTPException(status_code=503, detail="OAuth not configured — JWT_SIGNING_KEY missing")
    nonce = _sec.token_urlsafe(16)
    state_payload = f"{current_user.workspace_id}:{nonce}"
    sig = _hm.new(
        settings.jwt_signing_key.encode(),
        state_payload.encode(),
        _hl.sha256,
    ).hexdigest()
    state = f"{state_payload}:{sig}"
    scopes = "crm.objects.deals.read crm.objects.contacts.read crm.objects.companies.read crm.objects.notes.write crm.objects.emails.write"
    redirect_uri = settings.hubspot_redirect_uri
    url = (
        f"https://app.hubspot.com/oauth/authorize"
        f"?client_id={settings.hubspot_client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scopes.replace(' ', '%20')}"
        f"&state={state}"
    )
    return {"data": {"auth_url": url}, "meta": {}}


@router.post("/integrations/hubspot/disconnect")
async def hubspot_disconnect(
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """Revoke HubSpot tokens and clear from workspace."""
    result = await db.execute(
        select(Workspace).where(Workspace.id == current_user.workspace_id)
    )
    ws = result.scalar_one_or_none()
    if ws:
        ws.hubspot_access_token = None
        ws.hubspot_refresh_token = None
        ws.hubspot_portal_id = None
        ws.hubspot_token_expires_at = None
        await db.commit()
    log.info("hubspot_disconnected", workspace_id=current_user.workspace_id)
    return {"data": {"disconnected": True}, "meta": {}}


@router.post("/integrations/hubspot/sync")
async def hubspot_sync(
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger a full HubSpot deal sync for the workspace.
    Re-fetches all deals, resolves stage labels, updates contact/company IDs.
    Runs inline — returns sync stats when complete.
    """
    from app.services.hubspot_sync import HubSpotSyncService

    result = await db.execute(
        select(Workspace).where(Workspace.id == current_user.workspace_id)
    )
    ws = result.scalar_one_or_none()
    if not ws or not ws.hubspot_access_token:
        raise HTTPException(status_code=400, detail="HubSpot not connected")

    log.info("hubspot_manual_sync_triggered", workspace_id=current_user.workspace_id)

    # Run sync inline (it's typically fast, <5s for hundreds of deals)
    try:
        sync_service = HubSpotSyncService(db)
        stats = await sync_service.sync_workspace(current_user.workspace_id)
        log.info("hubspot_manual_sync_complete", workspace_id=current_user.workspace_id, **stats)
        return {
            "data": {
                "synced": True,
                "created": stats["created"],
                "updated": stats["updated"],
                "unchanged": stats["unchanged"],
                "errors": stats["errors"],
            },
            "meta": {"workspace_id": current_user.workspace_id},
        }
    except Exception as e:
        log.error("hubspot_manual_sync_failed", workspace_id=current_user.workspace_id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="HubSpot sync failed. Please try again or reconnect HubSpot in Settings.")


@router.post("/integrations/fireflies/backfill")
async def fireflies_backfill(
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """
    Pull all Fireflies transcripts (up to 200) and match each one to accounts
    using name fuzzy-matching + transcript date proximity.

    Idempotent — skips any transcript already ingested for a given account
    (matched by source + occurred_at + account_id).
    """
    from sqlalchemy import text
    from app.integrations.fireflies import FirefliesClient, backfill_all_transcripts
    from app.models.account import Interaction
    settings = get_settings()

    if not settings.fireflies_api_key:
        raise HTTPException(status_code=400, detail="FIREFLIES_API_KEY not configured")

    # Load all accounts for the workspace with date fields for proximity matching
    accs_result = await db.execute(text("""
        SELECT id, workspace_id, name, created_at, close_date
        FROM accounts
        WHERE deleted_at IS NULL AND workspace_id = :ws_id
        ORDER BY urgency_score DESC NULLS LAST
    """), {"ws_id": str(current_user.workspace_id)})
    accounts = [dict(r._mapping) for r in accs_result.fetchall()]

    if not accounts:
        return {"ingested": 0, "skipped": 0, "unmatched": 0, "accounts": 0}

    # Load existing Fireflies interactions so we can deduplicate
    existing_result = await db.execute(text("""
        SELECT account_id, occurred_at
        FROM interactions
        WHERE source = 'fireflies'
          AND account_id = ANY(ARRAY(
              SELECT id FROM accounts
              WHERE workspace_id = :ws_id AND deleted_at IS NULL
          )::uuid[])
    """), {"ws_id": str(current_user.workspace_id)})
    existing_keys = {
        (str(r.account_id), r.occurred_at.strftime("%Y-%m-%dT%H:%M:%S"))
        for r in existing_result.fetchall()
    }

    # Load calendar events (Outlook meetings) to use as the primary match signal.
    # Each row gives us: which account a meeting belongs to + when it occurred.
    # When Outlook isn't connected yet this returns an empty list and the matcher
    # falls back gracefully to email-domain + title-word matching.
    cal_result = await db.execute(text("""
        SELECT account_id, occurred_at
        FROM interactions
        WHERE source = 'outlook'
          AND type  = 'meeting'
          AND account_id = ANY(ARRAY(
              SELECT id FROM accounts
              WHERE workspace_id = :ws_id AND deleted_at IS NULL
          )::uuid[])
    """), {"ws_id": str(current_user.workspace_id)})
    calendar_events = [
        {"account_id": str(r.account_id), "occurred_at": r.occurred_at}
        for r in cal_result.fetchall()
    ]

    log.info(
        "fireflies_backfill_started",
        workspace_id=current_user.workspace_id,
        accounts=len(accounts),
        existing=len(existing_keys),
        calendar_events=len(calendar_events),
    )

    client = FirefliesClient(api_key=settings.fireflies_api_key)
    matched = await backfill_all_transcripts(client, accounts, calendar_events=calendar_events)

    ingested = 0
    skipped = 0

    for m in matched:
        idata = m["interaction"]
        occurred_at_raw = idata.get("occurred_at")
        if occurred_at_raw:
            from datetime import datetime as _dt
            occurred_at = _dt.fromisoformat(occurred_at_raw)
            occurred_at_key = occurred_at.strftime("%Y-%m-%dT%H:%M:%S")
        else:
            from datetime import datetime as _dt
            occurred_at = _dt.now(timezone.utc)
            occurred_at_key = occurred_at.strftime("%Y-%m-%dT%H:%M:%S")

        dedup_key = (m["account_id"], occurred_at_key)
        if dedup_key in existing_keys:
            skipped += 1
            continue

        interaction = Interaction(
            account_id=m["account_id"],
            workspace_id=m["workspace_id"],
            type=idata["type"],
            notes=idata["notes"],
            outcome=idata.get("outcome"),
            source="fireflies",
            occurred_at=occurred_at,
            is_training_signal=False,
        )
        db.add(interaction)
        existing_keys.add(dedup_key)  # prevent within-run dupes
        ingested += 1

    if ingested:
        await db.commit()

    unmatched = len(matched) == 0
    log.info(
        "fireflies_backfill_complete",
        workspace_id=current_user.workspace_id,
        ingested=ingested,
        skipped=skipped,
    )
    return {
        "ingested": ingested,
        "skipped": skipped,
        "accounts": len(accounts),
    }


# ── API Keys ──────────────────────────────────────────────────────────────────

@router.get("/api-keys")
async def list_api_keys(
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """List all API keys for the workspace (hashes only — raw key shown once at creation)."""
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.workspace_id == current_user.workspace_id,
            ApiKey.revoked_at.is_(None),
        )
    )
    keys = result.scalars().all()

    return {
        "data": [
            {
                "id": str(k.id),
                "name": k.name,
                "key_prefix": k.key_prefix,
                "scopes": k.scopes,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                "created_at": k.created_at.isoformat() if k.created_at else None,
            }
            for k in keys
        ],
        "meta": {"count": len(keys)},
    }


@router.post("/api-keys")
async def create_api_key(
    body: ApiKeyCreateRequest,
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new API key.
    Returns the raw key ONCE — store it securely, it cannot be retrieved again.
    """
    settings = get_settings()
    raw_key = f"{settings.api_key_prefix}{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12] + "..."

    api_key = ApiKey(
        workspace_id=uuid.UUID(current_user.workspace_id),
        name=body.name,
        key_prefix=key_prefix,
        key_hash=key_hash,
        scopes=body.scopes,
        created_by=uuid.UUID(current_user.user_id) if not current_user.is_api_key else None,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    log.info("api_key_created", workspace_id=current_user.workspace_id, name=body.name)
    return {
        "data": {
            "id": str(api_key.id),
            "key": raw_key,  # Only returned once
            "key_prefix": key_prefix,
            "name": body.name,
            "scopes": body.scopes,
            "warning": "Store this key securely. It will not be shown again.",
        },
        "meta": {},
    }


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an API key."""
    try:
        key_uuid = uuid.UUID(key_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="API key not found")

    result = await db.execute(
        select(ApiKey).where(
            ApiKey.id == key_uuid,
            ApiKey.workspace_id == current_user.workspace_id,
            ApiKey.revoked_at.is_(None),
        )
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    api_key.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    log.info("api_key_revoked", key_id=key_id, workspace_id=current_user.workspace_id)
    return {"data": {"revoked": True}, "meta": {}}


@router.post("/voice-profile/analyze")
async def analyze_voice_profile(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Analyze rep writing voice from email history.
    Uses Outlook sent items if connected, falls back to HubSpot outbound emails.
    Stores the extracted voice profile in workspace.settings["voice_profile"].
    """
    import anthropic as _anthropic
    from app.config import get_settings

    result = await db.execute(
        select(Workspace).where(Workspace.id == current_user.workspace_id)
    )
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    settings = get_settings()
    email_bodies: list[str] = []
    source = "none"

    # Try Outlook sent items first (token is a dedicated column, not in settings JSONB)
    if ws.outlook_access_token:
        try:
            from app.integrations.outlook import OutlookClient
            outlook = OutlookClient(ws.outlook_access_token)
            sent_messages = await outlook.get_sent_emails(limit=50)
            email_bodies = [
                (m.get("body", {}).get("content") or m.get("bodyPreview", ""))
                for m in sent_messages
                if m.get("body") or m.get("bodyPreview")
            ]
            email_bodies = [b[:2000] for b in email_bodies if b.strip()][:50]
            source = "outlook"
            log.info("voice_profile_outlook_emails", count=len(email_bodies))
        except Exception as e:
            log.warning("voice_profile_outlook_failed", error=str(e))

    # Fallback: HubSpot outbound emails
    if not email_bodies and ws.hubspot_access_token:
        try:
            from app.integrations.hubspot import HubSpotClient
            from sqlalchemy import select as _sel
            from app.models.account import Account as _Acc
            hs = HubSpotClient(ws.hubspot_access_token)
            acc_result = await db.execute(
                _sel(_Acc)
                .where(_Acc.workspace_id == ws.id, _Acc.deleted_at.is_(None))
                .limit(20)
            )
            accounts = acc_result.scalars().all()
            for acc in accounts[:10]:
                if not acc.hubspot_deal_id:
                    continue
                try:
                    emails = await asyncio.wait_for(
                        hs.get_deal_emails(acc.hubspot_deal_id, limit=10), timeout=8.0
                    )
                    for e in emails:
                        if e.get("direction") == "OUTBOUND" and e.get("body"):
                            email_bodies.append(e["body"][:2000])
                except Exception:
                    pass
                if len(email_bodies) >= 30:
                    break
            source = "hubspot"
            log.info("voice_profile_hubspot_emails", count=len(email_bodies))
        except Exception as e:
            log.warning("voice_profile_hubspot_failed", error=str(e))

    if len(email_bodies) < 3:
        raise HTTPException(
            status_code=422,
            detail="Not enough sent emails found (minimum 3 required). Connect Outlook or send more emails via HubSpot.",
        )

    # Extract voice profile using Haiku
    client = _anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    sample = "\n\n---\n\n".join(email_bodies[:30])

    response = await client.messages.create(
        model=settings.anthropic_model_bulk,
        max_tokens=512,
        system=(
            "You are analyzing a sales rep's email writing style. "
            "Extract a voice profile from these sent emails. "
            "Respond with JSON only, no markdown wrapping."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Analyze these {len(email_bodies)} sent emails and extract the rep's voice profile.\n\n"
                f"{sample}\n\n"
                "Return JSON with these exact keys:\n"
                '{"tone": "...", "avg_word_count": 45, "avg_sentence_length": 12, '
                '"common_openers": ["...", "..."], "common_ctas": ["...", "..."], '
                '"avoids": ["...", "..."], "signature_style": "..."}'
            ),
        }],
    )

    try:
        import json as _json
        voice_profile = _json.loads(response.content[0].text)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to parse voice profile from AI response")

    voice_profile["analyzed_at"] = datetime.now(timezone.utc).isoformat()
    voice_profile["emails_analyzed"] = len(email_bodies)
    voice_profile["source"] = source

    ws_settings = ws.settings or {}
    ws_settings["voice_profile"] = voice_profile
    ws.settings = ws_settings
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(ws, "settings")
    await db.commit()

    log.info("voice_profile_saved", workspace_id=str(ws.id), emails=len(email_bodies), source=source)
    return {
        "data": {"voice_profile": voice_profile, "emails_analyzed": len(email_bodies), "source": source},
        "meta": {"workspace_id": str(ws.id)},
    }


# ── Outbound Webhook Subscriptions ───────────────────────────────────────────

@router.post("/webhooks")
async def add_webhook_subscription(
    body: WebhookSubscriptionRequest,
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """
    Register an outbound webhook URL to receive Vantage events.
    Supported events: signal.critical, signal.high, draft.created, draft.approved,
    draft.declined, health.dropped, agent.run_complete, account.stage_changed, play.fired.
    Use ["all"] in events list to subscribe to everything.
    """
    result = await db.execute(
        select(Workspace).where(Workspace.id == current_user.workspace_id)
    )
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    await _validate_webhook_url(body.url)

    ws_settings = ws.settings or {}
    subs = ws_settings.get("webhook_subscriptions", [])
    import secrets as _secrets
    new_sub = {
        "id": str(uuid.uuid4()),
        "url": body.url,
        "events": body.events,
        "secret": body.secret or _secrets.token_hex(16),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    subs.append(new_sub)
    ws_settings["webhook_subscriptions"] = subs
    ws.settings = ws_settings
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(ws, "settings")
    await db.commit()

    log.info("webhook_subscription_added", workspace_id=current_user.workspace_id, url=body.url[:50])
    return {
        "data": new_sub,
        "meta": {"secret_notice": "Store the secret securely — it will not be shown again after this response."},
    }


@router.delete("/webhooks/{webhook_id}")
async def delete_webhook_subscription(
    webhook_id: str,
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """Remove an outbound webhook subscription."""
    result = await db.execute(
        select(Workspace).where(Workspace.id == current_user.workspace_id)
    )
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    ws_settings = ws.settings or {}
    subs = [s for s in ws_settings.get("webhook_subscriptions", []) if s.get("id") != webhook_id]
    ws_settings["webhook_subscriptions"] = subs
    ws.settings = ws_settings
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(ws, "settings")
    await db.commit()

    log.info("webhook_subscription_deleted", workspace_id=current_user.workspace_id, webhook_id=webhook_id)
    return {"data": {"deleted": True}, "meta": {}}


# ── Document templates ────────────────────────────────────────────────────────

class TemplateUploadRequest(BaseModel):
    template_b64: str = Field(..., max_length=15_000_000)  # ~10MB file = ~13.3MB base64; 15M is safe ceiling
    template_name: str = Field("", max_length=200)


@router.post("/documents/template")
async def upload_proposal_template(
    body: TemplateUploadRequest,
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a reference .docx proposal as the template for AI-generated proposals.
    Stored as base64 in workspace.settings. The generator uses it as the base document,
    inheriting styles, fonts, and margins. Claude writes the content on top.
    """
    import base64 as b64
    # Validate it's a real docx
    try:
        raw = b64.b64decode(body.template_b64)
        if not raw[:4] == b"PK\x03\x04":  # ZIP magic bytes (docx is a zip)
            raise ValueError("Not a valid .docx file")
        if len(raw) > 10 * 1024 * 1024:  # 10MB limit
            raise ValueError("Template exceeds 10MB limit")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid template: {e}")

    result = await db.execute(select(Workspace).where(Workspace.id == current_user.workspace_id))
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    ws_settings = ws.settings or {}
    ws_settings["proposal_template_docx_b64"] = body.template_b64
    ws_settings["proposal_template_name"] = body.template_name or "Custom Template"
    ws_settings["proposal_template_size_bytes"] = len(raw)
    ws.settings = ws_settings
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(ws, "settings")
    await db.commit()

    log.info("proposal_template_uploaded", workspace_id=current_user.workspace_id,
             size_bytes=len(raw), name=body.template_name)
    return {"data": {"uploaded": True, "size_bytes": len(raw), "name": ws_settings["proposal_template_name"]}}


@router.delete("/documents/template")
async def delete_proposal_template(
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """Remove the uploaded proposal template (reverts to built-in structure)."""
    result = await db.execute(select(Workspace).where(Workspace.id == current_user.workspace_id))
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    ws_settings = ws.settings or {}
    ws_settings.pop("proposal_template_docx_b64", None)
    ws_settings.pop("proposal_template_name", None)
    ws_settings.pop("proposal_template_size_bytes", None)
    ws.settings = ws_settings
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(ws, "settings")
    await db.commit()

    return {"data": {"deleted": True}}


@router.get("/webhooks")
async def list_webhook_subscriptions(
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """List all outbound webhook subscriptions for the workspace."""
    result = await db.execute(
        select(Workspace).where(Workspace.id == current_user.workspace_id)
    )
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    ws_settings = ws.settings or {}
    subs = ws_settings.get("webhook_subscriptions", [])
    # Mask secrets in list view
    masked = [
        {**s, "secret": s["secret"][:4] + "****" if s.get("secret") else None}
        for s in subs
    ]
    return {"data": masked, "meta": {"count": len(masked)}}


# ── Sprint 7-9 endpoints ──────────────────────────────────────────────────────

@router.get("/health-score")
async def get_workspace_health_score(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Workspace configuration completeness score 0-100."""
    result = await db.execute(select(Workspace).where(Workspace.id == current_user.workspace_id))
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    settings = ws.settings or {}
    checks = []

    def check(name: str, ok: bool, weight: int, fix: str):
        checks.append({"name": name, "ok": ok, "weight": weight, "fix": fix})

    check("HubSpot connected", bool(ws.hubspot_access_token), 25, "/settings → Integrations → Connect HubSpot")
    check("Deals synced", bool(settings.get("last_hubspot_sync")), 10, "Settings → Integrations → Sync now")
    check(
        "Perplexity key set",
        bool(settings.get("perplexity_api_key") or get_settings().perplexity_api_key),
        20,
        "Add PERPLEXITY_API_KEY to .env and restart",
    )
    check("Voice profile set", bool(settings.get("voice_profile")), 10, "Settings → Voice Profile → Analyse")
    check("ICP configured", bool(settings.get("icp_profile", {}).get("product_name")), 20, "Settings → Sales Intelligence → Configure ICP")
    check("Sender name set", bool(settings.get("sender_name")), 10, "Settings → Workspace → Set sender name")
    check("Outlook connected", bool(ws.outlook_access_token), 5, "Settings → Integrations → Connect Outlook")

    score = sum(c["weight"] for c in checks if c["ok"])
    missing = [c for c in checks if not c["ok"]]

    return {
        "data": {
            "score": score,
            "max": 100,
            "checks": checks,
            "missing": missing,
            "status": "excellent" if score >= 80 else "good" if score >= 60 else "needs_setup",
        },
        "meta": {},
    }


@router.get("/rules-log")
async def get_rules_log(
    limit: int = Query(50, ge=1, le=200),
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """Automation rules execution log — last N rule firings."""
    from app.models.account import Account
    from sqlalchemy import text as sql_text

    result = await db.execute(sql_text("""
        SELECT
            i.id,
            i.occurred_at,
            i.notes,
            i.outcome,
            a.name AS account_name,
            a.id::text AS account_id
        FROM interactions i
        JOIN accounts a ON i.account_id = a.id
        WHERE i.workspace_id = :ws
          AND i.source = 'rules_engine'
        ORDER BY i.occurred_at DESC
        LIMIT :limit
    """), {"ws": str(current_user.workspace_id), "limit": limit})
    rows = result.fetchall()

    return {
        "data": [
            {
                "id": str(r.id),
                "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
                "rule_name": r.outcome or "Unknown rule",
                "account_name": r.account_name,
                "account_id": r.account_id,
                "action_taken": r.notes,
            }
            for r in rows
        ],
        "meta": {"count": len(rows)},
    }


# Win-loss endpoint is in accounts.py at POST /v1/accounts/{id}/win-loss
