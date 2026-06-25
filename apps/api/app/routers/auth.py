"""
Auth router — WorkOS OAuth flow + HubSpot OAuth callback.
GET  /auth/login                — redirect to WorkOS authorization URL
GET  /auth/callback             — WorkOS callback handler (exchanges code for session)
POST /auth/logout               — invalidate session
GET  /auth/me                   — current user info
GET  /auth/hubspot/callback     — HubSpot OAuth callback (stores tokens in workspace)
"""
import uuid
import secrets
import hmac as _hmac
import hashlib as _hl2
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import workos
import structlog

from app.db.database import get_db
from app.config import get_settings
from app.middleware.auth import get_current_user, CurrentUser
from app.models.workspace import Workspace, WorkspaceUser
from app.integrations.hubspot import HubSpotClient

log = structlog.get_logger()
router = APIRouter()


@router.get("/login")
async def login():
    """
    Redirect to WorkOS authorization URL.
    Frontend calls this when user hits "Sign in with Google".
    """
    settings = get_settings()
    client = workos.WorkOS(api_key=settings.workos_api_key)

    if not settings.jwt_signing_key:
        raise HTTPException(status_code=503, detail="OAuth not configured — JWT_SIGNING_KEY missing")
    # HMAC-bind the state token so stolen cookies cannot be replayed across sessions
    _nonce = secrets.token_urlsafe(32)
    _sig = _hmac.new(
        settings.jwt_signing_key.encode(),
        _nonce.encode(),
        _hl2.sha256,
    ).hexdigest()
    state = f"{_nonce}:{_sig}"
    auth_url = client.user_management.get_authorization_url(
        provider="GoogleOAuth",
        redirect_uri=settings.workos_redirect_uri,
        client_id=settings.workos_client_id,
        state=state,
    )
    response = RedirectResponse(url=auth_url)
    response.set_cookie(
        key="_oauth_state",
        value=state,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=600,  # 10 minutes
    )
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: str,
    state: str = None,
    db: AsyncSession = Depends(get_db),
):
    """
    WorkOS OAuth callback.
    Exchanges code for session token, creates WorkspaceUser if first login.
    Redirects to frontend with session token as cookie.
    """
    settings = get_settings()

    # CSRF: validate cookie == query param AND verify HMAC binding
    if not settings.jwt_signing_key:
        log.error("oauth_csrf_jwt_key_missing_on_callback")
        return RedirectResponse(url=f"{settings.frontend_url}/auth/error?code=access_denied")
    expected_state = request.cookies.get("_oauth_state")
    _state_valid = False
    if expected_state and state and _hmac.compare_digest(expected_state, state):
        _parts = state.rsplit(":", 1)
        if len(_parts) == 2:
            _nonce, _received_sig = _parts
            _expected_sig = _hmac.new(
                settings.jwt_signing_key.encode(),
                _nonce.encode(),
                _hl2.sha256,
            ).hexdigest()
            _state_valid = _hmac.compare_digest(_received_sig, _expected_sig)
    if not _state_valid:
        log.warning("oauth_csrf_state_mismatch", has_cookie=bool(expected_state), has_param=bool(state))
        return RedirectResponse(url=f"{settings.frontend_url}/auth/error?code=access_denied")

    client = workos.WorkOS(api_key=settings.workos_api_key)

    try:
        auth_response = client.user_management.authenticate_with_code(
            code=code,
            client_id=settings.workos_client_id,
        )
        user = auth_response.user
        session_token = auth_response.sealed_session
    except Exception as e:
        log.error("workos_callback_failed", error=str(e))
        return RedirectResponse(url=f"{settings.frontend_url}/auth/error?code=auth_failed")

    # Find or create workspace user
    ws_user = await _find_or_create_workspace_user(db, user, settings)
    if not ws_user:
        return RedirectResponse(
            url=f"{settings.frontend_url}/auth/error?code=no_workspace_access"
        )

    import hashlib as _hl
    _email_hash = _hl.sha256(user.email.encode()).hexdigest()[:12]
    log.info("user_logged_in", email_hash=_email_hash, workspace_id=str(ws_user.workspace_id))

    # Redirect to frontend with session token in secure cookie
    response = RedirectResponse(url=f"{settings.frontend_url}/inbox")
    response.set_cookie(
        key="vantage_session",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,  # 7 days
    )
    return response


@router.post("/logout")
async def logout(current_user: CurrentUser = Depends(get_current_user)):
    """Invalidate session and clear cookie."""
    response = JSONResponse({"data": {"logged_out": True}, "meta": {}})
    response.delete_cookie("vantage_session")
    log.info("user_logged_out", user_id=current_user.user_id)
    return response


