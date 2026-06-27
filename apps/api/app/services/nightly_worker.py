"""
NightlyWorker — Orchestrates the per-account agent pipeline.
Runs nightly across all workspace accounts, or on-demand for specific accounts.
Called by: Azure Container Jobs (nightly), batch-refresh endpoint (manual).

Pipeline per account:
1. Pull fresh HubSpot data + Gong transcripts
2. Fetch web intelligence via Exa (semantic search)
3. Run 6-agent pipeline via AgentOrchestrator
4. Write updated Account state + new Signals + Drafts to DB
5. Log AgentRun record with costs

Cost: ~$0.22/account/night (Haiku × 4 + Sonnet × 2)
"""
import asyncio
import html as _html
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import structlog

from app.config import get_settings
from app.models.account import Account, Signal, Draft, AgentRun, AuditLog, Interaction
from app.models.workspace import Workspace
from app.agents.orchestrator import AgentOrchestrator
from app.integrations.hubspot import HubSpotClient
from app.integrations.exa import ExaClient
from app.integrations.anthropic_embed import get_embedding
from app.integrations.fireflies import FirefliesClient, backfill_all_transcripts, _domain_root, _SELLER_DOMAINS, _GENERIC_WORDS
from app.integrations.teams import TeamsWebhookClient
from app.services.account_service import AccountService
from app.services.plays_engine import PlaysEngine
from sqlalchemy import text as sql_text

log = structlog.get_logger()

# Concurrency: process N accounts at once per workspace
ACCOUNT_CONCURRENCY = 5
# Skip accounts that ran successfully less than X hours ago (avoid double-run)
MIN_HOURS_BETWEEN_RUNS = 6

# Stage-based run frequency policy — compared LOWERCASE. The canonical
# closed-stage set lives in app.agents.base.CLOSED_STAGES; a title-case copy
# here once missed "closed-lost" and kept running (and billing) closed deals.
from app.agents.base import CLOSED_STAGES as _SKIP_STAGES  # never run
_WEEKLY_STAGES = {"to nurture"}                    # run at most once per 7 days (was 30 — too stale for MENA cycles)
# Everything else (Proposal, Discovery, Tailored Demo, etc.) = daily (MIN_HOURS_BETWEEN_RUNS)

# Fireflies participant cross-reference urgency scores.
# Scores are lower than LLM-detected signals because source is attendance alone,
# not inferred intent — the agent does the intent scoring in its own pass.
_FF_NEW_CONTACT_URGENCY = 0.55      # unknown contact appeared on call → flag for HubSpot update
_FF_ENGAGEMENT_URGENCY  = 0.55      # known contact attended at least one call
_FF_ACTION_ITEM_URGENCY = 0.60      # Fireflies-extracted action item
_FF_CHAMPION_URGENCY    = 0.75      # known contact with HSE/Safety title on 2+ calls

# Signal construction constants
# _MAX_SIGNALS: cap raw input to the agent to prevent prompt overflow on deep HubSpot histories.
# 10 notes (dense deal context) + 40 recency-sorted others = 50 total.
_MAX_RAW_SIGNALS = 50
_MAX_NOTES_IN_CAP = 10

# Webhook dispatcher urgency thresholds (signal.critical / signal.high events)
_WEBHOOK_CRITICAL_THRESHOLD = 0.9
_WEBHOOK_HIGH_THRESHOLD = 0.85


def _build_signal(sig_data: dict, account, run_id: str, push_threshold: float) -> Signal:
    """
    Construct a Signal ORM object from an agent-produced signal dict.
    Shared by _process_account and run_partial_pipeline_for_deal so
    both paths use the same varchar clamps and push_threshold source.
    type/source are varchar(100) — LLM-provided values can overflow
    and kill the entire account flush if not clamped here.
    """
    urgency_score = sig_data.get("urgency_score", 0.0) or 0.0
    return Signal(
        account_id=account.id,
        workspace_id=account.workspace_id,
        type=str(sig_data.get("type", "unknown"))[:100],
        urgency=str(sig_data.get("urgency", "medium"))[:20],
        urgency_score=urgency_score,
        detail=sig_data.get("detail", ""),
        source=str(sig_data.get("source", "agent"))[:100],
        confidence=sig_data.get("confidence", 0.5),
        gold_sources=sig_data.get("gold_sources", []),
        gold_resolution=sig_data.get("gold_resolution", ""),
        agent_run_id=uuid.UUID(run_id),
        pushed_to_inbox=urgency_score >= push_threshold,
    )


def _build_current_state(account: Account) -> dict:
    """
    Bridge Account DB columns into a state dict for the agent pipeline.
    Without this, fresh accounts missing JSONB state get 'unknown stage, $0 amount'
    on every run because the researcher reads from current_state, not DB columns.
    Callers merge their own state on top: {**_build_current_state(account), ...extra}
    """
    return {
        **(account.state or {}),
        "account_id": str(account.id),
        "name": account.name,
        "stage": account.stage,
        "deal_amount": float(account.deal_amount) if account.deal_amount else None,
        "close_date": str(account.close_date) if account.close_date else None,
        "owner_rep_id": account.owner_rep_id,
        "hubspot_deal_id": account.hubspot_deal_id,
    }


async def _fetch_fireflies_map_with_timeout(
    worker: "NightlyWorker", ws: Workspace, accounts: list, log_suffix: str = ""
) -> dict:
    """
    Fetch Fireflies workspace map with the standard 120s outer timeout.
    The inner backfill has a 90s budget; 120s gives it headroom without
    silently cancelling every run (the previous 30s budget did exactly that).
    """
    try:
        return await asyncio.wait_for(
            worker._fetch_fireflies_map(ws, accounts), timeout=120.0
        )
    except asyncio.TimeoutError:
        log.warning("fireflies_fetch_timeout", suffix=log_suffix)
        return {}


