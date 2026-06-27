"""
AgentOrchestrator — Runs the full 6-agent pipeline for one account.
Manages: agent sequencing, error recovery, cost tracking, ASO update.

Pipeline:
  [1] ResearcherAgent (Haiku) → ResearchResult
  [2] RiskScannerAgent (Haiku) → RiskResult
  [3] GroundingAgent (Haiku) → GroundingResult   ← GA from Day 1
  [4] PrioritiserAgent (Sonnet) → PrioritiserResult
  [5] DrafterAgent (Sonnet) → DrafterResult       ← Only for urgency > threshold
  [6] StateWriter → updated ASO → PostgreSQL

Total cost: ~$0.22/account/night
"""
import uuid
from collections import Counter
from datetime import datetime, timezone
import structlog
from app.integrations.llm import bulk_model, quality_model

from app.agents.base import (
    compute_win_probability,
    compute_urgency_score,
    compute_forecast_confidence,
    normalize_stakeholder_name,
    reconcile_forecast_category,
    DrafterResult,
)
# Rep-facing prose polish — shared with the drafter/plays paths
from app.agents.drafter import polish_prose as _humanize_prose
from app.agents.researcher import ResearcherAgent
from app.agents.risk_scanner import RiskScannerAgent
from app.agents.grounding import GroundingAgent
from app.agents.prioritiser import PrioritiserAgent
from app.agents.drafter import DrafterAgent
from app.agents.smart_fields import SmartFieldsAgent
from app.config import get_settings

log = structlog.get_logger()

# Health delta that constitutes a meaningful trend movement (not noise)
_HEALTH_TREND_THRESHOLD = 0.03
# Max draft confidence = health_score + this buffer (prevents over-confident drafts on sick deals)
_CONF_HEALTH_BUFFER = 0.25
# Forecast history cap — ~3 months of weekly runs
_FORECAST_HISTORY_CAP = 12
# Draft types that are internal deliverables (close plan, renewal, competitive brief, meeting brief).
# These are never suppressed by the zero-verified-signals gate — they don't assert CRM facts
# as outbound claims, so they carry no hallucination risk that verified signals would mitigate.
_INTERNAL_DRAFT_TYPES = {"close_plan_proposal", "renewal_brief", "competitive_displacement", "meeting_brief"}


def _draft_type(d) -> str:
    """Extract draft type from either a DraftItem object or a dict."""
    return d.type if hasattr(d, "type") else d.get("type", "")


def _accumulate_costs(result: "PipelineResult", agents: list) -> None:
    """Sum token + cost counters from a list of agents into result in-place."""
    result.total_cost_usd = sum(a.total_cost_usd for a in agents)
    result.total_input_tokens = sum(a.total_input_tokens for a in agents)
    result.total_output_tokens = sum(a.total_output_tokens for a in agents)


def _upsert_stakeholder(index: dict, name_raw: str, fields: dict) -> None:
    """
    Normalize name and merge fields into the keyed stakeholder index.
    Invalid names (artifacts) are silently dropped — normalization is the only
    place that can self-heal already-stored artifacts like "Only Derick Sim".
    """
    clean = normalize_stakeholder_name(name_raw)
    if clean is None:
        log.info("stakeholder_artifact_dropped", name=name_raw)
        return
    key = clean.casefold()
    if key in index:
        index[key].update({k: v for k, v in fields.items() if v is not None and k != "name"})
    else:
        index[key] = {**fields, "name": clean}


def _count_three_whys(risk_result) -> int:
    """Count how many of the three whys are confirmed present in a RiskResult."""
    return sum(
        1 for v in (risk_result.three_whys_assessment or {}).values()
        if isinstance(v, dict) and v.get("present")
    )


def _signal_to_dict(s, run_id: str) -> dict:
    """
    Flatten a signal object to the DB insertion shape.
    Fields match the Signal ORM model columns exactly — any rename here breaks the insert.
    """
    return {
        "type": s.type,
        "urgency": s.urgency,
        "urgency_score": s.urgency_score,
        "detail": s.detail,
        "source": s.source,
        "source_url": s.source_url,
        "confidence": s.confidence,
        "gold_sources": s.gold_sources,
        "gold_resolution": s.gold_resolution,
        "agent_run_id": run_id,
    }


