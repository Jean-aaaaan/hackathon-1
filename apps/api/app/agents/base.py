"""
Base agent class + shared Pydantic schemas for agent I/O.
Every agent is a structured LLM call - no LangChain, no frameworks.
Direct Anthropic API with Pydantic v2 tool_use for guaranteed JSON output.

B2B Frameworks encoded:
  - MEDDPICC: Metrics, Economic Buyer, Decision Criteria, Decision Process,
              Implicate Pain, Champion, Competition, Paper Process
  - 3 Whys: Why Change / Why Now / Why Us (urgency trigger framework)
  - 5 Risk Vectors: Champion, Competition, Timeline, Economic, Stakeholder
  - Deal Velocity: stage momentum, engagement decay, close date integrity
  - Multi-threading: stakeholder coverage depth
"""
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
import contextvars  # ContextVar threads per-parse coercion warnings without global state
from app.integrations.llm import LLMUsage, structured_call, provider as llm_provider
import json
import re
import structlog
import time

log = structlog.get_logger()


# ── Coercion fallback tracking ───────────────────────────────────────────────
# Validators below coerce malformed LLM output (Haiku sometimes returns JSON
# strings instead of objects). Lossless coercions are fine; LOSSY fallbacks
# (substituted defaults, dropped data) must never be silent — they distort
# health/urgency scores downstream. BaseAgent.parse_output() sets this
# contextvar so validators can report what they had to throw away.

_coercion_warnings: contextvars.ContextVar[Optional[list]] = contextvars.ContextVar(
    "vantage_coercion_warnings", default=None
)


def _record_lossy_coercion(field: str, detail: str, raw: Any = None) -> None:
    log.warning(
        "llm_output_lossy_coercion",
        field=field,
        detail=detail,
        raw_snippet=str(raw)[:300] if raw is not None else None,
    )
    warnings = _coercion_warnings.get()
    if warnings is not None:
        warnings.append(f"{field}: {detail}")


def _try_parse_json_dict(v: Any) -> Optional[dict]:
    """Parse a JSON-encoded string to dict; returns None if v is not a '{'-prefixed string or parse fails."""
    if not isinstance(v, str):
        return None
    stripped = v.strip()
    if not stripped.startswith("{"):
        return None
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _coerce_optional_dict(
    field_name: str,
    v: Any,
    fallback: Any = None,
    fallback_label: str = "",
) -> Any:
    """
    Shared coercion for dict-typed fields that Haiku sometimes returns as JSON strings.
    Returns v unchanged if already a dict or None; records a lossy coercion if forced to fallback.
    """
    if isinstance(v, dict) or v is None:
        return v
    parsed = _try_parse_json_dict(v)
    if parsed is not None:
        return parsed
    _record_lossy_coercion(field_name, fallback_label or "unparseable value dropped", raw=v)
    return fallback


# ── Signal taxonomy ──────────────────────────────────────────────────────────
# Covers all Actively AI signal types + enterprise B2B standard signals.

SIGNAL_TYPES = """
RELATIONSHIP SIGNALS:
  champion_activity         - Champion engaged, replied, attended meeting
  champion_dark             - Champion non-responsive 7+ days after prior engagement
  champion_role_change      - Champion changed role, title, or team
  champion_promotion        - Champion promoted (more power - opportunity)
  champion_departure        - Champion left the company (critical risk)
  economic_buyer_identified - Economic buyer confirmed (person who signs)
  economic_buyer_dark       - Economic buyer not engaged or stopped responding
  economic_buyer_engaged    - Economic buyer joined meeting, replied, or sponsored
  executive_sponsor_engaged - Exec sponsor from seller side introduced/engaged
  new_stakeholder_added     - New buying committee member identified
  blocker_identified        - New internal blocker or detractor identified
  single_thread_risk        - Only 1 contact engaged; no multi-threading
  buying_committee_expanded - More stakeholders joining evaluation
  org_restructure           - Buyer org restructure; champion's team affected

DEAL HEALTH SIGNALS:
  deal_slip                 - Close date pushed back (track count of slips)
  stage_mismatch            - CRM stage inconsistent with actual deal progress
  close_plan_missing        - No mutual action plan / close plan exists
  close_plan_stale          - Close plan not updated in 14+ days
  meddpicc_gap              - Specific MEDDPICC component missing (specify which)
  decision_criteria_undefined - Formal evaluation criteria not obtained
  budget_risk               - Budget unconfirmed, in jeopardy, or delayed
  budget_confirmed          - Budget explicitly confirmed by economic buyer
  procurement_engaged       - Procurement/legal/security review has started
  legal_review_started      - Contract review or security questionnaire started
  contract_redlines_active  - Active contract negotiation in progress
  mutual_action_plan_created - Formal MAP/close plan agreed with buyer
  paper_process_delay       - Legal/procurement causing timeline risk

INTENT AND EVALUATION SIGNALS:
  competitive_mention       - Competitor referenced in any channel
  competitive_evaluation_active - Buyer running parallel evaluation with competitor
  evaluation_started        - Formal RFP/POC/pilot started
  rfp_issued                - Formal RFP received
  pilot_extended            - POC/pilot extended (could be positive or delay)
  pilot_success             - POC/pilot delivered success criteria
  reference_requested       - Buyer requested customer references
  roi_case_built            - ROI/business case model completed with buyer
  decision_timeline_set     - Buyer confirmed target decision date

EXTERNAL SIGNALS:
  leadership_change         - C-level or VP change at buyer company
  funding_event             - Funding round, acquisition, or major budget event
  acquisition_news          - Buyer being acquired or acquiring someone
  budget_cycle_risk         - End of budget period; unspent budget risk
  product_launch            - Buyer launched new product (potential expansion)
  usage_drop                - Drop in usage/engagement of current solution
  news_mention              - Company mentioned in relevant news
  engagement_trend_declining - Pattern of decreasing response rates over time

CUSTOMER SUCCESS SIGNALS (post-sale accounts only):
  renewal_risk              - Customer at risk of not renewing (health drop, champion dark, NPS risk)
  renewal_opportunity       - Customer showing strong renewal confidence (high usage, champion engaged)
  expansion_opportunity     - Upsell or cross-sell signal: new team, new use case, or usage growth
  usage_growth_detected     - Product usage growing meaningfully - expansion conversation is timely
  usage_decline_30d         - Product usage declining 30+ days - adoption risk
  qbr_overdue               - QBR hasn't happened in 90+ days
  contract_expiring_90d     - Contract renewal within 90 days
  nps_risk                  - Low NPS or negative sentiment from customer contacts
  champion_departure_cs     - Champion at a customer account changed roles or left
  support_surge             - Unusual spike in support tickets - implementation or adoption risk
  executive_sponsor_change  - Executive sponsor changed at customer company
  new_team_adoption         - New team or department started using the product
"""


