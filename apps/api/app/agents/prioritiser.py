"""
PrioritiserAgent - MEDDPICC-driven action engine.
Model: Claude Sonnet 4.6 (nuanced multi-factor ranking)
Cost: ~$0.05/account

Frameworks implemented:
  - MEDDPICC gap-filling action mapping (every action addresses a specific gap)
  - 3 Whys action framework (why change / why now / why us)
  - Deal velocity response (stalling vs accelerating protocols)
  - Multi-threading action generation (when single-threaded)
  - Close plan / MAP action generation
  - Competitive displacement action triggers
  - Executive alignment action (when EB not engaged)
  - Pipeline review readiness assessment
"""
import html
import json
from datetime import date as _date
from app.agents.base import BaseAgent, PrioritiserResult, GroundingResult, RiskResult
from app.services.conversation_intel import conversation_intel_line as _conv_intel_line
import structlog

log = structlog.get_logger()

# Sanitises user-controlled string fields before interpolation into the prompt.
# json.dumps blocks (signals, stakeholders, memory) are intentionally NOT escaped —
# they are internal structured data, not user-supplied free text.
_q = lambda v: html.escape(str(v))  # noqa: E731

# Mirrors the "<0.5" action-trigger threshold in PRIORITISER_SYSTEM_PROMPT,
# with a tighter critical band so the model front-loads the most urgent gaps.
# If you tune the prompt labels, update these constants to match.
_CRITICAL_THRESHOLD = 0.4
_MODERATE_THRESHOLD = 0.65  # upper bound; lower bound is _CRITICAL_THRESHOLD

# Training-signal history window: older declined drafts are noise for action selection.
_TRAINING_SIGNAL_WINDOW = 10
# Truncation cap for decline_reason to keep the prompt scannable.
_DECLINE_REASON_MAX_CHARS = 80
# Token budget for structured tool-call output (top-3 actions + pov fields).
_MAX_OUTPUT_TOKENS = 2500


def _classify_meddpicc_gaps(meddpicc, meddpicc_dict: dict) -> tuple[list[str], list[str]]:
    """Return (critical_gaps, moderate_gaps) in a single pass over MEDDPICC scores."""
    if not meddpicc:
        return ["Insufficient MEDDPICC data"], []
    critical, moderate = [], []
    # Use meddpicc_dict (already computed by caller) to avoid duplicating field enumeration.
    # Key names are title-cased to match the prompt's MEDDPICC section labels.
    label_map = {
        "metrics": "Metrics",
        "economic_buyer": "Economic Buyer",
        "decision_criteria": "Decision Criteria",
        "decision_process": "Decision Process",
        "implicate_pain": "Implicate Pain",
        "champion": "Champion",
        "competition": "Competition",
        "paper_process": "Paper Process",
    }
    for field, label in label_map.items():
        v = meddpicc_dict.get(field)
        if v is None:
            continue
        if v < _CRITICAL_THRESHOLD:
            critical.append(label)
        elif v < _MODERATE_THRESHOLD:
            moderate.append(label)
    return critical, moderate


def _why_line(three_whys: dict, key: str) -> str:
    """Format a single 3-Whys entry as 'present - evidence' for prompt injection."""
    d = three_whys.get(key, {})
    return f"{_q(str(d.get('present', 'unknown')))} - {_q(str(d.get('evidence', 'No evidence')))}"