@router.get("/me")
async def me(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current authenticated user's profile."""
    return {
        "data": {
            "user_id": current_user.user_id,
            "email": current_user.email,
            "role": current_user.role,
            "workspace_id": current_user.workspace_id,
            "scopes": current_user.scopes,
            "is_manager": current_user.is_manager(),
        },
        "meta": {},
    }


@router.get("/workspaces")
async def list_workspaces(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all workspaces the current user belongs to."""
    result = await db.execute(
        select(WorkspaceUser, Workspace)
        .join(Workspace, WorkspaceUser.workspace_id == Workspace.id)
        .where(WorkspaceUser.workos_user_id == current_user.workos_user_id)
    )
    rows = result.all()
    return {
        "data": [
            {
                "workspace_id": str(wsu.workspace_id),
                "name": ws.name,
                "role": wsu.role,
                "is_current": str(wsu.workspace_id) == current_user.workspace_id,
            }
            for wsu, ws in rows
        ],
        "meta": {"count": len(rows)},
    }


@router.get("/hubspot/callback")
async def hubspot_callback(
    code: str,
    state: str = None,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    HubSpot OAuth callback — exchanges code for access + refresh tokens.
    Stores tokens encrypted in workspace record.
    """
    import hashlib as _hl2
    settings = get_settings()

    # CSRF: validate HMAC-signed state (workspace_id:nonce:sig)
    if not state:
        log.warning("hubspot_oauth_missing_state", workspace_id=current_user.workspace_id)
        raise HTTPException(status_code=400, detail="Missing OAuth state parameter")
    parts = state.rsplit(":", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid OAuth state parameter")
    state_payload, sig = parts
    if not settings.jwt_signing_key:
        raise HTTPException(status_code=503, detail="OAuth not configured — JWT_SIGNING_KEY missing")
    expected_sig = _hmac.new(
        settings.jwt_signing_key.encode(),
        state_payload.encode(),
        _hl2.sha256,
    ).hexdigest()
    if not _hmac.compare_digest(sig, expected_sig):
        log.warning("hubspot_oauth_state_invalid", workspace_id=current_user.workspace_id)
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    ws_id_from_state = state_payload.split(":")[0]
    if ws_id_from_state != current_user.workspace_id:
        log.warning("hubspot_oauth_workspace_mismatch", workspace_id=current_user.workspace_id)
        raise HTTPException(status_code=403, detail="OAuth state workspace mismatch")

    hs = HubSpotClient(access_token="")  # temp — not needed for token exchange
    try:
        tokens = await hs.exchange_code(
            code=code,
            redirect_uri=settings.hubspot_redirect_uri,
        )
    except Exception as e:
        log.error("hubspot_oauth_failed", error=str(e), exc_info=True)
        raise HTTPException(status_code=400, detail="HubSpot authentication failed. Please try again.")

    # Store tokens in workspace
    result = await db.execute(
        select(Workspace).where(Workspace.id == current_user.workspace_id)
    )
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    ws.hubspot_access_token = tokens.get("access_token")
    ws.hubspot_refresh_token = tokens.get("refresh_token")
    ws.hubspot_portal_id = str(tokens.get("hub_id", ""))
    expires_in = tokens.get("expires_in", 1800)
    ws.hubspot_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    await db.commit()

    log.info(
        "hubspot_connected",
        workspace_id=current_user.workspace_id,
        portal_id=ws.hubspot_portal_id,
    )

    return RedirectResponse(url=f"{settings.frontend_url}/settings/integrations?connected=hubspot")


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _find_or_create_workspace_user(
    db: AsyncSession,
    workos_user,
    settings,
) -> WorkspaceUser | None:
    """
    Find existing WorkspaceUser by workos_user_id, or create one.
    For internal (single-workspace) mode, auto-assigns to the default workspace.
    """
    result = await db.execute(
        select(WorkspaceUser).where(WorkspaceUser.workos_user_id == workos_user.id)
    )
    ws_user = result.scalar_one_or_none()

    if ws_user:
        # Update email in case it changed
        ws_user.email = workos_user.email
        await db.commit()
        return ws_user

    # Auto-provision for internal mode: find the default workspace.
    # Enforce domain restriction if ALLOWED_EMAIL_DOMAINS is configured.
    if settings.default_workspace_id:
        if settings.allowed_email_domains:
            domain = workos_user.email.split("@")[-1].lower() if "@" in workos_user.email else ""
            if domain not in [d.lower() for d in settings.allowed_email_domains]:
                log.warning(
                    "auto_provision_blocked",
                    email_domain=domain,
                    allowed=settings.allowed_email_domains,
                )
                return None  # Redirects to /auth/error?message=no_workspace_access

        ws_user = WorkspaceUser(
            workspace_id=uuid.UUID(settings.default_workspace_id),
            workos_user_id=workos_user.id,
            email=workos_user.email,
            role="rep",  # Default role; admin can promote
        )
        db.add(ws_user)
        await db.commit()
        await db.refresh(ws_user)
        import hashlib as _hl3
        log.info("workspace_user_created", email_hash=_hl3.sha256(workos_user.email.encode()).hexdigest()[:12], workspace_id=settings.default_workspace_id)
        return ws_user

    return None