# ── Stakeholder schema ───────────────────────────────────────────────────────

class StakeholderUpdate(BaseModel):
    name: str
    title: Optional[str] = None
    role: Optional[str] = Field(
        default=None,
        description=(
            "economic_buyer | champion | decision_maker | technical_buyer | "
            "user_buyer | influencer | blocker | neutral | unknown. "
            "Economic Buyer = controls budget. Champion = sells internally on the seller's behalf. "
            "Decision Maker = signs off. These can overlap."
        )
    )
    sentiment: Optional[str] = Field(
        default=None,
        description="positive | neutral | negative | mixed | unknown"
    )
    sentiment_score: Optional[float] = Field(default=None, ge=-1.0, le=1.0)
    last_contact_date: Optional[str] = None
    engagement_level: Optional[str] = Field(
        default=None,
        description="highly_engaged | engaged | passive | dark | unknown"
    )
    has_budget_authority: Optional[bool] = None
    internal_influence: Optional[str] = Field(
        default=None,
        description="high | medium | low - their ability to move this deal internally"
    )
    recent_signals: list[str] = []
    communication_style: Optional[str] = None
    risk_flags: list[str] = Field(
        default=[],
        description="e.g. 'dark_7_days', 'negative_sentiment_trend', 'role_change_pending'"
    )


# ── MEDDPICC qualification schema ────────────────────────────────────────────

class MeddpiccScore(BaseModel):
    """
    MEDDPICC qualification framework scoring.
    The industry-standard enterprise deal qualification model.
    Each component scored 0-1 based on what's confirmed vs assumed.
    """
    metrics: float = Field(
        ge=0.0, le=1.0,
        description="Quantified business impact agreed with buyer (ROI, cost savings, revenue impact). 0=none, 1=fully agreed"
    )
    economic_buyer: float = Field(
        ge=0.0, le=1.0,
        description="Economic buyer identified AND engaged (not just known). 0=unknown, 0.5=identified only, 1.0=actively engaged"
    )
    decision_criteria: float = Field(
        ge=0.0, le=1.0,
        description="Formal evaluation criteria obtained and understood. 0=unknown, 1=fully documented"
    )
    decision_process: float = Field(
        ge=0.0, le=1.0,
        description="Approval and procurement process mapped end-to-end. 0=unknown, 1=fully mapped with owners"
    )
    implicate_pain: float = Field(
        ge=0.0, le=1.0,
        description="Business pain quantified AND linked to consequence of inaction. 0=pain not established, 1=urgency fully built"
    )
    champion: float = Field(
        ge=0.0, le=1.0,
        description="Champion identified, validated (has power), and actively selling internally. 0=none, 1=strong enabled champion"
    )
    competition: float = Field(
        ge=0.0, le=1.0,
        description="Competitive landscape fully known and actively positioned against. 0=unknown, 1=fully mapped and addressed"
    )
    paper_process: float = Field(
        ge=0.0, le=1.0,
        description="Legal/security/procurement process understood with timeline. 0=unknown, 1=fully mapped with dates"
    )
    overall_score: float = Field(
        default=0.0,
        ge=0.0, le=1.0,
        description="Weighted average - critical gaps (EB, champion) weighted 2x"
    )
    gaps: list[str] = Field(
        default=[],
        description="Explicit gap descriptions: e.g. 'Economic buyer identified but never met', 'No ROI model built'"
    )
    gap_risk: str = Field(
        default="medium",
        description="low | medium | high | critical - overall qualification risk"
    )
    three_whys: Optional[dict] = Field(
        default=None,
        description=(
            "Why Change (pain urgency), Why Now (timing trigger), Why Us (differentiation). "
            "Each present: true/false with evidence string."
        )
    )

    from pydantic import model_validator

    @model_validator(mode="after")
    def _fill_overall_score(self):
        if self.overall_score == 0.0:
            # Weighted average: EB + champion get 2x weight
            components = [
                self.metrics, self.decision_criteria, self.decision_process,
                self.implicate_pain, self.competition, self.paper_process,
            ]
            weighted = sum(components) + self.economic_buyer * 2 + self.champion * 2
            self.overall_score = round(weighted / (len(components) + 4), 3)
        return self


