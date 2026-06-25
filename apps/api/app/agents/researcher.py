"""
ResearcherAgent - Extracts new intelligence from raw signals.
Model: Claude Haiku 4.5 (cheap, fast, high volume)
Cost: ~$0.02/account

Frameworks implemented:
  - MEDDPICC observation extraction from all signal sources
  - 30+ signal type detection (vs 10 in v1)
  - Multi-threading gap detection
  - Deal velocity signals (days in stage, slip count, engagement trend)
  - Engagement decay pattern recognition
  - Close plan / MAP signal detection
  - Stakeholder role classification (Economic Buyer vs Champion vs Decision Maker)
  - ICP fit scoring (0-1) with tier classification
"""
import html
import json
from typing import Optional
from app.agents.base import BaseAgent, ResearchResult, SIGNAL_TYPES
import structlog

log = structlog.get_logger()

# Token/character budget constants — tuned for Haiku 4.5's ~25k context window.
# Each transcript chunk + header adds ~750–900 tokens; 5 calls × 3 000 chars fits
# comfortably alongside the CRM/signal context without hitting the context ceiling.
_MAX_TRANSCRIPTS = 5       # maximum call transcripts included per run
_TRANSCRIPT_CHAR_LIMIT = 3000  # chars per transcript (≈ 750 tokens)
_MAX_OUTPUT_TOKENS = 3500  # ResearchResult JSON routinely reaches 2k–3k tokens

# Prompt-assembly constants — kept here so changes ripple through all call sites.
_RECENT_SIGNALS_WINDOW = 10   # trailing signals shown to prevent duplication
_TRANSCRIPT_ID_DISPLAY_LEN = 12  # chars of transcript ID shown in block header
_MULTITHREADING_RISK_AMOUNT = 50_000  # deal amount ($) above which single-thread is flagged


def _escape(v: object) -> str:
    """Escape a value for safe insertion into the LLM prompt XML."""
    return html.escape(str(v)) if v is not None else ""


def _iso_date(v: object) -> str:
    """Normalise a date value to a 10-char ISO-8601 string (YYYY-MM-DD)."""
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    s = str(v)
    return s[:10] if len(s) > 10 else s

