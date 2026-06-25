"""
Timeline router — self-driving action queue per deal.

GET  /v1/accounts/{id}/timeline-actions      — full deal timeline
POST /v1/accounts/{id}/timeline-actions      — create a manual action
PATCH /v1/timeline-actions/{id}              — complete | skip | reschedule | edit title
DELETE /v1/timeline-actions/{id}             — delete a rep-created action

GET  /v1/workspace/action-queue              — today's + overdue across all deals
"""
import uuid
from datetime import date, datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, desc
from pydantic import BaseModel, Field
import structlog

from app.db.database import get_db
from app.middleware.auth import get_current_user, CurrentUser
from app.models.account import Account, TimelineAction, Draft, Interaction, Signal
from app.services.timeline_service import TimelineService

log = structlog.get_logger()
router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class TimelineActionOut(BaseModel):
    id: str
    account_id: str
    account_name: Optional[str] = None
    account_stage: Optional[str] = None
    action_type: str
    title: str
    reasoning: Optional[str]
    due_date: str
    priority: float
    status: str
    skip_count: int
    draft_id: Optional[str]
    prepared_content: Optional[dict]
    source: Optional[str]
    meddpicc_component: Optional[str]
    deal_stage_at_creation: Optional[str]
    created_at: Optional[str]
    completed_at: Optional[str]
    completed_notes: Optional[str]


class CreateActionRequest(BaseModel):
    action_type: str = Field(..., pattern="^(email|call_prep|meeting_prep|stakeholder_intro|proposal_follow|close_push|champion_checkin|escalation|rep_created)$")
    title: str = Field(..., min_length=3, max_length=500)
    reasoning: Optional[str] = Field(None, max_length=1000)
    due_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    priority: float = Field(0.5, ge=0.0, le=1.0)


class PatchActionRequest(BaseModel):
    action: str = Field(..., pattern="^(complete|skip|reschedule|edit)$")
    notes: Optional[str] = Field(None, max_length=2000)
    outcome: Optional[str] = Field(None, pattern="^(sent_email|had_call|got_response|meeting_booked|not_relevant|done)$")
    new_due_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    new_title: Optional[str] = Field(None, max_length=500)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _serialize(action: TimelineAction, account: Account = None) -> dict:
    return {
        "id": str(action.id),
        "account_id": str(action.account_id),
        "account_name": account.name if account else None,
        "account_stage": account.stage if account else action.deal_stage_at_creation,
        "action_type": action.action_type,
        "title": action.title,
        "reasoning": action.reasoning,
        "due_date": str(action.due_date),
        "priority": action.priority or 0.5,
        "status": action.status,
        "skip_count": action.skip_count or 0,
        "draft_id": str(action.draft_id) if action.draft_id else None,
        "prepared_content": action.prepared_content,
        "source": action.source,
        "meddpicc_component": action.meddpicc_component,
        "deal_stage_at_creation": action.deal_stage_at_creation,
        "created_at": action.created_at.isoformat() if action.created_at else None,
        "completed_at": action.completed_at.isoformat() if action.completed_at else None,
        "completed_notes": action.completed_notes,
    }


