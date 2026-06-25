"""
Signals router — Signal feed and acknowledgment.
GET  /v1/signals                — list signals across portfolio (Watchtower view)
GET  /v1/signals/{id}           — single signal detail
POST /v1/signals/{id}/acknowledge — mark as seen (removes from inbox badge)
"""
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
import structlog

from app.db.database import get_db
from app.middleware.auth import get_current_user, CurrentUser, require_scope
from app.models.account import Signal, Account

log = structlog.get_logger()
router = APIRouter()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_signals(
    account_id: Optional[str] = None,
    signal_type: Optional[str] = None,
    min_urgency: Optional[float] = None,
    pushed_only: bool = False,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List signals across the portfolio — Watchtower feed.
    Ordered by urgency_score DESC, created_at DESC.
    """
    q = (
        select(Signal)
        .join(Account, Signal.account_id == Account.id)
        .where(
            Account.workspace_id == current_user.workspace_id,
            Account.deleted_at.is_(None),
        )
        .options(selectinload(Signal.account))
    )

    if account_id:
        try:
            _acct_uuid = uuid.UUID(account_id)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=404, detail="Account not found")
        q = q.where(Signal.account_id == _acct_uuid)
    if signal_type:
        q = q.where(Signal.type == signal_type)
    if min_urgency is not None:
        q = q.where(Signal.urgency_score >= min_urgency)
    if pushed_only:
        q = q.where(Signal.pushed_to_inbox == True)

    # Reps see only their accounts
    if not current_user.is_manager():
        q = q.where(Account.owner_rep_id == current_user.workos_user_id)

    # Total count (before pagination)
    count_q = select(func.count()).select_from(q.subquery())
    count_result = await db.execute(count_q)
    total = count_result.scalar_one()

    q = q.order_by(Signal.urgency_score.desc().nullslast(), Signal.created_at.desc())
    q = q.offset((page - 1) * limit).limit(limit)

    result = await db.execute(q)
    signals = result.scalars().all()

    return {
        "data": [_format_signal(s) for s in signals],
        "meta": {"filters_applied": {
            "account_id": account_id,
            "type": signal_type,
            "min_urgency": min_urgency,
        }},
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "returned": len(signals),
            "has_more": (page * limit) < total,
        },
    }


@router.get("/{signal_id}")
async def get_signal(
    signal_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return full signal detail including Gold Data audit trail."""
    try:
        _signal_uuid = uuid.UUID(signal_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="Signal not found")
    q = (
        select(Signal)
        .join(Account, Signal.account_id == Account.id)
        .where(
            Signal.id == _signal_uuid,
            Account.workspace_id == current_user.workspace_id,
        )
        .options(selectinload(Signal.account))
    )
    if not current_user.is_manager():
        q = q.where(Account.owner_rep_id == current_user.workos_user_id)
    result = await db.execute(q)
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    data = _format_signal(signal)
    # Full detail: gold sources for Audit Panel
    data["gold_sources"] = signal.gold_sources or []
    data["gold_resolution"] = signal.gold_resolution
    data["source_url"] = signal.source_url
    data["confidence"] = signal.confidence

    return {"data": data, "meta": {"signal_id": signal_id}}


@router.post("/{signal_id}/acknowledge")
async def acknowledge_signal(
    signal_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    _write: None = Depends(require_scope("write")),
    db: AsyncSession = Depends(get_db),
):
    """Mark a signal as acknowledged — removes from inbox badge count."""
    try:
        _ack_uuid = uuid.UUID(signal_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="Signal not found")
    ack_q = (
        select(Signal)
        .join(Account, Signal.account_id == Account.id)
        .where(
            Signal.id == _ack_uuid,
            Account.workspace_id == current_user.workspace_id,
        )
    )
    if not current_user.is_manager():
        ack_q = ack_q.where(Account.owner_rep_id == current_user.workos_user_id)

    result = await db.execute(ack_q)
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")

    signal.acknowledged = True
    signal.acknowledged_by = current_user.user_id
    await db.commit()

    log.info("signal_acknowledged", signal_id=signal_id, user=current_user.user_id)
    return {"data": {"acknowledged": True}, "meta": {}}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_signal(signal: Signal) -> dict:
    account = signal.account if hasattr(signal, "account") and signal.account else None
    return {
        "id": str(signal.id),
        "type": signal.type,
        "urgency": signal.urgency,
        "urgency_score": signal.urgency_score,
        "detail": signal.detail,
        "source": signal.source,
        "account": {
            "id": str(signal.account_id),
            "name": account.name if account else None,
            "stage": account.stage if account else None,
        },
        "processed": signal.processed,
        "pushed_to_inbox": signal.pushed_to_inbox,
        "acknowledged": getattr(signal, "acknowledged", False),
        "created_at": signal.created_at.isoformat() if signal.created_at else None,
        "agent_run_id": str(signal.agent_run_id) if signal.agent_run_id else None,
    }