# ── Shared signal schema ─────────────────────────────────────────────────────

class SignalOut(BaseModel):
    type: str = Field(
        description=f"Signal type from the taxonomy. Options:\n{SIGNAL_TYPES}"
    )
    urgency: str = Field(description="critical | high | medium | low")
    urgency_score: float = Field(ge=0.0, le=1.0, description="0.0 to 1.0")
    detail: str = Field(description="Specific, evidence-backed description. No vague statements.")
    source: str = Field(description="e.g. gong:call/456, perplexity:news, hubspot:deal/123, hubspot:note/789")
    source_url: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    detected_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    meddpicc_component: Optional[str] = Field(
        default=None,
        description="Which MEDDPICC component this signal affects, if any"
    )

    # Gold Data Layer - audit trail (our differentiator vs Actively AI)
    gold_sources: Optional[list[dict]] = Field(
        default=None,
        description="List of {source, raw_value, confidence, updated_at} for conflict resolution audit"
    )
    gold_resolution: Optional[str] = None


class GoldDataPoint(BaseModel):
    """Fully auditable resolved data point - shown in Audit Panel to reps."""
    resolved_value: Any
    confidence: float
    confidence_explanation: str
    sources: dict[str, dict]  # {source_name: {value, confidence, updated_at}}
    weighted_votes: dict[str, float]
    audit_trail: list[dict]
    resolved_at: str


# ── Agent I/O schemas ────────────────────────────────────────────────────────

class IcpScore(BaseModel):
    """ICP (Ideal Customer Profile) fit score for an account."""
    score: float = Field(ge=0.0, le=1.0, default=0.5, description="0.0-1.0 ICP fit score")
    tier: str = Field(default="unknown", description="strong | moderate | weak | unknown")
    signals: list[str] = Field(default=[], description="Matching ICP factors")
    gaps: list[str] = Field(default=[], description="ICP mismatch factors")


class ResearchResult(BaseModel):
    """Output of ResearcherAgent."""
    new_signals: list[SignalOut] = []
    updated_stakeholders: list[StakeholderUpdate] = []
    account_summary_delta: str = Field(default="", description="What changed about this account since last run")
    key_facts_extracted: list[str] = Field(default=[], description="New facts discovered this run")
    meddpicc_observations: list[str] = Field(
        default=[],
        description="Raw observations about MEDDPICC components from this run's signals"
    )
    deal_velocity_signals: dict = Field(
        default={},
        description="days_in_stage, close_date_slips, last_meaningful_activity_days, engagement_trend"
    )
    confidence_scores: dict[str, float] = {}
    icp_score: Optional[IcpScore] = Field(
        default=None,
        description="ICP fit score for this account (0-1 scale)"
    )
    ai_fields_extracted: Optional[dict] = Field(
        default=None,
        description="Workspace-defined custom AI field extraction results"
    )
    resolved_signals: list[str] = Field(
        default=[],
        description=(
            "Signal types that were previously raised but are now resolved based on "
            "recent activity evidence. Example: 'legal_review_started' resolved because "
            "the customer signed the DPA and an outbound confirmation email was sent. "
            "Use exact signal type strings from the taxonomy. "
            "Only include if there is clear evidence of resolution in this run's context."
        )
    )

    @field_validator("new_signals", "updated_stakeholders", mode="before")
    @classmethod
    def _coerce_signal_lists(cls, v, info):
        return _coerce_model_list(v, info.field_name)

    @field_validator("deal_velocity_signals", "confidence_scores", mode="before")
    @classmethod
    def _coerce_str_dict(cls, v, info):
        """Haiku sometimes returns JSON-encoded strings instead of dicts."""
        if isinstance(v, dict):
            return v
        parsed = _try_parse_json_dict(v)
        if parsed is not None:
            return parsed
        if v is not None:
            _record_lossy_coercion(info.field_name, "unparseable value dropped — empty dict substituted", raw=v)
        return {}

    @field_validator("resolved_signals", "key_facts_extracted", "meddpicc_observations", mode="before")
    @classmethod
    def _coerce_str_list(cls, v, info):
        return _coerce_to_list(v, info.field_name)


def _coerce_model_list(v, field: str = "model_list_field"):
    """
    Coerce a list of Pydantic model objects (SignalOut, StakeholderUpdate, etc.) from LLM output.
    Keeps dict items as dicts so Pydantic can construct the model from them.
    Parses JSON-encoded strings to dicts. Never stringifies — unlike _coerce_to_list.
    """
    if isinstance(v, list):
        result = []
        for item in v:
            if isinstance(item, dict):
                result.append(item)
            elif isinstance(item, str):
                parsed = _try_parse_json_dict(item)
                if parsed is not None:
                    result.append(parsed)
        return result
    if isinstance(v, str):
        stripped = v.strip()
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return _coerce_model_list(parsed, field)
            except Exception:
                pass
    if v is not None:
        _record_lossy_coercion(field, "unparseable value dropped — empty list substituted", raw=v)
    return []