def _apply_draft_gate(
    drafter_result: "DrafterResult",
    suppressed_types: set,
    reason: str,
    account_name: str,
    log_level: str = "info",
) -> "DrafterResult":
    """
    Remove drafts of suppressed_types from drafter_result and append reason to notes.
    Returns the original result unchanged if no drafts were suppressed.
    """
    filtered = [d for d in drafter_result.drafts if _draft_type(d) not in suppressed_types]
    if len(filtered) == len(drafter_result.drafts):
        return drafter_result
    getattr(log, log_level)("draft_gate_applied", account=account_name, reason=reason,
                            suppressed=len(drafter_result.drafts) - len(filtered))
    return DrafterResult(
        drafts=filtered,
        drafting_notes=drafter_result.drafting_notes + f" [{reason}]",
    )


class PipelineResult:
    """Full result from one account pipeline run."""
    def __init__(self):
        self.success = False
        self.error = None
        self.updated_aso = {}
        self.signals_created = []
        self.drafts_created = []
        self.resolved_signals: list[str] = []   # signal types the researcher marked resolved
        self.total_cost_usd = 0.0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.stages_completed = []


class AgentOrchestrator:
    """
    Runs the full agent pipeline for a single account.
    Called by the nightly worker and by the webhook event processor.
    """

    def __init__(self):
        self.settings = get_settings()

    async def run_account(
        self,
        account_id: str,
        account_name: str,
        current_state: dict,
        raw_signals: list[dict],
        gong_transcripts: list[dict] = None,
        news_content: str = "",
        rep_bandwidth: float = 1.0,
        seller_context: dict | None = None,
        partial: bool = False,
        decline_patterns: dict | None = None,
    ) -> PipelineResult:
        """
        Full pipeline execution for one account.
        Returns PipelineResult with updated ASO, signals, and drafts.
        """
        result = PipelineResult()
        run_id = str(uuid.uuid4())

        log.info("pipeline_start", account_id=account_id, account=account_name, run_id=run_id)

        seller_context = seller_context or {}
        icp = seller_context.get("icp_profile") or {}

        # If workspace has configured ICP, inject it into seller_context for agents
        if icp.get("product_name") and icp.get("product_description"):
            seller_context = {
                **seller_context,
                "product_description": icp.get("product_description", seller_context.get("product_description", "")),
                "icp_differentiators": icp.get("differentiators", []),
                "icp_competitors": icp.get("competitors", []),
                "icp_reference_stories": icp.get("reference_stories", []),
                "icp_ideal_customer": icp.get("ideal_customer", ""),
                "icp_pain_points": icp.get("pain_points", []),
            }
        else:
            # Placeholder defaults — workspace should configure product context in Settings
            _AGENT_DEFAULTS = {
                "sender_name": "Your Name",
                "sender_title": "Account Executive",
                "sender_company": "Your Company",
                "product_description": "Configure your product description in Settings → Workspace.",
            }
            seller_context = {**_AGENT_DEFAULTS, **{k: v for k, v in seller_context.items() if v}}

        # Initialise agents
        bulk = bulk_model()
        quality = quality_model()

        researcher = ResearcherAgent(bulk)
        risk_scanner = RiskScannerAgent(bulk)
        grounding = GroundingAgent(bulk)
        prioritiser = PrioritiserAgent(quality)
        drafter = DrafterAgent(quality)
        smart_fields = SmartFieldsAgent(bulk)

        try:
            # [1] RESEARCHER
            log.info("stage_start", stage="researcher", account=account_name)
            research_result = await researcher.run(
                account_name=account_name,
                current_state=current_state,
                raw_signals=raw_signals,
                gong_transcripts=gong_transcripts,
                news_content=news_content,
                workspace_settings=seller_context or {},
            )
            result.stages_completed.append("researcher")
            result.resolved_signals = list(research_result.resolved_signals or [])
            if result.resolved_signals:
                log.info("researcher_resolved_signals", account=account_name,
                         resolved=result.resolved_signals)

            # [2] RISK SCANNER
            log.info("stage_start", stage="risk_scanner", account=account_name)
            risk_result = await risk_scanner.run(
                account_name=account_name,
                current_state=current_state,
                research_result=research_result,
            )
            result.stages_completed.append("risk_scanner")

            # Partial run: Researcher + RiskScanner only (webhook stage-change trigger)
            if partial:
                _partial_win_prob = compute_win_probability(
                    meddpicc_overall=risk_result.meddpicc.overall_score if risk_result.meddpicc else 0.3,
                    champion_risk=risk_result.champion_risk or "medium",
                    competition_risk=risk_result.competition_risk or "medium",
                    deal_momentum=risk_result.deal_momentum or "neutral",
                    three_whys_present=_count_three_whys(risk_result),
                    close_date_integrity=risk_result.close_date_integrity or "unknown",
                )
                updated_aso = {
                    **current_state,
                    "health_score": risk_result.health_score,
                    "health_trend": current_state.get("health_trend", "stable"),
                    # RiskResult has no urgency_score (the old attribute access
                    # crashed every partial run) — blend from what this stage knows.
                    "urgency_score": compute_urgency_score(
                        llm_urgency=current_state.get("urgency_score") or 0.5,
                        max_signal_urgency=max(
                            (s.urgency_score for s in research_result.new_signals),
                            default=0.0,
                        ),
                        deal_momentum=risk_result.deal_momentum or "neutral",
                        close_date=current_state.get("close_date"),
                        stage=current_state.get("stage"),
                    ),
                    "pov": {
                        **(current_state.get("pov") or {}),
                        "forecast_category": reconcile_forecast_category(
                            llm_category=risk_result.pov_forecast_category,
                            win_probability=_partial_win_prob,
                            deal_amount=current_state.get("deal_amount"),
                        ),
                        "deal_momentum": risk_result.deal_momentum,
                        "health_score": risk_result.health_score,
                        "win_probability": _partial_win_prob,
                    },
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "partial_run": True,
                }
                result.signals_created = [
                    _signal_to_dict(s, run_id) for s in research_result.new_signals
                ]
                result.drafts_created = []
                _accumulate_costs(result, [researcher, risk_scanner])
                result.updated_aso = updated_aso
                result.success = True
                log.info("partial_pipeline_complete", account=account_name, cost_usd=round(result.total_cost_usd, 4))
                return result

            # [3] GROUNDING AGENT (GA from day 1 — not beta)
            log.info("stage_start", stage="grounding", account=account_name)
            grounding_result = await grounding.run(
                account_name=account_name,
                current_state=current_state,
                research_result=research_result,
                risk_result=risk_result,
            )
            result.stages_completed.append("grounding")

            # [4] PRIORITISER
            log.info("stage_start", stage="prioritiser", account=account_name)
            prioritiser_result = await prioritiser.run(
                account_name=account_name,
                current_state=current_state,
                grounding_result=grounding_result,
                risk_result=risk_result,
                rep_bandwidth=rep_bandwidth,
            )
            result.stages_completed.append("prioritiser")

            # [5] DRAFTER (only if actions recommend drafts)
            log.info("stage_start", stage="drafter", account=account_name)

            # Fix 2: Strip sender from stakeholder list before drafter sees it.
            # Prevents self-addressed drafts (e.g. drafter writing emails to "Vishnu Saran").
            sender_name_lower = (seller_context or {}).get("sender_name", "").lower()
            if sender_name_lower and current_state.get("stakeholders"):
                current_state = {
                    **current_state,
                    "stakeholders": [
                        s for s in current_state["stakeholders"]
                        if s.get("name", "").lower() != sender_name_lower
                    ],
                }

            drafter_result = await drafter.run(
                account_name=account_name,
                current_state=current_state,
                prioritiser_result=prioritiser_result,
                grounding_result=grounding_result,
                risk_result=risk_result,
                seller_context=seller_context,
                decline_patterns=decline_patterns,
            )
            result.stages_completed.append("drafter")

            # ── Post-drafter safety gates ──────────────────────────────────────
            # These are code-enforced, not prompt-enforced. Order matters.

            # Fix 1: Hard cap at 2 drafts. Prompt rule alone is ignored by the model.
            if len(drafter_result.drafts) > 2:
                log.warning("draft_cap_enforced", account=account_name, original_count=len(drafter_result.drafts))
                drafter_result = DrafterResult(
                    drafts=drafter_result.drafts[:2],
                    drafting_notes=drafter_result.drafting_notes + " [truncated to 2]",
                )

            # Fix 3: No outbound drafts when there are 0 verified signals.
            # Zero signals means the grounding agent had nothing to verify — outbound emails
            # built on unverified intelligence are hallucination risks.
            has_verified_signals = len(grounding_result.verified_signals) > 0
            if not has_verified_signals:
                _all_types = {_draft_type(d) for d in drafter_result.drafts}
                _outbound_types = _all_types - _INTERNAL_DRAFT_TYPES
                if _outbound_types:
                    drafter_result = _apply_draft_gate(
                        drafter_result, _outbound_types,
                        "outbound drafts suppressed: 0 verified signals",
                        account_name, log_level="warning",
                    )

            # Fix 4: Block champion_reengagement when no champion has ever been identified.
            # champion_reengagement requires a prior relationship — you cannot reengage someone
            # you have never engaged. MEDDPICC champion < 0.2 means no meaningful champion exists.
            champion_meddpicc = (risk_result.meddpicc.champion if risk_result.meddpicc else 0.0) or 0.0
            if champion_meddpicc < 0.2:
                drafter_result = _apply_draft_gate(
                    drafter_result, {"champion_reengagement"},
                    f"champion_reengagement blocked: champion MEDDPICC={champion_meddpicc:.2f}",
                    account_name,
                )

            # Fix 5: Block ROI / exec-alignment drafts when the account has never replied.
            # Sending an ROI model or exec email before a single inbound reply is a
            # Discovery-stage anti-pattern that treats unverified assumptions as confirmed facts.
            _inbound_replies = int((current_state.get("activity_summary") or {}).get("total_emails_received", 0) or 0)
            _REQUIRES_REPLY = {"roi_business_case", "executive_alignment"}
            if _inbound_replies == 0:
                drafter_result = _apply_draft_gate(
                    drafter_result, _REQUIRES_REPLY,
                    "roi/exec drafts suppressed: 0 inbound replies",
                    account_name,
                )

            # [6] STATE WRITER — merge all outputs into updated ASO
            log.info("stage_start", stage="state_writer", account=account_name)
            updated_aso = self._build_updated_aso(
                current_state=current_state,
                research_result=research_result,
                risk_result=risk_result,
                grounding_result=grounding_result,
                prioritiser_result=prioritiser_result,
                drafter_result=drafter_result,
                run_id=run_id,
            )
            result.stages_completed.append("state_writer")

            # [7] SMART FIELDS — surface HubSpot field update suggestions
            log.info("stage_start", stage="smart_fields", account=account_name)
            smart_fields_result = await smart_fields.run(
                account_name=account_name,
                current_state=current_state,
                risk_result=risk_result,
                prioritiser_result=prioritiser_result,
                grounding_result=grounding_result,
                research_result=research_result,
            )
            result.stages_completed.append("smart_fields")

            # Merge smart field suggestions into ASO — preserve existing applied/dismissed
            existing_suggestions = current_state.get("smart_fields", [])
            existing_by_field = {
                s["field_name"]: s for s in existing_suggestions
                if s.get("status") in ("applied", "dismissed")
            }
            new_suggestions = []
            for suggestion in smart_fields_result.suggestions:
                # Don't re-suggest recently applied/dismissed fields
                if suggestion.field_name not in existing_by_field:
                    s_dict = suggestion.model_dump()
                    # Rep-facing prose: humanize ISO dates, strip dash tells.
                    # (The suggested VALUE stays machine-format — it goes to HubSpot.)
                    if s_dict.get("reason"):
                        s_dict["reason"] = _humanize_prose(s_dict["reason"])
                    new_suggestions.append({
                        **s_dict,
                        "status": "pending",
                        "generated_at": updated_aso["last_updated"],
                        "run_id": run_id,
                    })
            # Keep applied/dismissed history (last 20) + new pending suggestions
            retained_history = list(existing_by_field.values())[-20:]
            updated_aso["smart_fields"] = retained_history + new_suggestions

            # Build signals list for DB insertion
            result.signals_created = [
                _signal_to_dict(s, run_id) for s in grounding_result.verified_signals
            ]

            # Build drafts list for DB insertion
            # Fix 6: Cap draft confidence by deal health + buffer.
            # A draft on a 0.06-health account cannot credibly be 0.88 confident —
            # the ceiling ensures reps see honest signal-to-noise before approving.
            _health = risk_result.health_score or 0.5
            _max_conf = min(0.95, _health + _CONF_HEALTH_BUFFER)
            result.drafts_created = [
                {
                    "type": d.type,
                    "content": d.content,
                    "subject_line": d.subject_line,
                    "target_contact": d.target_contact,
                    "sources_cited": d.sources_cited,
                    "confidence": round(min(getattr(d, "confidence", 0.8) or 0.8, _max_conf), 2),
                    "agent_run_id": run_id,
                }
                for d in drafter_result.drafts
            ]

            # Aggregate costs
            agents = [researcher, risk_scanner, grounding, prioritiser, drafter, smart_fields]
            _accumulate_costs(result, agents)

            # Data quality: surface any lossy LLM-output fallbacks on the ASO.
            # A flagged account means scores in this run are partially defaulted
            # and should be reviewed, not trusted.
            fallback_warnings = [
                f"{a.__class__.__name__}: {w}" for a in agents for w in a.parse_warnings
            ]
            updated_aso["data_quality"] = {
                "fallback_applied": bool(fallback_warnings),
                "warnings": fallback_warnings[:20],
                "flagged_run_id": run_id if fallback_warnings else None,
            }
            if fallback_warnings:
                log.warning(
                    "pipeline_fallbacks_flagged",
                    account=account_name,
                    count=len(fallback_warnings),
                    warnings=fallback_warnings[:5],
                )

            result.updated_aso = updated_aso
            result.success = True

            log.info(
                "pipeline_complete",
                account_id=account_id,
                account=account_name,
                stages=result.stages_completed,
                signals=len(result.signals_created),
                drafts=len(result.drafts_created),
                cost_usd=round(result.total_cost_usd, 4),
            )

        except Exception as e:
            result.success = False
            result.error = str(e)
            log.error(
                "pipeline_failed",
                account_id=account_id,
                account=account_name,
                stage=result.stages_completed[-1] if result.stages_completed else "init",
                error=str(e),
                exc_info=True,
            )

        return result

    def _build_updated_aso(
        self,
        current_state: dict,
        research_result,
        risk_result,
        grounding_result,
        prioritiser_result,
        drafter_result,
        run_id: str,
    ) -> dict:
        """
        Merges all agent outputs into the updated Account State Object.
        This is the canonical state that powers every surface.
        """
        now = datetime.now(timezone.utc).isoformat()

        # Merge stakeholder updates — keyed by normalized name so artifact
        # variants ("Only Derick Sim") merge into the real person instead of
        # appearing as a second contact. Invalid names are dropped entirely,
        # which also self-heals artifacts already stored in the ASO.
        existing_stakeholders: dict = {}
        for s in current_state.get("stakeholders", []):
            _upsert_stakeholder(existing_stakeholders, s.get("name", ""), s)
        for update in research_result.updated_stakeholders:
            _upsert_stakeholder(existing_stakeholders, update.name, update.model_dump())

        # Win probability — deterministic formula, fully auditable
        win_probability = compute_win_probability(
            meddpicc_overall=risk_result.meddpicc.overall_score if risk_result.meddpicc else 0.3,
            champion_risk=risk_result.champion_risk or "medium",
            competition_risk=risk_result.competition_risk or "medium",
            deal_momentum=risk_result.deal_momentum or "neutral",
            three_whys_present=_count_three_whys(risk_result),
            close_date_integrity=risk_result.close_date_integrity or "unknown",
        )

        # Reconcile the LLM category against the win-probability band + $0 gate
        forecast_category = reconcile_forecast_category(
            llm_category=risk_result.pov_forecast_category,
            win_probability=win_probability,
            deal_amount=current_state.get("deal_amount"),
        )
        if forecast_category != risk_result.pov_forecast_category:
            log.info(
                "forecast_category_reconciled",
                llm_category=risk_result.pov_forecast_category,
                final_category=forecast_category,
                win_probability=win_probability,
            )

        # Confidence is derived, not self-reported — LLM value kept for audit
        forecast_confidence = compute_forecast_confidence(
            verified_signal_count=len(grounding_result.verified_signals or []),
            days_since_activity=risk_result.days_since_meaningful_activity,
            win_probability=win_probability,
        )

        pov = self._build_pov(
            current_state=current_state,
            risk_result=risk_result,
            prioritiser_result=prioritiser_result,
            grounding_result=grounding_result,
            win_probability=win_probability,
            forecast_category=forecast_category,
            forecast_confidence=forecast_confidence,
            now=now,
        )

        updated_episodes, compressed_facts, health_trend = self._update_memory(
            current_state=current_state,
            risk_result=risk_result,
            grounding_result=grounding_result,
            drafter_result=drafter_result,
            research_result=research_result,
            now=now,
        )

        # Build gold_data section (audit-visible resolved facts)
        # Use mode="json" to ensure all nested values (including Any-typed fields) are
        # JSON-serializable primitives before this dict reaches PostgreSQL JSONB.
        gold_data = current_state.get("gold_data", {})
        for key, point in grounding_result.gold_data_points.items():
            gold_data[key] = point.model_dump(mode="json")

        return {
            # Core identity (from current state)
            "account_id": current_state.get("account_id"),
            "name": current_state.get("name"),
            "stage": current_state.get("stage"),
            "deal_amount": current_state.get("deal_amount"),
            "close_date": current_state.get("close_date"),

            # ── CRM sync fields — set by HubSpot sync, must survive agent runs ──
            # These are NEVER generated by the AI pipeline; they come from the CRM.
            # Without this carry-forward, the nightly state=aso write wipes them out.
            "contact_ids":           current_state.get("contact_ids", []),
            "company_ids":           current_state.get("company_ids", []),
            "crm_forecast_category": current_state.get("crm_forecast_category"),
            "last_contacted":        current_state.get("last_contacted"),
            "next_activity":         current_state.get("next_activity"),
            # account_type: "customer" for closed-won, "prospect" for active pipeline
            # Drives CS/AM vs new-logo play routing in PlaysEngine
            "account_type":          current_state.get("account_type", "prospect"),
            # Activity timeline — computed by NightlyWorker from HubSpot + interactions DB
            "activity_summary":      current_state.get("activity_summary", {}),
            # HubSpot deal creation date — set by sync, carried forward across runs
            "deal_created_at":       current_state.get("deal_created_at"),
            # Fireflies call data — written at ingest (webhook + nightly), never by
            # the AI pipeline. Missing from this allowlist, every full run wiped them.
            "transcripts":           current_state.get("transcripts", []),
            "conversation_intel":    current_state.get("conversation_intel", {}),

            # Agent-maintained fields
            "last_updated": now,
            "last_run_id": run_id,
            "health_score": risk_result.health_score,
            "health_trend": health_trend,
            # Deterministic blend — LLM urgency anchors but cannot saturate the
            # score without corroborating signal/close-date/momentum evidence.
            "urgency_score": compute_urgency_score(
                llm_urgency=prioritiser_result.urgency_score,
                max_signal_urgency=max(
                    (s.urgency_score for s in grounding_result.verified_signals),
                    default=0.0,
                ),
                deal_momentum=risk_result.deal_momentum,
                close_date=current_state.get("close_date"),
                stage=current_state.get("stage"),
            ),

            # Summary (agent's narrative on this account)
            "summary": self._update_summary(
                current_state.get("summary", ""),
                research_result.account_summary_delta,
                research_result.key_facts_extracted,
            ),

            # Stakeholders (merged)
            "stakeholders": list(existing_stakeholders.values()),

            # Latest signals (verified only — unverified flagged separately)
            "signals": [s.model_dump() for s in grounding_result.verified_signals],
            "unverified_signals": grounding_result.unverified_claims,

            # AI Point of View
            "pov": pov,

            # Per-run forecast snapshots — powers week-over-week deltas.
            "forecast_history": (
                current_state.get("forecast_history", [])
                + [{
                    "date": now,
                    "category": forecast_category,
                    "win_probability": win_probability,
                    "health_score": risk_result.health_score,
                }]
            )[-_FORECAST_HISTORY_CAP:],

            # Next actions (prioritised — MEDDPICC-driven)
            "next_actions": [a.model_dump() for a in prioritiser_result.next_actions],
            "pipeline_review_ready": prioritiser_result.pipeline_review_ready,
            "top_risk_summary": _humanize_prose(prioritiser_result.top_risk_summary),

            # Latest drafts (pending review)
            "drafts": {
                d.type: {
                    "content": d.content,
                    "subject_line": d.subject_line,
                    "sources_cited": d.sources_cited,
                    "confidence": d.confidence,
                }
                for d in drafter_result.drafts
            },

            # Memory (semantic + procedural + episodic)
            "memory": {
                "semantic": compressed_facts,
                "procedural": current_state.get("memory", {}).get("procedural", []),
                "episodic": updated_episodes,
            },

            # Gold Data Layer — full audit trail (shown in Audit Panel)
            "gold_data": gold_data,
            "grounding_confidence": grounding_result.overall_confidence,
            "grounding_summary": grounding_result.verification_summary,

            # Source citations
            "sources_cited": list({
                s.source for s in grounding_result.verified_signals if s.source
            }),

            # ICP score (from ResearcherAgent)
            "icp_score": research_result.icp_score.model_dump() if research_result.icp_score else None,

            # Custom AI fields extracted (workspace-defined)
            "ai_fields_extracted": research_result.ai_fields_extracted or {},
        }

    def _build_pov(
        self,
        current_state: dict,
        risk_result,
        prioritiser_result,
        grounding_result,
        win_probability: float,
        forecast_category: str,
        forecast_confidence: float,
        now: str,
    ) -> dict:
        """
        Assemble the AI Point of View object from risk + prioritiser outputs.
        Kept separate from the main ASO assembly so each score source is traceable.
        """
        return {
            "forecast_category": forecast_category,
            "forecast_confidence": forecast_confidence,
            "forecast_confidence_llm": risk_result.pov_forecast_confidence,
            "signals": risk_result.pov_signals,
            "risks": [_humanize_prose(r) if isinstance(r, str) else r for r in risk_result.pov_risks],
            "commit_explanation": _humanize_prose(risk_result.pov_commit_explanation),
            "forecast_explanation": _humanize_prose(risk_result.pov_forecast_explanation),
            "pov_amount": prioritiser_result.pov_amount,      # Sonnet: more reliable than Haiku
            "pov_close_date": prioritiser_result.pov_close_date,
            "health_score": risk_result.health_score,
            "health_score_delta": risk_result.health_score_delta,
            "health_reasoning": _humanize_prose(risk_result.health_reasoning),
            "last_updated": now,

            # MEDDPICC framework scores — preserve existing state if agent returned defaults
            # (gpt-4o-mini returns {} for complex schemas at high context; overall_score=0.24
            # is the computed default from all-minimum component values)
            "meddpicc": (
                risk_result.meddpicc.model_dump()
                if risk_result.meddpicc and round(risk_result.meddpicc.overall_score, 2) != 0.24
                else current_state.get("pov", {}).get("meddpicc") or (risk_result.meddpicc.model_dump() if risk_result.meddpicc else None)
            ),
            "qualification_score": risk_result.qualification_score,

            # 5 risk vectors
            "risk_vectors": {
                "champion":    risk_result.champion_risk,
                "competition": risk_result.competition_risk,
                "timeline":    risk_result.timeline_risk,
                "economic":    risk_result.economic_risk,
                "stakeholder": risk_result.stakeholder_risk,
            },

            # Deal velocity
            "deal_momentum": risk_result.deal_momentum,
            "close_date_integrity": risk_result.close_date_integrity,
            # Deterministic CRM/calendar fact wins over the LLM's number — the
            # model once wrote "151" while its own context said "2 days"
            # (champion email silence projected onto the whole deal).
            "days_since_meaningful_activity": (
                _crm_days
                if (_crm_days := (current_state.get("activity_summary") or {}).get("days_since_last_activity")) is not None
                else risk_result.days_since_meaningful_activity
            ),

            # 3 Whys — fall through to existing state if agent returned nothing
            "three_whys": (
                risk_result.three_whys_assessment
                or (risk_result.meddpicc.three_whys if risk_result.meddpicc else None)
                or current_state.get("pov", {}).get("three_whys")
            ),

            # Win probability — deterministic formula, fully auditable
            "win_probability": win_probability,

            # Flowing narrative — preserve existing if agent returned empty
            "deal_narrative": (
                _humanize_prose(risk_result.deal_narrative)
                or current_state.get("pov", {}).get("deal_narrative", "")
            ),
            "signal_themes": risk_result.signal_themes,

            # Top risk as a single sentence (for morning brief)
            "top_risk_summary": _humanize_prose(prioritiser_result.top_risk_summary),
            "pipeline_review_ready": prioritiser_result.pipeline_review_ready,
            "forecast_rationale": _humanize_prose(
                risk_result.pov_forecast_explanation
                or risk_result.pov_commit_explanation
                or risk_result.deal_narrative
            ),
        }

    def _update_memory(
        self,
        current_state: dict,
        risk_result,
        grounding_result,
        drafter_result,
        research_result,
        now: str,
    ) -> tuple[list, dict, str]:
        """
        Build the new episodic memory entry, compress if over the 20-entry window,
        and derive the health trend. Returns (updated_episodes, compressed_facts, health_trend).
        """
        def _safe_score(v) -> float | None:
            if v is None:
                return None
            try:
                f = float(v)
                return round(max(0.0, min(1.0, f)), 4)
            except (TypeError, ValueError):
                return None

        new_episode = {
            "date": now[:10],
            "event": "agent_run",
            "signals_detected": max(0, int(len(grounding_result.verified_signals))),
            "drafts_created": max(0, int(len(drafter_result.drafts))),
            "health_score": _safe_score(risk_result.health_score),
            "deal_momentum": str(risk_result.deal_momentum)[:50] if risk_result.deal_momentum else None,
            "meddpicc_score": _safe_score(risk_result.meddpicc.overall_score) if risk_result.meddpicc else None,
            "meddpicc_gaps": [str(g)[:100] for g in (risk_result.meddpicc.gaps[:3] if risk_result.meddpicc else [])],
            "pov_category": str(risk_result.pov_forecast_category)[:50] if risk_result.pov_forecast_category else None,
            "top_risks": [str(risk_result.champion_risk)[:100], str(risk_result.competition_risk)[:100]],
            "key_changes": str(research_result.account_summary_delta)[:200] if research_result.account_summary_delta else "",
        }

        existing_episodes = current_state.get("memory", {}).get("episodic", [])
        all_episodes = existing_episodes + [new_episode]

        # If episodic memory exceeds 20, compress the oldest episodes into semantic facts
        # so institutional knowledge is never lost (Actively AI "Canvas SSOT" pattern)
        compressed_facts = current_state.get("memory", {}).get("semantic", {})
        if len(all_episodes) > 20:
            to_compress = all_episodes[:-20]  # all but the 20 most recent
            updated_episodes = all_episodes[-20:]
            if to_compress:
                compressed_facts = self._compress_episodes(to_compress, compressed_facts)
        else:
            updated_episodes = all_episodes

        # Compute health trend from episodic memory
        prev_health_scores = [
            ep.get("health_score") for ep in updated_episodes[-3:-1]
            if ep.get("health_score") is not None
        ]
        current_health = risk_result.health_score
        if prev_health_scores:
            delta = current_health - prev_health_scores[-1]
            health_trend = "up" if delta > _HEALTH_TREND_THRESHOLD else "down" if delta < -_HEALTH_TREND_THRESHOLD else "stable"
        else:
            health_trend = "stable"

        return updated_episodes, compressed_facts, health_trend

    def _update_summary(
        self, current_summary: str, delta: str, new_facts: list[str]
    ) -> str:
        """Merge delta into existing summary. Keep under 500 chars."""
        # new_facts is deliberately unused here: individual facts are stored in the
        # gold_data layer (with source + confidence) rather than folded into freeform
        # prose, so they remain individually auditable and don't inflate the summary.
        if not current_summary:
            return delta[:500]
        # Simple merge: append delta if meaningful
        if delta and delta.lower() not in current_summary.lower():
            combined = f"{current_summary} {delta}"
            # 500-char cap: summary is rendered as a single line in the War Room header
            # and stored in a varchar(500) column — truncation beats a DB write error.
            return combined[:500]
        return current_summary

    def _compress_episodes(self, episodes: list[dict], existing_facts: dict) -> dict:
        """
        Compress old episodic memory entries into semantic facts.
        These facts persist indefinitely in memory.semantic — no cap.
        Called when episodic list exceeds 20 entries to prevent institutional knowledge loss.
        """
        # Fingerprint length for dedup: short enough to catch near-duplicates that
        # differ only in trailing detail, long enough to avoid false merges.
        _DEDUP_PREFIX = 50
        # Snippet length stored per compressed change: enough context to be useful in
        # the morning brief without blowing the JSONB column budget.
        _SNIPPET_LEN = 200
        # Keep the last 10 compressed snippets — beyond that, the trend signals in
        # historical_health_trend + historical_forecast_pattern carry the signal.
        _HISTORY_CAP = 10

        facts = dict(existing_facts)  # copy

        # Aggregate patterns from old episodes
        health_scores = [e.get("health_score") for e in episodes if e.get("health_score")]
        pov_categories = [e.get("pov_category") for e in episodes if e.get("pov_category")]

        if health_scores:
            avg_health = sum(health_scores) / len(health_scores)
            trend = "improving" if health_scores[-1] > health_scores[0] else "declining" if health_scores[-1] < health_scores[0] else "stable"
            facts["historical_health_trend"] = f"avg {avg_health:.2f}, {trend} over {len(health_scores)} runs"

        # Count how often deal was in each forecast category
        if pov_categories:
            cat_counts = Counter(pov_categories)
            facts["historical_forecast_pattern"] = dict(cat_counts)

        # Extract key changes text from old episodes
        key_changes = [e.get("key_changes", "") for e in episodes if e.get("key_changes")]
        if key_changes:
            # Deduplicate and keep first 3 meaningful ones
            unique = []
            seen = set()
            for kc in key_changes:
                k = kc[:_DEDUP_PREFIX].strip()
                if k and k not in seen:
                    seen.add(k)
                    unique.append(kc[:_SNIPPET_LEN])
                if len(unique) >= 3:
                    break
            if unique:
                existing_history = facts.get("compressed_run_history", [])
                facts["compressed_run_history"] = (existing_history + unique)[-_HISTORY_CAP:]

        # Date range of compressed episodes
        dates = [e.get("date") for e in episodes if e.get("date")]
        if dates:
            facts["compressed_period"] = f"{min(dates)} to {max(dates)} ({len(episodes)} runs)"

        return facts