class NightlyWorker:
    """Orchestrates the full per-account agent pipeline for a workspace."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()

    async def run_workspace(self, workspace_id: str) -> str:
        """
        Run the full nightly pipeline for a workspace.
        Called by Azure Container Jobs at midnight UTC.
        Returns run_id.
        """
        run_id = str(uuid.uuid4())
        log.info("nightly_run_started", workspace_id=workspace_id, run_id=run_id)

        # Load workspace
        ws = await self._get_workspace(workspace_id)
        if not ws:
            log.error("workspace_not_found", workspace_id=workspace_id)
            return run_id

        # Refresh HubSpot + Outlook tokens if needed
        ws = await self._maybe_refresh_hubspot_token(ws)
        ws = await self._maybe_refresh_outlook_token(ws)

        # Get all accounts for this workspace
        service = AccountService(self.db)
        all_accounts = await service.get_accounts_for_batch(workspace_id=workspace_id)

        # Filter by stage policy and recency
        now = datetime.now(timezone.utc)
        daily_cutoff = now - timedelta(hours=MIN_HOURS_BETWEEN_RUNS)
        weekly_cutoff = now - timedelta(days=7)
        accounts = []
        skipped_stage = 0
        for a in all_accounts:
            stage = (a.stage or "").strip().lower()
            if stage in _SKIP_STAGES:
                skipped_stage += 1
                continue
            cutoff = weekly_cutoff if stage in _WEEKLY_STAGES else daily_cutoff
            if a.last_agent_run_at and a.last_agent_run_at >= cutoff:
                continue
            accounts.append(a)

        log.info(
            "nightly_run_accounts",
            workspace_id=workspace_id,
            total=len(all_accounts),
            skipped_stage=skipped_stage,
            to_process=len(accounts),
            run_id=run_id,
        )

        # Pre-fetch Fireflies transcripts at workspace level — one batch call
        # instead of per-account fetches; the 120s outer timeout gives headroom
        # over the inner 90s backfill budget.
        fireflies_map = await _fetch_fireflies_map_with_timeout(self, ws, accounts, workspace_id)

        # Create AgentRun record
        agent_run = self._make_agent_run(run_id, workspace_id, "nightly", len(accounts))
        self.db.add(agent_run)
        await self.db.commit()

        results = await self._run_accounts_with_semaphore(accounts, ws, run_id, fireflies_map)

        # Re-rank portfolio urgency now that every account has a fresh raw score
        await self._normalize_urgency_scores(self.db, workspace_id)
        await self._finalize_agent_run(agent_run, results, workspace_id)

        log.info(
            "nightly_run_complete",
            run_id=run_id,
            processed=agent_run.accounts_processed,
            failed=agent_run.accounts_failed,
            signals=agent_run.signals_detected,
            drafts=agent_run.drafts_created,
            cost_usd=round(agent_run.total_cost_usd, 4),
        )

        # Teams morning brief — sent after nightly run finishes
        if self.settings.teams_webhook_url:
            try:
                teams = TeamsWebhookClient(self.settings.teams_webhook_url)
                service = AccountService(self.db)
                top_accounts_raw = await service.get_accounts_for_batch(workspace_id=workspace_id)
                top_accounts = sorted(
                    [{"name": a.name, "urgency_score": a.urgency_score, "stage": a.stage}
                     for a in top_accounts_raw if a.urgency_score],
                    key=lambda x: x["urgency_score"] or 0,
                    reverse=True,
                )[:3]

                # Get DAR for brief
                dar_result = await self.db.execute(sql_text("""
                    SELECT ROUND(
                        COUNT(*) FILTER (WHERE d.status IN ('approved','approved_modified'))::numeric
                        / NULLIF(COUNT(*), 0) * 100, 1
                    ) AS dar_pct,
                    COUNT(*) FILTER (WHERE d.status = 'pending') AS pending
                    FROM drafts d JOIN accounts a ON d.account_id = a.id
                    WHERE a.workspace_id = :ws
                      AND d.created_at >= NOW() - INTERVAL '30 days'
                """), {"ws": workspace_id})
                dar_row = dar_result.fetchone()
                dar_pct = float(dar_row.dar_pct or 0) if dar_row else 0.0
                pending_drafts = int(dar_row.pending or 0) if dar_row else 0

                await teams.send_morning_brief(
                    workspace_name=ws.name,
                    top_accounts=top_accounts,
                    pending_drafts=pending_drafts,
                    dar_pct=dar_pct,
                    frontend_url=self.settings.frontend_url,
                )
            except Exception as e:
                log.warning("teams_morning_brief_failed", error=str(e))

        # Pre-generate meeting briefs for top 5 urgency accounts (Responder fast path for briefs)
        await self._pregenerate_meeting_briefs(workspace_id, ws)

        return run_id

    async def trigger_manual_run(
        self,
        workspace_id: str,
        account_ids: Optional[list[str]] = None,
        triggered_by_user: Optional[str] = None,
    ) -> str:
        """
        Trigger an immediate agent run for specific accounts (or all).
        Called from the batch-refresh endpoint.
        Queues via Azure Service Bus for async processing.
        """
        run_id = str(uuid.uuid4())

        try:
            from azure.servicebus.aio import ServiceBusClient
            from azure.servicebus import ServiceBusMessage

            payload = {
                "run_id": run_id,
                "workspace_id": workspace_id,
                "account_ids": account_ids,
                "trigger": "manual",
                "triggered_by": triggered_by_user,
                "queued_at": datetime.now(timezone.utc).isoformat(),
            }

            async with ServiceBusClient.from_connection_string(
                self.settings.azure_service_bus_connection_string
            ) as client:
                async with client.get_queue_sender("vantage-agent-runs") as sender:
                    msg = ServiceBusMessage(
                        body=json.dumps(payload),
                        content_type="application/json",
                    )
                    await sender.send_messages(msg)

            log.info("manual_run_queued", run_id=run_id, workspace_id=workspace_id, count=len(account_ids or []))
        except Exception as e:
            log.error("service_bus_queue_failed", error=str(e), run_id=run_id)
            # Service Bus not available (local dev) — caller handles fallback via BackgroundTasks

        return run_id

    async def _run_immediate_sync(
        self,
        run_id: str,
        workspace_id: str,
        account_ids: Optional[list[str]],
        stage_filter: Optional[str] = None,
    ) -> None:
        """Immediate fallback when Service Bus is unavailable. Runs in background task."""
        ws = await self._get_workspace(workspace_id)
        if not ws:
            log.error("manual_run_fallback_no_workspace", run_id=run_id)
            return

        ws = await self._maybe_refresh_outlook_token(ws)

        service = AccountService(self.db)
        accounts = await service.get_accounts_for_batch(
            workspace_id=workspace_id,
            account_ids=account_ids,
            stage_filter=stage_filter,
        )

        # Cap manual runs at 20 accounts — running all 300+ accounts in a background task
        # takes several hours. Nightly runs via the Azure job handle the full workspace.
        # Priority: urgency-sorted, so the most critical accounts go first.
        MANUAL_RUN_LIMIT = 20
        if not account_ids and len(accounts) > MANUAL_RUN_LIMIT:
            log.info(
                "manual_run_capped",
                run_id=run_id,
                total=len(accounts),
                processing=MANUAL_RUN_LIMIT,
            )
            accounts = accounts[:MANUAL_RUN_LIMIT]

        log.info("manual_run_sync_fallback", run_id=run_id, count=len(accounts))

        fireflies_map = await _fetch_fireflies_map_with_timeout(self, ws, accounts, run_id)

        # Create AgentRun record so Analytics can track manual runs
        agent_run = self._make_agent_run(run_id, workspace_id, "manual", len(accounts))
        self.db.add(agent_run)
        await self.db.commit()

        results = await self._run_accounts_with_semaphore(accounts, ws, run_id, fireflies_map)

        # Re-rank portfolio urgency now that every account has a fresh raw score
        await self._normalize_urgency_scores(self.db, workspace_id)
        await self._finalize_agent_run(agent_run, results, workspace_id)

    async def _pregenerate_meeting_briefs(self, workspace_id: str, ws: Workspace) -> None:
        """
        Pre-build meeting briefs for the top-5 urgency accounts and cache them
        in account.state["prebuilt_meeting_brief"].  Runs after the nightly sweep
        so reps get instant brief loads when they open the War Room.
        Uses its own DB session to avoid polluting the workspace-level session.
        """
        from app.services.assistant import AssistantService
        from app.db.database import AsyncSessionLocal
        from sqlalchemy import select as _sel_br
        from sqlalchemy.orm.attributes import flag_modified as _fm
        try:
            service = AccountService(self.db)
            all_accounts = await service.get_accounts_for_batch(workspace_id=workspace_id)
            top_for_briefs = sorted(
                [a for a in all_accounts if a.urgency_score and a.last_agent_run_at],
                key=lambda x: x.urgency_score or 0,
                reverse=True,
            )[:5]
            ws_settings = ws.settings or {}
            seller_context = {
                "sender_name":         ws_settings.get("sender_name", ""),
                "sender_title":        ws_settings.get("sender_title", ""),
                "sender_company":      ws_settings.get("sender_company", ws.name or ""),
                "product_description": ws_settings.get("product_description", ""),
            }
            async with AsyncSessionLocal() as brief_db:
                svc = AssistantService(brief_db)
                for acct in top_for_briefs:
                    try:
                        result = await brief_db.execute(
                            _sel_br(Account).where(Account.id == acct.id)
                        )
                        acct_full = result.scalar_one_or_none()
                        if not acct_full:
                            continue
                        brief = await svc.build_meeting_brief(
                            account=acct_full,
                            workspace_id=workspace_id,
                            seller_context=seller_context,
                        )
                        state = acct_full.state or {}
                        state["prebuilt_meeting_brief"] = {
                            **brief,
                            "generated_at": datetime.now(timezone.utc).isoformat(),
                        }
                        acct_full.state = state
                        _fm(acct_full, "state")
                        await brief_db.commit()
                        log.info("prebuilt_brief_generated", account=acct.name)
                    except Exception as e:
                        log.debug("prebuilt_brief_failed", account=acct.name, error=str(e))
        except Exception as e:
            log.warning("nightly_briefs_failed", error=str(e))

    async def _run_accounts_with_semaphore(
        self, accounts: list, ws: Workspace, run_id: str, fireflies_map: dict
    ) -> list:
        """
        Spawn one task per account under a shared semaphore to cap concurrency.
        Each task opens its own DB session — AsyncSession is not concurrency-safe.
        (account/ws attribute reads are safe because expire_on_commit=False.)
        """
        from app.db.database import AsyncSessionLocal
        semaphore = asyncio.Semaphore(ACCOUNT_CONCURRENCY)

        async def _run_one(account: Account):
            async with semaphore:
                async with AsyncSessionLocal() as task_db:
                    return await NightlyWorker(task_db)._process_account(
                        account, ws, run_id, fireflies_map=fireflies_map
                    )

        return await asyncio.gather(*[_run_one(a) for a in accounts], return_exceptions=True)

    async def _finalize_agent_run(
        self, agent_run: AgentRun, results: list, workspace_id: str
    ) -> None:
        """Aggregate per-account results into the AgentRun record and commit."""
        agent_run.status = "completed"
        agent_run.accounts_processed = sum(1 for r in results if isinstance(r, dict) and r.get("success"))
        agent_run.accounts_failed    = sum(1 for r in results if isinstance(r, Exception) or (isinstance(r, dict) and not r.get("success")))
        agent_run.signals_detected   = sum(r.get("signals", 0) for r in results if isinstance(r, dict))
        agent_run.drafts_created     = sum(r.get("drafts", 0) for r in results if isinstance(r, dict))
        agent_run.total_cost_usd     = sum(r.get("cost_usd", 0.0) for r in results if isinstance(r, dict))
        agent_run.completed_at       = datetime.now(timezone.utc)
        await self.db.commit()

    async def _normalize_urgency_scores(self, db, workspace_id: str) -> None:
        """
        Post-sweep portfolio rank normalization.

        The raw urgency blend's terms are correlated (signal urgency comes from
        the same LLMs, overdue CRM close dates add +0.15 to nearly every active
        deal), so raw scores saturate near the 0.97 clamp and the whole queue
        reads 0.92-0.95. Re-map raw scores to percentile ranks across the active
        portfolio: final = 0.30 + 0.65 * percentile. Order is preserved; ties are
        broken by deal amount (bigger $ ranks higher) then health (sicker ranks
        higher) so identical raw scores still triage meaningfully. The raw score
        is kept at state->urgency_score_raw for audit, which also makes re-runs
        idempotent: normalization always re-ranks from raw, never from itself.
        Closed stages keep their fixed 0.1 and are excluded.
        """
        try:
            await db.execute(sql_text("""
                WITH raws AS (
                    SELECT id, deal_amount, health_score,
                           COALESCE(
                               CASE WHEN jsonb_exists(COALESCE(state, '{}'::jsonb), 'urgency_score_raw')
                                    THEN (state->>'urgency_score_raw')::float END,
                               (state->>'urgency_score')::float,
                               urgency_score
                           ) AS raw_score
                    FROM accounts
                    WHERE workspace_id = :ws
                      AND deleted_at IS NULL
                      AND urgency_score IS NOT NULL
                      AND LOWER(COALESCE(stage, '')) NOT IN ('won', 'closed lost', 'closed-lost', 'partners')
                ),
                ranked AS (
                    SELECT id, raw_score,
                           (ROW_NUMBER() OVER (
                                ORDER BY raw_score ASC,
                                         COALESCE(deal_amount, 0) ASC,
                                         COALESCE(health_score, 1) DESC,
                                         id ASC
                            ) - 1)::float / NULLIF(COUNT(*) OVER () - 1, 0) AS pct
                    FROM raws
                    WHERE raw_score IS NOT NULL
                )
                UPDATE accounts a
                SET urgency_score = ROUND((0.30 + 0.65 * COALESCE(r.pct, 0.5))::numeric, 2),
                    state = jsonb_set(
                        jsonb_set(
                            COALESCE(a.state, '{}'::jsonb),
                            '{urgency_score_raw}', to_jsonb(ROUND(r.raw_score::numeric, 2))
                        ),
                        '{urgency_score}',
                        to_jsonb(ROUND((0.30 + 0.65 * COALESCE(r.pct, 0.5))::numeric, 2))
                    )
                FROM ranked r
                WHERE a.id = r.id
            """), {"ws": workspace_id})
            await db.commit()
            log.info("urgency_rank_normalized", workspace_id=workspace_id)
        except Exception as e:
            await db.rollback()
            log.error("urgency_normalization_failed", workspace_id=workspace_id, error=str(e))

    async def _process_account(
        self,
        account: Account,
        ws: Workspace,
        run_id: str,
        fireflies_map: dict | None = None,
    ) -> dict:
        """
        Run the full 6-agent pipeline for a single account.
        Returns result dict with success, signals, drafts, cost_usd.
        """
        start = datetime.now(timezone.utc)

        # Workspace isolation guard — defence-in-depth against data cross-contamination
        if str(account.workspace_id) != str(ws.id):
            log.error(
                "workspace_mismatch_abort",
                account_id=str(account.id),
                account_workspace=str(account.workspace_id),
                expected_workspace=str(ws.id),
            )
            return {"success": False, "account_id": str(account.id), "error": "workspace_mismatch"}

        log.info("account_processing_started", account_id=str(account.id), name=account.name)

        try:
            # 1. Fetch fresh HubSpot activity (notes + contacts + emails)
            raw_signals = []
            # Keep raw lists for War Room activity feed persistence (step 5b)
            raw_emails: list[dict] = []
            raw_engagements: list[dict] = []
            if ws.hubspot_access_token and account.hubspot_deal_id:
                hs = HubSpotClient(ws.hubspot_access_token)

                # All notes — full history, no date cap
                try:
                    activity = await asyncio.wait_for(
                        hs.get_deal_activity(account.hubspot_deal_id),
                        timeout=15.0,
                    )
                    raw_signals.extend(_activity_to_signals(activity))
                except asyncio.TimeoutError:
                    log.warning("notes_fetch_timeout", account=account.name, deal_id=account.hubspot_deal_id)
                except Exception as e:
                    log.warning("notes_fetch_error", account=account.name, error=str(e))

                # Contact details (name, email, title, engagement dates)
                try:
                    contacts = await asyncio.wait_for(
                        hs.get_deal_contacts(account.hubspot_deal_id),
                        timeout=12.0,
                    )
                    raw_signals.extend(_contacts_to_signals(contacts))
                except asyncio.TimeoutError:
                    log.warning("contacts_fetch_timeout", account=account.name, deal_id=account.hubspot_deal_id)
                except Exception as e:
                    log.warning("contacts_fetch_error", account=account.name, deal_id=account.hubspot_deal_id,
                                error=repr(e), error_type=type(e).__name__)

                # Email engagements — full history (up to 100)
                try:
                    emails = await asyncio.wait_for(
                        hs.get_deal_emails(account.hubspot_deal_id, limit=100),
                        timeout=20.0,
                    )
                    raw_emails = emails  # save for activity feed persistence
                    raw_signals.extend(_emails_to_signals(emails))
                except asyncio.TimeoutError:
                    log.warning("emails_fetch_timeout", account=account.name, deal_id=account.hubspot_deal_id)
                except Exception as e:
                    log.warning("emails_fetch_error", account=account.name, deal_id=account.hubspot_deal_id,
                                error=repr(e), error_type=type(e).__name__)

                # V1 Engagements API — full history: Gmail/Outlook threads, calls, meetings
                try:
                    engagements = await asyncio.wait_for(
                        hs.get_deal_engagements(account.hubspot_deal_id, limit=200),
                        timeout=25.0,
                    )
                    raw_engagements = engagements  # save for activity feed persistence
                    raw_signals.extend(_engagements_to_signals(engagements))
                except (asyncio.TimeoutError, Exception) as e:
                    log.warning("engagements_fetch_error", account=account.name, error=str(e))

                # Company firmographics (industry, size, revenue)
                try:
                    company = await asyncio.wait_for(
                        hs.get_deal_company(account.hubspot_deal_id),
                        timeout=10.0,
                    )
                    raw_signals.extend(_company_to_signals(company))
                except (asyncio.TimeoutError, Exception) as e:
                    log.warning("company_fetch_error", account=account.name, error=str(e))

            # 1b. Use pre-matched Fireflies transcripts from workspace-level backfill
            fireflies_transcripts = (fireflies_map or {}).get(str(account.id), [])
            if fireflies_transcripts:
                log.info("fireflies_from_map", account=account.name, count=len(fireflies_transcripts))

            # 1c. Extract Fireflies action items as signals (they're already in the transcript)
            for transcript in fireflies_transcripts:
                for item in (transcript.get("action_items") or []):
                    if item and isinstance(item, str) and item.strip():
                        raw_signals.append({
                            "type": "fireflies_action_item",
                            "urgency": "medium",
                            "urgency_score": _FF_ACTION_ITEM_URGENCY,
                            "detail": item.strip()[:500],
                            "source": "fireflies",
                            "confidence": 0.85,
                            "gold_sources": [],
                            "gold_resolution": "",
                            "source_url": None,
                            "meddpicc_component": None,
                        })

            # 1c2. Cross-reference Fireflies participants against HubSpot contacts
            # This is the primary signal for champion identification — who actually showed up.
            if fireflies_transcripts:
                # Collect all HubSpot contact emails for this deal (already fetched above).
                # Type must match _contacts_to_signals output — "contact_details".
                hs_contact_emails: dict[str, dict] = {}  # email → contact properties
                for sig in raw_signals:
                    if sig.get("type") == "contact_details" and sig.get("email"):
                        hs_contact_emails[sig["email"].lower()] = sig

                # Collect all unique participant emails from Fireflies (buyer side only)
                # Filter out internal seller emails to isolate buyer participants
                internal_domains = set((ws.settings or {}).get("seller_domains", []))
                buyer_participants: dict[str, list[str]] = {}  # email → list of transcript titles
                for transcript in fireflies_transcripts:
                    for participant_email in (transcript.get("participants") or []):
                        if not participant_email or "@" not in participant_email:
                            continue
                        domain = participant_email.split("@")[-1].lower()
                        if domain in internal_domains:
                            continue
                        buyer_participants.setdefault(participant_email.lower(), []).append(
                            transcript.get("title", "")[:60]
                        )

                # Emit engagement signals per participant
                for email, call_titles in buyer_participants.items():
                    is_known_contact = email in hs_contact_emails
                    contact_info = hs_contact_emails.get(email, {})
                    name = contact_info.get("contact_name") or email.split("@")[0]
                    title = contact_info.get("contact_title", "")
                    call_count = len(call_titles)

                    if not is_known_contact:
                        # New contact found in Fireflies not in HubSpot — flag it
                        raw_signals.append({
                            "type": "new_contact_identified",
                            "urgency": "medium",
                            "urgency_score": _FF_NEW_CONTACT_URGENCY,
                            "detail": (
                                f"{_html.escape(email)} appeared in {call_count} Fireflies call(s) "
                                f"but is not in HubSpot deal contacts. "
                                f"Calls: {', '.join(_html.escape(t) for t in call_titles[:3])}. "
                                f"Add this contact to the HubSpot deal."
                            ),
                            "source": "fireflies",
                            "confidence": 0.9,
                            "meddpicc_component": "champion",
                        })
                    else:
                        # Known contact — enrich with call attendance for champion scoring
                        champion_titles = {
                            "hse manager", "hsqe manager", "hsqe director", "safety manager",
                            "ehs director", "health and safety", "vp safety", "head of safety",
                            "hse director", "qhse manager", "qhse director",
                        }
                        title_lower = title.lower()
                        is_champion_role = any(ct in title_lower for ct in champion_titles)
                        raw_signals.append({
                            "type": "champion_activity" if call_count >= 2 else "contact_engagement",
                            "urgency": "high" if (call_count >= 2 and is_champion_role) else "medium",
                            "urgency_score": _FF_CHAMPION_URGENCY if (call_count >= 2 and is_champion_role) else _FF_ENGAGEMENT_URGENCY,
                            "detail": (
                                f"{_html.escape(name)} ({_html.escape(title or 'title unknown')}, {_html.escape(email)}) attended "
                                f"{call_count} recorded call(s): {', '.join(_html.escape(t) for t in call_titles[:3])}. "
                                + ("Champion role match (HSE/Safety title)." if is_champion_role else "")
                            ),
                            "source": "fireflies",
                            "confidence": 0.85,
                            "meddpicc_component": "champion",
                        })

            # 1d. Store Fireflies transcripts in current_state for ASO persistence (D1)
            # Entries arrive canonical from build_transcript_entry (speaker stats,
            # talk ratio, buyer questions, commitments already computed at ingest).
            from app.services.conversation_intel import merge_transcript_entries
            _merged_transcripts = merge_transcript_entries(
                (account.state or {}).get("transcripts", []),
                fireflies_transcripts or [],
            )

            # 2. Fetch web intelligence via Exa
            # exa_api_key: workspace-level key takes precedence; global .env key is the dev fallback.
            _exa_key = getattr(ws, "exa_api_key", None) or self.settings.exa_api_key
            news_content = ""
            if _exa_key:
                try:
                    exa = ExaClient(_exa_key)
                    news_content = await asyncio.wait_for(
                        exa.research_account(account.name),
                        timeout=25.0,
                    )
                    if news_content:
                        log.info("exa_research_complete", account=account.name, chars=len(news_content))
                except asyncio.TimeoutError:
                    log.warning("exa_timeout", account=account.name)
                except Exception as e:
                    log.warning("exa_error", account=account.name, error=str(e))

            # 2b. Stakeholder people signals via Exa
            if _exa_key:
                stakeholders = (account.state or {}).get("stakeholders", [])
                key_roles = {"champion", "economic_buyer", "decision_maker"}
                key_stakeholders = [
                    s for s in stakeholders
                    if s.get("role") in key_roles and s.get("name")
                ][:3]
                if key_stakeholders:
                    try:
                        exa_people = ExaClient(_exa_key)
                        for stk in key_stakeholders:
                            stk_name = stk.get("name", "")
                            stk_title = stk.get("title", "")
                            if not stk_name:
                                continue
                            change_text = await asyncio.wait_for(
                                exa_people.check_people_signals(
                                    name=stk_name,
                                    title=stk_title,
                                    company=account.name,
                                ),
                                timeout=12.0,
                            )
                            if change_text:
                                lower = change_text.lower()
                                sig_type = "champion_departure" if any(
                                    w in lower for w in ["left", "departed", "resigned", "no longer", "join"]
                                ) else "champion_role_change"
                                raw_signals.append({
                                    "type": sig_type,
                                    "source": "exa:linkedin",
                                    "detail": f"{_html.escape(stk_name)} ({_html.escape(stk.get('role', 'stakeholder'))}): {_html.escape(change_text)}",
                                    "raw": {"name": stk_name, "change": change_text},
                                })
                                log.info("people_signal_detected", account=account.name, name=stk_name, sig_type=sig_type)
                    except asyncio.TimeoutError:
                        log.debug("people_signals_timeout", account=account.name)
                    except Exception as e:
                        log.debug("people_signals_error", account=account.name, error=str(e))

            # 3. Run agent pipeline
            orchestrator = AgentOrchestrator()

            current_state = _build_current_state(account)
            # Fix 7: Auto-decay stakeholder engagement_level based on days since last contact.
            # Prevents stale "engaged" labels on contacts who have been dark for months,
            # which misleads the researcher and drafter into treating cold contacts as warm.
            if current_state.get("stakeholders"):
                current_state["stakeholders"] = _decay_engagement_levels(current_state["stakeholders"])

            # Convert bandwidth string to float scalar (orchestrator expects 0.0-1.0 float)
            bw_map = {"low": 0.5, "normal": 1.0, "high": 1.5}
            rep_bw = bw_map.get(_get_rep_bandwidth(ws), 1.0)

            # Seller context — who is writing these emails (read from workspace settings)
            ws_settings = ws.settings or {}
            seller_context = {
                "sender_name":        ws_settings.get("sender_name", ""),
                "sender_title":       ws_settings.get("sender_title", ""),
                "sender_company":     ws_settings.get("sender_company", ws.name or ""),
                "product_description": ws_settings.get("product_description", ""),
                "voice_profile":      ws_settings.get("voice_profile"),
                "ai_fields":          ws_settings.get("ai_fields"),
            }

            # Persist transcripts in current_state so ASO always has the latest
            current_state["transcripts"] = _merged_transcripts

            # Account-level conversation rollup — recomputed whenever transcripts
            # change; the agents read it from deal context, the UI from /transcripts
            from app.services.conversation_intel import compute_conversation_rollup
            current_state["conversation_intel"] = compute_conversation_rollup(
                _merged_transcripts,
                current_state.get("stakeholders", []),
            )

            # Compute precise activity timeline and merge into current_state
            activity_summary = await self._compute_activity_summary(
                account_id=str(account.id),
                workspace_id=str(account.workspace_id),
                raw_emails=raw_emails,
                raw_engagements=raw_engagements,
                fireflies_transcripts=fireflies_transcripts,
            )
            # Fill deal_created_at from state if available
            activity_summary["deal_created_at"] = current_state.get("deal_created_at")
            current_state["activity_summary"] = activity_summary

            # Load declined draft history — Prioritiser uses this to avoid repeating failed action types
            try:
                from sqlalchemy import select as _sel_d, desc as _desc_d
                import uuid as _uuid_d
                declined_result = await self.db.execute(
                    _sel_d(Interaction)
                    .where(
                        Interaction.account_id == _uuid_d.UUID(str(account.id)),
                        Interaction.workspace_id == _uuid_d.UUID(str(account.workspace_id)),
                        Interaction.type == "draft_declined",
                        Interaction.occurred_at.is_not(None),
                    )
                    .order_by(_desc_d(Interaction.occurred_at))
                    .limit(20)
                )
                declined_interactions = declined_result.scalars().all()
                training_signals = [
                    {
                        "date": i.occurred_at.strftime("%Y-%m-%d") if i.occurred_at else None,
                        "decline_reason": i.notes or "",
                        "training_category": i.training_category or "",
                        "draft_content_hint": (i.outcome or "")[:100],
                    }
                    for i in declined_interactions
                ]
                current_state["training_signals"] = training_signals
            except Exception as e:
                log.debug("training_signals_load_failed", account=account.name, error=str(e))
                current_state["training_signals"] = []

            # Load decline patterns for DrafterAgent feedback loop
            decline_patterns: dict = {}
            try:
                from sqlalchemy import func as _func_dp
                import uuid as _uuid_dp
                dp_result = await self.db.execute(
                    select(Interaction.training_category, _func_dp.count().label("n"))
                    .where(
                        Interaction.account_id == _uuid_dp.UUID(str(account.id)),
                        Interaction.workspace_id == _uuid_dp.UUID(str(account.workspace_id)),
                        Interaction.is_training_signal == True,
                        Interaction.training_category.is_not(None),
                        Interaction.occurred_at >= datetime.now(timezone.utc) - timedelta(days=60),
                    )
                    .group_by(Interaction.training_category)
                )
                decline_patterns = {row.training_category: row.n for row in dp_result}
            except Exception as e:
                log.debug("decline_patterns_load_failed", account=account.name, error=str(e))

            # Cap raw signals to prevent prompt overflow on deals with deep HubSpot history.
            # Strategy: keep up to _MAX_RAW_SIGNALS total — _MAX_NOTES_IN_CAP notes
            # (critical deal context) + the most recent email/engagement signals
            # (HubSpot returns newest-first so taking from the front preserves recency).
            if len(raw_signals) > _MAX_RAW_SIGNALS:
                notes = [s for s in raw_signals if s.get("type") == "crm_note"][:_MAX_NOTES_IN_CAP]
                others = [s for s in raw_signals if s.get("type") != "crm_note"]
                capped = (notes + others[:(_MAX_RAW_SIGNALS - len(notes))])[:_MAX_RAW_SIGNALS]
                log.info(
                    "raw_signals_capped",
                    account=account.name,
                    original=len(raw_signals),
                    capped=len(capped),
                )
                raw_signals = capped

            result = await orchestrator.run_account(
                account_id=str(account.id),
                account_name=account.name,
                current_state=current_state,
                raw_signals=raw_signals,
                # Orchestrator parameter is named gong_transcripts (legacy Gong slot);
                # we feed Fireflies data there — schema is identical, rename is deferred.
                gong_transcripts=fireflies_transcripts,
                news_content=news_content,
                rep_bandwidth=rep_bw,
                seller_context=seller_context,
                decline_patterns=decline_patterns if decline_patterns else None,
            )

            # Guard: if pipeline failed, don't overwrite DB with empty state
            if not result.success:
                log.error(
                    "pipeline_failed_skipping_persist",
                    account_id=str(account.id),
                    account=account.name,
                    stages_completed=result.stages_completed,
                    error=result.error,
                )
                return {"success": False, "account_id": str(account.id), "error": result.error}

            # 4. Persist signals — result.signals_created is a list of dicts
            new_signals = []
            dedup_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            for sig_data in result.signals_created:
                # Skip duplicates: same type + detail in last 7 days
                try:
                    dup_check = await self.db.execute(
                        select(Signal.id).where(
                            Signal.account_id == account.id,
                            Signal.type == (sig_data.get("type") or ""),
                            Signal.detail == (sig_data.get("detail") or ""),
                            Signal.created_at >= dedup_cutoff,
                        ).limit(1)
                    )
                    if dup_check.scalar():
                        continue
                except Exception:
                    pass  # on error, allow insert

                sig = _build_signal(sig_data, account, run_id, self.settings.agent_push_threshold)
                self.db.add(sig)
                new_signals.append(sig)

            # 4b. Teams alert for critical signals
            if self.settings.teams_webhook_url and new_signals:
                teams = TeamsWebhookClient(self.settings.teams_webhook_url)
                for sig in new_signals:
                    if (sig.urgency_score or 0.0) >= self.settings.teams_alert_urgency_threshold:
                        try:
                            await teams.send_signal_alert(
                                account_name=account.name,
                                account_id=str(account.id),
                                signal_type=sig.type,
                                detail=sig.detail,
                                urgency=sig.urgency,
                                urgency_score=sig.urgency_score,
                                frontend_url=self.settings.frontend_url,
                            )
                        except Exception as e:
                            log.warning("teams_alert_failed", error=str(e))

            # 5. Persist drafts — supersede old pending drafts of the same type first,
            # then insert new ones. Prevents pile-up from repeated runs on the same account.
            new_drafts = []
            new_draft_types = [d.get("type") for d in result.drafts_created if d.get("type")]
            if new_draft_types:
                from sqlalchemy import update as _upd
                await self.db.execute(
                    _upd(Draft)
                    .where(
                        Draft.account_id == account.id,
                        Draft.type.in_(new_draft_types),
                        # "queued" = rules-engine placeholders awaiting content —
                        # the real draft arriving now is that content.
                        Draft.status.in_(("pending", "queued")),
                    )
                    .values(status="superseded")
                )
            for draft_data in result.drafts_created:
                draft = Draft(
                    account_id=account.id,
                    workspace_id=account.workspace_id,
                    type=draft_data.get("type", "follow_up"),
                    content=draft_data.get("content", ""),
                    subject_line=draft_data.get("subject_line"),
                    target_contact=draft_data.get("target_contact"),
                    sources_cited=draft_data.get("sources_cited", []),
                    gold_data_used={},
                    confidence=draft_data.get("confidence"),
                    status="pending",
                    expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                    agent_run_id=uuid.UUID(run_id),
                )
                self.db.add(draft)
                new_drafts.append(draft)

            # 6. Update account state — extract scores from updated_aso
            # JSON round-trip strips any lingering Pydantic model instances before JSONB write
            _raw_aso = result.updated_aso or {}
            try:
                aso = json.loads(json.dumps(
                    _raw_aso,
                    default=lambda o: o.model_dump(mode="json") if hasattr(o, "model_dump") else str(o)
                ))
            except Exception:
                aso = _raw_aso
            pov = aso.get("pov", {})
            icp_data = aso.get("icp_score") or {}
            icp_score_val = icp_data.get("score") if isinstance(icp_data, dict) else None
            await self.db.execute(
                update(Account)
                .where(Account.id == account.id)
                .values(
                    state=aso,
                    health_score=aso.get("health_score"),
                    urgency_score=aso.get("urgency_score"),
                    pov_forecast_cat=pov.get("forecast_category"),
                    pov_confidence=pov.get("forecast_confidence"),
                    icp_score=icp_score_val,
                    last_agent_run_at=datetime.now(timezone.utc),
                    agent_run_count=Account.agent_run_count + 1,
                )
            )

            # 6b. Evaluate plays — auto-queue drafts for triggered conditions
            try:
                plays = PlaysEngine(self.db)
                play_drafts = await plays.evaluate_and_fire(
                    account=account,
                    updated_aso=result.updated_aso or {},
                    run_id=run_id,
                )
                new_drafts.extend(play_drafts)
                if play_drafts:
                    log.info(
                        "plays_fired",
                        account=account.name,
                        count=len(play_drafts),
                        types=[d.type for d in play_drafts],
                    )
            except Exception as e:
                log.warning("plays_engine_failed", account=account.name, error=str(e))

            # 6c. Rules engine — user-defined automation rules
            try:
                from app.services.rules_engine import RulesEngine
                rules = RulesEngine(self.db)
                rule_results = await rules.evaluate(
                    account=account,
                    updated_aso=result.updated_aso or {},
                    workspace_settings=ws.settings or {},
                    run_id=run_id,
                )
                if rule_results:
                    log.info("rules_engine_fired", account=account.name, results=rule_results)
            except Exception as e:
                log.warning("rules_engine_failed", account=account.name, error=str(e))

            # 6d. Outbound webhook dispatch
            try:
                from app.services.webhook_dispatcher import WebhookDispatcher
                dispatcher = WebhookDispatcher()
                aso_wd = result.updated_aso or {}
                ws_settings_wd = ws.settings or {}
                for sig in new_signals:
                    if (sig.urgency_score or 0) >= _WEBHOOK_CRITICAL_THRESHOLD:
                        await dispatcher.dispatch(
                            "signal.critical", str(account.id), account.name,
                            str(account.workspace_id), ws_settings_wd,
                            {"signal_type": sig.type, "detail": sig.detail},
                        )
                    elif (sig.urgency_score or 0) >= _WEBHOOK_HIGH_THRESHOLD:
                        await dispatcher.dispatch(
                            "signal.high", str(account.id), account.name,
                            str(account.workspace_id), ws_settings_wd,
                            {"signal_type": sig.type},
                        )
                if new_drafts:
                    await dispatcher.dispatch(
                        "draft.created", str(account.id), account.name,
                        str(account.workspace_id), ws_settings_wd,
                        {"draft_count": len(new_drafts)},
                    )
                await dispatcher.dispatch(
                    "agent.run_complete", str(account.id), account.name,
                    str(account.workspace_id), ws_settings_wd,
                    {
                        "health_score": aso_wd.get("health_score"),
                        "urgency_score": aso_wd.get("urgency_score"),
                    },
                )
            except Exception as e:
                log.debug("webhook_dispatch_failed", account=account.name, error=str(e))

            # 6e. Persist ForecastSnapshot for AI forecast accuracy tracking (F3)
            try:
                from app.models.account import ForecastSnapshot
                pov_snap = aso.get("pov", {})
                if pov_snap.get("forecast_category"):
                    snap = ForecastSnapshot(
                        account_id=account.id,
                        workspace_id=account.workspace_id,
                        pov_category=pov_snap.get("forecast_category"),
                        pov_amount=pov_snap.get("pov_amount"),
                        crm_amount=float(account.deal_amount) if account.deal_amount else None,
                        crm_stage=account.stage,
                    )
                    self.db.add(snap)
            except Exception as e:
                log.debug("forecast_snapshot_failed", account=account.name, error=str(e))

            # 7. Persist HubSpot engagements as Interaction records (War Room activity feed)
            # This makes emails, calls, and meeting notes visible in the account timeline.
            try:
                await self._persist_hubspot_interactions(account, raw_emails, raw_engagements)
            except Exception as e:
                log.warning("hubspot_interactions_persist_failed", account=account.name, error=str(e))

            # 7b. Timeline gap-fill — self-driving action planning
            try:
                from app.services.timeline_service import TimelineService
                pov_for_timeline = (result.updated_aso or {}).get("pov", {})
                signals_for_timeline = [
                    {"type": s.type, "urgency_score": s.urgency_score or 0,
                     "detail": s.detail or "", "id": str(s.id),
                     "created_at": s.created_at}
                    for s in new_signals
                ]
                resolved = list(result.resolved_signals or [])
                tl = TimelineService(self.db)
                tl_created = await tl.gap_fill(
                    account, pov_for_timeline, signals_for_timeline,
                    resolved_signal_types=resolved,
                )
                if tl_created:
                    log.info("timeline_actions_created", account=account.name, count=tl_created)
            except Exception as e:
                log.warning("timeline_gap_fill_failed", account=account.name, error=str(e))

            # 8. Update embedding (for semantic search)
            if result.updated_aso:
                summary_text = _aso_to_search_text(account.name, result.updated_aso)
                embedding = await get_embedding(summary_text)
                if embedding:
                    await self.db.execute(
                        update(Account)
                        .where(Account.id == account.id)
                        .values(embedding=embedding)
                    )

            await self.db.commit()

            # Publish SSE event so War Room clients get real-time updates (N1)
            try:
                from app.services.cache import get_redis
                redis_client = await get_redis()
                if redis_client:
                    event_data = json.dumps({
                        "type": "agent_run_complete",
                        "account_id": str(account.id),
                        "health_score": (result.updated_aso or {}).get("health_score"),
                        "urgency_score": (result.updated_aso or {}).get("urgency_score"),
                        "signals_count": len(new_signals),
                        "drafts_count": len(new_drafts),
                    })
                    await redis_client.publish(
                        f"account:{account.workspace_id}:{account.id}",
                        event_data,
                    )
            except Exception as e:
                log.debug("sse_publish_failed", account=account.name, error=str(e))

            # Write updated ASO to Redis for fast reads
            try:
                from app.services.cache import cache_aso
                if result.updated_aso:
                    await cache_aso(str(account.id), result.updated_aso, workspace_id=str(account.workspace_id))
            except Exception as e:
                log.debug("aso_cache_write_failed", account=account.name, error=str(e))

            # Write pre-compressed assistant context to Redis (Responder fast path)
            try:
                from app.services.cache import cache_compressed_context
                aso = result.updated_aso or {}
                pov = aso.get("pov", {})
                activity = aso.get("activity_summary", {})
                signals = aso.get("signals", [])
                next_actions = aso.get("next_actions", [])
                stakeholders = aso.get("stakeholders", [])
                amt = f"${float(account.deal_amount or 0):,.0f}" if account.deal_amount else "?"
                ctx_lines = [
                    f"# {account.name} | {account.stage} | {amt} | Close: {account.close_date}",
                    f"Health: {aso.get('health_score','?')} | Urgency: {aso.get('urgency_score','?')} | AI POV: {pov.get('forecast_category','?')} ({pov.get('forecast_confidence') or 0:.0%})",
                ]
                if pov.get("pov_amount") and account.deal_amount:
                    ctx_lines.append(f"AI amount: ${pov['pov_amount']:,.0f} (CRM: {amt})")
                if activity.get("last_inbound_reply_date"):
                    ctx_lines.append(f"Last reply: {activity['last_inbound_reply_date']} ({activity.get('days_since_last_inbound','?')}d ago)")
                meddpicc = pov.get("meddpicc", {})
                gaps = (meddpicc.get("gaps", []) if meddpicc else [])[:2]
                if gaps:
                    ctx_lines.append(f"MEDDPICC gaps: {'; '.join(gaps)}")
                for s in stakeholders[:3]:
                    ctx_lines.append(f"  {s.get('name','?')} ({s.get('role','?')}, {s.get('engagement_level','?')})")
                for sig in signals[:4]:
                    ctx_lines.append(f"  [{sig.get('urgency','?')}] {sig.get('detail','')[:100]}")
                for a in next_actions[:2]:
                    ctx_lines.append(f"  Action: {a.get('action','')[:100]}")
                compressed = "\n".join(ctx_lines)
                if compressed:
                    await cache_compressed_context(str(account.id), str(account.workspace_id), compressed)
            except Exception as e:
                log.debug("compressed_ctx_cache_failed", account=account.name, error=str(e))

            # 9. Store run summary as a Vantage interaction (visible in War Room timeline)
            try:
                await self._store_run_summary(account, result.updated_aso or {})
            except Exception as e:
                log.debug("run_summary_store_failed", account=account.name, error=str(e))

            # 9b. Auto-apply Smart Fields (Loop 3) — confidence >= threshold → apply to HubSpot
            auto_threshold = (ws.settings or {}).get("auto_apply_smart_fields_threshold")
            if auto_threshold and account.hubspot_deal_id and ws.hubspot_access_token:
                try:
                    await self._auto_apply_smart_fields(account, aso, ws, float(auto_threshold))
                except Exception as e:
                    log.warning("auto_apply_smart_fields_failed", account=account.name, error=str(e))

            elapsed = (datetime.now(timezone.utc) - start).total_seconds()
            log.info(
                "account_processing_complete",
                account_id=str(account.id),
                signals=len(new_signals),
                drafts=len(new_drafts),
                cost_usd=round(result.total_cost_usd, 4),
                elapsed_s=round(elapsed, 1),
            )

            return {
                "success": True,
                "account_id": str(account.id),
                "signals": len(new_signals),
                "drafts": len(new_drafts),
                "cost_usd": result.total_cost_usd,
            }

        except Exception as e:
            try:
                log.error(
                    "account_processing_failed",
                    account_id=str(account.id),
                    error=str(e),
                    exc_info=True,
                )
            except Exception:
                # Guard against log rendering failures (e.g. Unicode in traceback on Windows)
                import sys
                safe_err = str(e).encode("ascii", errors="replace").decode("ascii")
                print(
                    f"[ERROR] account_processing_failed account_id={account.id} error={type(e).__name__}: {safe_err}",
                    file=sys.stderr,
                )
            return {"success": False, "account_id": str(account.id), "error": str(e)}

    async def _auto_apply_smart_fields(
        self, account: Account, aso: dict, ws: Workspace, threshold: float
    ) -> None:
        """Auto-apply high-confidence Smart Field suggestions directly to HubSpot (Loop 3)."""
        ALLOWED_FIELDS = {
            "hs_forecast_category", "closedate", "hs_deal_stage_probability",
            "notes_next_activity_date",
        }
        suggestions = aso.get("smart_fields", [])
        hs = HubSpotClient(ws.hubspot_access_token)
        to_apply = {}

        for suggestion in suggestions:
            if suggestion.get("status", "pending") != "pending":
                continue
            field_name = suggestion.get("field_name")
            confidence = suggestion.get("confidence", 0.0) or 0.0
            if field_name not in ALLOWED_FIELDS or confidence < threshold:
                continue
            to_apply[field_name] = suggestion.get("suggested_value")
            suggestion["status"] = "auto_applied"
            suggestion["auto_applied_at"] = datetime.now(timezone.utc).isoformat()
            suggestion["auto_applied_confidence"] = confidence

        if not to_apply:
            return

        try:
            await hs.update_deal_properties(account.hubspot_deal_id, to_apply)
            await self.db.execute(
                update(Account)
                .where(Account.id == account.id)
                .values(state=aso)
            )
            await self.db.commit()
            log.info("smart_fields_auto_applied", account=account.name, fields=list(to_apply.keys()))
        except Exception as e:
            log.warning("smart_fields_hubspot_write_failed", account=account.name, error=str(e))
            for s in suggestions:
                if s.get("status") == "auto_applied":
                    s["status"] = "pending"
                    s.pop("auto_applied_at", None)
                    s.pop("auto_applied_confidence", None)

    async def run_partial_pipeline_for_deal(
        self, workspace_id: str, hubspot_deal_id: str, trigger_type: str
    ) -> None:
        """
        Run Researcher + RiskScanner only for a specific deal (Loop 2).
        Called on HubSpot stage-change webhooks for immediate re-analysis.
        """
        from app.db.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            try:
                ws = await self._get_workspace_by_id(db, workspace_id)
                if not ws:
                    log.warning("partial_pipeline_no_workspace", workspace_id=workspace_id)
                    return

                result = await db.execute(
                    select(Account).where(
                        Account.workspace_id == uuid.UUID(workspace_id),
                        Account.hubspot_deal_id == hubspot_deal_id,
                        Account.deleted_at.is_(None),
                    )
                )
                account = result.scalar_one_or_none()
                if not account:
                    log.warning("partial_pipeline_no_account", hubspot_deal_id=hubspot_deal_id)
                    return

                log.info("partial_pipeline_start", account=account.name, trigger=trigger_type)

                # Fetch fresh HubSpot signals
                raw_signals: list[dict] = []
                if ws.hubspot_access_token and account.hubspot_deal_id:
                    hs = HubSpotClient(ws.hubspot_access_token)
                    try:
                        activity = await hs.get_deal_activity(account.hubspot_deal_id)
                        raw_signals.extend(_activity_to_signals(activity))
                    except Exception as e:
                        log.warning("partial_notes_error", account=account.name, error=str(e))
                    try:
                        contacts = await asyncio.wait_for(
                            hs.get_deal_contacts(account.hubspot_deal_id), timeout=12.0
                        )
                        raw_signals.extend(_contacts_to_signals(contacts))
                    except Exception as e:
                        log.warning("partial_contacts_error", account=account.name, error=str(e))

                current_state = _build_current_state(account)

                orchestrator = AgentOrchestrator()
                run_id = str(uuid.uuid4())
                pipeline_result = await orchestrator.run_account(
                    account_id=str(account.id),
                    account_name=account.name,
                    current_state=current_state,
                    raw_signals=raw_signals,
                    partial=True,
                )

                if not pipeline_result.success:
                    log.warning("partial_pipeline_failed", account=account.name, error=pipeline_result.error)
                    return

                # Write signals — mirrors _process_account step 4 (varchar clamps, dedup
                # omitted here because stage-change webhooks fire infrequently, not nightly).
                for sig_data in pipeline_result.signals_created:
                    sig = _build_signal(sig_data, account, run_id, self.settings.agent_push_threshold)
                    db.add(sig)

                # Update account state + scores
                updated_aso = pipeline_result.updated_aso or {}
                pov = updated_aso.get("pov", {})
                await db.execute(
                    update(Account)
                    .where(Account.id == account.id)
                    .values(
                        state=updated_aso,
                        health_score=updated_aso.get("health_score"),
                        urgency_score=updated_aso.get("urgency_score"),
                        pov_forecast_cat=pov.get("forecast_category"),
                        last_agent_run_at=datetime.now(timezone.utc),
                        agent_run_count=Account.agent_run_count + 1,
                    )
                )

                # Re-rank so this account's fresh raw score lands on the same
                # normalized scale as the rest of the portfolio
                await self._normalize_urgency_scores(db, workspace_id)

                # AgentRun record
                agent_run = AgentRun(
                    id=uuid.UUID(run_id),
                    workspace_id=uuid.UUID(workspace_id),
                    trigger=trigger_type,
                    status="completed",
                    accounts_total=1,
                    accounts_processed=1,
                    accounts_failed=0,
                    signals_detected=len(pipeline_result.signals_created),
                    drafts_created=0,
                    total_cost_usd=pipeline_result.total_cost_usd,
                    completed_at=datetime.now(timezone.utc),
                )
                db.add(agent_run)
                await db.commit()
                log.info("partial_pipeline_complete", account=account.name, trigger=trigger_type, signals=len(pipeline_result.signals_created))

            except Exception as e:
                log.error("partial_pipeline_error", workspace_id=workspace_id, deal_id=hubspot_deal_id, error=str(e), exc_info=True)

    def _make_agent_run(
        self,
        run_id: str,
        workspace_id: str,
        trigger: str,
        accounts_total: int,
    ) -> AgentRun:
        """Build an AgentRun record with all counters zeroed. trigger is 'nightly' or 'manual'."""
        return AgentRun(
            id=uuid.UUID(run_id),
            workspace_id=uuid.UUID(workspace_id),
            trigger=trigger,
            status="running",
            accounts_total=accounts_total,
            accounts_processed=0,
            accounts_failed=0,
            signals_detected=0,
            drafts_created=0,
            total_cost_usd=0.0,
        )

    async def _get_workspace_by_id(self, db, workspace_id: str) -> Workspace | None:
        result = await db.execute(select(Workspace).where(Workspace.id == uuid.UUID(workspace_id)))
        return result.scalar_one_or_none()

    async def _store_run_summary(self, account: Account, aso: dict) -> None:
        """Store a Vantage pipeline run summary as an Interaction in the local DB."""
        pov = aso.get("pov", {})
        health = aso.get("health_score") or pov.get("health_score")
        urgency = aso.get("urgency_score") or pov.get("urgency_score") or 0
        forecast = pov.get("forecast_category", "?")
        health_str = f"{health:.2f}" if health is not None else "?"

        lines = [f"Health: {health_str} | POV: {forecast} | Urgency: {urgency or 0:.0%}"]

        meddpicc = pov.get("meddpicc", {})
        gaps = meddpicc.get("gaps", []) if meddpicc else []
        if gaps:
            lines.append(f"MEDDPICC gaps: {'; '.join(gaps)}")

        top_risk = pov.get("top_risk_summary") or pov.get("health_reasoning", "")
        if top_risk:
            lines.append(f"Top risk: {top_risk}")

        next_actions = aso.get("next_actions", [])
        for action in next_actions:
            lines.append(f"Action: {action.get('action', '')} — {action.get('reason', '')}")

        self.db.add(Interaction(
            account_id=account.id,
            workspace_id=account.workspace_id,
            type="agent_run",
            source="vantage",
            notes="\n".join(lines),
            occurred_at=datetime.now(timezone.utc),
        ))
        await self.db.commit()
        log.info("run_summary_stored", account=account.name)

    async def _persist_hubspot_interactions(
        self,
        account: Account,
        raw_emails: list[dict],
        raw_engagements: list[dict],
    ) -> None:
        """
        Persist HubSpot emails and v1 engagements as Interaction records so they
        appear in the War Room activity feed (GET /v1/accounts/{id}/notes).

        Dedup: uses `outcome = 'hs:{id}'` as a soft unique key — skips any
        record already stored with that reference. Safe to re-run on every
        agent run (re-runs are no-ops for existing records).
        """
        from sqlalchemy import and_ as sql_and

        new_count = 0

        # --- v3 email objects (CRM emails: tracked sends + logged inbound) ---
        for email in raw_emails:
            email_id = email.get("id")
            if not email_id:
                continue
            hs_ref = f"hs_email:{email_id}"

            # Skip if already imported
            existing = await self.db.execute(
                select(Interaction).where(
                    sql_and(
                        Interaction.account_id == account.id,
                        Interaction.outcome == hs_ref,
                    )
                ).limit(1)
            )
            if existing.scalar_one_or_none():
                continue

            props = email.get("properties", {})
            subject = props.get("hs_email_subject") or "No subject"
            direction = (props.get("hs_email_direction") or "INCOMING_EMAIL").upper()
            from_email = props.get("hs_email_from_email") or ""
            to_email = props.get("hs_email_to_email") or ""
            body = props.get("hs_email_text") or ""
            ts_str = props.get("hs_timestamp") or props.get("hs_createdate") or ""

            occurred_at = None
            if ts_str:
                try:
                    occurred_at = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except Exception:
                    pass
            if not occurred_at:
                continue

            itype = "email_received" if "INCOMING" in direction else "email_sent"
            notes = f"Subject: {subject}"
            if body:
                notes += f"\n\n{body[:5000]}"

            self.db.add(Interaction(
                account_id=account.id,
                workspace_id=account.workspace_id,
                type=itype,
                source="hubspot",
                notes=notes,
                contact_email=from_email if itype == "email_received" else to_email,
                occurred_at=occurred_at,
                outcome=hs_ref,  # dedup key
            ))
            new_count += 1

        # --- v1 engagement objects (logged threads, calls, meetings, notes) ---
        type_map = {
            "EMAIL": "email_sent",
            "INCOMING_EMAIL": "email_received",
            "CALL": "call",
            "MEETING": "meeting",
            "NOTE": "note",
        }
        for item in raw_engagements:
            engagement = item.get("engagement", {})
            eng_id = engagement.get("id")
            if not eng_id:
                continue
            hs_ref = f"hs_eng:{eng_id}"

            eng_type = engagement.get("type", "NOTE")
            itype = type_map.get(eng_type, "note")
            metadata = item.get("metadata", {})

            existing_row = (await self.db.execute(
                select(Interaction).where(
                    sql_and(
                        Interaction.account_id == account.id,
                        Interaction.outcome == hs_ref,
                    )
                ).limit(1)
            )).scalar_one_or_none()

            # For meetings, re-import if startTime changed (stale occurred_at).
            if existing_row and eng_type == "MEETING":
                start_ms = metadata.get("startTime")
                if start_ms:
                    try:
                        scheduled_at = datetime.fromtimestamp(int(start_ms) / 1000, tz=timezone.utc)
                        if existing_row.occurred_at and abs(
                            (existing_row.occurred_at - scheduled_at).total_seconds()
                        ) > 60:
                            await self.db.delete(existing_row)
                            await self.db.flush()
                            existing_row = None
                    except Exception:
                        pass
            if existing_row:
                continue

            # Timestamp (milliseconds → datetime)
            ts_ms = engagement.get("timestamp") or engagement.get("createdAt") or 0
            occurred_at = None
            if ts_ms:
                try:
                    occurred_at = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
                except Exception:
                    pass
            if not occurred_at:
                continue

            # Build notes from metadata
            if eng_type in ("EMAIL", "INCOMING_EMAIL"):
                subject = metadata.get("subject") or "No subject"
                from_info = metadata.get("from") or {}
                from_email = from_info.get("email", "") if isinstance(from_info, dict) else str(from_info)
                body = (metadata.get("text") or metadata.get("html") or "")[:5000]
                notes = f"Subject: {subject}"
                if body:
                    notes += f"\n\n{body}"
                contact_email = from_email if eng_type == "INCOMING_EMAIL" else None
            elif eng_type == "CALL":
                title = metadata.get("title") or "Call"
                body = (metadata.get("body") or metadata.get("notes") or "")[:5000]
                notes = title
                if body:
                    notes += f"\n\n{body}"
                contact_email = None
            elif eng_type == "MEETING":
                title = metadata.get("title") or "Meeting"
                body = (metadata.get("body") or metadata.get("notes") or "")[:5000]
                outcome_status = metadata.get("meetingOutcome") or "SCHEDULED"
                # Use the actual scheduled meeting time (startTime) as occurred_at so
                # the agent sees "meeting on July 10" not "meeting booked on June 5".
                start_ms = metadata.get("startTime")
                if start_ms:
                    try:
                        occurred_at = datetime.fromtimestamp(int(start_ms) / 1000, tz=timezone.utc)
                    except Exception:
                        pass  # fall back to engagement.timestamp set above
                notes = f"[{outcome_status}] {title}"
                if body:
                    notes += f"\n\n{body}"
                contact_email = None
            else:  # NOTE
                notes = (metadata.get("body") or "")[:5000]
                contact_email = None

            if not notes.strip():
                continue  # skip empty records

            self.db.add(Interaction(
                account_id=account.id,
                workspace_id=account.workspace_id,
                type=itype,
                source="hubspot",
                notes=notes,
                contact_email=contact_email,
                occurred_at=occurred_at,
                outcome=hs_ref,  # dedup key
            ))
            new_count += 1

        if new_count > 0:
            log.info(
                "hubspot_interactions_persisted",
                account_id=str(account.id),
                account=account.name,
                new_records=new_count,
            )

    async def _compute_activity_summary(
        self,
        account_id: str,
        workspace_id: str,
        raw_emails: list[dict],
        raw_engagements: list[dict],
        fireflies_transcripts: list[dict],
    ) -> dict:
        """
        Build a precise activity timeline from HubSpot data + stored interactions.
        Gives the ResearcherAgent exact temporal context instead of estimates.
        """
        now = datetime.now(timezone.utc)

        # Parse dates from v3 email objects
        emails_sent: list[datetime] = []
        emails_received: list[datetime] = []
        for email in raw_emails:
            props = email.get("properties", {})
            ts = props.get("hs_timestamp") or props.get("hs_createdate", "")
            direction = (props.get("hs_email_direction") or "").upper()
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if "INCOMING" in direction:
                    emails_received.append(dt)
                else:
                    emails_sent.append(dt)
            except Exception:
                pass

        # Parse dates from v1 engagement records
        meetings: list[datetime] = []
        upcoming_meetings: list[dict] = []  # future-dated confirmed meetings
        calls: list[datetime] = []
        for item in raw_engagements:
            eng = item.get("engagement", {})
            eng_type = eng.get("type", "")
            metadata = item.get("metadata", {})
            if eng_type == "MEETING":
                # Prefer startTime (when the meeting is scheduled) over creation timestamp
                ts_ms = metadata.get("startTime") or eng.get("timestamp") or eng.get("createdAt") or 0
            else:
                ts_ms = eng.get("timestamp") or eng.get("createdAt") or 0
            if not ts_ms:
                continue
            try:
                dt = datetime.fromtimestamp(int(ts_ms) / 1000, tz=timezone.utc)
                if eng_type == "MEETING":
                    meetings.append(dt)
                    if dt > now:
                        outcome_status = metadata.get("meetingOutcome") or "SCHEDULED"
                        upcoming_meetings.append({
                            "date": dt.strftime("%Y-%m-%d"),
                            "title": metadata.get("title") or "Meeting",
                            "status": outcome_status,
                        })
                elif eng_type == "CALL":
                    calls.append(dt)
                elif eng_type in ("EMAIL", "INCOMING_EMAIL"):
                    if eng_type == "INCOMING_EMAIL":
                        emails_received.append(dt)
                    else:
                        emails_sent.append(dt)
            except Exception:
                pass

        # Fireflies transcript dates
        ff_dates: list[datetime] = []
        for t in (fireflies_transcripts or []):
            date_ms = t.get("date", 0)
            if date_ms:
                try:
                    ff_dates.append(datetime.fromtimestamp(date_ms / 1000, tz=timezone.utc))
                except Exception:
                    pass

        # Query historical interactions from DB (for context beyond current run's 24h window)
        import uuid as _uuid
        from sqlalchemy import select as _sel, desc as _desc
        hist = await self.db.execute(
            _sel(Interaction)
            .where(
                Interaction.account_id == _uuid.UUID(account_id),
                Interaction.workspace_id == _uuid.UUID(workspace_id),
                Interaction.occurred_at.is_not(None),
            )
            .order_by(_desc(Interaction.occurred_at))
            .limit(200)
        )
        stored = hist.scalars().all()

        # Merge stored interactions (deduplicate by date to avoid double-counting)
        def merge_dates(current: list[datetime], stored_items, types: tuple) -> list[datetime]:
            extra = [i.occurred_at for i in stored_items if i.type in types and i.occurred_at]
            combined = list({
                d.date() for d in current
            } | {
                d.date() for d in extra if d
            })
            return sorted(
                [datetime(d.year, d.month, d.day, tzinfo=timezone.utc) for d in combined],
                reverse=True,
            )

        emails_sent = merge_dates(emails_sent, stored, ("email_sent",))
        emails_received = merge_dates(emails_received, stored, ("email_received",))
        meetings = merge_dates(meetings + ff_dates, stored, ("meeting",))
        calls = merge_dates(calls, stored, ("call",))
        notes = [i.occurred_at for i in stored if i.type in ("note", "crm_note") and i.occurred_at]

        all_activity = sorted(
            [d for d in emails_sent + emails_received + meetings + calls if d],
            reverse=True,
        )

        def days_ago(dt: Optional[datetime]) -> Optional[int]:
            if not dt:
                return None
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0, (now - dt).days)

        last_sent = emails_sent[0] if emails_sent else None
        last_received = emails_received[0] if emails_received else None
        last_meeting = meetings[0] if meetings else None
        last_call = calls[0] if calls else None
        last_activity = all_activity[0] if all_activity else None
        first_contact = all_activity[-1] if all_activity else None

        # Get recent email subjects for agent context
        recent_emails = []
        for i in stored[:20]:
            if i.type in ("email_sent", "email_received") and i.occurred_at and i.notes:
                subject = i.notes.split("\n")[0].replace("Subject: ", "")[:80]
                recent_emails.append({
                    "direction": "inbound" if i.type == "email_received" else "outbound",
                    "date": i.occurred_at.strftime("%Y-%m-%d"),
                    "subject": subject,
                })

        return {
            "deal_created_at": None,  # filled from ASO if available
            "first_contact_date": first_contact.strftime("%Y-%m-%d") if first_contact else None,
            "last_meaningful_activity_date": last_activity.strftime("%Y-%m-%d") if last_activity else None,
            "last_outbound_email_date": last_sent.strftime("%Y-%m-%d") if last_sent else None,
            "last_inbound_reply_date": last_received.strftime("%Y-%m-%d") if last_received else None,
            "last_meeting_date": last_meeting.strftime("%Y-%m-%d") if last_meeting else None,
            "last_call_date": last_call.strftime("%Y-%m-%d") if last_call else None,
            "upcoming_confirmed_meetings": sorted(upcoming_meetings, key=lambda m: m["date"]),
            "days_since_last_activity": days_ago(last_activity),
            "days_since_last_inbound": days_ago(last_received),
            "days_since_last_outbound": days_ago(last_sent),
            "total_emails_sent": len(emails_sent),
            "total_emails_received": len(emails_received),
            "total_meetings": len(meetings),
            "total_calls": len(calls),
            "total_fireflies_transcripts": len(ff_dates),
            "email_exchange_count": len(emails_sent) + len(emails_received),
            "engagement_depth": (
                "deep" if len(all_activity) > 15
                else "active" if len(all_activity) > 5
                else "light" if len(all_activity) > 1
                else "none"
            ),
            "recent_email_history": recent_emails[:5],
            "notes_count": len(notes),
        }

    async def _get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        result = await self.db.execute(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        return result.scalar_one_or_none()

    async def _maybe_refresh_hubspot_token(self, ws: Workspace) -> Workspace:
        """Refresh HubSpot access token if it expires within 5 minutes."""
        if not ws.hubspot_refresh_token:
            return ws

        expires_at = ws.hubspot_token_expires_at
        if not expires_at:
            return ws

        if expires_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            return ws  # Still valid

        log.info("hubspot_token_refreshing", workspace_id=str(ws.id))
        try:
            hs = HubSpotClient(access_token="")
            tokens = await hs.refresh_token(ws.hubspot_refresh_token)
            ws.hubspot_access_token = tokens.get("access_token")
            if tokens.get("refresh_token"):
                ws.hubspot_refresh_token = tokens.get("refresh_token")
            expires_in = tokens.get("expires_in", 1800)
            ws.hubspot_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            await self.db.commit()
            log.info("hubspot_token_refreshed", workspace_id=str(ws.id))
        except Exception as e:
            log.error("hubspot_token_refresh_failed", workspace_id=str(ws.id), error=str(e))

        return ws

    async def _maybe_refresh_outlook_token(self, ws: Workspace) -> Workspace:
        """Refresh Outlook access token if expired or expiring within 10 minutes."""
        if not ws.outlook_refresh_token:
            return ws

        expires_at = ws.outlook_token_expires_at
        if expires_at:
            expires_at = expires_at.replace(tzinfo=timezone.utc) if not expires_at.tzinfo else expires_at
            if expires_at > datetime.now(timezone.utc) + timedelta(minutes=10):
                return ws  # still valid

        log.info("outlook_token_refreshing", workspace_id=str(ws.id))
        try:
            from app.integrations.outlook import refresh_access_token
            tokens = await refresh_access_token(ws.outlook_refresh_token)
            ws.outlook_access_token = tokens.get("access_token")
            expires_in = tokens.get("expires_in", 3600)
            ws.outlook_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            if tokens.get("refresh_token"):
                ws.outlook_refresh_token = tokens.get("refresh_token")
            await self.db.commit()
            log.info("outlook_token_refreshed", workspace_id=str(ws.id))
        except Exception as e:
            log.error("outlook_token_refresh_failed", workspace_id=str(ws.id), error=repr(e))

        return ws

    async def _fetch_fireflies_map(self, ws: Workspace, accounts: list) -> dict:
        """
        Fetch Fireflies transcripts ONCE at the workspace level and match to accounts.
        Uses Outlook calendar events (90 days back) for calendar-time matching (+4 score),
        then email domain (+2) and title word (+2) matching as fallbacks.
        Returns {str(account_id): [interaction_dict, ...]}
        """
        if not self.settings.fireflies_api_key or not accounts:
            return {}

        # Fetch Outlook calendar events for calendar-time matching
        calendar_events: list[dict] = []
        if ws.outlook_access_token:
            try:
                from app.integrations.outlook import OutlookClient
                ol = OutlookClient(ws.outlook_access_token)
                raw_events = await asyncio.wait_for(
                    ol.get_calendar_events(days_back=90, days_ahead=7),
                    timeout=20.0,
                )
                calendar_events = await self._link_calendar_to_accounts(raw_events, accounts)
                log.info("outlook_calendar_loaded", events=len(raw_events), linked=len(calendar_events))
            except asyncio.TimeoutError:
                log.warning("outlook_calendar_timeout")
            except Exception as e:
                log.warning("outlook_calendar_error", error=repr(e))
        else:
            log.info("outlook_calendar_skipped", reason="no_access_token")

        try:
            ff = FirefliesClient(api_key=self.settings.fireflies_api_key)
            account_dicts = [
                {
                    "id": a.id,
                    "workspace_id": a.workspace_id,
                    "name": a.name,
                    "created_at": a.created_at,
                    "close_date": a.close_date,
                }
                for a in accounts
            ]
            matched = await asyncio.wait_for(
                backfill_all_transcripts(
                    ff,
                    account_dicts,
                    limit=200,
                    calendar_events=calendar_events,
                ),
                timeout=90.0,
            )
            result: dict = {}
            for m in matched:
                aid = m["account_id"]
                # Transcript-shaped entry (id/title/action_items/speaker_stats/…).
                # The old code put the interaction dict here, so every downstream
                # .get("action_items")/.get("participants") read None.
                result.setdefault(aid, []).append(m.get("entry") or m["interaction"])
            log.info(
                "fireflies_workspace_map_built",
                accounts_matched=len(result),
                total_interactions=len(matched),
                calendar_events_used=len(calendar_events),
            )
            return result
        except asyncio.TimeoutError:
            log.warning("fireflies_workspace_backfill_timeout")
            return {}
        except Exception as e:
            log.warning("fireflies_workspace_backfill_error", error=repr(e))
            return {}

    async def _link_calendar_to_accounts(
        self, calendar_events: list[dict], accounts: list
    ) -> list[dict]:
        """
        Match Outlook calendar events to accounts by attendee email domain.
        Returns list of {account_id, occurred_at} for backfill_all_transcripts calendar index.
        """
        import re as _re
        linked = []
        for event in calendar_events:
            start_str = event.get("start")
            if not start_str:
                continue
            try:
                occurred_at = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

            attendees = event.get("attendees", [])
            subject_lower = (event.get("subject") or "").lower()

            for account in accounts:
                name = (account.name if hasattr(account, "name") else account.get("name") or "").lower()
                clean = _re.sub(
                    r"\s*[-–]\s*(new deal|pilot|phase \d+|poc|demo|renewal|expansion|follow.?up).*$",
                    "", name, flags=_re.IGNORECASE,
                ).strip()
                clean = _re.sub(r"\s*\(.*?\)", "", clean).strip()
                specific_words = {w for w in clean.split() if len(w) >= 5} - _GENERIC_WORDS

                if not specific_words:
                    continue

                matched = False
                # Check attendee email domains
                for email in attendees:
                    root = _domain_root(email)
                    if not root or root in _SELLER_DOMAINS:
                        continue
                    if any(root == w or root in w or w in root for w in specific_words):
                        matched = True
                        break
                # Also check event subject as a fallback
                if not matched and any(w in subject_lower for w in specific_words):
                    matched = True

                if matched:
                    account_id = str(account.id if hasattr(account, "id") else account.get("id"))
                    linked.append({"account_id": account_id, "occurred_at": occurred_at})

        return linked


# ── Helpers ───────────────────────────────────────────────────────────────────

def _activity_to_signals(activity: list[dict]) -> list[dict]:
    """Convert HubSpot deal notes to signal format for the agent pipeline."""
    signals = []
    for item in activity:
        props = item.get("properties", {})
        body = _html.escape(props.get("hs_note_body", "") or "")
        timestamp = (props.get("hs_timestamp") or "")[:10]
        if body:
            detail = f"Note on {timestamp}: {body}" if timestamp else body
            signals.append({
                "type": "crm_note",
                "source": "hubspot",
                "detail": detail[:2000],  # Full note body — notes are critical deal context
                "raw": item,
            })
    return signals


def _contacts_to_signals(contacts: list[dict]) -> list[dict]:
    """
    Convert HubSpot contacts to enriched signals for the agent pipeline.

    CONTRACT: each returned dict with type=="contact_details" MUST expose these
    top-level keys (Fireflies participant cross-reference reads them by name):
      "email"          — lowercase email string (used as join key against participant list)
      "contact_name"   — display name (used as fallback when participant email has no HubSpot record)
      "contact_title"  — job title (used for champion-role scoring)
    Do not rename or nest these without updating the cross-reference block in _process_account.
    """
    signals = []
    for contact in contacts:
        props = contact.get("properties", {})
        first = _html.escape((props.get("firstname") or "").strip())
        last = _html.escape((props.get("lastname") or "").strip())
        name = f"{first} {last}".strip()
        if not name:
            continue

        parts = [f"Contact: {name}"]
        if props.get("jobtitle"):
            parts.append(_html.escape(props["jobtitle"]))
        if props.get("email"):
            parts.append(f"({_html.escape(props['email'])})")

        timeline = []
        if props.get("notes_last_contacted"):
            timeline.append(f"last contacted {props['notes_last_contacted'][:10]}")
        if props.get("hs_email_last_reply_date"):
            timeline.append(f"last reply {props['hs_email_last_reply_date'][:10]}")
        if props.get("hs_email_open_date"):
            timeline.append(f"email opened {props['hs_email_open_date'][:10]}")
        if timeline:
            parts.append(f"| {', '.join(timeline)}")

        signals.append({
            "type": "contact_details",
            "source": "hubspot",
            "detail": " ".join(parts),
            # Contract keys — read by Fireflies cross-reference in _process_account
            "email": props.get("email", "").lower() if props.get("email") else "",
            "contact_name": name,
            "contact_title": props.get("jobtitle", ""),
            "raw": {k: str(v)[:500] if isinstance(v, str) and len(v) > 500 else v for k, v in props.items() if v},
        })
    return signals


def _emails_to_signals(emails: list[dict]) -> list[dict]:
    """Convert HubSpot email engagements to signals for the agent pipeline."""
    signals = []
    for email in emails:
        props = email.get("properties", {})
        subject = _html.escape(props.get("hs_email_subject") or "No subject")
        direction = _html.escape((props.get("hs_email_direction") or "").lower())
        timestamp = (props.get("hs_timestamp") or "")[:10]
        from_email = _html.escape(props.get("hs_email_from_email") or "")
        body_preview = _html.escape((props.get("hs_email_text") or "")[:1500])

        detail = f"Email ({direction}): '{subject}'"
        if timestamp:
            detail += f" on {timestamp}"
        if from_email:
            detail += f" from {from_email}"
        if body_preview:
            detail += f"\n---\n{body_preview}"

        signals.append({
            "type": "email_activity",
            "source": "hubspot",
            "detail": detail[:2000],
            "raw": {
                k: str(v)[:500] if isinstance(v, str) and len(v) > 500 else v
                for k, v in props.items()
                if k not in ("hs_email_html",)
            },
        })
    return signals


def _engagements_to_signals(engagements: list[dict]) -> list[dict]:
    """
    Convert HubSpot v1 engagement records to signals for the agent pipeline.
    Handles EMAIL (logged threads), CALL (call notes), MEETING, NOTE types.
    """
    signals = []
    type_map = {
        "EMAIL": "email_activity",
        "INCOMING_EMAIL": "email_activity",  # HubSpot uses INCOMING_EMAIL for inbound
        "CALL": "call_activity",
        "MEETING": "meeting_activity",
        "NOTE": "crm_note",
    }
    for item in engagements:
        engagement = item.get("engagement", {})
        metadata = item.get("metadata", {})
        eng_type = engagement.get("type", "NOTE")
        signal_type = type_map.get(eng_type, "crm_activity")

        # Convert millisecond timestamp to date string
        timestamp_ms = engagement.get("timestamp") or engagement.get("createdAt") or 0
        timestamp_str = ""
        if timestamp_ms:
            try:
                dt = datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=timezone.utc)
                timestamp_str = dt.strftime("%Y-%m-%d")
            except Exception:
                pass

        detail = ""
        if eng_type in ("EMAIL", "INCOMING_EMAIL"):
            subject = _html.escape(metadata.get("subject") or "No subject")
            from_info = metadata.get("from") or {}
            from_email = _html.escape(from_info.get("email", "") if isinstance(from_info, dict) else str(from_info))
            body = _html.escape((metadata.get("text") or metadata.get("html") or "")[:1500])
            direction_label = "Inbound email" if eng_type == "INCOMING_EMAIL" else "Outbound email"
            detail = f"{direction_label}: '{subject}'"
            if timestamp_str:
                detail += f" on {timestamp_str}"
            if from_email:
                detail += f" from {from_email}"
            if body:
                detail += f"\n---\n{body}"
        elif eng_type == "CALL":
            title = _html.escape(metadata.get("title") or "Call")
            notes = _html.escape((metadata.get("body") or metadata.get("notes") or "")[:1500])
            duration_ms = metadata.get("durationMilliseconds") or 0
            duration_str = f"{int(duration_ms) // 60000}min" if duration_ms else ""
            detail = f"Call: '{title}'"
            if timestamp_str:
                detail += f" on {timestamp_str}"
            if duration_str:
                detail += f" ({duration_str})"
            if notes:
                detail += f"\n---\n{notes}"
        elif eng_type == "MEETING":
            title = _html.escape(metadata.get("title") or "Meeting")
            notes = _html.escape((metadata.get("body") or metadata.get("notes") or "")[:1500])
            detail = f"Meeting: '{title}'"
            if timestamp_str:
                detail += f" on {timestamp_str}"
            if notes:
                detail += f"\n---\n{notes}"
        else:  # NOTE
            body = _html.escape((metadata.get("body") or "")[:2000])
            detail = f"Note on {timestamp_str}: {body}" if body else ""

        if detail:
            signals.append({
                "type": signal_type,
                "source": "hubspot",
                "detail": detail[:600],
                # Strip large text/html bodies from raw — keep only metadata fields
                "raw": {k: v for k, v in metadata.items() if k not in ("text", "html", "body") or not v or len(str(v)) < 500},
            })
    return signals


def _company_to_signals(company: Optional[dict]) -> list[dict]:
    """Convert HubSpot company data to context signals for the agent pipeline."""
    if not company:
        return []

    def _q(v: str) -> str:
        return _html.escape(str(v))

    props = company.get("properties", {})

    parts = []
    name = props.get("name") or ""
    if name:
        parts.append(f"Company: {_q(name)}")
    if props.get("domain"):
        parts.append(f"({_q(props['domain'])})")
    if props.get("industry"):
        parts.append(f"| Industry: {_q(props['industry'])}")
    if props.get("annualrevenue"):
        try:
            rev = float(props["annualrevenue"])
            parts.append(f"| Revenue: ${rev:,.0f}")
        except (ValueError, TypeError):
            pass
    if props.get("numberofemployees"):
        parts.append(f"| Employees: {_q(str(props['numberofemployees']))}")
    if props.get("country"):
        loc = _q(props["country"])
        if props.get("city"):
            loc = f"{_q(props['city'])}, {loc}"
        parts.append(f"| Location: {loc}")
    if props.get("description"):
        parts.append(f"| {_q(props['description'][:200])}")

    if not parts:
        return []

    return [{
        "type": "company_info",
        "source": "hubspot",
        "detail": " ".join(parts)[:600],
        "raw": {k: v for k, v in props.items() if v},
    }]


def _get_rep_bandwidth(ws: Workspace) -> str:
    """Read rep bandwidth setting from workspace settings."""
    settings = ws.settings or {}
    return settings.get("rep_bandwidth", "normal")  # low | normal | high


def _decay_engagement_levels(stakeholders: list[dict]) -> list[dict]:
    """
    Auto-downgrade stakeholder engagement_level based on days since last_contact_date.
    Prevents stale 'engaged' labels on contacts who have been dark for months.
      >60 days without contact → dark
      >30 days without contact → passive (if currently highly_engaged or engaged)
    Adds a risk_flag like 'dark_91_days' for the researcher to pick up.
    """
    now = datetime.now(timezone.utc)
    for s in stakeholders:
        last = s.get("last_contact_date")
        if not last:
            continue
        try:
            last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            days_dark = (now - last_dt).days
        except (ValueError, TypeError):
            continue

        current_level = s.get("engagement_level", "unknown")
        if days_dark >= 60 and current_level not in ("dark", "unknown"):
            s["engagement_level"] = "dark"
            flags = s.setdefault("risk_flags", [])
            flag = f"dark_{days_dark}_days"
            if not any(f.startswith("dark_") for f in flags):
                flags.append(flag)
        elif days_dark >= 30 and current_level in ("highly_engaged", "engaged"):
            s["engagement_level"] = "passive"
    return stakeholders


def _risk_to_str(r) -> str:
    """Safely convert a risk to a string — handles both str and dict formats."""
    if isinstance(r, dict):
        return r.get("description", "") or r.get("detail", "") or str(r)
    return str(r)


def _aso_to_search_text(account_name: str, aso: dict) -> str:
    """Convert ASO to a text blob for embedding (semantic search index)."""
    parts = [f"Account: {account_name}"]

    pov = aso.get("pov", {})
    if pov:
        parts.append(f"Forecast: {pov.get('forecast_category', '')}")
        risks = pov.get("risks", [])
        if risks:
            parts.append(f"Risks: {', '.join(_risk_to_str(r) for r in risks[:3])}")

    signals = aso.get("signals", [])
    for sig in signals[:5]:
        if sig.get("detail"):
            parts.append(sig["detail"][:200])

    next_actions = aso.get("next_actions", [])
    for action in next_actions[:3]:
        if action.get("action"):
            parts.append(action["action"])

    summary = aso.get("account_summary", "")
    if summary:
        parts.append(summary[:500])

    return "\n".join(parts)