def _coerce_to_list(v, field: str = "list_field"):
    """
    Shared coercion: Haiku sometimes returns JSON-encoded strings or newline-delimited
    strings instead of arrays. Try JSON parse first; fall back to newline splitting.
    For list[str] fields only — use _coerce_model_list for list[BaseModel] fields.
    """
    if isinstance(v, list):
        # Stringify non-string items — this is correct for list[str] fields
        return [item if isinstance(item, str) else json.dumps(item) if isinstance(item, dict) else str(item) for item in v]
    if isinstance(v, str):
        stripped = v.strip()
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
        # Newline-delimited fallback (e.g. "- item one\n- item two")
        lines = [line.strip().lstrip("-*•").strip() for line in v.split("\n") if line.strip()]
        if lines:
            return [line for line in lines if line]
    if v is not None:
        _record_lossy_coercion(field, "unparseable value dropped — empty list substituted", raw=v)
    return []


class RiskResult(BaseModel):
    """Output of RiskScannerAgent."""
    risks: list[SignalOut] = []
    health_score: float = Field(default=0.5, ge=0.0, le=1.0, description="Overall account health 0-1")
    health_score_delta: float = Field(
        default=0.0,
        description="Change vs previous health_score (positive = improving)"
    )
    health_reasoning: str = Field(default="", description="Multi-factor breakdown of why this health score")

    # MEDDPICC
    meddpicc: MeddpiccScore = Field(
        default_factory=lambda: MeddpiccScore(
            metrics=0.3, economic_buyer=0.2, decision_criteria=0.2,
            decision_process=0.2, implicate_pain=0.3, champion=0.3,
            competition=0.3, paper_process=0.1, overall_score=0.24,
            gaps=["Insufficient data for full assessment"]
        )
    )
    qualification_score: float = Field(
        ge=0.0, le=1.0,
        default=0.3,
        description="Overall deal qualification 0-1 (MEDDPICC completion weighted)"
    )

    # Risk vectors (5-factor risk matrix)
    champion_risk: str = Field(default="medium", description="low | medium | high | critical")
    competition_risk: str = Field(default="medium", description="low | medium | high | critical")
    timeline_risk: str = Field(default="medium", description="low | medium | high | critical")
    economic_risk: str = Field(default="medium", description="low | medium | high | critical")
    stakeholder_risk: str = Field(default="medium", description="low | medium | high | critical")

    # Deal velocity
    deal_momentum: str = Field(
        default="neutral",
        description="accelerating | neutral | stalling | declining"
    )
    days_since_meaningful_activity: Optional[int] = None
    close_date_integrity: str = Field(
        default="unknown",
        description="solid | soft | at_risk | unknown - probability close date is real"
    )

    # POV
    pov_forecast_category: str = Field(
        default="Pipeline",
        description="AI forecast: Pipeline | Best Case | Commit | Omit"
    )
    pov_forecast_confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    pov_signals: list[str] = Field(default=[], description="Top signals driving POV")
    pov_risks: list[str] = Field(default=[], description="Top risks to current POV")
    pov_commit_explanation: Optional[str] = None
    pov_forecast_explanation: Optional[str] = None

    # Flowing deal narrative - the story of this deal, not a scorecard
    deal_narrative: str = Field(
        default="",
        description=(
            "A flowing 2-4 sentence narrative synthesising the full deal picture. "
            "Correlate: champion state + economic buyer engagement + MEDDPICC gaps + momentum + competitive risk + POV. "
            "Reference specific people (by name if known), dates, and signals. "
            "Written like a deal brief handed to a VP before a pipeline review, not a list of scores. "
            "Example: 'Sarah (HSE Director) has been engaged weekly since the site visit but the CFO hasn't been in the loop since the January business case, "
            "which is the blocking gap at Proposal stage. A parallel Voxel evaluation surfaced two weeks ago and the champion is fielding internal questions about pricing. "
            "This is a Best Case deal that needs an executive escalation this week or it risks slipping into Q3.'"
        )
    )

    # Signal themes - correlated groups, not a flat list
    signal_themes: list[dict] = Field(
        default=[],
        description=(
            "Top 2-3 signal themes. Each groups related signals into a pattern. "
            "Format: [{theme: str, severity: 'critical'|'high'|'medium'|'low', "
            "summary: str (1 sentence), signal_count: int, signals: [str]}]. "
            "Example: {theme: 'Champion engagement declining', severity: 'high', "
            "summary: 'HSE Director dark 18 days after previously weekly contact', "
            "signal_count: 2, signals: ['champion_dark', 'engagement_trend_declining']}"
        )
    )

    three_whys_assessment: Optional[dict] = Field(
        default=None,
        description="why_change, why_now, why_us - each with present:bool and evidence:str"
    )

    @field_validator("pov_forecast_category", mode="before")
    @classmethod
    def _normalize_forecast_category(cls, v):
        """
        Free-string category from the LLM ("omit", "best case", "BestCase",
        "Forecast"…) silently fell through every frontend style map to the
        Omit badge. Map to the 4 canonical values; unknowns become Pipeline.
        """
        canonical = {
            "pipeline": "Pipeline",
            "best case": "Best Case",
            "bestcase": "Best Case",
            "best_case": "Best Case",
            "commit": "Commit",
            "committed": "Commit",
            "omit": "Omit",
            "omitted": "Omit",
        }
        if isinstance(v, str):
            mapped = canonical.get(v.strip().lower())
            if mapped:
                return mapped
            _record_lossy_coercion(
                "pov_forecast_category",
                f"unknown category {v!r} — Pipeline substituted",
                raw=v,
            )
        return "Pipeline"

    @field_validator("meddpicc", mode="before")
    @classmethod
    def _coerce_meddpicc(cls, v):
        """Haiku sometimes returns MeddpiccScore as a JSON-encoded string instead of a dict."""
        return _coerce_optional_dict(
            "meddpicc",
            v,
            fallback={
                "metrics": 0.3, "economic_buyer": 0.2, "decision_criteria": 0.2,
                "decision_process": 0.2, "implicate_pain": 0.3, "champion": 0.3,
                "competition": 0.3, "paper_process": 0.1, "overall_score": 0.24,
                "gaps": ["Insufficient data for full assessment"],
            },
            fallback_label="unparseable string — default scores substituted (overall 0.24)",
        )

    @field_validator("risks", mode="before")
    @classmethod
    def _coerce_risk_signals(cls, v, info):
        return _coerce_model_list(v, info.field_name)

    @field_validator("pov_signals", "pov_risks", mode="before")
    @classmethod
    def coerce_str_to_list(cls, v, info):
        return _coerce_to_list(v, info.field_name)

    @field_validator("three_whys_assessment", mode="before")
    @classmethod
    def _coerce_three_whys(cls, v):
        """Haiku sometimes returns JSON-encoded string instead of dict."""
        return _coerce_optional_dict(
            "three_whys_assessment",
            v,
            fallback=None,
            fallback_label="unparseable value dropped — 3 Whys missing from this run",
        )


