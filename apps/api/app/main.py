"""
Vantage API — Main FastAPI application entry point.
"""
# ── Force UTF-8 I/O on Windows before any logging starts ─────────────────────
# Windows defaults to cp1252 which can't encode Claude's Unicode output
# (smart quotes, em-dashes, etc.), causing UnicodeEncodeError in structlog.
import sys as _sys
for _s in (_sys.stdout, _sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
del _sys, _s
# ─────────────────────────────────────────────────────────────────────────────

import structlog
import sentry_sdk
import time
from collections import defaultdict, deque
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from app.config import get_settings
from app.db.database import check_db_connection
from app.routers import accounts, workspace, drafts, signals, agent, auth, webhooks, analytics, fireflies_webhook, forecast, timeline, help as help_router, documents

log = structlog.get_logger()

# ── Rate limiter ──────────────────────────────────────────────────────────────
# Redis-backed (shared across all container replicas) with in-memory fallback
# for local dev when Redis is unavailable.
_RATE_LIMITS = {
    "auth":          (10,  60),    # 10 req / 60s
    "batch_refresh": (5,   3600),  # 5 req / hour
    "agent_chat":    (30,  60),    # 30 req / 60s
    "help_chat":     (20,  60),    # 20 req / 60s
    "feedback":      (10,  60),    # 10 req / 60s  — protects interactions table
    "default":       (120, 60),    # 120 req / 60s
}

# In-memory fallback (single-instance only — used when Redis is unreachable)
_fallback_windows: dict = defaultdict(deque)

def _get_route_group(path: str) -> str:
    # /auth/me and /auth/workspaces are cheap reads fired on every page load —
    # rate them as normal traffic. The strict "auth" budget is for
    # login/callback/OAuth flows only.
    if path in ("/auth/me", "/auth/workspaces"):
        return "default"
    if path.startswith("/auth"):
        return "auth"
    if "/batch-refresh" in path:
        return "batch_refresh"
    if path.startswith("/v1/agent"):
        return "agent_chat"
    if path.startswith("/v1/help"):
        return "help_chat"
    if path.endswith("/feedback"):
        return "feedback"
    return "default"


async def _check_rate_limit_redis(ip: str, route_group: str) -> bool:
    """Redis fixed-window rate limiter. Returns True if request is allowed."""
    try:
        from app.services.cache import get_redis
        r = await get_redis()
        if not r:
            return _check_rate_limit_fallback(ip, route_group)
        limit, window = _RATE_LIMITS[route_group]
        key = f"rl:{ip}:{route_group}"
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, window)
        return count <= limit
    except Exception:
        return _check_rate_limit_fallback(ip, route_group)