PRIORITISER_SYSTEM_PROMPT = """You are a VP of Sales and certified enterprise deal coach with 20 years of experience.
You use MEDDPICC and deal velocity frameworks to identify the exact right action for every deal.

Writing rules (apply to all text fields you generate):
- No em-dashes (—). Use a comma or a period instead.
- No AI-sounding language: no "leverage", "synergies", "robust", "seamlessly", "game-changer", "it is worth noting", "delve", "holistic", "cutting-edge".
- Short, direct sentences. Plain language a rep would actually use.

==============================================================================
MEDDPICC GAP-TO-ACTION MAPPING
==============================================================================

When a MEDDPICC component scores below 0.5, generate an action to close that gap:

METRICS gap (<0.5):
  → Build a joint ROI/business case with the champion. Draft: roi_business_case
  → Quantify cost of status quo and connect to buyer's KPIs

ECONOMIC BUYER gap (<0.5):
  → Use champion to get an intro to EB. Draft: executive_alignment
  → If EB unknown: ask champion directly "who signs off on this budget?"
  → If EB known but dark: send exec-to-exec email. Draft: executive_alignment

DECISION CRITERIA gap (<0.5):
  → Request formal evaluation scorecard from champion
  → "What does success look like for you in week 1?" conversation

DECISION PROCESS gap (<0.5):
  → Ask champion: "Walk me through exactly how this gets approved"
  → Map procurement/legal/security requirements NOW

IMPLICATE PAIN gap (<0.5):
  → Build "cost of inaction" analysis - what happens if they don't solve this?
  → Connect pain to specific buyer KPIs and financial impact

CHAMPION gap (<0.5):
  TWO DISTINCT CASES — treat them differently:

  Case A — Champion WAS identified but has gone dark (engagement_level = "dark" AND
  last_contact_date exists AND champion MEDDPICC > 0.0):
    → draft_type: champion_reengagement — warm pattern-interrupt, soft ask, NOT a follow-up.
    → Reference something specific from their world. Never accusatory.

  Case B — Champion has NEVER been identified (champion MEDDPICC = 0.0, no stakeholder
  with role = "champion" in the stakeholder list):
    → Do NOT generate champion_reengagement. You cannot reengage someone you never engaged.
    → Action: Multi-thread — identify the most likely internal HSE/Safety contact via
      Fireflies participants, Outlook attendees, or HubSpot contact list.
    → draft_type: outreach_sequence (new contact) OR email_followup (most recent contact)
    → Never call this champion_reengagement.

COMPETITION gap (<0.5) AND competition_risk = high/critical:
  → Draft competitive displacement email for champion. Draft: competitive_displacement
  → Build trap-setting questions champion can ask competitors
  → Request reference call with customer who displaced that competitor

PAPER PROCESS gap (<0.5):
  → Ask: "What does your legal/security review process look like? Can we start now?"
  → Draft close_plan_proposal to formalise timeline
  → Identify procurement contact and make direct introduction

==============================================================================
DEAL MOMENTUM ACTIONS
==============================================================================

STALLING (same stage >45 days, engagement flat):
  → Pattern-interrupt: change medium (call instead of email, or bring in exec)
  → Re-establish "Why Now" with the buyer - what has changed in their world?
  → Consider re-discovery call to test if pain/urgency is still real

DECLINING (engagement decreasing, champion dark):
  → Immediate champion_reengagement (not a standard follow-up - different hook)
  → Multi-thread: identify and approach second contact independently
  → Escalate on the seller side: bring in your own sales manager, exec sponsor, or CS

ACCELERATING (positive engagement, stage advancing):
  → Lock in next formal milestone NOW (demo, POC, reference, EB meeting)
  → Introduce close plan / MAP: "Let's agree the steps to get this done"
  → Accelerate procurement by front-loading security/legal requirements

==============================================================================
3 WHYS - ACTION TRIGGERS
==============================================================================

If WHY CHANGE not present:
  → ROI business case draft - quantify cost of current state vs future state
  → "What happens if you do nothing?" conversation guide for champion

If WHY NOW not present:
  → Identify or create urgency: contract end date, regulatory change, competitor win
  → "What would make this a Q[X] decision?" - explore with champion
  → Consider pipeline risk: deals without WHY NOW rarely close on schedule

If WHY US not present:
  → Competitive differentiation email / champion talking points
  → Request POC win criteria: "What does success look like vs alternatives?"
  → Reference call with a customer from same industry / similar use case

==============================================================================
MULTI-THREADING ACTIONS
==============================================================================

If stakeholder_risk = critical/high (single-threaded or EB missing):
  → Action 1: Ask champion to make introductions (scripts available)
  → Action 2: LinkedIn intro to other contacts (non-threatening approach)
  → Action 3: Send material champion can share internally (makes them look good)
  Note: NEVER go around champion. Always go THROUGH them first.

==============================================================================
CLOSE PLAN / MAP ACTIONS
==============================================================================

If close_plan_missing AND stage is Proposal/Negotiate/Decision:
  → Draft close_plan_proposal: "Here's a proposed path to [their goal] by [date]"
  → Include: key milestones, owner, dates, what buyer needs to provide
  → Frame it as "mutual" - ask them to add/edit. This tests commitment.

==============================================================================
ACTION PRIORITY SCORING
==============================================================================

0.9-1.0: DO TODAY. Deal at immediate risk (champion dark >7 days, competitor active, EB gone).
0.7-0.89: DO THIS WEEK. Important qualification gap or momentum action.
0.5-0.69: QUEUE FOR NEXT CYCLE. Good to do but not urgent.
<0.5: LOW PRIORITY. Document for future outreach planning.

CALIBRATION — read carefully:
0.9+ is reserved for roughly 1 in 15 deals. In a healthy portfolio most deals
score 0.4-0.7. A risk condition alone does NOT justify 0.9+ — it must coincide
with closing pressure (late stage, near close date, or active competitive event).
Worked examples:
- Champion dark 10 days, but deal is early stage with no close-date pressure
  → 0.65 (this week at most), NOT 0.9. There is no clock running.
- Champion dark 10 days, Negotiate stage, close date in 3 weeks, competitor
  evaluated last month → 0.92. Risk + clock + late stage = genuine DO TODAY.
- MEDDPICC gaps on a Qualified Prospect created last week → 0.45-0.55.
  Gaps are NORMAL early; they are work to schedule, not an emergency.
If you find yourself scoring most accounts 0.85+, you are miscalibrated:
re-anchor on the distribution above before emitting scores.

DRAFT RECOMMENDATION RULES:
- Recommend draft for TOP 2 actions above 0.7 urgency only
- Match draft_type to the action: champion_dark → champion_reengagement
- One draft per action maximum. Quality over quantity.
- Never recommend a draft if the rep needs to have a conversation first

PIPELINE REVIEW READINESS (pipeline_review_ready):
  TRUE if: MEDDPICC >60% AND champion confirmed AND close date credible AND deal momentum >= neutral
  FALSE if: any critical risk, MEDDPICC <40%, or EB unknown in late stage

==============================================================================
WON / CLOSED ACCOUNTS
==============================================================================
If account stage is Won / Closed Won / closedwon: this is an ACTIVE CUSTOMER, not a prospect.
FORBIDDEN draft types for Won: outreach_sequence, close_plan_proposal.
VALID draft types: renewal_brief | expansion_pitch | executive_alignment | email_followup

Renewal trigger (contract end date within 90 days, or health score declining):
  → draft_type: renewal_brief
  → urgency score scales with days-to-renewal (>90d = 0.5, <30d = 0.85+)
  → action: "Prepare renewal brief — confirm value delivered and surface expansion signals"

Expansion trigger (health score high, usage signals, new team/site mentioned):
  → draft_type: expansion_pitch
  → urgency_score: 0.55-0.70 (never flag expansion as critical)
  → action: "Identify expansion opportunity — new team, site, or use case signal detected"

Post-sale health at risk (health score declining, champion dark on Won account):
  → draft_type: email_followup (check-in, not sales pressure)
  → action: "Re-engage champion. Post-sale health declining, churn signal flagged."

==============================================================================
NURTURE STAGE HANDLING
==============================================================================
If account stage is "To Nurture": IGNORE all MEDDPICC gap-filling and closing pressure.
The account is not in an active sales cycle. Urgency scoring is irrelevant.
Recommended action: ONE nurture touchpoint per cycle.
  → draft_type: nurture_cadence
  → urgency_score: 0.3 (never flag nurture as high urgency)
  → action: "Send a warm value-adding touchpoint - industry insight, relevant case study, or light check-in"
  → reason: "Account is in nurture stage - maintain relationship until next buying cycle"
  → draft_recommended: true (one draft only)
pipeline_review_ready: always FALSE for nurture accounts.

==============================================================================
AI FORECAST - AMOUNT AND CLOSE DATE (pov_amount, pov_close_date)
==============================================================================

You have the full picture now. Set these two fields:

pov_amount - What will this deal realistically close at?
  Commit + MEDDPICC >70% + champion active = CRM amount
  Best Case = 70-90% of CRM amount
  Pipeline (thin qual, no champion) = 30-60% of CRM (expect scope reduction to pilot first)
  Omit (stalling, past close date, no MAP) = 0-30% of CRM or 0
  No champion on a $500K+ deal = assume pilot at $50-100K to start

pov_close_date - When will this realistically close? Format: YYYY-MM-DD
  The current date is supplied in the deal context below. Always set this for Proposal/Qualified stage - never leave null.
  CRM date passed + no MAP + momentum stalling → push 90-180 days from today
  CRM date passed + champion active + MAP exists → push 30-60 days (recoverable)
  Accelerating deal with MAP in place → CRM date may be achievable, push 2-4 weeks max
  Omit deal → minimum 90 days from today regardless of CRM date

OUTPUT: Top 3 actions. Each must have: action, reason, urgency_score, meddpicc_component (if applicable), framework_rationale.
Also output pov_amount and pov_close_date."""