class GroundingResult(BaseModel):
    """Output of GroundingAgent - fact verification layer. GA from day 1."""
    verified_signals: list[SignalOut] = Field(default=[], description="Signals verified against cited sources")
    unverified_claims: list[dict] = Field(
        default=[],
        description="Claims that could not be verified - flagged, not discarded"
    )
    verification_summary: str = Field(default="", description="Summary of verification process and confidence assessment")
    overall_confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="Overall confidence in verified signals 0-1")
    gold_data_points: dict[str, GoldDataPoint] = Field(
        default={},
        description="Resolved, confidence-scored data points with full audit trail"
    )

    @field_validator("gold_data_points", mode="before")
    @classmethod
    def _coerce_gold_data(cls, v):
        if not isinstance(v, dict):
            return {}
        # Drop keys whose values aren't GoldDataPoint-compatible dicts
        return {k: val for k, val in v.items() if isinstance(val, dict)}

    @field_validator("verified_signals", "unverified_claims", mode="before")
    @classmethod
    def _coerce_signal_list(cls, v, info):
        return _coerce_model_list(v, info.field_name)


class ActionItem(BaseModel):
    action: str
    reason: str = ""
    priority: int = Field(ge=1)
    urgency_score: float = Field(ge=0.0, le=1.0)
    draft_recommended: bool = False
    target_contact: Optional[str] = None
    draft_type: Optional[str] = Field(
        default=None,
        description=(
            "email_followup | meeting_brief | roi_business_case | "
            "competitive_displacement | executive_alignment | "
            "close_plan_proposal | champion_reengagement | outreach_sequence | "
            "renewal_brief | expansion_pitch | nurture_cadence"
        )
    )
    meddpicc_component: Optional[str] = Field(
        default=None,
        description="Which MEDDPICC gap this action addresses"
    )
    framework_rationale: Optional[str] = Field(
        default=None,
        description="Brief note on which framework drives this recommendation (e.g. MEDDPICC:champion, 3Whys:now)"
    )


class PrioritiserResult(BaseModel):
    """Output of PrioritiserAgent."""
    next_actions: list[ActionItem] = []

    @field_validator("next_actions", mode="before")
    @classmethod
    def _coerce_actions(cls, v, info):
        return _coerce_model_list(v, info.field_name)

    urgency_score: float = Field(ge=0.0, le=1.0, description="Composite account urgency")
    prioritisation_reasoning: str = Field(default="", description="Reasoning behind prioritisation decisions")
    pipeline_review_ready: bool = Field(
        default=False,
        description="Is this deal ready to discuss confidently in a pipeline review?"
    )
    top_risk_summary: str = Field(
        default="",
        description="One-sentence top risk for this account right now"
    )
    pov_amount: Optional[float] = Field(
        default=None,
        description=(
            "AI-predicted realistic close amount in USD. May differ from CRM amount. "
            "Base it on MEDDPICC qualification, champion strength, and competition risk. "
            "Commit + well-qualified = CRM amount. Omit or thin qualification = lower (pilot scope or 0). "
            "Best Case = 60-90% of CRM amount. Only set when you have enough context."
        )
    )
    pov_close_date: Optional[str] = Field(
        default=None,
        description=(
            "AI-predicted realistic close date as YYYY-MM-DD. "
            "If CRM close date is past and deal is stalling: push out 60-180 days from today. "
            "If deal is accelerating with MAP in place: close date may be achievable. "
            "If Omit: set to a realistic future date. Always set this - never leave null for Proposal+ stage."
        )
    )


