"""
Auth middleware — WorkOS JWT validation + API key verification.
Every request must pass one of these.
"""
from typing import Optional, Tuple
import hashlib
import hmac
from datetime import datetime, timezone
from fastapi import Depends, HTTPException, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import workos
import structlog

from app.config import get_settings
from app.db.database import get_db
from app.models.workspace import Workspace, WorkspaceUser
from app.models.account import ApiKey

log = structlog.get_logger()
security = HTTPBearer(auto_error=False)


class CurrentUser:
    """Authenticated user context — attached to every request."""
    def __init__(
        self,
        user_id: str,
        workspace_id: str,
        email: str,
        role: str,
        workos_user_id: str,
        scopes: list[str] = None,
        is_api_key: bool = False,
    ):
        self.user_id = user_id
        self.workspace_id = workspace_id
        self.email = email
        self.role = role
        self.workos_user_id = workos_user_id
        self.scopes = scopes or ["read", "write"]
        self.is_api_key = is_api_key

    def can(self, scope: str) -> bool:
        return scope in self.scopes

    def is_manager(self) -> bool:
        return self.role in ("manager", "admin", "owner")


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    """
    FastAPI dependency: validates WorkOS JWT or API key.
    Returns CurrentUser with workspace context.
    """
    settings = get_settings()

    # Cookie fallback — for browser clients that can't set Authorization headers.
    # The WorkOS callback sets `vantage_session` as httponly; JS cannot read it but
    # fetch with credentials:"include" sends it here, so we read it server-side.
    # samesite=lax + secure=True makes this CSRF-safe for our use case.
    token = None
    if credentials:
        token = credentials.credentials
    elif request:
        cookie_token = request.cookies.get("vantage_session")
        if cookie_token:
            preferred_ws = request.headers.get("X-Preferred-Workspace")
            return await _validate_workos_jwt(cookie_token, db, settings, preferred_ws)

    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Dev bypass — DEBUG mode only, AND only when debug_bypass_token is explicitly set in .env.
    # Never active in production (startup check blocks DEBUG=true there).
    # Token must match the configured secret — not a hardcoded string.
    if (
        settings.debug
        and settings.debug_bypass_token
        and token == settings.debug_bypass_token
    ):
        log.info("dev_bypass_auth", note="DEBUG mode — bypassing WorkOS via configured bypass token")
        return CurrentUser(
            user_id="00000000-0000-0000-0000-000000000001",
            workspace_id=settings.default_workspace_id,
            email="dev-bypass@localhost",
            role="admin",
            workos_user_id="dev-bypass",
            scopes=["read", "write", "admin"],
        )

    # API Key path (prefix: vnt_live_)
    if token.startswith(settings.api_key_prefix):
        return await _validate_api_key(token, db)

    # WorkOS JWT path
    preferred_ws = request.headers.get("X-Preferred-Workspace") if request else None
    return await _validate_workos_jwt(token, db, settings, preferred_ws)


async def _validate_workos_jwt(
    token: str, db: AsyncSession, settings, preferred_workspace_id: Optional[str] = None
) -> CurrentUser:
    """Validate a WorkOS JWT and return user context."""
    try:
        workos_client = workos.WorkOS(api_key=settings.workos_api_key)
        # Verify the JWT — raises on invalid/expired
        payload = workos_client.user_management.load_sealed_session(
            session_data=token,
            cookie_password=settings.workos_cookie_secret or settings.workos_client_id,
        )
        workos_user_id = payload.get("sub") or payload.get("user_id")
        email = payload.get("email", "")

    except Exception as e:
        log.warning("jwt_validation_failed", error=str(e))
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Look up workspace memberships — support multi-workspace via X-Preferred-Workspace
    result = await db.execute(
        select(WorkspaceUser).where(WorkspaceUser.workos_user_id == workos_user_id)
    )
    ws_users = result.scalars().all()

    if not ws_users:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Prefer explicitly requested workspace if user has access; fall back to first.
    # Log workspace switches — auditable trail for the X-Preferred-Workspace hop.
    ws_user = ws_users[0]
    if preferred_workspace_id and preferred_workspace_id != str(ws_users[0].workspace_id):
        for wu in ws_users:
            if str(wu.workspace_id) == preferred_workspace_id:
                ws_user = wu
                log.info(
                    "workspace_switch",
                    workos_user_id=workos_user_id,
                    from_workspace=str(ws_users[0].workspace_id),
                    to_workspace=preferred_workspace_id,
                )
                break

    return CurrentUser(
        user_id=str(ws_user.id),
        workspace_id=str(ws_user.workspace_id),
        email=ws_user.email or email,
        role=ws_user.role,
        workos_user_id=workos_user_id,
        scopes=["read", "write", "admin"] if ws_user.role in ("admin", "owner") else ["read", "write"],
    )


async def _validate_api_key(token: str, db: AsyncSession) -> CurrentUser:
    """Validate an API key (vnt_live_...) and return user context."""
    key_hash = hashlib.sha256(token.encode()).hexdigest()

    # Indexed lookup — no full table scan
    result = await db.execute(
        select(ApiKey).where(
            ApiKey.key_hash == key_hash,
            ApiKey.revoked_at.is_(None),
        )
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Belt-and-suspenders: constant-time comparison after DB lookup
    # Guards against any ORM shortcut that might skip character-level comparison
    if not hmac.compare_digest(api_key.key_hash, key_hash):
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Check expiry
    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        log.warning("api_key_expired", key_id=str(api_key.id), workspace_id=str(api_key.workspace_id))
        raise HTTPException(status_code=401, detail="API key has expired")

    # Update last_used_at at most every 5 minutes (reduce write amplification)
    now = datetime.now(timezone.utc)
    if not api_key.last_used_at or (now - api_key.last_used_at).total_seconds() > 300:
        api_key.last_used_at = now
        await db.commit()

    return CurrentUser(
        user_id=str(api_key.id),
        workspace_id=str(api_key.workspace_id),
        email="api-key",
        role="api",
        workos_user_id="",
        scopes=api_key.scopes or ["read"],
        is_api_key=True,
    )


def require_scope(scope: str):
    """Dependency factory: require a specific scope."""
    async def _require(user: CurrentUser = Depends(get_current_user)):
        if not user.can(scope):
            raise HTTPException(
                status_code=403,
                detail=f"This action requires '{scope}' scope"
            )
        return user
    return _require


def require_manager():
    """Dependency: require manager role or higher."""
    async def _require(user: CurrentUser = Depends(get_current_user)):
        if not user.is_manager():
            raise HTTPException(
                status_code=403,
                detail="This action requires manager role or higher"
            )
        return user
    return _require