def _check_rate_limit_fallback(ip: str, route_group: str) -> bool:
    """In-process sliding-window fallback when Redis is unavailable."""
    limit, window = _RATE_LIMITS[route_group]
    key = f"{ip}:{route_group}"
    now = time.time()
    # Evict the oldest key when the dict grows too large (prevents unbounded memory growth
    # during extended Redis outages under high-cardinality IP traffic)
    if len(_fallback_windows) > 10_000:
        try:
            oldest_key = next(iter(_fallback_windows))
            del _fallback_windows[oldest_key]
        except (StopIteration, RuntimeError):
            pass
    dq = _fallback_windows[key]
    while dq and dq[0] < now - window:
        dq.popleft()
    if len(dq) >= limit:
        return False
    dq.append(now)
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    settings = get_settings()

    # Configure Sentry
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            traces_sample_rate=0.1,
        )

    # Refuse to start in production with debug mode active
    if settings.environment == "production" and settings.debug:
        raise RuntimeError(
            "FATAL: DEBUG=true is not allowed in production. "
            "Set DEBUG=false and restart."
        )

    # Require JWT_SIGNING_KEY in all non-dev environments
    if settings.environment != "development" and not settings.jwt_signing_key:
        raise RuntimeError(
            "FATAL: JWT_SIGNING_KEY must be set. "
            "Generate with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    if not settings.jwt_signing_key:
        log.warning("jwt_signing_key_not_set", note="Share links disabled until JWT_SIGNING_KEY is set in .env")

    # Require WORKOS_COOKIE_SECRET in production (prevents client_id being used as cookie key)
    if settings.environment != "development" and not settings.workos_cookie_secret:
        raise RuntimeError(
            "FATAL: WORKOS_COOKIE_SECRET must be set. "
            "Generate with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    if not settings.workos_cookie_secret:
        log.warning("workos_cookie_secret_not_set", note="Using workos_client_id as cookie password — set WORKOS_COOKIE_SECRET before deploying")

    # Warn if FIELD_ENCRYPTION_KEY is missing (tokens stored plaintext)
    if not settings.field_encryption_key:
        if settings.environment != "development":
            raise RuntimeError(
                "FATAL: FIELD_ENCRYPTION_KEY must be set. "
                "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        log.warning("field_encryption_key_not_set", note="OAuth tokens stored as plaintext — set FIELD_ENCRYPTION_KEY before deploying")

    # Validate FRONTEND_URL — must start with https:// to prevent open redirect
    if settings.frontend_url:
        _fe_url = settings.frontend_url.strip()
        if not _fe_url.startswith("https://"):
            if settings.environment == "production":
                raise RuntimeError(
                    "FATAL: FRONTEND_URL must start with 'https://' in production to prevent open redirects."
                )
            log.warning("frontend_url_insecure", note="FRONTEND_URL should start with https:// before deploying")

    # Require Redis password — no default fallback allowed
    if "vantage_redis_local" in settings.redis_url or settings.redis_url == "redis://localhost:6379/0":
        if settings.environment == "production":
            raise RuntimeError(
                "FATAL: Redis is using default/no password in production. "
                "Set REDIS_URL with a strong password."
            )
        else:
            log.warning("redis_default_password", note="Redis is using the default dev password. Set REDIS_URL with a strong password before deploying.")

    # Verify DB on startup
    db_ok = await check_db_connection()
    if not db_ok:
        log.error("startup_failed", reason="database_unreachable")
        raise RuntimeError("Cannot connect to database")

    log.info("vantage_api_started", environment=settings.environment)
    yield
    log.info("vantage_api_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Vantage API",
        description="Per-Account Agent Platform for Enterprise Sales",
        version="1.0.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # Security headers — applied to every response
    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    # Rate limiting middleware
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        # Skip rate limiting for health checks and OPTIONS (CORS preflight)
        if request.method == "OPTIONS" or request.url.path == "/health":
            return await call_next(request)

        # Azure Container Apps appends its own ingress IP as the rightmost XFF entry.
        # The actual client IP is the penultimate entry (one before Azure's hop).
        # Using [-1] would always yield Azure's internal IP, making per-IP limits useless.
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            ip = parts[-2] if len(parts) >= 2 else parts[0]
        else:
            ip = request.client.host if request.client else "unknown"
        route_group = _get_route_group(request.url.path)

        if not await _check_rate_limit_redis(ip, route_group):
            limit, window = _RATE_LIMITS[route_group]
            log.warning("rate_limit_exceeded", ip=ip, path=request.url.path, route_group=route_group)
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "rate_limited", "message": f"Too many requests. Limit: {limit} per {window}s."}},
                headers={"Retry-After": str(window)},
            )
        return await call_next(request)

    # CORS — added LAST so it is the OUTERMOST middleware. Responses generated by
    # inner middleware (rate-limit 429s, security headers) must still pass through
    # CORS or the browser masks them as opaque CORS failures.
    # Fallback origins for local dev only — http:// is intentional (browsers don't issue
    # HTTPS for localhost). Production deployments must set CORS_ORIGINS in env to
    # https:// origins exclusively; the http:// entries must never appear there.
    _cors_origins = settings.cors_origins if settings.cors_origins else [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "https://vantage.vercel.app",
        "https://app.vantage.ai",
        "https://web-puce-three-40.vercel.app",
        "https://acetone-underpaid-undertook.ngrok-free.dev",
    ]
    if settings.environment == "production":
        insecure = [o for o in _cors_origins if o.startswith("http://")]
        if insecure:
            raise RuntimeError(
                f"FATAL: CORS_ORIGINS contains http:// origins in production: {insecure}. "
                "Set CORS_ORIGINS to https:// origins only."
            )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Cookie"],
    )

    # Routers
    app.include_router(auth.router,     prefix="/auth",          tags=["Auth"])
    app.include_router(workspace.router, prefix="/v1/workspace",  tags=["Workspace"])
    app.include_router(accounts.router,  prefix="/v1/accounts",   tags=["Accounts"])
    app.include_router(drafts.router,    prefix="/v1/drafts",      tags=["Drafts"])
    app.include_router(signals.router,   prefix="/v1/signals",     tags=["Signals"])
    app.include_router(agent.router,     prefix="/v1/agent",       tags=["Agent"])
    app.include_router(webhooks.router,  prefix="/webhooks",       tags=["Webhooks"])
    app.include_router(analytics.router,          prefix="/v1/analytics",   tags=["Analytics"])
    app.include_router(fireflies_webhook.router,  prefix="/webhooks",       tags=["Webhooks"])
    app.include_router(forecast.router,              prefix="/v1/forecast",   tags=["Forecast"])
    app.include_router(forecast.accounts_router,     prefix="/v1/accounts",   tags=["Forecast"])
    app.include_router(timeline.router,              prefix="/v1/accounts",         tags=["Timeline"])
    app.include_router(timeline.actions_router,      prefix="/v1/timeline-actions", tags=["Timeline"])
    app.include_router(timeline.workspace_router,    prefix="/v1/workspace",        tags=["Timeline"])
    app.include_router(help_router.router,           prefix="/v1/help",             tags=["Help"])
    app.include_router(documents.router,             prefix="/v1/documents",        tags=["Documents"])

    # Health check — minimal public response (no internal state disclosure)
    @app.get("/health", tags=["Health"])
    async def health():
        db_ok = await check_db_connection()
        if not db_ok:
            return JSONResponse(status_code=503, content={"status": "degraded"})
        return {"status": "ok"}

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        try:
            log.error(
                "unhandled_exception",
                path=request.url.path,
                method=request.method,
                error=str(exc),
                exc_info=True,
            )
        except Exception:
            # Fallback: structlog may fail on Windows with non-cp1252 chars in traceback
            import sys
            print(f"[ERROR] unhandled_exception path={request.url.path} error={type(exc).__name__}: {exc}", file=sys.stderr)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred",
                    "request_id": request.headers.get("x-request-id", ""),
                }
            },
        )

    return app


app = create_app()