class DraftItem(BaseModel):
    type: str = Field(
        description=(
            "MUST be one of these exact values only: "
            "email_followup | meeting_brief | roi_business_case | "
            "competitive_displacement | executive_alignment | "
            "close_plan_proposal | champion_reengagement | outreach_sequence | "
            "renewal_brief | expansion_pitch | nurture_cadence. "
            "Never invent new type names. Use email_followup for any outbound email."
        )
    )
    content: str
    subject_line: Optional[str] = None
    target_contact: Optional[str] = None
    target_role: Optional[str] = Field(
        default=None,
        description="champion | economic_buyer | executive | decision_maker"
    )
    sources_cited: list[dict] = Field(
        default=[],
        description="Every fact cited: {fact, source, source_id, confidence, verified}"
    )
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    send_trigger: Optional[str] = Field(
        default=None,
        description="What specific event triggered this draft (e.g. 'champion dark 8 days', 'competitor mentioned in call')"
    )


class DrafterResult(BaseModel):
    """Output of DrafterAgent."""
    drafts: list[DraftItem] = []
    drafting_notes: str = ""

    @field_validator("drafts", mode="before")
    @classmethod
    def _coerce_drafts(cls, v, info):
        return _coerce_model_list(v, info.field_name)


# ── Smart Fields schemas ─────────────────────────────────────────────────────

class SmartFieldSuggestion(BaseModel):
    """
    A single AI-suggested HubSpot field update.
    Only surfaces when confidence >= 0.65 and the current value materially differs.
    """
    field_name: str = Field(
        description=(
            "HubSpot property name: hs_forecast_category | closedate | amount | "
            "notes_next_activity_date | hubspot_owner_id"
        )
    )
    field_label: str = Field(description="Human-readable label shown in the UI")
    current_value: Optional[str] = Field(default=None, description="Current value in HubSpot (may be null)")
    suggested_value: str = Field(description="The AI-suggested new value")
    reason: str = Field(description="Specific, evidence-backed reason for this suggestion")
    source: str = Field(description="Signal or data source that supports this suggestion")
    confidence: float = Field(ge=0.0, le=1.0, description="0.0-1.0 - only surface >= 0.65")
    meddpicc_component: Optional[str] = Field(
        default=None,
        description="Which MEDDPICC component this improves, e.g. 'Economic Buyer', 'Timeline'"
    )
    impact: str = Field(
        default="medium",
        description="low | medium | high - how much keeping CRM wrong hurts pipeline accuracy"
    )


class SmartFieldsResult(BaseModel):
    """Output of SmartFieldsAgent."""
    suggestions: list[SmartFieldSuggestion] = []
    fields_scanned: int = Field(default=0, description="Number of HubSpot fields examined")
    meddpicc_gaps_addressed: list[str] = Field(default=[], description="MEDDPICC gaps that field updates would close")
    reasoning: str = Field(default="", description="Brief summary of why these fields need updating")


# ── Stakeholder name hygiene ─────────────────────────────────────────────────
# LLM-extracted stakeholder updates sometimes carry sentence fragments as
# names ("Only Derick Sim", "The CFO") which then surface in the UI as people.

_NAME_LEADING_ARTIFACTS = {
    "only", "the", "a", "an", "both", "either", "all", "new",
    "unknown", "possibly", "likely", "maybe",
}
_NAME_INVALID = {"unknown", "n/a", "na", "tbd", "none", "team", "everyone", "various"}


def normalize_stakeholder_name(name: Any) -> Optional[str]:
    """
    Canonical display name for a stakeholder, or None if the value is an
    LLM artifact rather than a person's name.
    """
    if not name or not isinstance(name, str):
        return None
    # Researcher often writes "Mogan (Construction Safety Lead)" — keep the name
    cleaned = re.sub(r"\s*\([^)]*\)", "", name)
    cleaned = " ".join(cleaned.split()).strip(" .,;:!\"'")
    words = cleaned.split(" ")
    while words and words[0].lower() in _NAME_LEADING_ARTIFACTS:
        words = words[1:]
    if not words:
        return None
    cleaned = " ".join(words)
    if cleaned.lower() in _NAME_INVALID:
        return None
    if len(words) > 4:  # real names fit in 4 tokens; longer strings are sentence fragments
        return None
    if not cleaned[0].isupper():  # fragments are lowercase; names are capitalized
        return None
    if any(ch in cleaned for ch in ":;@/\\()"):
        return None
    if not any(c.isalpha() for c in cleaned):
        return None
    return cleaned


# ── Urgency formula ──────────────────────────────────────────────────────────

# Stages where a deal can never be "urgent" — mirrors the nightly worker's
# skip policy. Stale urgency on closed deals poisons every triage surface.
CLOSED_STAGES = {"won", "closed lost", "closed-lost", "partners"}

# Parked deals: signals still accrue (dark champions, slipped dates are the
# NORM here), but a nurture deal must never outrank active pipeline in the
# Today queue. Cap, don't zero — a rep may still want the weekly touchpoint.
NURTURE_STAGES = {"to nurture", "nurture"}