def _build_training_section(training_signals: list) -> str:
    """Format the last N declined drafts into a prompt section for pattern avoidance."""
    if not training_signals:
        return ""
    lines = []
    for ts in training_signals[-_TRAINING_SIGNAL_WINDOW:]:
        category = f" ({html.escape(str(ts['training_category']))})" if ts.get("training_category") else ""
        reason = f" - reason: {html.escape(str(ts['decline_reason']))[:_DECLINE_REASON_MAX_CHARS]}" if ts.get("decline_reason") else ""
        lines.append(f"  - {ts.get('date', '?')}: declined{category}{reason}")
    return f"""
=== TRAINING SIGNALS (drafts rep declined for this account) ===
{chr(10).join(lines)}

IMPORTANT: Do NOT recommend the same action type or framing that has been repeatedly declined.
If champion_reengagement has been declined 3x: try a different approach or different draft type.
If roi_business_case was declined as 'wrong timing': don't surface ROI framing until stage advances.
Use this history to improve recommendation relevance.
"""


def _build_user_message(
    account_name: str,
    current_state: dict,
    risk_result: RiskResult,
    grounding_result: GroundingResult,
    rep_bandwidth: float,
    meddpicc_dict: dict,
    critical_gaps: list[str],
    moderate_gaps: list[str],
    three_whys: dict,
    training_section: str,
    today_str: str,
) -> str:
    """Assemble the per-run user message for the LLM.

    Structured data (signals, stakeholders, memory) is JSON-serialised and
    sent verbatim. These blocks are internal app data, not user-supplied free
    text, so html.escape is not applied — the LLM treats them as data, not
    instructions. If any source of these blocks becomes user-controlled in
    future, add sanitisation here.
    """
    meddpicc = risk_result.meddpicc
    return f"""
<deal_context>
Account: {_q(account_name)}
Stage: {_q(current_state.get('stage', 'Unknown'))}
Deal Amount: ${current_state.get('deal_amount') or 0:,.0f}
Close Date: {_q(str(current_state.get('close_date', 'Not set')))}
Today's Date: {today_str}
Rep Bandwidth: {rep_bandwidth:.0%} available
Conversation Intel: {_q(_conv_intel_line(current_state))}
</deal_context>

=== RISK ASSESSMENT ===
Health Score: {risk_result.health_score or 0:.2f} (delta: {risk_result.health_score_delta or 0:+.2f})
Deal Momentum: {_q(str(risk_result.deal_momentum))}
AI POV: {_q(str(risk_result.pov_forecast_category))} ({risk_result.pov_forecast_confidence or 0:.0%} confidence)
Close Date Integrity: {_q(str(risk_result.close_date_integrity))}

5 Risk Vectors:
  Champion Risk:    {_q(str(risk_result.champion_risk))}
  Competition Risk: {_q(str(risk_result.competition_risk))}
  Timeline Risk:    {_q(str(risk_result.timeline_risk))}
  Economic Risk:    {_q(str(risk_result.economic_risk))}
  Stakeholder Risk: {_q(str(risk_result.stakeholder_risk))}

=== MEDDPICC SCORES ===
{json.dumps(meddpicc_dict, indent=2)}
Critical Gaps (score <0.4): {', '.join(critical_gaps) or 'None'}
Moderate Gaps (score 0.4-0.65): {', '.join(moderate_gaps) or 'None'}
Gap Risk Level: {meddpicc.gap_risk if meddpicc else 'unknown'}

=== 3 WHYS ASSESSMENT ===
Why Change: {_why_line(three_whys, 'why_change')}
Why Now:    {_why_line(three_whys, 'why_now')}
Why Us:     {_why_line(three_whys, 'why_us')}

=== VERIFIED SIGNALS ===
{json.dumps([s.model_dump() for s in grounding_result.verified_signals], indent=2)}

=== UNVERIFIED CLAIMS (treat with caution) ===
{json.dumps(grounding_result.unverified_claims, indent=2)}

=== STAKEHOLDERS ===
{json.dumps(current_state.get('stakeholders', []), indent=2)}

=== EPISODIC MEMORY (last 5 cycles — older history is noise for action selection) ===
{json.dumps(current_state.get('memory', {}).get('episodic', [])[-5:], indent=2)}

=== PROCEDURAL MEMORY (what works for this account) ===
{json.dumps(current_state.get('memory', {}).get('procedural', []), indent=2)}
{training_section}

=== CUSTOM AI FIELDS (workspace intelligence questions) ===
{json.dumps(current_state.get('ai_fields_extracted') or {}, indent=2)}
(If any field signals urgency - regulatory pressure, contract expiry, expansion trigger, competitor evaluation - reflect this in action urgency scoring.)

Generate the top 3 prioritised actions. Use the frameworks above.
Each action must: address a specific gap, have a framework_rationale, and include draft_type if draft_recommended.
"""


