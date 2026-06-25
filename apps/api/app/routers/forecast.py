"""
Forecast router — AI vs CRM comparison + rep POV override.
GET  /v1/forecast/rollup              — workspace forecast breakdown
POST /v1/accounts/{id}/pov/override   — rep overrides AI forecast
"""
import uuid as _uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from pydantic import BaseModel
import structlog

from app.db.database import get_db
from app.middleware.auth import get_current_user, CurrentUser
from app.models.account import Account, AuditLog
from app.models.workspace import Workspace

log = structlog.get_logger()

router = APIRouter()           # mounted at /v1/forecast
accounts_router = APIRouter()  # mounted at /v1/accounts


class PovOverrideRequest(BaseModel):
    override_category: str
    reason: str


def _week_ago_snapshot(history: list, now: datetime) -> Optional[dict]:
    """Most recent snapshot that is at least 6 days old — the week-over-week baseline."""
    cutoff = now - timedelta(days=6)
    eligible = []
    for h in history or []:
        try:
            d = datetime.fromisoformat(str(h.get("date")).replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            if d <= cutoff:
                eligible.append((d, h))
        except (ValueError, TypeError):
            continue
    return max(eligible, key=lambda t: t[0])[1] if eligible else None


@router.get("/rollup")
async def get_forecast_rollup(
    rep: Optional[str] = Query(None, description="Filter by HubSpot owner ID"),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ws = current_user.workspace_id
    result = await db.execute(
        select(Account).where(
            Account.workspace_id == ws,
            Account.deleted_at.is_(None),
        )
    )
    accounts = result.scalars().all()

    # Owner ID → display name, synced from HubSpot into workspace settings
    ws_row = (await db.execute(select(Workspace).where(Workspace.id == ws))).scalar_one_or_none()
    owner_names: dict = (ws_row.settings or {}).get("hubspot_owners", {}) if ws_row else {}

    # Rep rollup is computed over ALL accounts (before the rep filter) so the
    # filter chips always show the full team
    reps: dict = {}
    for acc in accounts:
        if not acc.owner_rep_id:
            continue
        r = reps.setdefault(acc.owner_rep_id, {
            "id": acc.owner_rep_id,
            "name": owner_names.get(str(acc.owner_rep_id)) or f"Rep #{acc.owner_rep_id}",
            "count": 0,
            "total_amount": 0.0,
        })
        r["count"] += 1
        r["total_amount"] += float(acc.deal_amount or 0)

    if rep:
        accounts = [a for a in accounts if a.owner_rep_id == rep]

    categories: dict = {}
    ai_vs_crm = []
    week_deltas = []
    now = datetime.now(timezone.utc)
    total_pipeline = 0.0
    overridden_count = 0

    for acc in accounts:
        amount = float(acc.deal_amount or 0)
        total_pipeline += amount
        ai_cat = acc.pov_forecast_cat or "Pipeline"
        ai_conf = acc.pov_confidence or 0.0
        state = acc.state or {}
        pov = state.get("pov", {})
        crm_cat = state.get("crm_forecast_category", "Unknown")
        human_override = pov.get("human_override")
        if human_override:
            overridden_count += 1
        display_cat = human_override.get("category") if human_override else ai_cat
        if display_cat not in categories:
            categories[display_cat] = {"count": 0, "total_amount": 0.0, "accounts": []}
        categories[display_cat]["count"] += 1
        categories[display_cat]["total_amount"] += amount
        categories[display_cat]["accounts"].append({
            "id": str(acc.id),
            "name": acc.name,
            "amount": amount,
            "health_score": acc.health_score,
            "confidence": ai_conf,
            "overridden": bool(human_override),
        })
        if ai_cat and crm_cat and crm_cat != "Unknown" and ai_cat != crm_cat:
            ai_vs_crm.append({
                "account_id": str(acc.id),
                "name": acc.name,
                "amount": amount,
                "ai_category": ai_cat,
                "crm_category": crm_cat,
                "ai_confidence": ai_conf,
                "delta": f"AI says '{ai_cat}', CRM says '{crm_cat}'",
                "overridden": bool(human_override),
            })

        # Week-over-week category movement from per-run forecast snapshots
        baseline = _week_ago_snapshot(state.get("forecast_history"), now)
        if baseline and baseline.get("category") and baseline["category"] != display_cat:
            week_deltas.append({
                "account_id": str(acc.id),
                "name": acc.name,
                "amount": amount,
                "from_category": baseline["category"],
                "to_category": display_cat,
                "as_of": baseline.get("date"),
                "reason": pov.get("forecast_rationale") or pov.get("forecast_explanation"),
                "owner_rep_id": acc.owner_rep_id,
            })

    ai_vs_crm.sort(key=lambda x: x["amount"], reverse=True)
    week_deltas.sort(key=lambda x: x["amount"], reverse=True)

    return {
        "data": {
            "categories": categories,
            "ai_vs_crm_deltas": ai_vs_crm[:20],
            "week_deltas": week_deltas[:20],
            "reps": sorted(reps.values(), key=lambda r: r["total_amount"], reverse=True),
            "total_pipeline": total_pipeline,
            "overridden_count": overridden_count,
            "accounts_analyzed": len([a for a in accounts if a.last_agent_run_at]),
            "accounts_total": len(accounts),
        },
        "meta": {"workspace_id": ws, "rep_filter": rep},
    }


@accounts_router.post("/{account_id}/pov/override")
async def override_pov(
    account_id: str,
    body: PovOverrideRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    valid = {"Pipeline", "Best Case", "Commit", "Omit"}
    if body.override_category not in valid:
        raise HTTPException(status_code=422, detail=f"category must be one of {valid}")

    override_q = select(Account).where(
        Account.id == account_id,
        Account.workspace_id == current_user.workspace_id,
        Account.deleted_at.is_(None),
    )
    if not current_user.is_manager():
        override_q = override_q.where(Account.owner_rep_id == current_user.workos_user_id)

    result = await db.execute(override_q)
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    state = account.state or {}
    pov = state.get("pov", {})
    ai_category = account.pov_forecast_cat or pov.get("forecast_category", "Unknown")
    pov["human_override"] = {
        "category": body.override_category,
        "reason": body.reason,
        "ai_category": ai_category,
        "overridden_by": current_user.user_id,
        "overridden_at": datetime.now(timezone.utc).isoformat(),
    }
    state["pov"] = pov
    account.state = state
    flag_modified(account, "state")

    db.add(AuditLog(
        workspace_id=_uuid.UUID(current_user.workspace_id),
        action="pov_override",
        resource_type="account",
        resource_id=account_id,
        actor_id=current_user.user_id,
        changes={"ai_category": ai_category, "override_category": body.override_category, "reason": body.reason},
    ))
    await db.commit()

    try:
        from app.services.cache import invalidate_aso
        await invalidate_aso(account_id, workspace_id=current_user.workspace_id)
    except Exception:
        pass

    log.info("pov_overridden", account_id=account_id, ai=ai_category, override=body.override_category)
    return {
        "data": {"applied": True, "ai_category": ai_category, "override_category": body.override_category},
        "meta": {"account_id": account_id},
    }