def compute_urgency_score(
    llm_urgency: float,
    max_signal_urgency: float,
    deal_momentum: str,
    close_date: Optional[str],
    stage: Optional[str],
) -> float:
    """
    Deterministic urgency blend — code-enforced, auditable, reproducible.

    The LLM composite anchors the score but cannot saturate it alone:
    deterministic evidence (verified signal urgency, close-date proximity,
    momentum) must corroborate for a deal to reach the top of the queue.
    This prevents the score compression where every account reads 0.93-0.95
    and triage becomes meaningless.
    """
    if stage and stage.strip().lower() in CLOSED_STAGES:
        return 0.1

    # 0.45 LLM composite + 0.30 verified signal + 0.15 close-date + 0.10 momentum = 1.0 max.
    # LLM anchors the score; deterministic evidence must corroborate to reach the top of the queue.
    score = 0.45 * max(0.0, min(1.0, llm_urgency))
    score += 0.30 * max(0.0, min(1.0, max_signal_urgency))

    # Close-date proximity: ramps to +0.15 inside 30 days, full weight once due/overdue.
    # 30d = one typical enterprise sales cycle sprint; anything further out shouldn't
    # move the needle on daily triage — urgency comes from signals, not a distant date.
    if close_date:
        try:
            from datetime import timezone as _tz
            cd = datetime.fromisoformat(str(close_date)[:10]).date()
            days = (cd - datetime.now(_tz.utc).date()).days
            if days <= 0:
                score += 0.15
            elif days <= 30:
                score += 0.15 * (1 - days / 30)
        except (ValueError, TypeError):
            pass

    score += {"stalling": 0.05, "declining": 0.10}.get(deal_momentum, 0.0)

    # 0.35 = highest urgency a nurture deal can reach without being promoted
    # out of nurture. Keeps them below active pipeline (typically 0.40+) while
    # still surfacing genuinely hot signals (e.g. champion departure).
    if stage and stage.strip().lower() in NURTURE_STAGES:
        score = min(score, 0.35)

    return round(max(0.05, min(0.97, score)), 2)


# ── Win probability formula ──────────────────────────────────────────────────

def compute_win_probability(
    meddpicc_overall: float,
    champion_risk: str,
    competition_risk: str,
    deal_momentum: str,
    three_whys_present: int,
    close_date_integrity: str,
) -> float:
    """
    Deterministic win probability from already-scored inputs.
    No Claude call - fully auditable and reproducible across runs.
    Maps to POV categories: >=0.75 Commit, 0.50-0.74 Best Case, 0.30-0.49 Pipeline, <0.30 Omit.
    """
    score = meddpicc_overall * 0.40
    score += {"low": 0.20, "medium": 0.12, "high": 0.03, "critical": -0.10}.get(champion_risk, 0.10)
    score += {"low": 0.10, "medium": 0.04, "high": -0.06, "critical": -0.15}.get(competition_risk, 0.0)
    score += {"accelerating": 0.10, "neutral": 0.0, "stalling": -0.08, "declining": -0.18}.get(deal_momentum, 0.0)
    # three_whys_present is 0-3 (count of why_change/why_now/why_us confirmed).
    # +0.05 per why: all three present adds +0.15, matching a strong-champion bump.
    score += three_whys_present * 0.05
    score += {"solid": 0.05, "soft": 0.0, "at_risk": -0.08, "unknown": -0.03}.get(close_date_integrity, 0.0)
    return round(max(0.05, min(0.95, score)), 2)


def compute_forecast_confidence(
    verified_signal_count: int,
    days_since_activity: Optional[int],
    win_probability: float,
) -> float:
    """
    Deterministic forecast confidence. LLM self-reported confidence clusters
    in a meaningless 0.62-0.72 band; this derives confidence from things we
    can actually defend in an audit: how much verified evidence exists, how
    fresh the buyer activity is, and how decisive the win probability is
    (a 0.50 win probability IS low confidence — the model can't tell).
    """
    # Base 0.35 + up to 0.30 from signal evidence. Cap at 6 signals: beyond that
    # each extra signal adds minimal confidence (law of diminishing returns on
    # corroboration) and we don't want signal-heavy accounts to overwhelm fresh ones.
    score = 0.35 + 0.05 * min(max(verified_signal_count, 0), 6)   # 0.35..0.65
    if days_since_activity is not None:
        # 7d = active buyer; 21d = cooling; 45d+ = stale — B2B enterprise deal rhythm
        if days_since_activity <= 7:
            score += 0.10
        elif days_since_activity <= 21:
            score += 0.05
        elif days_since_activity > 45:
            score -= 0.05
    # abs(wp - 0.5) * 2 maps [0.0..1.0] win_probability → [0.0..1.0] distance from
    # the uncertain midpoint. Multiplied by 0.20: a decisive wp (0.9 or 0.1) adds
    # full +0.20; a coin-flip wp (0.5) adds nothing — because it genuinely isn't confident.
    score += 0.20 * abs(win_probability - 0.5) * 2                # +0..0.20
    return round(max(0.20, min(0.95, score)), 2)


FORECAST_CATEGORY_ORDER = ["Omit", "Pipeline", "Best Case", "Commit"]


def win_probability_category(win_probability: float) -> str:
    """Forecast category band implied by the deterministic win probability."""
    if win_probability >= 0.75:
        return "Commit"
    if win_probability >= 0.50:
        return "Best Case"
    if win_probability >= 0.30:
        return "Pipeline"
    return "Omit"