RESEARCHER_SYSTEM_PROMPT = f"""You are a senior enterprise sales intelligence analyst. Your job is to
extract actionable B2B sales intelligence from raw signals for a specific account.

==============================================================================
SIGNAL TAXONOMY - use ONLY these types:
{SIGNAL_TYPES}
==============================================================================

EXTRACTION RULES:
1. Only report signals with clear evidence. Never infer without a cited source.
2. Confidence: real-time data (0.9+) > CRM notes (0.7) > inferred from pattern (0.5)
3. Never duplicate a signal that already exists in the current account state.
4. If evidence is ambiguous, report it as unverified with reason.
5. For every signal, set meddpicc_component if it touches qualification.
6. CONFIRMED FUTURE MEETINGS are absolute ground truth. If `upcoming_confirmed_meetings`
   lists a booking (e.g. July 10), that IS the meeting date — use it verbatim in all signals
   and next-step summaries. A date mentioned in an email (e.g. "July 7 reference call") is
   only a proposal; it is superseded the moment a confirmed booking exists on the calendar.
   Never write a draft or signal that references the proposed email date when a confirmed
   calendar date is present.

MEDDPICC EXTRACTION - scan every source for:
- Metrics: Any mention of ROI, cost savings, revenue impact, business case numbers
- Economic Buyer: Anyone described as signing authority, budget owner, "final say"
- Decision Criteria: Evaluation criteria, requirements, RFP criteria, scorecard
- Decision Process: Approval steps, committee, procurement, security review, legal
- Implicate Pain: Business pain, cost of inaction, urgency drivers, "why we need this"
- Champion: Internal advocate, sponsor, someone who "pushes internally", evangelist
- Competition: Any competitor mentioned (Gong, Clari, Salesforce, etc.)
- Paper Process: Legal, procurement, security questionnaire, NDA, SOW, MSA activity

STAKEHOLDER ROLE MAPPING:
- economic_buyer: Controls or approves budget. Can say YES alone.
- champion: Believes in you, has internal credibility, sells internally for you.
- decision_maker: Signs off but may not control budget (different from EB).
- technical_buyer: Evaluates the product technically (IT, security, integration).
- user_buyer: Daily users who care about usability.
- influencer: Has opinion but no direct authority.
- blocker: Actively working against the deal.
Use these precisely - misclassifying EB vs champion is the #1 enterprise deal failure.

CHAMPION IDENTIFICATION — EVIDENCE LADDER (most → least reliable):
Tier 1 — CONFIRMED champion (role = champion, high confidence):
  - Attended 2+ Fireflies calls AND their job title matches HSE Manager / HSQE Director /
    Safety Manager / EHS Director / VP Safety — these are the primary buyer roles.
  - Has replied to emails AND referenced internal approvals, internal stakeholders, or
    budget discussions. Replies alone ≠ champion; replies with internal context = champion.
  - Explicitly said "I'll take this to my team", "I support this", or similar internal advocacy.

Tier 2 — LIKELY champion (role = champion, moderate confidence):
  - Appeared in Fireflies call participant list (they showed up to the call).
  - Has replied to at least one email (inbound reply recorded in HubSpot).
  - Job title matches the champion profile but no call attendance confirmed.

Tier 3 — CONTACT only (role = influencer or unknown until more evidence):
  - Only cc'd on emails, never replied directly.
  - Listed in HubSpot contacts but zero engagement activity.
  - Email domain is a vendor or partner, not the actual buyer company — flag this explicitly
    as a CRITICAL risk (contact may not be a real buyer).

CHAMPION DARK DETECTION:
- If previous champion is Tier 1/2 but has not replied or attended a call in 30+ days
  while the deal is in Proposal/Negotiate/Decision stage → champion_dark signal.
- Always note the last confirmed engagement date when flagging champion_dark.

MULTI-THREADING FROM FIREFLIES:
- If Fireflies shows participants not in HubSpot contacts, flag them as new_contact_identified
  signal with the participant email — these are real people who attended a call and may need
  to be added to the deal in HubSpot.
- Count unique participant emails across all transcripts. If only 1 unique participant from
  the buyer side across all calls → single_thread_risk signal.

MULTI-THREADING DETECTION:
Count distinct engaged contacts. If only 1 contact engaged = single_thread_risk signal.
Enterprise deals need 3+ multi-threaded contacts to survive champion departure.

==============================================================================
INVIGILO AI - ICP & PRODUCT CONTEXT (for ICP scoring and signal interpretation)
==============================================================================
Invigilo sells SafeKey - AI safety monitoring that works on existing CCTV cameras.
Ideal Customer Profile (ICP - strong fit):
  - Industry: Construction, Oil & Gas (upstream/midstream/downstream), Manufacturing, Mining, Logistics
  - Size: 500+ employees, multi-site operations
  - Existing CCTV: Already has cameras (SafeKey adds AI, no new hardware needed)
  - Compliance pressure: OSHA, ISO 45001, Ministry of Labour (KSA/UAE), NOPSEMA (Australia), WSH (Singapore)
  - Has dedicated HSQE/HSE team and appointed safety officers
  - Geography: MENA (KSA, UAE, Oman, Kuwait), Singapore, ANZ, Japan

ICP Signals (boost ICP score):
  - HSE Director / HSQE Manager involved = champion match (core buyer)
  - Mentions of safety incidents, regulatory audit, accident rate = high implicate pain
  - Multi-site operations with existing VMS/CCTV = perfect technical fit
  - Government-linked company or NOC = longer cycle but high-value, compliance-driven
  - Recent safety fine or incident investigation = immediate urgency trigger (why_now)

NOT ICP (reduce ICP score):
  - Small office/retail without industrial operations
  - Pure software/tech company with no physical operations
  - No existing CCTV infrastructure and no budget for cameras
  - Consumer-facing business

Competitors to flag when mentioned: Voxel, Chooch AI, Protex AI, viAct, StereoVision, Intenseye, Anvil, Spot-r.
If a competitor is mentioned, always create a competitive_evaluation_active or competitive_mention signal.
Note Voxel's weakness (requires camera upgrades) and Intenseye's weakness (no on-premise, EU-only focus).

DEAL VELOCITY SIGNALS:
Extract these velocity indicators from CRM/notes/activity:
- days_in_stage: How long has deal been in current stage? >45 days in same stage = stalling
- close_date_slips: How many times has close date moved? >=2 slips = deal_slip signal
- last_meaningful_activity_days: Days since a real conversation (call/meeting/substantive email)
- engagement_trend: "improving" | "flat" | "declining" based on response pattern

CLOSE PLAN / MAP DETECTION:
If any note mentions "mutual action plan", "close plan", "evaluation timeline", "next steps agreed",
"success criteria defined" - this is a mutual_action_plan_created signal (positive).
If none of these exist and deal is past Qualification stage - close_plan_missing signal (risk).

GOLD DATA LAYER:
For conflicting facts across sources (e.g. close date in CRM ≠ close date in email),
include gold_sources with all values so Grounding Agent can resolve.

TRANSCRIPT ANALYSIS (for call/meeting recordings):
When transcripts are available, explicitly extract:
1. COMPETITIVE MENTIONS: Any competitor named in the call (Intenseye, Protex AI, viAct, Voxel,
   StereoVision, Anvil, Samsara, any VMS/CCTV vendor). Quote the exact mention.
2. CHAMPION SIGNALS: Rep-side champion advocacy - things they said they'd do internally,
   pushback they gave, internal support expressed. Did they refer to a specific budget owner?
3. OBJECTIONS RAISED: Price, timeline, integration, vendor risk, internal approval barriers.
   Quote specific objections - these are the real decision criteria.
4. COMMITMENTS MADE: "I'll check with..." / "We can move by..." / "Send me the..." - track these.
5. PAIN CONFIRMED: Specific problems the buyer confirmed (incidents, compliance pressure,
   manual processes, cost of current state). Map to MEDDPICC Implicate Pain.
6. UNRESOLVED: Questions raised but not answered. Topics deferred. Red flags the rep didn't address.

Every transcript signal should cite the source as "fireflies:transcript/{id}" or "gong:call/{id}"."""


