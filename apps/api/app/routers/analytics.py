"""
Analytics router — DAR trend, LLM costs, account coverage, signal patterns.
GET /v1/analytics/overview     — KPI snapshot (DAR, coverage, cost, pipeline)
GET /v1/analytics/dar-trend    — DAR over time (30/60/90d)
GET /v1/analytics/cost-trend   — LLM cost per day
GET /v1/analytics/signal-types — Signal distribution across portfolio
GET /v1/analytics/rep-performance — Per-rep DAR + urgency response rate
GET /v1/accounts/{id}/timeline — Full event timeline for one account
"""
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, func
import structlog

from app.db.database import get_db
from app.middleware.auth import get_current_user, CurrentUser, require_manager
from app.models.account import Account, Draft, Signal, Interaction, AgentRun

log = structlog.get_logger()
router = APIRouter()


@router.get("/overview")
async def get_overview(
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """
    KPI snapshot for the analytics dashboard header.
    Returns current DAR, coverage, pipeline value, avg urgency.
    """
    ws = current_user.workspace_id

    # Account metrics
    result = await db.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(last_agent_run_at) AS covered,
            COALESCE(AVG(urgency_score), 0) AS avg_urgency,
            COALESCE(AVG(health_score), 0) AS avg_health,
            COALESCE(SUM(deal_amount), 0) AS total_pipeline
        FROM accounts
        WHERE workspace_id = :ws AND deleted_at IS NULL
    """), {"ws": ws})
    acc = result.fetchone()

    # DAR (all time) — approved ÷ reviewed. Pending/superseded/expired drafts
    # are not decisions; counting them dilutes the North Star metric to noise.
    result = await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE d.status IN ('approved','approved_modified')) AS approved,
            COUNT(*) FILTER (WHERE d.status IN ('approved','approved_modified','declined')) AS reviewed,
            COUNT(*) AS total
        FROM drafts d
        JOIN accounts a ON d.account_id = a.id
        WHERE a.workspace_id = :ws
    """), {"ws": ws})
    dar_row = result.fetchone()
    dar = round(dar_row.approved / max(dar_row.reviewed, 1), 4)

    # Pending reviews
    result = await db.execute(text("""
        SELECT COUNT(*) FROM drafts d
        JOIN accounts a ON d.account_id = a.id
        WHERE a.workspace_id = :ws AND d.status = 'pending'
    """), {"ws": ws})
    pending = result.scalar_one()

    # Cost last 30 days
    result = await db.execute(text("""
        SELECT COALESCE(SUM(total_cost_usd), 0) FROM agent_runs
        WHERE workspace_id = :ws AND created_at >= NOW() - INTERVAL '30 days'
    """), {"ws": ws})
    cost_30d = float(result.scalar_one())

    return {
        "data": {
            "accounts": {
                "total": int(acc.total),
                "covered": int(acc.covered),
                "coverage_pct": round(acc.covered / max(acc.total, 1), 4),
                "total_pipeline": float(acc.total_pipeline),
                "avg_urgency": round(float(acc.avg_urgency), 3),
                "avg_health": round(float(acc.avg_health), 3),
            },
            "drafts": {
                "total": int(dar_row.total),
                "approved": int(dar_row.approved),
                "pending": int(pending),
                "dar": dar,
                "dar_pct": round(dar * 100, 1),
                "dar_target": 60.0,
                "dar_vs_target": round((dar * 100) - 60.0, 1),
            },
            "cost_30d_usd": round(cost_30d, 4),
        },
        "meta": {"workspace_id": ws},
    }