def reconcile_forecast_category(
    llm_category: Optional[str],
    win_probability: float,
    deal_amount: Optional[float],
) -> str:
    """
    The LLM's category and the deterministic win probability must roughly agree.
    The LLM gets one step of judgment latitude; beyond that, snap to the
    auditable band — this is what stopped a 376-deal portfolio from reading
    "Commit: $0" while win probabilities said otherwise. A deal with no amount
    can never sit above Pipeline (it has nothing to forecast).
    """
    category = llm_category if llm_category in FORECAST_CATEGORY_ORDER else "Pipeline"
    band = win_probability_category(win_probability)
    if abs(FORECAST_CATEGORY_ORDER.index(category) - FORECAST_CATEGORY_ORDER.index(band)) > 1:
        category = band
    if not deal_amount and FORECAST_CATEGORY_ORDER.index(category) > FORECAST_CATEGORY_ORDER.index("Pipeline"):
        category = "Pipeline"
    return category


# ── Model pricing ────────────────────────────────────────────────────────────
# Rates in USD per 1 M tokens. Key is a substring matched against the model ID.
# Update rates here when Anthropic changes pricing; never inline them in code.
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "haiku":      (0.80,  4.0),
    "sonnet":     (3.0,  15.0),
    "gpt-4o-mini": (0.15,  0.60),
    "gpt-4o":     (2.50, 10.0),
}
_DEFAULT_PRICING = (2.5, 10.0)


# ── Base Agent ───────────────────────────────────────────────────────────────

class BaseAgent:
    """
    Base class for all Vantage agents.
    Handles: LLM calls, token tracking, error recovery, cost logging.
    """

    def __init__(self, model: str):
        self.model = model
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        # Lossy coercion fallbacks applied while parsing this agent's output.
        # Non-empty means scores/data in the result are partially defaulted.
        self.parse_warnings: list[str] = []

    def parse_output(self, model_cls: type, raw: dict):
        """
        Validate raw LLM output into `model_cls`, recording any lossy coercion
        fallbacks on self.parse_warnings instead of letting them pass silently.
        """
        warnings: list[str] = []
        token = _coercion_warnings.set(warnings)
        try:
            parsed = model_cls(**raw)
        finally:
            _coercion_warnings.reset(token)
        if warnings:
            self.parse_warnings.extend(warnings)
            log.warning(
                "llm_output_fallbacks_applied",
                agent=self.__class__.__name__,
                model=self.model,
                fields=warnings,
                raw_snippet=str(raw)[:500],
            )
        return parsed

    @property
    def total_cost_usd(self) -> float:
        """Estimate cost based on model pricing (rates defined in _MODEL_PRICING)."""
        input_rate, output_rate = next(
            (rates for key, rates in _MODEL_PRICING.items() if key in self.model),
            _DEFAULT_PRICING,
        )
        return (self.total_input_tokens / 1_000_000 * input_rate) + \
               (self.total_output_tokens / 1_000_000 * output_rate)

    def _record_call_metrics(self, usage: LLMUsage, latency_ms: float) -> None:
        """Accumulate token counts, emit structured log, and fire PostHog trace."""
        self.total_input_tokens += usage.input_tokens
        self.total_output_tokens += usage.output_tokens
        log.info(
            "llm_call_complete",
            agent=self.__class__.__name__,
            provider=llm_provider(),
            model=self.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=round(latency_ms),
            cost_usd=round(self.total_cost_usd, 6),
        )
        try:
            from app.config import get_settings as _gs
            _s = _gs()
            if _s.posthog_api_key:
                import posthog as _ph
                _ph.api_key = _s.posthog_api_key
                _ph.host = _s.posthog_host
                _ph.capture("vantage_api", "$ai_generation", {
                    "$ai_provider": llm_provider(),
                    "$ai_model": self.model,
                    "$ai_input_tokens": usage.input_tokens,
                    "$ai_output_tokens": usage.output_tokens,
                    "$ai_latency": round(latency_ms / 1000, 3),
                    "agent_name": self.__class__.__name__,
                    "cost_usd": round(self.total_cost_usd, 6),
                })
        except Exception as e:
            log.warning("posthog_capture_failed", error=str(e))

    async def _call_llm(
        self,
        system_prompt: str,
        user_message: str,
        tool_name: str,
        tool_schema: dict,
        max_tokens: int = 2048,
    ) -> dict:
        """Structured LLM call — OpenAI function calling or Anthropic tool_use."""
        start = time.time()
        try:
            result, usage = await structured_call(
                system_prompt=system_prompt,
                user_message=user_message,
                tool_name=tool_name,
                tool_schema=tool_schema,
                model=self.model,
                max_tokens=max_tokens,
                agent_name=self.__class__.__name__,
            )
            self._record_call_metrics(usage, latency_ms=(time.time() - start) * 1000)
            if not isinstance(result, dict):
                log.warning(
                    "structured_non_dict_output",
                    agent=self.__class__.__name__,
                    tool=tool_name,
                    type=type(result).__name__,
                )
            return result
        except Exception as e:
            log.error("llm_call_failed", agent=self.__class__.__name__, error=str(e))
            raise