async def _get_account(account_id: str, workspace_id: str, db: AsyncSession) -> Account:
    result = await db.execute(
        select(Account).where(
            Account.id == uuid.UUID(account_id),
            Account.workspace_id == uuid.UUID(workspace_id),
            Account.deleted_at.is_(None),
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


# ── Account-scoped endpoints ──────────────────────────────────────────────────

@router.get("/{account_id}/timeline-actions")
async def get_timeline_actions(
    account_id: str,
    include_done: bool = Query(False),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full timeline for one deal: past (done), today, upcoming, overdue."""
    account = await _get_account(account_id, current_user.workspace_id, db)

    statuses = ["today", "overdue", "upcoming"]
    if include_done:
        statuses.append("done")

    result = await db.execute(
        select(TimelineAction)
        .where(
            TimelineAction.account_id == account.id,
            TimelineAction.status.in_(statuses),
        )
        .order_by(TimelineAction.due_date, TimelineAction.priority.desc())
    )
    actions = result.scalars().all()

    # Also pull last 10 completed for history
    done_result = await db.execute(
        select(TimelineAction)
        .where(
            TimelineAction.account_id == account.id,
            TimelineAction.status == "done",
        )
        .order_by(TimelineAction.completed_at.desc())
        .limit(10)
    )
    done_actions = done_result.scalars().all()

    # Enrich today-actions with draft content if available
    enriched = []
    for a in actions:
        item = _serialize(a, account)
        if a.draft_id and not a.prepared_content:
            dr = await db.execute(select(Draft).where(Draft.id == a.draft_id))
            draft = dr.scalar_one_or_none()
            if draft:
                item["prepared_content"] = {
                    "type": "draft",
                    "content": draft.content,
                    "subject_line": draft.subject_line,
                    "target_contact": draft.target_contact,
                }
        enriched.append(item)

    return {
        "data": {
            "upcoming": [i for i in enriched if i["status"] in ("today", "upcoming")],
            "overdue": [i for i in enriched if i["status"] == "overdue"],
            "history": [_serialize(a, account) for a in done_actions],
        },
        "meta": {"account_id": account_id},
    }


@router.post("/{account_id}/timeline-actions")
async def create_timeline_action(
    account_id: str,
    body: CreateActionRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rep creates a manual action on a deal."""
    account = await _get_account(account_id, current_user.workspace_id, db)
    due = date.fromisoformat(body.due_date)
    today = date.today()
    action = TimelineAction(
        account_id=account.id,
        workspace_id=account.workspace_id,
        action_type=body.action_type,
        title=body.title,
        reasoning=body.reasoning,
        due_date=due,
        priority=body.priority,
        source="rep_created",
        deal_stage_at_creation=account.stage,
        status="today" if due <= today else "upcoming",
    )
    db.add(action)
    await db.commit()
    await db.refresh(action)
    return {"data": _serialize(action, account), "meta": {}}


# ── Action-scoped patch / delete (mounted at /v1/timeline-actions) ────────────

actions_router = APIRouter()


@actions_router.patch("/{action_id}")
async def patch_timeline_action(
    action_id: str,
    body: PatchActionRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Complete, skip, reschedule, or edit a timeline action."""
    result = await db.execute(
        select(TimelineAction).where(
            TimelineAction.id == uuid.UUID(action_id),
            TimelineAction.workspace_id == uuid.UUID(current_user.workspace_id),
        )
    )
    action = result.scalar_one_or_none()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    svc = TimelineService(db)

    if body.action == "complete":
        outcome_notes = body.notes or ""
        if body.outcome:
            outcome_labels = {
                "sent_email": "Sent email",
                "had_call": "Had a call",
                "got_response": "Got a response",
                "meeting_booked": "Booked a meeting",
                "not_relevant": "Not relevant",
                "done": "Done",
            }
            outcome_notes = f"[{outcome_labels.get(body.outcome, body.outcome)}] {body.notes or ''}".strip()
        await svc.complete(action_id, current_user.workspace_id, outcome_notes or None)

        # Log completion as an Interaction so the agent learns from it
        interaction_type_map = {
            "sent_email": "email_sent",
            "had_call": "call",
            "got_response": "email_received",
            "meeting_booked": "meeting",
            "not_relevant": "note",
            "done": "note",
        }
        interaction = Interaction(
            account_id=action.account_id,
            workspace_id=action.workspace_id,
            type=interaction_type_map.get(body.outcome or "done", "note"),
            source="vantage_action",
            notes=f"Action completed: {action.title}. {outcome_notes}".strip(". "),
            outcome=body.outcome,
            occurred_at=datetime.now(timezone.utc),
        )
        db.add(interaction)

        # Immediately gap-fill this deal — surface the next action
        try:
            acc_result = await db.execute(select(Account).where(Account.id == action.account_id))
            acc = acc_result.scalar_one_or_none()
            if acc:
                pov = (acc.state or {}).get("pov", {})
                sig_result = await db.execute(
                    select(Signal).where(
                        Signal.account_id == action.account_id,
                        Signal.created_at >= datetime.now(timezone.utc) - timedelta(days=30),
                    ).order_by(Signal.urgency_score.desc()).limit(10)
                )
                signals = [{"type": s.type, "urgency_score": s.urgency_score or 0,
                            "detail": s.detail or "", "id": str(s.id),
                            "created_at": s.created_at}
                           for s in sig_result.scalars().all()]
                await svc.gap_fill(acc, pov, signals)
        except Exception as e:
            log.warning("auto_gap_fill_failed", action_id=action_id, error=str(e))

    elif body.action == "skip":
        await svc.skip(action_id, current_user.workspace_id)
    elif body.action == "reschedule":
        if not body.new_due_date:
            raise HTTPException(status_code=422, detail="new_due_date required for reschedule")
        await svc.reschedule(action_id, current_user.workspace_id, date.fromisoformat(body.new_due_date))
    elif body.action == "edit":
        if body.new_title:
            action.title = body.new_title
        if body.notes:
            action.reasoning = body.notes

    await db.commit()
    await db.refresh(action)
    return {"data": _serialize(action), "meta": {}}


@actions_router.delete("/{action_id}")
async def delete_timeline_action(
    action_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a rep-created action (only rep_created source allowed)."""
    result = await db.execute(
        select(TimelineAction).where(
            TimelineAction.id == uuid.UUID(action_id),
            TimelineAction.workspace_id == uuid.UUID(current_user.workspace_id),
        )
    )
    action = result.scalar_one_or_none()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    if action.source != "rep_created":
        raise HTTPException(status_code=403, detail="Only manually created actions can be deleted")
    await db.delete(action)
    await db.commit()
    return {"data": {"deleted": True}, "meta": {}}


# ── Workspace action queue ────────────────────────────────────────────────────

workspace_router = APIRouter()


@workspace_router.post("/backfill-timeline")
async def backfill_timeline(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Run gap_fill() on all accounts using their existing state — no LLM calls.
    Call this once after the Sprint 6 migration to seed the action queue.
    Safe to call multiple times (cooldown rules prevent duplicates).
    """
    from app.services.timeline_service import TimelineService
    from app.models.account import Signal

    accounts_result = await db.execute(
        select(Account).where(
            Account.workspace_id == uuid.UUID(current_user.workspace_id),
            Account.deleted_at.is_(None),
        )
    )
    accounts = accounts_result.scalars().all()

    svc = TimelineService(db)
    total_created = 0
    processed = 0

    for account in accounts:
        try:
            state = account.state or {}
            pov = state.get("pov", {})

            # Pull recent signals from DB (last 30 days)
            sig_result = await db.execute(
                select(Signal).where(
                    Signal.account_id == account.id,
                    Signal.created_at >= datetime.now(timezone.utc) - timedelta(days=30),
                ).order_by(Signal.urgency_score.desc()).limit(10)
            )
            signals = [
                {"type": s.type, "urgency_score": s.urgency_score or 0,
                 "detail": s.detail or "", "id": str(s.id),
                 "created_at": s.created_at}
                for s in sig_result.scalars().all()
            ]

            created = await svc.gap_fill(account, pov, signals)
            total_created += created
            processed += 1
        except Exception as e:
            log.warning("backfill_gap_fill_failed", account=account.name, error=str(e))

    await db.commit()
    log.info("timeline_backfill_complete",
             workspace_id=current_user.workspace_id,
             accounts=processed, actions_created=total_created)

    return {
        "data": {
            "accounts_processed": processed,
            "actions_created": total_created,
        },
        "meta": {},
    }


@workspace_router.get("/action-queue")
async def get_action_queue(
    limit: int = Query(50, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Cross-deal action queue — today's + overdue actions across the whole workspace,
    sorted by urgency. This is the primary inbox view for the rep.
    """
    today = date.today()

    # Refresh statuses for this workspace (upcoming → today/overdue as dates pass)
    stale_result = await db.execute(
        select(TimelineAction).where(
            TimelineAction.workspace_id == uuid.UUID(current_user.workspace_id),
            TimelineAction.status == "upcoming",
            TimelineAction.due_date <= today,
        ).limit(200)
    )
    stale = stale_result.scalars().all()
    for a in stale:
        a.status = "today" if a.due_date == today else "overdue"
    if stale:
        await db.commit()

    result = await db.execute(
        select(TimelineAction, Account)
        .join(Account, Account.id == TimelineAction.account_id)
        .where(
            TimelineAction.workspace_id == uuid.UUID(current_user.workspace_id),
            TimelineAction.status.in_(["today", "overdue"]),
            Account.deleted_at.is_(None),
        )
        .order_by(
            TimelineAction.status.desc(),    # overdue first, then today
            TimelineAction.priority.desc(),
            Account.urgency_score.desc(),
        )
        .limit(limit)
    )
    rows = result.all()

    # Also count upcoming this week
    week_result = await db.execute(
        select(TimelineAction).where(
            TimelineAction.workspace_id == uuid.UUID(current_user.workspace_id),
            TimelineAction.status == "upcoming",
            TimelineAction.due_date <= today + timedelta(days=7),
        ).order_by(TimelineAction.due_date, TimelineAction.priority.desc()).limit(20)
    )
    upcoming = week_result.scalars().all()

    # Need account info for upcoming too
    upcoming_enriched = []
    acc_cache: dict[str, Account] = {}
    for a in upcoming:
        acc_id = str(a.account_id)
        if acc_id not in acc_cache:
            ar = await db.execute(select(Account).where(Account.id == a.account_id))
            acc = ar.scalar_one_or_none()
            if acc:
                acc_cache[acc_id] = acc
        acc = acc_cache.get(acc_id)
        if acc:
            upcoming_enriched.append(_serialize(a, acc))

    # Focus slice: top 7 by composite score (urgency × deal value × overdue penalty)
    all_actions = [_serialize(a, acc) for a, acc in rows]
    for item in all_actions:
        acc_obj = next((acc for a, acc in rows if str(a.id) == item["id"]), None)
        urgency = float(acc_obj.urgency_score or 0) if acc_obj else 0
        amount = float(acc_obj.deal_amount or 0) if acc_obj else 0
        overdue_bonus = 0.3 if item["status"] == "overdue" else 0
        amount_norm = min(1.0, amount / 200_000) if amount else 0
        item["_focus_score"] = urgency * 0.5 + amount_norm * 0.2 + overdue_bonus + float(item["priority"]) * 0.3

    focus = sorted(all_actions, key=lambda x: x.get("_focus_score", 0), reverse=True)[:7]
    for item in all_actions:
        item.pop("_focus_score", None)
    for item in focus:
        item.pop("_focus_score", None)

    return {
        "data": {
            "today_and_overdue": all_actions,
            "focus": focus,
            "upcoming_this_week": upcoming_enriched,
            "counts": {
                "overdue": sum(1 for a, _ in rows if a.status == "overdue"),
                "today": sum(1 for a, _ in rows if a.status == "today"),
                "this_week": len(upcoming_enriched),
            },
        },
        "meta": {"workspace_id": current_user.workspace_id},
    }


@workspace_router.get("/activity-history")
async def get_activity_history(
    limit: int = Query(100, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cross-deal completed action history, grouped by ISO week. Used for the History tab."""
    result = await db.execute(
        select(TimelineAction, Account)
        .join(Account, Account.id == TimelineAction.account_id)
        .where(
            TimelineAction.workspace_id == uuid.UUID(current_user.workspace_id),
            TimelineAction.status == "done",
            Account.deleted_at.is_(None),
        )
        .order_by(TimelineAction.completed_at.desc())
        .limit(limit)
    )
    rows = result.all()

    # Group by ISO week
    from collections import defaultdict
    weeks: dict[str, list] = defaultdict(list)
    for action, account in rows:
        completed = action.completed_at or action.updated_at
        if not completed:
            continue
        week_key = completed.strftime("%Y-W%V")  # e.g. "2026-W22"
        weeks[week_key].append({
            **_serialize(action, account),
            "completed_week": week_key,
            "completed_date": completed.strftime("%Y-%m-%d"),
        })

    week_list = [
        {"week": k, "label": _week_label(k), "actions": v}
        for k, v in sorted(weeks.items(), reverse=True)
    ]

    return {
        "data": week_list,
        "meta": {"total": sum(len(w["actions"]) for w in week_list)},
    }


def _week_label(iso_week: str) -> str:
    """Convert '2026-W22' to 'Week of May 26'."""
    try:
        from datetime import datetime
        year, week = iso_week.split("-W")
        d = datetime.strptime(f"{year}-{week}-1", "%Y-%W-%w")
        # %-d is not portable (ValueError on Windows) — build manually
        return f"Week of {d.strftime('%b')} {d.day}"
    except Exception:
        return iso_week