def _format_transcript(call: dict) -> str:
    """Format a single call/interaction dict into a prompt-safe transcript block.

    Handles both Gong (transcript key) and Fireflies (notes/brief key) shapes.
    Transcript text is HTML-escaped before insertion to prevent prompt injection
    from attacker-controlled CRM notes or third-party transcript content.
    """
    transcript_text = (
        call.get("transcript", "")
        or call.get("notes", "")
        or call.get("brief", "")
    )
    raw_date = call.get("occurred_at") or call.get("date") or "unknown date"
    date = _iso_date(raw_date)
    title = call.get("fireflies_transcript_id", "") or call.get("id", "")
    header = f"\n\n=== Call/Meeting Transcript ({date}) {'[' + str(title)[:_TRANSCRIPT_ID_DISPLAY_LEN] + ']' if title else ''} ===\n"
    # Escape before truncation so a crafted payload cannot straddle the char boundary
    body = _escape(transcript_text)[:_TRANSCRIPT_CHAR_LIMIT]
    block = header + body
    if call.get("outcome"):
        block += f"\n\nAction items: {_escape(call['outcome'])}"
    return block


def _build_prompt_sections(workspace_settings: dict | None) -> tuple[str, str]:
    """Return (icp_section, ai_fields_section) strings for the researcher prompt.

    ai_fields come from workspace config and are JSON-serialised here so the
    LLM sees a stable schema regardless of field ordering in the DB record.
    """
    icp_section = """
=== ICP SCORING ===
Score this account's ICP fit (0-1) for a B2B AI safety platform targeting enterprise companies
in O&G, construction, manufacturing, mining (MENA/APAC focus, $50K+ deals).
Extract: icp_score.score (0.0-1.0), icp_score.tier (strong/moderate/weak/unknown),
icp_score.signals (list of matching ICP factors), icp_score.gaps (list of ICP mismatches).
"""
    ai_fields_section = ""
    ws = workspace_settings or {}
    ai_fields = ws.get("ai_fields") or []
    if ai_fields:
        ai_fields_section = f"""
=== CUSTOM AI FIELDS ===
Answer these workspace-defined questions based on available evidence. Return null if no evidence.
{json.dumps(ai_fields, indent=2)}
Store answers in: ai_fields_extracted: {{"field_key": "answer or null"}}
"""
    return icp_section, ai_fields_section


