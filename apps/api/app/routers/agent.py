"""
Agent router — Streaming chat assistant + thread management.
POST /v1/agent/chat             — stream chat response (SSE)
GET  /v1/agent/threads          — list conversation threads
GET  /v1/agent/threads/{id}     — thread history
DELETE /v1/agent/threads/{id}   — clear thread
POST /v1/agent/chat/{account_id}/prepare — pre-fetch meeting brief (non-streaming)
"""
import json
import uuid
from typing import Optional, AsyncGenerator
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel, Field as _Field
import structlog

from app.db.database import get_db
from app.middleware.auth import get_current_user, CurrentUser, require_scope, require_manager
from app.models.account import Account
from app.services.assistant import AssistantService

log = structlog.get_logger()
router = APIRouter()


# ── Request/Response schemas ──────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = _Field(..., min_length=1, max_length=10000)
    account_id: Optional[str] = None  # if scoped to a specific account
    thread_id: Optional[str] = None   # continue existing thread
    use_web_research: bool = False     # live Exa web search for this query


class MeetingBriefRequest(BaseModel):
    meeting_context: Optional[str] = _Field(None, max_length=2000)  # optional extra context from calendar


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(
    body: ChatRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Stream a chat response grounded on account ASO + episodic memory.
    Returns Server-Sent Events (SSE).

    The Assistant is always grounded — every fact it cites is traceable to
    the Gold Data Layer. Users can click any fact to open the Audit Panel.
    """
    # Validate account if scoped — enforce rep-level isolation
    account = None
    if body.account_id:
        try:
            _acct_uuid = uuid.UUID(body.account_id)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=404, detail="Account not found")
        acct_q = select(Account).where(
            Account.id == _acct_uuid,
            Account.workspace_id == current_user.workspace_id,
            Account.deleted_at.is_(None),
        )
        if not current_user.is_manager():
            acct_q = acct_q.where(Account.owner_rep_id == current_user.workos_user_id)
        result = await db.execute(acct_q)
        account = result.scalar_one_or_none()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

    thread_id = body.thread_id or str(uuid.uuid4())

    # Load workspace seller context for grounded, seller-POV responses
    from app.models.workspace import Workspace
    ws_row = await db.execute(select(Workspace).where(Workspace.id == current_user.workspace_id))
    ws = ws_row.scalar_one_or_none()
    ws_settings = (ws.settings or {}) if ws else {}
    seller_context = {
        "sender_name":         ws_settings.get("sender_name", ""),
        "sender_title":        ws_settings.get("sender_title", ""),
        "sender_company":      ws_settings.get("sender_company", ws.name if ws else ""),
        "product_description": ws_settings.get("product_description", ""),
    }

    service = AssistantService(db)

    async def event_stream() -> AsyncGenerator[str, None]:
        """SSE generator — yields JSON chunks as they stream."""
        try:
            # Send thread_id immediately so frontend can display/persist it
            yield _sse_event("thread", {"thread_id": thread_id})

            citations = []
            full_response = ""

            async for chunk in service.stream_response(
                workspace_id=current_user.workspace_id,
                user_id=current_user.user_id,
                message=body.message,
                account=account,
                thread_id=thread_id,
                use_web_research=body.use_web_research,
                seller_context=seller_context,
            ):
                if chunk["type"] == "text":
                    full_response += chunk["text"]
                    yield _sse_event("text", {"delta": chunk["text"]})
                elif chunk["type"] == "citation":
                    citations.append(chunk["citation"])
                elif chunk["type"] == "done":
                    # Send final citations for Audit Panel
                    yield _sse_event("citations", {"citations": citations})
                    yield _sse_event("done", {
                        "thread_id": thread_id,
                        "token_count": chunk.get("tokens", 0),
                    })
                elif chunk["type"] == "error":
                    yield _sse_event("error", {"message": chunk.get("message", "Stream interrupted. Please retry.")})

        except Exception as e:
            log.error("chat_stream_error", error=str(e), thread_id=thread_id)
            yield _sse_event("error", {"message": "Stream interrupted. Please retry."})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/threads")
async def list_threads(
    account_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List conversation threads for the current user."""
    service = AssistantService(db)
    threads = await service.list_threads(
        user_id=current_user.user_id,
        workspace_id=current_user.workspace_id,
        account_id=account_id,
        page=page,
        limit=limit,
    )
    return {
        "data": threads,
        "meta": {"user_id": current_user.user_id},
    }


@router.get("/threads/{thread_id}")
async def get_thread(
    thread_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return full message history for a thread."""
    service = AssistantService(db)
    messages = await service.get_thread(
        thread_id=thread_id,
        user_id=current_user.user_id,
        workspace_id=current_user.workspace_id,
    )
    if messages is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    return {"data": {"thread_id": thread_id, "messages": messages}, "meta": {}}


@router.delete("/threads/{thread_id}")
async def delete_thread(
    thread_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    _write: None = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a conversation thread."""
    service = AssistantService(db)
    deleted = await service.delete_thread(
        thread_id=thread_id,
        user_id=current_user.user_id,
        workspace_id=current_user.workspace_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Thread not found")

    return {"data": {"deleted": True}, "meta": {}}


@router.post("/{account_id}/prepare")
async def prepare_meeting_brief(
    account_id: str,
    body: MeetingBriefRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Pre-fetch a meeting brief for an account (non-streaming).
    Called by calendar integration or on-demand from account page.
    Returns structured brief: stakeholders, risks, questions, latest signals.
    """
    try:
        _brief_uuid = uuid.UUID(account_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="Account not found")

    result = await db.execute(
        select(Account).where(
            Account.id == _brief_uuid,
            Account.workspace_id == current_user.workspace_id,
            Account.deleted_at.is_(None),
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    from app.models.workspace import Workspace
    ws_row2 = await db.execute(select(Workspace).where(Workspace.id == current_user.workspace_id))
    ws2 = ws_row2.scalar_one_or_none()
    ws_settings2 = (ws2.settings or {}) if ws2 else {}
    seller_ctx2 = {
        "sender_name":         ws_settings2.get("sender_name", ""),
        "sender_title":        ws_settings2.get("sender_title", ""),
        "sender_company":      ws_settings2.get("sender_company", ws2.name if ws2 else ""),
        "product_description": ws_settings2.get("product_description", ""),
    }

    service = AssistantService(db)
    brief = await service.build_meeting_brief(
        account=account,
        workspace_id=current_user.workspace_id,
        meeting_context=body.meeting_context,
        seller_context=seller_ctx2,
    )

    return {
        "data": brief,
        "meta": {"account_id": account_id, "account_name": account.name},
    }


@router.post("/refresh-urgent")
async def refresh_urgent_accounts(
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """
    Intraday sweep — immediately re-run agents on accounts with urgency >= 0.85
    that haven't been processed in the last 6 hours.
    Designed to be called at noon (midday sweep) or on-demand.
    Returns count of accounts queued.
    """
    from app.services.nightly_worker import NightlyWorker
    from app.models.workspace import Workspace

    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    result = await db.execute(
        select(Account).where(
            Account.workspace_id == current_user.workspace_id,
            Account.deleted_at.is_(None),
            Account.urgency_score >= 0.85,
            (Account.last_agent_run_at.is_(None)) | (Account.last_agent_run_at < cutoff),
        ).order_by(Account.urgency_score.desc()).limit(10)
    )
    urgent = result.scalars().all()

    if not urgent:
        return {"data": {"queued": 0, "message": "No urgent accounts need refresh"}, "meta": {}}

    # Get workspace
    ws_result = await db.execute(select(Workspace).where(Workspace.id == current_user.workspace_id))
    ws = ws_result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Run urgent accounts in background
    account_ids = [str(a.id) for a in urgent]
    from app.db.database import AsyncSessionLocal

    async def _run_urgent():
        async with AsyncSessionLocal() as bg_db:
            worker = NightlyWorker(bg_db)
            ws_bg = await bg_db.execute(select(Workspace).where(Workspace.id == ws.id))
            ws_obj = ws_bg.scalar_one_or_none()
            if not ws_obj:
                return
            accs_bg = await bg_db.execute(
                select(Account).where(Account.id.in_([uuid.UUID(i) for i in account_ids]))
            )
            for acct in accs_bg.scalars().all():
                try:
                    await worker._process_account(acct, ws_obj, "intraday_sweep")
                except Exception as e:
                    log.warning("intraday_sweep_failed", account=str(acct.id), error=str(e))

    background_tasks.add_task(_run_urgent)

    log.info("intraday_sweep_triggered", workspace_id=current_user.workspace_id, count=len(urgent))
    return {
        "data": {
            "queued": len(urgent),
            "accounts": [{"id": a.id, "name": a.name, "urgency": a.urgency_score} for a in urgent],
            "message": f"Running agents on {len(urgent)} urgent accounts in background",
        },
        "meta": {},
    }


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse_event(event_type: str, data: dict) -> str:
    """Format a Server-Sent Events message."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