@router.get("/dar-trend")
async def get_dar_trend(
    days: int = Query(30, ge=7, le=90),
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """
    DAR trend by day over the last N days.
    Each data point: date, drafts_generated, drafts_approved, dar.
    """
    ws = current_user.workspace_id
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(text("""
        SELECT
            DATE(d.created_at) AS day,
            COUNT(*) AS generated,
            COUNT(*) FILTER (WHERE d.status IN ('approved','approved_modified')) AS approved,
            ROUND(
                COUNT(*) FILTER (WHERE d.status IN ('approved','approved_modified'))::numeric
                / NULLIF(COUNT(*), 0) * 100,
                1
            ) AS dar_pct
        FROM drafts d
        JOIN accounts a ON d.account_id = a.id
        WHERE a.workspace_id = :ws
          AND d.created_at >= :cutoff
        GROUP BY DATE(d.created_at)
        ORDER BY day ASC
    """), {"ws": ws, "cutoff": cutoff})

    rows = result.fetchall()
    return {
        "data": [
            {
                "date": str(r.day),
                "generated": int(r.generated),
                "approved": int(r.approved),
                "dar_pct": float(r.dar_pct or 0),
            }
            for r in rows
        ],
        "meta": {"days": days, "target_dar_pct": 60.0},
    }


@router.get("/cost-trend")
async def get_cost_trend(
    days: int = Query(30, ge=7, le=90),
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """LLM cost per day, with token breakdown."""
    ws = current_user.workspace_id
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(text("""
        SELECT
            DATE(created_at) AS day,
            COALESCE(SUM(total_cost_usd), 0) AS cost_usd,
            COALESCE(SUM(total_prompt_tokens), 0) AS prompt_tokens,
            COALESCE(SUM(total_completion_tokens), 0) AS completion_tokens,
            COUNT(*) AS runs,
            COUNT(*) FILTER (WHERE trigger = 'nightly') AS nightly_runs,
            COUNT(*) FILTER (WHERE trigger = 'manual') AS manual_runs
        FROM agent_runs
        WHERE workspace_id = :ws
          AND created_at >= :cutoff
        GROUP BY DATE(created_at)
        ORDER BY day ASC
    """), {"ws": ws, "cutoff": cutoff})

    rows = result.fetchall()
    return {
        "data": [
            {
                "date": str(r.day),
                "cost_usd": round(float(r.cost_usd), 4),
                "prompt_tokens": int(r.prompt_tokens),
                "completion_tokens": int(r.completion_tokens),
                "runs": int(r.runs),
                "nightly_runs": int(r.nightly_runs),
                "manual_runs": int(r.manual_runs),
            }
            for r in rows
        ],
        "meta": {"days": days},
    }


@router.get("/signal-types")
async def get_signal_types(
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """Signal distribution by type + urgency across portfolio."""
    ws = current_user.workspace_id
    result = await db.execute(text("""
        SELECT
            s.type,
            s.urgency,
            COUNT(*) AS count,
            ROUND(AVG(s.urgency_score)::numeric, 3) AS avg_score
        FROM signals s
        JOIN accounts a ON s.account_id = a.id
        WHERE a.workspace_id = :ws
          AND s.created_at >= NOW() - INTERVAL '30 days'
        GROUP BY s.type, s.urgency
        ORDER BY count DESC
    """), {"ws": ws})

    rows = result.fetchall()
    # Group by type
    by_type: dict = {}
    for r in rows:
        if r.type not in by_type:
            by_type[r.type] = {"type": r.type, "total": 0, "by_urgency": {}}
        by_type[r.type]["total"] += int(r.count)
        by_type[r.type]["by_urgency"][r.urgency] = int(r.count)

    return {
        "data": list(by_type.values()),
        "meta": {"period_days": 30},
    }


@router.get("/rep-performance")
async def get_rep_performance(
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """Per-rep DAR and response rate. Managers only."""
    ws = current_user.workspace_id

    # owner_rep_id is a HubSpot owner ID — resolve to a human name via the
    # mapping refreshed on every HubSpot sync (workspace.settings.hubspot_owners).
    import uuid as _uuid
    from app.models.workspace import Workspace
    ws_settings_result = await db.execute(
        select(Workspace.settings).where(Workspace.id == _uuid.UUID(ws))
    )
    owners_map = (ws_settings_result.scalar_one_or_none() or {}).get("hubspot_owners", {})

    result = await db.execute(text("""
        SELECT
            a.owner_rep_id,
            wu.email AS rep_email,
            COUNT(d.id) AS total_drafts,
            COUNT(d.id) FILTER (WHERE d.status IN ('approved','approved_modified')) AS approved,
            COUNT(d.id) FILTER (WHERE d.status = 'declined') AS declined,
            COUNT(d.id) FILTER (WHERE d.status = 'pending') AS pending,
            ROUND(
                COUNT(d.id) FILTER (WHERE d.status IN ('approved','approved_modified'))::numeric
                / NULLIF(COUNT(d.id) FILTER (WHERE d.status != 'pending'), 0) * 100,
                1
            ) AS dar_pct,
            ROUND(AVG(a.urgency_score)::numeric, 3) AS avg_account_urgency,
            COUNT(DISTINCT d.account_id) AS accounts_with_drafts
        FROM drafts d
        JOIN accounts a ON d.account_id = a.id
        LEFT JOIN workspace_users wu
          ON wu.workspace_id = a.workspace_id
          AND wu.workos_user_id = a.owner_rep_id
        WHERE a.workspace_id = :ws AND a.owner_rep_id IS NOT NULL
        GROUP BY a.owner_rep_id, wu.email
        ORDER BY dar_pct DESC NULLS LAST
    """), {"ws": ws})

    rows = result.fetchall()
    return {
        "data": [
            {
                "rep_id": r.owner_rep_id,
                "rep_email": r.rep_email or (owners_map.get(str(r.owner_rep_id)) or {}).get("email"),
                "rep_name": (owners_map.get(str(r.owner_rep_id)) or {}).get("name"),
                "total_drafts": int(r.total_drafts),
                "approved": int(r.approved),
                "declined": int(r.declined),
                "pending": int(r.pending),
                "dar_pct": float(r.dar_pct or 0),
                "avg_account_urgency": float(r.avg_account_urgency or 0),
                "accounts_with_drafts": int(r.accounts_with_drafts),
            }
            for r in rows
        ],
        "meta": {},
    }


@router.get("/stalled")
async def get_stalled_deals(
    limit: int = Query(10, ge=1, le=50),
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """
    Return deals with declining/stalling momentum and extended time in stage.
    Sorted by deal amount descending — highest $ at risk first.
    """
    ws = current_user.workspace_id
    result = await db.execute(text("""
        SELECT
            id::text,
            name,
            stage,
            deal_amount,
            COALESCE(state->>'deal_momentum', state->'pov'->>'deal_momentum') AS momentum,
            -- Buyer-side inactivity, written by the risk scanner each run.
            -- NULL when unknown (the frontend shows a dash). A literal 0 on a
            -- deal flagged stalling contradicts the momentum verdict — it's the
            -- model's default, not evidence — so treat it as unknown here too.
            NULLIF((COALESCE(
                state->'pov'->>'days_since_meaningful_activity',
                state->>'days_since_meaningful_activity'
            ))::int, 0) AS days_stuck,
            last_agent_run_at,
            urgency_score
        FROM accounts
        WHERE workspace_id = :ws
          AND deleted_at IS NULL
          AND lower(trim(stage)) NOT IN ('won', 'closed lost', 'closed-lost', 'partners')
          AND COALESCE(state->>'deal_momentum', state->'pov'->>'deal_momentum')
              IN ('stalling', 'declining')
        ORDER BY deal_amount DESC NULLS LAST
        LIMIT :limit
    """), {"ws": ws, "limit": limit})

    rows = result.fetchall()
    total_at_risk = sum(float(r.deal_amount or 0) for r in rows)

    return {
        "data": {
            "deals": [
                {
                    "id": r.id,
                    "name": r.name,
                    "stage": r.stage,
                    "deal_amount": float(r.deal_amount) if r.deal_amount else None,
                    "momentum": r.momentum,
                    "days_stuck": int(r.days_stuck) if r.days_stuck is not None else None,
                    "urgency_score": float(r.urgency_score or 0),
                    "last_agent_run_at": r.last_agent_run_at.isoformat() if r.last_agent_run_at else None,
                }
                for r in rows
            ],
            "total_at_risk": round(total_at_risk, 0),
            "count": len(rows),
        },
        "meta": {"workspace_id": ws},
    }


@router.get("/pipeline-review")
async def get_pipeline_review(
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """
    Weekly AI Pipeline Review — the Monday-morning artifact.
    Pure aggregation over nightly agent data (no LLM call):
    moved / stalled / slipped deals, MEDDPICC gaps, next-step gaps.
    Every row links back to its account as evidence.
    """
    from app.routers.forecast import _week_ago_snapshot

    ws = current_user.workspace_id
    result = await db.execute(
        select(Account).where(
            Account.workspace_id == ws,
            Account.deleted_at.is_(None),
        )
    )
    accounts = result.scalars().all()
    now = datetime.now(timezone.utc)

    OPEN = lambda a: (a.stage or "").strip().lower() not in {"won", "closed lost", "closed-lost", "partners"}
    LATE_STAGES = {"proposal", "negotiate", "negotiation", "decision"}

    moved, stalled, slipped, meddpicc_gaps, no_next_step = [], [], [], [], []

    for acc in accounts:
        if not OPEN(acc):
            continue
        state = acc.state or {}
        pov = state.get("pov", {})
        amount = float(acc.deal_amount or 0)
        base = {
            "account_id": str(acc.id),
            "name": acc.name,
            "stage": acc.stage,
            "amount": amount,
            "owner_rep_id": acc.owner_rep_id,
        }

        # Moved — forecast category changed vs ~1 week ago
        baseline = _week_ago_snapshot(state.get("forecast_history"), now)
        current_cat = acc.pov_forecast_cat or pov.get("forecast_category")
        if baseline and current_cat and baseline.get("category") and baseline["category"] != current_cat:
            moved.append({
                **base,
                "from_category": baseline["category"],
                "to_category": current_cat,
                "reason": pov.get("forecast_rationale") or pov.get("forecast_explanation"),
            })

        # Stalled — momentum from the risk scanner
        momentum = state.get("deal_momentum") or pov.get("deal_momentum")
        if momentum in ("stalling", "declining"):
            stalled.append({
                **base,
                "momentum": momentum,
                "days_since_buyer_activity": pov.get("days_since_meaningful_activity"),
            })

        # Slipped — close date in the past on an open deal (close_date is a DATE column)
        if acc.close_date and acc.close_date < now.date():
            slipped.append({
                **base,
                "close_date": acc.close_date.isoformat(),
                "days_overdue": (now.date() - acc.close_date).days,
            })

        # MEDDPICC gaps — late-stage deals below 50% qualification
        meddpicc = pov.get("meddpicc") or {}
        overall = meddpicc.get("overall_score")
        if (
            overall is not None and overall < 0.5
            and (acc.stage or "").strip().lower() in LATE_STAGES
        ):
            meddpicc_gaps.append({
                **base,
                "overall_score": overall,
                "gaps": (meddpicc.get("gaps") or [])[:3],
            })

        # Next-step gaps — no recorded next step on an open deal
        next_step = state.get("next_step") or {}
        if not (next_step.get("text") or "").strip():
            no_next_step.append(base)

    for lst in (moved, stalled, slipped, meddpicc_gaps, no_next_step):
        lst.sort(key=lambda x: x["amount"], reverse=True)

    def _section(rows, cap=10):
        return {
            "count": len(rows),
            "total_amount": round(sum(r["amount"] for r in rows), 0),
            "deals": rows[:cap],
        }

    return {
        "data": {
            "generated_at": now.isoformat(),
            "week_of": (now - timedelta(days=now.weekday())).date().isoformat(),
            "moved": _section(moved),
            "stalled": _section(stalled),
            "slipped": _section(slipped),
            "meddpicc_gaps": _section(meddpicc_gaps),
            "no_next_step": _section(no_next_step),
        },
        "meta": {"workspace_id": ws},
    }


@router.get("/competitive")
async def get_competitive_leaderboard(
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """
    Aggregate competitive mentions across all accounts.
    Groups signals by extracted competitor name, sorted by deal value at risk.
    """
    ws = current_user.workspace_id
    result = await db.execute(text("""
        SELECT
            s.type,
            s.detail,
            a.deal_amount,
            a.id::text AS account_id,
            a.name AS account_name,
            s.urgency_score
        FROM signals s
        JOIN accounts a ON s.account_id = a.id
        WHERE a.workspace_id = :ws
          AND s.type IN ('competitive_mention', 'competitive_evaluation_active', 'competitive_win_risk')
          AND s.created_at >= NOW() - INTERVAL '90 days'
        ORDER BY s.urgency_score DESC NULLS LAST
        LIMIT 200
    """), {"ws": ws})

    rows = result.fetchall()

    # Group by competitor (extract from detail text — look for known keywords)
    from collections import defaultdict
    competitor_map: dict[str, dict] = defaultdict(lambda: {"deals": 0, "total_amount": 0.0, "accounts": set()})

    for r in rows:
        detail = (r.detail or "").lower()
        competitor = "Unknown competitor"
        # Try to extract competitor name from signal detail
        import re
        # Look for "vs <name>", "competing with <name>", "<name> is evaluating"
        patterns = [
            r"vs\s+([A-Z][a-zA-Z\s]{2,20})",
            r"compe(?:ting|titor|tition)[^\w]*(?:with|from|by)?\s+([A-Z][a-zA-Z\s]{2,20})",
            r"([A-Z][a-zA-Z]{2,20})\s+(?:VMS|AI|Safety|Systems|Platform)",
        ]
        for pat in patterns:
            m = re.search(pat, r.detail or "")
            if m:
                competitor = m.group(1).strip()
                break

        competitor_map[competitor]["deals"] += 1
        competitor_map[competitor]["total_amount"] += float(r.deal_amount or 0)
        competitor_map[competitor]["accounts"].add(r.account_id)

    leaderboard = sorted(
        [
            {
                "competitor": name,
                "deal_count": data["deals"],
                "total_amount_at_risk": round(data["total_amount"], 0),
                "account_count": len(data["accounts"]),
            }
            for name, data in competitor_map.items()
        ],
        key=lambda x: x["total_amount_at_risk"],
        reverse=True,
    )[:10]

    return {
        "data": {"competitors": leaderboard, "total_competitive_deals": len(rows)},
        "meta": {"workspace_id": ws, "period_days": 90},
    }


@router.get("/draft-performance")
async def get_draft_performance(
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """
    DAR breakdown by draft type.
    Shows which draft types get approved vs declined — training signal for agent tuning.
    """
    ws = current_user.workspace_id
    result = await db.execute(text("""
        SELECT
            d.type,
            COUNT(*) AS total,
            SUM(CASE WHEN d.status IN ('approved','approved_modified') THEN 1 ELSE 0 END) AS approved,
            ROUND(
                SUM(CASE WHEN d.status IN ('approved','approved_modified') THEN 1.0 ELSE 0 END)
                / NULLIF(COUNT(*), 0) * 100,
                1
            ) AS dar_pct
        FROM drafts d
        JOIN accounts a ON d.account_id = a.id
        WHERE a.workspace_id = :ws
        GROUP BY d.type
        ORDER BY dar_pct DESC NULLS LAST
    """), {"ws": ws})
    rows = result.fetchall()
    return {
        "data": [
            {
                "type": r.type,
                "total": int(r.total),
                "approved": int(r.approved),
                "dar_pct": float(r.dar_pct or 0),
            }
            for r in rows
        ],
        "meta": {"workspace_id": ws},
    }


@router.get("/training-feedback")
async def get_training_feedback(
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """
    Decline reason distribution from training signals.
    Shows why reps decline AI drafts — used to tune agent behaviour.
    """
    ws = current_user.workspace_id
    result = await db.execute(text("""
        SELECT
            i.training_category,
            COUNT(*) AS count
        FROM interactions i
        JOIN accounts a ON i.account_id = a.id
        WHERE a.workspace_id = :ws
          AND i.type = 'draft_declined'
          AND i.training_category IS NOT NULL
        GROUP BY i.training_category
        ORDER BY count DESC
    """), {"ws": ws})
    rows = result.fetchall()
    return {
        "data": [
            {"training_category": r.training_category, "count": int(r.count)}
            for r in rows
        ],
        "meta": {"workspace_id": ws},
    }


@router.get("/forecast-accuracy")
async def get_forecast_accuracy(
    current_user: CurrentUser = Depends(require_manager()),
    db: AsyncSession = Depends(get_db),
):
    """
    AI forecast accuracy vs actual outcomes over 90 days.
    Compares AI pov_category against account's final CRM forecast category.
    """
    ws = current_user.workspace_id
    try:
        result = await db.execute(text("""
            SELECT
                pov_category,
                COUNT(*) AS total_predictions,
                COUNT(*) FILTER (WHERE a.pov_forecast_cat = pov_category) AS correct,
                ROUND(
                    COUNT(*) FILTER (WHERE a.pov_forecast_cat = pov_category)::numeric
                    / NULLIF(COUNT(*), 0) * 100,
                    1
                ) AS accuracy_pct,
                ROUND(AVG(ABS(COALESCE(fs.pov_amount, 0) - COALESCE(fs.crm_amount, 0))), 0) AS avg_amount_delta
            FROM forecast_snapshots fs
            JOIN accounts a ON fs.account_id = a.id
            WHERE fs.workspace_id = :ws
              AND fs.run_date >= NOW() - INTERVAL '90 days'
            GROUP BY pov_category
        """), {"ws": ws})
        rows = result.fetchall()
        return {
            "data": [
                {
                    "category": r.pov_category,
                    "total": int(r.total_predictions),
                    "correct": int(r.correct),
                    "accuracy_pct": float(r.accuracy_pct or 0),
                    "avg_amount_delta": float(r.avg_amount_delta or 0),
                }
                for r in rows
            ],
            "meta": {"workspace_id": ws, "period_days": 90},
        }
    except Exception:
        return {
            "data": [],
            "meta": {"workspace_id": ws, "period_days": 90, "note": "No forecast history yet"},
        }


@router.get("/accounts/{account_id}/timeline")
async def get_account_timeline(
    account_id: str,
    limit: int = Query(50, ge=1, le=200),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Full chronological event timeline for one account.
    Merges: signals detected, interactions logged, drafts created/reviewed,
    agent runs, and HubSpot sync changes.
    Used by the Account War Room to show deal history at a glance.
    """
    # Verify account access — workspace isolation + rep-level IDOR protection
    _owner_clause = "" if current_user.is_manager() else "AND owner_rep_id = :owner_rep_id"
    _params = {"id": account_id, "ws": current_user.workspace_id}
    if not current_user.is_manager():
        _params["owner_rep_id"] = current_user.workos_user_id

    result = await db.execute(text(f"""
        SELECT id FROM accounts
        WHERE id = :id AND workspace_id = :ws AND deleted_at IS NULL {_owner_clause}
    """), _params)
    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Account not found")

    result = await db.execute(text("""
        SELECT * FROM (
            -- Signals
            SELECT
                s.created_at AS occurred_at,
                'signal' AS event_type,
                s.type AS subtype,
                s.detail AS description,
                s.urgency AS urgency,
                s.urgency_score AS score,
                s.source AS source,
                s.id::text AS event_id
            FROM signals s
            WHERE s.account_id = :account_id

            UNION ALL

            -- Interactions (calls, meetings, emails)
            SELECT
                i.occurred_at,
                CASE WHEN i.source = 'vantage' THEN 'agent_run' ELSE 'interaction' END AS event_type,
                i.type AS subtype,
                i.notes AS description,
                NULL AS urgency,
                NULL AS score,
                i.source AS source,
                i.id::text AS event_id
            FROM interactions i
            WHERE i.account_id = :account_id

            UNION ALL

            -- Drafts created
            SELECT
                d.created_at AS occurred_at,
                'draft_created' AS event_type,
                d.type AS subtype,
                CONCAT('AI drafted: ', d.type) AS description,
                NULL AS urgency,
                NULL AS score,
                'agent' AS source,
                d.id::text AS event_id
            FROM drafts d
            WHERE d.account_id = :account_id

            UNION ALL

            -- Drafts reviewed
            SELECT
                d.reviewed_at AS occurred_at,
                'draft_reviewed' AS event_type,
                d.status AS subtype,
                COALESCE(d.reviewer_notes, CONCAT('Draft ', d.status)) AS description,
                NULL AS urgency,
                NULL AS score,
                'rep' AS source,
                d.id::text AS event_id
            FROM drafts d
            WHERE d.account_id = :account_id AND d.reviewed_at IS NOT NULL

            -- Audit log changes
            UNION ALL
            SELECT
                al.created_at AS occurred_at,
                'crm_change' AS event_type,
                al.action AS subtype,
                al.action AS description,
                NULL AS urgency,
                NULL AS score,
                'hubspot' AS source,
                al.id::text AS event_id
            FROM audit_log al
            -- resource_id is VARCHAR while the other branches compare UUID columns;
            -- asyncpg infers one type per parameter, so cast this side to text
            WHERE al.resource_id = CAST(:account_id AS TEXT)
              AND al.action LIKE 'crm_%'

        ) events
        WHERE occurred_at IS NOT NULL
        ORDER BY occurred_at DESC
        LIMIT :limit
    """), {"account_id": account_id, "limit": limit})

    rows = result.fetchall()
    return {
        "data": [
            {
                "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
                "event_type": r.event_type,
                "subtype": r.subtype,
                "description": r.description,
                "urgency": r.urgency,
                "score": float(r.score) if r.score else None,
                "source": r.source,
                "event_id": r.event_id,
            }
            for r in rows
        ],
        "meta": {"account_id": account_id, "count": len(rows)},
    }


# ── Sprint 7-10 analytics endpoints ──────────────────────────────────────────

@router.get("/execution-rate")
async def get_execution_rate(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Weekly execution rate: completed actions / generated actions for last 5 weeks."""
    from app.models.account import TimelineAction
    ws = current_user.workspace_id

    result = await db.execute(text("""
        SELECT
            date_trunc('week', created_at) AS week_start,
            COUNT(*) AS total_generated,
            COUNT(*) FILTER (WHERE status = 'done') AS completed,
            COUNT(*) FILTER (WHERE status IN ('upcoming','today','overdue')) AS pending,
            COUNT(*) FILTER (WHERE status = 'skipped') AS skipped
        FROM timeline_actions
        WHERE workspace_id = :ws
          AND created_at >= NOW() - INTERVAL '5 weeks'
        GROUP BY week_start
        ORDER BY week_start DESC
    """), {"ws": ws})
    rows = result.fetchall()

    overall_result = await db.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status = 'done') AS completed
        FROM timeline_actions
        WHERE workspace_id = :ws
    """), {"ws": ws})
    overall = overall_result.fetchone()
    overall_rate = round((overall.completed / max(overall.total, 1)) * 100, 1) if overall else 0

    return {
        "data": {
            "weeks": [
                {
                    "week_start": r.week_start.strftime("%Y-%m-%d") if r.week_start else None,
                    "week_label": f"{r.week_start.day} {r.week_start.strftime('%b')}" if r.week_start else "",
                    "total_generated": r.total_generated,
                    "completed": r.completed,
                    "rate_pct": round((r.completed / max(r.total_generated, 1)) * 100, 1),
                    "pending": r.pending,
                    "skipped": r.skipped,
                }
                for r in rows
            ],
            "overall_rate_pct": overall_rate,
            "total_generated": overall.total if overall else 0,
            "total_completed": overall.completed if overall else 0,
            "target_pct": 60,
        },
        "meta": {},
    }


@router.get("/pipeline-movement")
async def get_pipeline_movement(
    days: int = Query(30, ge=7, le=90),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deals that advanced or regressed stages in the last N days, from audit log."""
    ws = current_user.workspace_id

    result = await db.execute(text("""
        SELECT
            al.resource_id AS account_id,
            a.name AS account_name,
            a.deal_amount,
            al.changes->'stage'->>'before' AS stage_before,
            al.changes->'stage'->>'after' AS stage_after,
            al.created_at AS changed_at
        FROM audit_log al
        JOIN accounts a ON al.resource_id = a.id::text
        WHERE al.workspace_id = :ws
          AND al.action = 'crm_sync_update'
          AND al.changes ? 'stage'
          AND al.created_at >= NOW() - :days * INTERVAL '1 day'
          AND a.deleted_at IS NULL
        ORDER BY al.created_at DESC
        LIMIT 50
    """), {"ws": ws, "days": days})
    rows = result.fetchall()

    stage_order = ["Qualification","Demo","Discovery","Proposal","Negotiation","Closed Won","Closed Lost"]
    def stage_delta(before: str, after: str) -> str:
        bi = stage_order.index(before) if before in stage_order else -1
        ai = stage_order.index(after) if after in stage_order else -1
        if ai > bi: return "advanced"
        if ai < bi: return "regressed"
        return "lateral"

    movements = []
    for r in rows:
        before = (r.stage_before or "").strip('"')
        after = (r.stage_after or "").strip('"')
        if not before or not after or before == after:
            continue
        movements.append({
            "account_id": r.account_id,
            "account_name": r.account_name,
            "deal_amount": float(r.deal_amount) if r.deal_amount else None,
            "from_stage": before,
            "to_stage": after,
            "direction": stage_delta(before, after),
            "changed_at": r.changed_at.isoformat() if r.changed_at else None,
        })

    advanced = [m for m in movements if m["direction"] == "advanced"]
    regressed = [m for m in movements if m["direction"] == "regressed"]

    return {
        "data": {
            "movements": movements,
            "advanced_count": len(advanced),
            "regressed_count": len(regressed),
            "advanced_value": sum(m["deal_amount"] or 0 for m in advanced),
            "regressed_value": sum(m["deal_amount"] or 0 for m in regressed),
        },
        "meta": {"days": days},
    }


@router.get("/agent-roi")
async def get_agent_roi(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Agent ROI: cost per deal advanced, cost per closed deal."""
    ws = current_user.workspace_id

    # Total LLM cost last 30 days
    cost_result = await db.execute(text("""
        SELECT COALESCE(SUM(total_cost_usd), 0) AS cost_30d,
               COUNT(*) AS run_count
        FROM agent_runs
        WHERE workspace_id = :ws
          AND started_at >= NOW() - INTERVAL '30 days'
    """), {"ws": ws})
    cost_row = cost_result.fetchone()
    cost_30d = float(cost_row.cost_30d or 0)

    # Deals advanced in last 30 days (from audit log stage changes)
    moved_result = await db.execute(text("""
        SELECT COUNT(DISTINCT al.resource_id) AS deals_moved
        FROM audit_log al
        WHERE al.workspace_id = :ws
          AND al.action = 'crm_sync_update'
          AND al.changes ? 'stage'
          AND al.created_at >= NOW() - INTERVAL '30 days'
    """), {"ws": ws})
    moved = moved_result.fetchone()
    deals_advanced = int(moved.deals_moved or 0)

    # Closed Won last 90 days
    won_result = await db.execute(text("""
        SELECT COUNT(DISTINCT al.resource_id) AS closed_won
        FROM audit_log al
        JOIN accounts a ON al.resource_id = a.id::text
        WHERE al.workspace_id = :ws
          AND al.action = 'crm_sync_update'
          AND al.changes->'after'->>'stage' ILIKE '%won%'
          AND al.created_at >= NOW() - INTERVAL '90 days'
    """), {"ws": ws})
    won = won_result.fetchone()
    deals_won = int(won.closed_won or 0)

    cost_per_advanced = round(cost_30d / deals_advanced, 2) if deals_advanced > 0 else None
    cost_per_won = round((cost_30d * 3) / deals_won, 2) if deals_won > 0 else None  # 3x for 90d window

    return {
        "data": {
            "cost_30d_usd": round(cost_30d, 2),
            "run_count_30d": int(cost_row.run_count or 0),
            "deals_advanced_30d": deals_advanced,
            "deals_won_90d": deals_won,
            "cost_per_deal_advanced_usd": cost_per_advanced,
            "cost_per_deal_won_usd": cost_per_won,
        },
        "meta": {},
    }


@router.get("/reply-rate")
async def get_reply_rate(
    days: int = Query(30, ge=7, le=90),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Reply rate: of emails approved and sent via Vantage, how many got a reply?
    Derived from Interaction table — 'email_sent' followed by 'email_received' for same account.
    """
    ws = current_user.workspace_id

    # Sent emails (approved drafts or actions marked 'sent_email')
    sent = await db.execute(text("""
        SELECT COUNT(DISTINCT account_id) AS accounts_contacted,
               COUNT(*) AS emails_sent
        FROM interactions
        WHERE workspace_id = :ws
          AND type = 'email_sent'
          AND source IN ('vantage_action', 'approved_draft', 'outlook_send')
          AND occurred_at >= NOW() - :days * INTERVAL '1 day'
    """), {"ws": ws, "days": days})
    sent_row = sent.fetchone()

    # Replies received (email_received within 14d after a sent email from same account)
    replied = await db.execute(text("""
        SELECT COUNT(DISTINCT i_reply.account_id) AS accounts_replied
        FROM interactions i_sent
        JOIN interactions i_reply
          ON i_reply.account_id = i_sent.account_id
         AND i_reply.type = 'email_received'
         AND i_reply.occurred_at BETWEEN i_sent.occurred_at AND i_sent.occurred_at + INTERVAL '14 days'
        WHERE i_sent.workspace_id = :ws
          AND i_sent.type = 'email_sent'
          AND i_sent.source IN ('vantage_action', 'approved_draft', 'outlook_send')
          AND i_sent.occurred_at >= NOW() - :days * INTERVAL '1 day'
    """), {"ws": ws, "days": days})
    replied_row = replied.fetchone()

    accounts_contacted = int(sent_row.accounts_contacted or 0)
    accounts_replied = int(replied_row.accounts_replied or 0)
    reply_rate_pct = round(accounts_replied / max(accounts_contacted, 1) * 100, 1)

    # Weekly breakdown
    weekly = await db.execute(text("""
        SELECT
            date_trunc('week', occurred_at) AS week_start,
            COUNT(*) AS sent
        FROM interactions
        WHERE workspace_id = :ws
          AND type = 'email_sent'
          AND source IN ('vantage_action', 'approved_draft', 'outlook_send')
          AND occurred_at >= NOW() - :days * INTERVAL '1 day'
        GROUP BY week_start
        ORDER BY week_start DESC
    """), {"ws": ws, "days": days})
    weekly_rows = weekly.fetchall()

    return {
        "data": {
            "emails_sent": int(sent_row.emails_sent or 0),
            "accounts_contacted": accounts_contacted,
            "accounts_replied": accounts_replied,
            "reply_rate_pct": reply_rate_pct,
            "target_pct": 30,
            "weekly": [
                {
                    "week_start": r.week_start.strftime("%Y-%m-%d") if r.week_start else None,
                    "week_label": f"{r.week_start.day} {r.week_start.strftime('%b')}" if r.week_start else "",
                    "sent": r.sent,
                }
                for r in weekly_rows
            ],
        },
        "meta": {"days": days},
    }


@router.get("/deal-velocity")
async def get_deal_velocity(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Deal velocity: avg days deals spend in each stage, vs. current deals stuck in that stage.
    Computed from audit_log stage-change entries.
    """
    ws = current_user.workspace_id

    # Historical avg days per stage (closed deals only — they have complete trajectories)
    hist = await db.execute(text("""
        WITH stage_spans AS (
            SELECT
                al.changes->>'stage' AS stage,
                EXTRACT(EPOCH FROM (
                    LEAD(al.created_at) OVER (PARTITION BY al.resource_id ORDER BY al.created_at)
                    - al.created_at
                )) / 86400.0 AS days_in_stage
            FROM audit_log al
            JOIN accounts a ON al.resource_id = a.id::text
            WHERE al.workspace_id = :ws
              AND al.action = 'crm_sync_update'
              AND al.changes ? 'stage'
              AND a.stage ILIKE '%closed%'
        )
        SELECT stage, ROUND(AVG(days_in_stage)::numeric, 1) AS avg_days, COUNT(*) AS sample_size
        FROM stage_spans
        WHERE days_in_stage IS NOT NULL AND days_in_stage > 0 AND days_in_stage < 365
        GROUP BY stage
        ORDER BY avg_days DESC
    """), {"ws": ws})
    hist_rows = hist.fetchall()
    avg_by_stage = {r.stage: {"avg_days": float(r.avg_days), "sample_size": int(r.sample_size)} for r in hist_rows}

    # Current active deals: days in current stage
    current = await db.execute(text("""
        SELECT
            a.name,
            a.id::text AS account_id,
            a.stage,
            a.deal_amount,
            a.urgency_score,
            EXTRACT(EPOCH FROM (NOW() - MAX(al.created_at))) / 86400.0 AS days_in_current_stage
        FROM accounts a
        LEFT JOIN audit_log al ON al.resource_id = a.id::text
            AND al.workspace_id = :ws
            AND al.action = 'crm_sync_update'
            AND al.changes ? 'stage'
        WHERE a.workspace_id = :ws
          AND a.deleted_at IS NULL
          AND a.stage NOT ILIKE '%closed%'
        GROUP BY a.id, a.name, a.stage, a.deal_amount, a.urgency_score
        HAVING COUNT(al.id) > 0
        ORDER BY days_in_current_stage DESC NULLS LAST
        LIMIT 50
    """), {"ws": ws})
    current_rows = current.fetchall()

    deals = []
    for r in current_rows:
        stage = r.stage or "Unknown"
        days = round(float(r.days_in_current_stage or 0), 0)
        hist_info = avg_by_stage.get(stage, {})
        avg = float(hist_info.get("avg_days", 0))
        delta = round(days - avg, 0) if avg > 0 else None
        deals.append({
            "account_id": r.account_id,
            "name": r.name,
            "stage": stage,
            "deal_amount": float(r.deal_amount or 0),
            "days_in_stage": int(days),
            "avg_days_for_stage": avg,
            "days_over_avg": delta,
            "stalled": delta is not None and delta > 7,
        })

    return {
        "data": {
            "stage_averages": avg_by_stage,
            "deals": deals,
            "stalled_count": sum(1 for d in deals if d["stalled"]),
        },
        "meta": {},
    }


@router.get("/stage-funnel")
async def get_stage_funnel(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Pipeline stage funnel: deal count, total value, avg health per stage."""
    ws = current_user.workspace_id

    result = await db.execute(text("""
        SELECT
            stage,
            COUNT(*) AS deal_count,
            COALESCE(SUM(deal_amount), 0) AS total_value,
            ROUND(AVG(health_score)::numeric, 2) AS avg_health,
            ROUND(AVG(urgency_score)::numeric, 2) AS avg_urgency,
            COUNT(*) FILTER (WHERE urgency_score >= 0.85) AS critical_count
        FROM accounts
        WHERE workspace_id = :ws
          AND deleted_at IS NULL
          AND stage IS NOT NULL
          AND stage NOT ILIKE '%closed%'
          AND stage NOT ILIKE '%won%'
          AND stage NOT ILIKE '%lost%'
        GROUP BY stage
        ORDER BY SUM(deal_amount) DESC NULLS LAST
    """), {"ws": ws})
    rows = result.fetchall()

    STAGE_ORDER = ["Qualification", "Demo", "Discovery", "Proposal", "Negotiation", "Verbal Commit", "Closed Won", "Closed Lost"]

    stages = [
        {
            "stage": r.stage,
            "deal_count": int(r.deal_count),
            "total_value": float(r.total_value or 0),
            "avg_health": float(r.avg_health or 0),
            "avg_urgency": float(r.avg_urgency or 0),
            "critical_count": int(r.critical_count or 0),
            "order": STAGE_ORDER.index(r.stage) if r.stage in STAGE_ORDER else 99,
        }
        for r in rows
    ]
    stages.sort(key=lambda x: x["order"])

    total_value = sum(s["total_value"] for s in stages)
    for s in stages:
        s["pct_of_pipeline"] = round(s["total_value"] / max(total_value, 1) * 100, 1)

    return {
        "data": {
            "stages": stages,
            "total_pipeline": total_value,
            "total_deals": sum(s["deal_count"] for s in stages),
        },
        "meta": {},
    }


@router.get("/watchtower-delta")
async def get_watchtower_delta(
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """What changed this week vs last week: health changes, new signals, stage moves."""
    ws = current_user.workspace_id

    # New signals this week vs last week
    signals = await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') AS this_week,
            COUNT(*) FILTER (WHERE created_at BETWEEN NOW() - INTERVAL '14 days' AND NOW() - INTERVAL '7 days') AS last_week,
            COUNT(*) FILTER (WHERE urgency_score >= 0.85 AND created_at >= NOW() - INTERVAL '7 days') AS critical_this_week
        FROM signals
        WHERE workspace_id = :ws
    """), {"ws": ws})
    sig_row = signals.fetchone()

    # Stage moves this week
    moves = await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days') AS this_week,
            COUNT(*) FILTER (WHERE created_at BETWEEN NOW() - INTERVAL '14 days' AND NOW() - INTERVAL '7 days') AS last_week
        FROM audit_log
        WHERE workspace_id = :ws
          AND action = 'crm_sync_update'
          AND changes ? 'stage'
    """), {"ws": ws})
    moves_row = moves.fetchone()

    # Deals with biggest health change
    health_delta = await db.execute(text("""
        SELECT
            a.id::text AS account_id,
            a.name,
            a.health_score,
            a.stage,
            a.urgency_score
        FROM accounts a
        WHERE a.workspace_id = :ws
          AND a.deleted_at IS NULL
          AND a.health_score IS NOT NULL
        ORDER BY a.urgency_score DESC
        LIMIT 5
    """), {"ws": ws})
    top_urgent = [
        {"account_id": r.account_id, "name": r.name, "health_score": float(r.health_score or 0),
         "stage": r.stage, "urgency_score": float(r.urgency_score or 0)}
        for r in health_delta.fetchall()
    ]

    return {
        "data": {
            "signals": {
                "this_week": int(sig_row.this_week or 0),
                "last_week": int(sig_row.last_week or 0),
                "delta": int(sig_row.this_week or 0) - int(sig_row.last_week or 0),
                "critical_this_week": int(sig_row.critical_this_week or 0),
            },
            "stage_moves": {
                "this_week": int(moves_row.this_week or 0),
                "last_week": int(moves_row.last_week or 0),
                "delta": int(moves_row.this_week or 0) - int(moves_row.last_week or 0),
            },
            "top_urgent_accounts": top_urgent,
        },
        "meta": {},
    }