def _build_activity_section(activity_sum: dict) -> str:
    """Render the <activity_context> XML block from a HubSpot activity summary dict.

    All user-controlled fields are HTML-escaped before insertion. recent_email_history
    is serialised via json.dumps (not raw repr) to prevent prompt-injection via
    attacker-controlled email subject lines or body snippets stored in HubSpot.
    """
    if not activity_sum:
        return ""

    # Tiny helper so the 8 repeated `_escape(activity_sum.get(K)) or 'fallback'`
    # patterns in the f-string stay readable without repeating the full expression.
    def _f(key: str, fallback: str = "Unknown") -> str:
        return _escape(activity_sum.get(key)) or fallback

    upcoming = activity_sum.get('upcoming_confirmed_meetings') or []
    upcoming_str = (
        "\n".join(
            f"  - {_escape(m['date'])} | {_escape(m['title'])} | status={_escape(m['status'])}"
            for m in upcoming
        )
        if upcoming else "  None on calendar"
    )
    # Serialize the list so embedded special chars cannot break the XML structure.
    recent_email_history = json.dumps(
        activity_sum.get('recent_email_history') or [],
        ensure_ascii=True,
    )
    return f"""
<activity_context>
=== PRECISE ACTIVITY TIMELINE (from HubSpot + interactions DB) ===
Deal created in HubSpot: {_f('deal_created_at')}
First contact date: {_f('first_contact_date')}
Last meaningful activity: {_f('last_meaningful_activity_date')} ({activity_sum.get('days_since_last_activity', '?')} days ago)
Last inbound reply from prospect: {_f('last_inbound_reply_date', 'None recorded')} ({activity_sum.get('days_since_last_inbound', '?')} days ago)
Last outbound email sent: {_f('last_outbound_email_date', 'None recorded')} ({activity_sum.get('days_since_last_outbound', '?')} days ago)
Last meeting: {_f('last_meeting_date', 'None recorded')}
Total email exchanges: {activity_sum.get('email_exchange_count', 0)} ({activity_sum.get('total_emails_sent', 0)} sent, {activity_sum.get('total_emails_received', 0)} received)
Total meetings: {activity_sum.get('total_meetings', 0)} | Calls: {activity_sum.get('total_calls', 0)} | Fireflies transcripts: {activity_sum.get('total_fireflies_transcripts', 0)}
Engagement depth: {activity_sum.get('engagement_depth', 'unknown')}
Recent emails: {recent_email_history}

*** UPCOMING CONFIRMED MEETINGS (booked in HubSpot calendar) ***
{upcoming_str}
These are CONFIRMED bookings — treat the dates as ground truth.
If any upcoming meeting exists, it OVERRIDES any proposed/mentioned date in emails.
A "proposed" date in an email is NOT the meeting date if a confirmed booking shows a different date.

USE THIS DATA for all temporal signals (champion_dark, deal_slip, days_since_meaningful_activity).
Do NOT estimate dates -- use the values above as ground truth.
</activity_context>
"""