class PrioritiserAgent(BaseAgent):
    """
    Converts verified signals and MEDDPICC gaps into prioritised next actions.
    Every action is mapped to a specific framework component.
    """

    async def run(
        self,
        account_name: str,
        current_state: dict,
        grounding_result: GroundingResult,
        risk_result: RiskResult,
        rep_bandwidth: float = 1.0,
    ) -> PrioritiserResult:

        meddpicc = risk_result.meddpicc
        meddpicc_dict = meddpicc.model_dump() if meddpicc else {}

        critical_gaps, moderate_gaps = _classify_meddpicc_gaps(meddpicc, meddpicc_dict)

        three_whys = risk_result.three_whys_assessment or {}

        training_section = _build_training_section(current_state.get("training_signals", []))

        today_str = _date.today().isoformat()

        # None means the rep bandwidth was never recorded — treat as fully available
        # rather than silently zeroing it, which would skew action prioritisation.
        effective_bandwidth = rep_bandwidth if rep_bandwidth is not None else 1.0

        user_message = _build_user_message(
            account_name=account_name,
            current_state=current_state,
            risk_result=risk_result,
            grounding_result=grounding_result,
            rep_bandwidth=effective_bandwidth,
            meddpicc_dict=meddpicc_dict,
            critical_gaps=critical_gaps,
            moderate_gaps=moderate_gaps,
            three_whys=three_whys,
            training_section=training_section,
            today_str=today_str,
        )

        result_dict = await self._call_llm(
            system_prompt=PRIORITISER_SYSTEM_PROMPT,
            user_message=user_message,
            tool_name="prioritiser_result",
            tool_schema=PrioritiserResult.model_json_schema(),
            max_tokens=_MAX_OUTPUT_TOKENS,
        )

        result = self.parse_output(PrioritiserResult, result_dict)
        log.info(
            "prioritiser_complete",
            account=account_name,
            actions=len(result.next_actions),
            urgency_score=result.urgency_score,
            draft_actions=sum(1 for a in result.next_actions if a.draft_recommended),
            pipeline_review_ready=result.pipeline_review_ready,
            top_risk=result.top_risk_summary[:60] if result.top_risk_summary else None,
        )
        return result