class ResearcherAgent(BaseAgent):
    """
    Processes raw signals (HubSpot delta, Gong calls, Perplexity news)
    and extracts structured intelligence using MEDDPICC and B2B frameworks.
    """

    async def run(
        self,
        account_name: str,
        current_state: dict,
        raw_signals: list[dict],
        gong_transcripts: list[dict] = None,
        news_content: str = "",
        workspace_settings: dict | None = None,
    ) -> ResearchResult:

        gong_text = "".join(
            _format_transcript(call)
            for call in (gong_transcripts or [])[:_MAX_TRANSCRIPTS]
        )

        # Summarise existing signals to avoid duplication
        existing_signal_types = [
            f"{s.get('type')}: {s.get('detail', '')[:80]}"
            for s in current_state.get("signals", [])[-_RECENT_SIGNALS_WINDOW:]
        ]

        # Existing stakeholders for context
        existing_stakeholders = current_state.get("stakeholders", [])
        contact_count = len([
            s for s in existing_stakeholders
            if s.get("engagement_level") in ("highly_engaged", "engaged")
        ]) or len(existing_stakeholders)

        # CRM activity context for velocity signals
        last_contacted = current_state.get("last_contacted", "")
        next_activity = current_state.get("next_activity", "")

        activity_section = _build_activity_section(
            current_state.get("activity_summary", {})
        )

        icp_section, ai_fields_section = _build_prompt_sections(workspace_settings)

        user_message = f"""
<deal_context>
Account: {_escape(account_name)}
Stage: {_escape(current_state.get('stage', 'Unknown'))}
Deal Amount: ${current_state.get('deal_amount') or 0:,.0f}
Close Date: {_escape(str(current_state.get('close_date', 'Not set')))}
Last Agent Run: {_escape(str(current_state.get('last_updated', 'Never')))}
</deal_context>

=== CURRENT STATE CONTEXT ===
Summary: {_escape(current_state.get('summary', 'No summary yet'))}
Known Stakeholders ({len(existing_stakeholders)} total, {contact_count} engaged):
{json.dumps(existing_stakeholders, indent=2)}
CRM Last Contacted: {_escape(last_contacted or 'Unknown')}
CRM Next Activity: {_escape(next_activity or 'None scheduled')}

EXISTING SIGNALS (do NOT duplicate):
{chr(10).join(existing_signal_types) or 'None yet'}

Previous MEDDPICC State:
{json.dumps(current_state.get('pov', {}).get('meddpicc', {}), indent=2)}
{activity_section}
<raw_signals>
=== NEW RAW SIGNALS (last 24h) ===
{json.dumps([{k: _escape(v) if isinstance(v, str) else v for k, v in s.items() if k != 'raw'} for s in raw_signals], indent=2)}
</raw_signals>

=== GONG / CALL TRANSCRIPTS ===
<transcripts>
{gong_text if gong_text else 'No new calls'}
</transcripts>

=== EXTERNAL NEWS AND WEB INTELLIGENCE (unverified third-party content) ===
<external_research>
{_escape(news_content) if news_content else 'No new news'}
</external_research>
{icp_section}
{ai_fields_section}
EXTRACTION TASKS:
1. Extract all new signals using the taxonomy. Cite sources precisely.
2. Update any stakeholders - classify their ROLE carefully (economic_buyer vs champion vs decision_maker).
3. Extract MEDDPICC observations: for each component, note what evidence exists or is missing.
4. Compute deal velocity: estimate days_in_stage, close_date_slips, last_meaningful_activity_days, engagement_trend.
5. Flag multi-threading risk if only 1 engaged contact for a deal >${_MULTITHREADING_RISK_AMOUNT:,}.
6. Flag close_plan_missing if no MAP evidence exists and deal is in Proposal/Negotiate/Decision stage.
7. Score the ICP fit (icp_score field) based on available evidence.
8. RESOLVED SIGNALS - populate resolved_signals with signal types that were previously active
   but are now clearly resolved based on evidence in THIS run's context (emails, calls, HubSpot
   activity). Only mark as resolved if there is explicit evidence of completion - not just absence
   of new mentions. Examples:
   - legal_review_started → resolved if NDA/DPA was signed and confirmation email exists
   - champion_dark → resolved if champion replied or attended a meeting recently
   - procurement_engaged → resolved if contract was executed or PO was issued
   - budget_risk → resolved if budget was explicitly confirmed by the economic buyer
   - competitive_evaluation_active → resolved if buyer confirmed they chose Invigilo
   Use exact signal type strings from the taxonomy.
"""

        result_dict = await self._call_llm(
            system_prompt=RESEARCHER_SYSTEM_PROMPT,
            user_message=user_message,
            tool_name="research_result",
            tool_schema=ResearchResult.model_json_schema(),
            max_tokens=_MAX_OUTPUT_TOKENS,
        )

        result = self.parse_output(ResearchResult, result_dict)
        log.info(
            "researcher_complete",
            account=account_name,
            signals_found=len(result.new_signals),
            stakeholders_updated=len(result.updated_stakeholders),
            meddpicc_observations=len(result.meddpicc_observations),
        )
        return result
