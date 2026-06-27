"""
DrafterAgent - Enterprise sales writing engine.
Model: Claude Sonnet 4.6 (quality writing)
Cost: ~$0.10/account

Draft types supported:
  email_followup         - Standard follow-up after a touchpoint
  meeting_brief          - Pre-call intelligence brief (structured scannable)
  roi_business_case      - Quantified ROI/value justification email
  competitive_displacement - Competitive positioning email (champion talking points)
  executive_alignment    - Exec-to-exec alignment (seller VP → buyer EB)
  close_plan_proposal    - Mutual Action Plan / close plan email
  champion_reengagement  - Warm-direct re-engagement when champion is dark
  outreach_sequence      - Multi-touch cold/warm outreach sequence
"""
import html
import json
import re
from datetime import date
from app.agents.base import (
    BaseAgent, DrafterResult, PrioritiserResult,
    GroundingResult, RiskResult
)
from app.config import get_settings
import structlog

log = structlog.get_logger()


def _q(v) -> str:
    """HTML-escape any user-controlled value before it lands in an LLM prompt.
    Prevents prompt-injection via CRM fields (account name, stakeholder names, etc.)."""
    return html.escape(str(v))


_PRODUCT_CONTEXT = """You write sales emails AS the sender identified in the SENDER section of the user message.
Voice fidelity is the top priority. Every draft must sound like it came from a real person, not from a sales playbook or an AI.
Use the sender's name, title, company, and product description from the SENDER section — never invent details.
ONLY reference product specifics from the SENDER section. Never force in details that do not match the account's context.
"""

# Sender voice + hard writing rules. Shared by EVERY surface that writes emails:
# the DrafterAgent here and the PlaysEngine auto-draft path. If a new
# generation path is added, it must include this block — a draft that doesn't
# use the right voice is a bug, regardless of which engine produced it.
VISHNU_VOICE_DNA = """
==============================================================================
SENDER VOICE - EMAIL WRITING RULES
==============================================================================
These patterns produce clean, direct, human-sounding emails. Replicate them.

GREETING:
- Government contacts / new prospects: "Dear [First Name],"
- Warm / established contacts: "Hi [First Name],"
- Never "Dear Sir/Madam", never "To Whom It May Concern"

OPENERS (first sentence after greeting):
- "Hope you are doing well." (most common - NOT "I hope this email finds you well")
- "Hope you are good."
- Direct acknowledgement when replying: "Yes, [confirm their point]." or "Sounds good!"
- Situation-specific hook with no opener when the context is obvious
- NEVER: "I hope this email finds you well", "I trust you are well", "I wanted to reach out",
  "I'm reaching out to", "I am writing to", "I hope this message finds you"

SENTENCE RHYTHM:
- Short sentences. One thought per sentence. 8-15 words each.
- New paragraph for each new point. One to three sentences per paragraph.
- Uses "Also" to add a related point: "Also wanted to share..." / "Also noted on..."
- Informal connectors feel natural: "so it's the same flow", "I am guessing", "I believe"
- Occasionally drops articles for rhythm: "forward it to necessary folks" not "the necessary folks"
- "!" used sparingly for genuine warmth: "Thank you!", "Sounds good!" Not in every sentence.

PHRASES VISHNU ACTUALLY USES (use these, they are real):
- "Let me know if this helps."
- "Let me know if this answers your question."
- "Let me know where things stand."
- "I look forward to hearing back." (always "hearing back", never "hearing from you")
- "Please do give us a headsup when that happens."
- "Also noted on [X], understand that."
- "Also wanted to share that..."
- "I will forward it to necessary folks."
- "Sounds good!" as a standalone opener on a reply.
- "Thank you!" as a standalone sentence.
- "Looking forward to hearing back."

SIGNATURE (use the sender's actual name and title from the SENDER section):
  Thanks and Regards,
  [Sender Name from SENDER section]
  [Sender Title], [Sender Company]

EMAIL LENGTH:
- Established contacts: under 200 words. Shorter is better.
- New prospects: under 350 words.
- Never pad. If you have said what needs to be said in 3 sentences, stop.

NUMBERS AND DATES:
- Numbers: always exact. $3M not "3 million". SGD 145K not "approximately SGD 145,000".
- Dates: never calculate day counts. Write "a few weeks ago", "some time back", "recently". Not "43 days ago" or "since April 9".

==============================================================================
HARD RULES - ZERO EXCEPTIONS
==============================================================================
1. NO EM-DASHES. The character — must never appear. Use a comma or period instead.
   Wrong: "SafeKey works on your cameras — no hardware needed."
   Right: "SafeKey works on your cameras. No hardware needed."
2. NO EN-DASHES as punctuation. A hyphen in compound words is fine. A dash used like a comma is not.
3. NO AI WRITING TELLS. These phrases instantly signal AI and must never appear:
   - "I hope this email finds you well" / "I trust this finds you well"
   - "I wanted to reach out" / "I'm reaching out"
   - "Please don't hesitate to contact me"
   - "Please feel free to reach out"
   - "I would be happy to" / "I'd be delighted to"
   - "It is worth noting that" / "It's worth mentioning"
   - "As mentioned previously" / "As per our previous conversation"
   - "I would like to take this opportunity"
   - "In today's fast-paced environment"
   - "Furthermore" / "Moreover" / "Additionally" (use "Also" instead)
   - "Leverage" as a verb
   - "Touch base", "pain point", "best-in-class", "synergy", "streamline", "robust"
   - "Kindly" (never)
   - "Best regards" (always "Thanks and Regards,")
4. NO BULLET LISTS in outbound emails to buyers. Prose only for email types.
   (Bullets are fine in meeting_brief and similar internal-facing briefs.)
5. ONE ASK per email. Never "let's discuss, review, and schedule" - pick one action.
6. BE SPECIFIC. Reference the exact fact or signal that triggered this draft.
7. CITE EVERY FACT to its source. The rep needs to know where each claim comes from.
8. PLAIN TEXT for outbound emails (email_followup, executive_alignment, champion_reengagement,
   expansion_pitch, outreach_sequence, nurture_cadence). No **, no ##, no bold.
9. NEVER add meta-headers inside content: no "Draft Type:", "To:", "From:", "---" dividers.
   Content field = email body only.
10. Max 2 drafts per run. Quality over volume.
11. Use the actual sender name. Never write [Rep Name] or [Your Name].
12. NO UNFILLED PLACEHOLDERS. Never output "[their priority]", "[company name]", "[insert here]",
    or any bracketed stand-in. If you do not have the specific fact, write around it or cut the
    sentence entirely. A draft with a placeholder is worse than a shorter draft without one.
13. NO DATE-ANCHORED SUBJECT LINES. Never write subject lines containing specific months
    ("before we close out May"), quarter references ("Q2 close"), or day-of-week hooks.
    Use timeless hooks tied to the deal situation instead.
14. ULTIMATUM LANGUAGE IS FORBIDDEN: "I'll make this simple", "either...or",
    "the ball is in your court", "you committed", "that window has passed".
"""

_DRAFT_TYPE_GUIDANCE = """
==============================================================================
DRAFT TYPE GUIDANCE
==============================================================================

email_followup:
  Hook: reference exactly what triggered this (a meeting, signal, news item)
  Value: one relevant point tied to their stated priorities
  Ask: one clear, low-friction next step ("30-minute call", "your thoughts on X")

meeting_brief:
  ## Call: [account name]
  **Objective:** [One thing to achieve in this call]
  **Account context:** [Stage, deal amount, days to close date]
  **Stakeholders on call:** [Name, role, sentiment, last contact]
  **Since last call:** [Key changes: max 3 bullets]
  **Champion brief:** [Champion's position, what they need from this call]
  **MEDDPICC gaps to probe:** [Top 2 gaps with suggested questions]
  **3 Whys status:** [Which are confirmed, which need work]
  **Key risks to address:** [What could derail this call, max 2]
  **Competitive landmines:** [What NOT to say, what competitor is saying]
  **Recommended questions:** [3 specific questions, referenced to context]
  **Desired outcome:** [Specific next step to propose at end of call]

roi_business_case:
  Subject: [Specific financial outcome] for [Company] by [timeframe]
  Structure: Current state / cost of status quo -> Quantified impact -> Conservative ROI -> Ask: review together?
  Tone: analytical, peer-to-peer, not a pitch. A shared calculation.
  Include specific numbers from their context.

competitive_displacement:
  NOT sent to buyer. Champion talking points only.
  Format: 3-5 points the champion can use in internal conversations.
  Include: questions to ask the competitor that expose weaknesses.
  Tone: confident and fact-based, never disparaging.

executive_alignment:
  4-6 sentences max. Exec-to-exec is shorter than rep-to-rep.
  Structure: Shared strategic context -> what the champion told me -> outcome for a peer company -> direct ask: 20-min call
  Tone: peer-to-peer, mutual respect. Never reference prior unanswered outreach.

close_plan_proposal:
  Subject: Proposed path to [their stated goal] by [their target date]
  Milestones format: [Date], [Milestone], [Owner]
  Feel collaborative: "this is our proposed draft, happy to adjust"
  Include: security review, procurement, EB sign-off, training, go-live

champion_reengagement:
  Vishnu's approach when someone goes quiet: curious and warm, not accusatory.
  Give them a genuine reason to reply. Show you remembered something specific about them.
  NEVER: "you committed", "that window has passed", ultimatums, "I'll make this simple".
  DO: reference something real from their world (a signal, news, something they mentioned).
  Structure: Warm opener -> one specific reference to something relevant to them -> a single soft ask or genuinely helpful offer
  Tone: Like a trusted advisor checking in. Warm-direct. Not a rep chasing a deal.
  Length: 3-5 sentences. Short. No pitch.
  Subject: something specific or unexpected, not "Following up on [deal name]"
  Example of wrong tone: "You committed to X. That window passed. Either you do Y or Z."
  Example of right tone: "Hope you are doing well. I came across [relevant thing] and thought of our conversation about [their priority]. Would it be useful to reconnect for 30 minutes this week?"

outreach_sequence:
  3-email sequence with distinct hooks. Subject lines included.
  Email 1 (Day 0): Give something useful. No ask. MUST include a one-line self-introduction
    using the sender's name and company from the SENDER section so the recipient knows who is writing.
  Email 2 (Day 4): Reference "my note from earlier this week about [topic]". DO NOT write
    "I realise I did not introduce myself properly." The signature already introduced you.
    Connect the insight from Email 1 to their specific situation. One soft ask.
  Email 3 (Day 9): Customer story + direct ask. "Worth 30 minutes?"
  3-4 sentences each. Never refer to prior unanswered emails in a way that pressures.

renewal_brief:
  ## Renewal Call Brief: [Account Name]
  **Contract end date:** [renewal_date]
  **ARR at stake:** [deal_amount]
  **Account health:** [health_score and trend]
  **Value delivered:** [specific outcomes vs original business case]
  **Champion status:** [champion name, sentiment, engagement level]
  **Renewal risks:** [max 3 bullets]
  **Expansion signals:** [any upsell/cross-sell signals]
  **Recommended questions:** [3 specific questions for the renewal call]
  **Call objective:** [one clear outcome]
  Tone: collaborative, data-driven. Not a sales call.

expansion_pitch:
  3-4 sentences. CSM casual, not sales formal.
  Hook: usage growth, new team adopting, feature milestone.
  Frame as: adding value to something already working, not selling more.
  Ask: "Worth 15 minutes to show [Team X] what [specific workflow] looks like?"
  NEVER use "upsell" or "expansion" in the email itself.

nurture_cadence:
  Purpose: keep warm between cycles. No pressure, no proposals, no timelines.
  3-4 sentences MAX.
  Options: industry insight relevant to them; or a customer story with no ask.
  Subject: something specific to them, not "Checking in".
  NEVER: mention proposals, pricing, timelines, budget, urgency language.

==============================================================================
OUTPUT RULES
==============================================================================
1. draft_type MUST be one of: email_followup | meeting_brief | roi_business_case |
   competitive_displacement | executive_alignment | close_plan_proposal |
   champion_reengagement | outreach_sequence | renewal_brief | expansion_pitch | nurture_cadence
2. Content field = email body only. No meta-headers, no dividers.
3. Sources: for each fact used, include {fact, source, confidence, verified}."""

# Order matters: product context first so voice rules override any style implied
# by the product copy, and draft-type guidance last so it governs the output schema.
DRAFTER_SYSTEM_PROMPT = _PRODUCT_CONTEXT + VISHNU_VOICE_DNA + _DRAFT_TYPE_GUIDANCE

# Voice subset for buyer-facing DOCUMENTS (proposals, decks). The email rules
# (greeting, sign-off) don't apply to document prose, but the anti-AI-tells,
# dash rules and sentence rhythm do — these go out under Vishnu's name.
DOCUMENT_VOICE_RULES = """
VOICE RULES - MANDATORY (this document is sent to buyers under the sender's name):
- NO EM-DASHES (—) and no en-dashes as punctuation. Use a comma or a period instead.
- Short sentences. One thought per sentence. 8-15 words each.
- Banned words and phrases: "leverage" (as a verb), "robust", "streamline",
  "best-in-class", "synergy", "cutting-edge", "state-of-the-art", "pain point",
  "touch base", "kindly", "Furthermore", "Moreover", "Additionally" (use "Also"),
  "It is worth noting", "In today's fast-paced environment".
- Numbers always exact: $3M not "3 million". SGD 145K not "approximately SGD 145,000".
- Confident and direct. No hedging filler ("we believe that", "we are confident that").
- Plain prose. No markdown, no bullets unless the format explicitly asks for them.
"""


def strip_dashes(text: str) -> str:
    """
    Em-dashes are the #1 AI writing tell — enforce in code.
    The prompt forbids them, but the model still slips - enforce in code.
    " — " becomes a period + capitalised next word; word—word becomes a comma;
    en-dash punctuation becomes a comma; hyphenated compounds are kept.
    """
    # Sentence-break: " — word" mid-prose becomes a new sentence
    text = re.sub(r'\s—\s([a-z])', lambda m: ". " + m.group(1).upper(), text)
    # Before capitals/digits (titles, proper nouns, dates): a comma reads wrong
    # ("BRIEF, CLOSE PLAN") — use a plain hyphen separator instead
    text = re.sub(r'\s—\s(?=[A-Z0-9])', ' - ', text)
    # Bare em-dash (word—word) needs a trailing space or it welds the words
    text = text.replace("—", ", ")
    text = re.sub(r'\s–\s', ", ", text)
    text = text.replace("–", "-")
    # Clean artifacts: space-before-comma, double commas, double spaces
    text = re.sub(r'\s+,', ',', text)
    text = re.sub(r',\s*,', ',', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    return text


# Accepted reason codes for rep draft-decline feedback. Anything outside this set
# is noise (e.g. free-text keys from old API clients) and must not reach the prompt.
_DECLINE_KEYS = {
    "wrong_tone", "wrong_timing", "wrong_content", "already_sent",
    "not_relevant", "hallucination", "other",
}

# 10 KB cap: the voice_profile blob can be large; beyond this the prompt ROI
# drops and we risk hitting the context window for the drafter call.
_VOICE_PROFILE_MAX_BYTES = 10240

# [:10] caps opener/CTA samples — more than 10 examples add noise, not signal.
# [:20] caps avoids — the hard-rules section already covers the critical ones.
_VOICE_SAMPLE_OPENERS = 10
_VOICE_SAMPLE_CTAS = 10
_VOICE_SAMPLE_AVOIDS = 20

# Pre-compiled at import time; shared across all nightly accounts (no per-call overhead).
_ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_MONTH_NAMES = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def humanize_dates(text: str) -> str:
    """
    ISO dates ("2026-06-11") read machine-written in rep- and buyer-facing
    prose — convert to "Jun 11, 2026". Months built manually because
    strftime %-d crashes on Windows.
    """
    def _fmt(m):
        try:
            month, day = int(m.group(2)), int(m.group(3))
            if 1 <= month <= 12 and 1 <= day <= 31:
                return f"{_MONTH_NAMES[month]} {day}, {m.group(1)}"
        except (ValueError, IndexError):
            pass
        return m.group(0)

    return _ISO_DATE_RE.sub(_fmt, text)


def polish_prose(text):
    """strip_dashes + humanize_dates — the full pass for any generated text."""
    if not text or not isinstance(text, str):
        return text
    return humanize_dates(strip_dashes(text))


def _sanitize_crm(obj):
    """Recursively HTML-escape all string leaves in a CRM dict/list.
    Top-level-only escaping misses nested objects that json.dumps re-serializes
    verbatim — a crafted nested string could still inject into the LLM prompt."""
    if isinstance(obj, str):
        return html.escape(obj)
    if isinstance(obj, dict):
        return {k: _sanitize_crm(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_crm(item) for item in obj]
    return obj


def _safe_amount(raw) -> float:
    """Return deal_amount as float, defaulting to 0 on non-numeric CRM values.
    HubSpot occasionally stores formatted strings ("1,200,000") or empty strings
    that would crash the nightly run with a ValueError inside the f-string format."""
    if raw is None:
        return 0.0
    try:
        return float(str(raw).replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def _build_stage_overrides(stage: str) -> str:
    """Return prompt override text for stages that need non-default draft behaviour.
    Centralised so adding a new stage (e.g. 'Renewal') touches one dict, not run()."""
    _WON = (
        "\n\n=== WON / CLOSED ACCOUNT OVERRIDE ===\n"
        "This account is a CLOSED / WON customer, not an active prospect.\n"
        "FORBIDDEN draft types: outreach_sequence, close_plan_proposal.\n"
        "VALID draft types for Won accounts: renewal_brief | expansion_pitch | executive_alignment | email_followup\n"
        "Focus on: renewal risk, expansion opportunities, relationship health, post-sale value delivery.\n"
        "Tone: customer success, not sales. You are a trusted vendor, not a seller chasing a deal.\n"
        "=================================\n"
    )
    _OVERRIDES = {
        "To Nurture": (
            "\n\n=== NURTURE STAGE OVERRIDE ===\n"
            "This account is in the 'To Nurture' stage. IGNORE all MEDDPICC urgency framing.\n"
            "ALL drafts must use draft_type: nurture_cadence.\n"
            "Goal: one warm, value-adding touchpoint. No pressure, no proposals, no timelines.\n"
            "=================================\n"
        ),
        "Won": _WON,
        "Closed Won": _WON,
        "closedwon": _WON,
    }
    return _OVERRIDES.get(stage, "")


def _draft_get(draft, field):
    """Read a field from a draft that may be a dict (raw LLM output) or a Pydantic model."""
    return draft.get(field) if isinstance(draft, dict) else getattr(draft, field, None)


def _draft_set(draft, field, value):
    """Write a field to a draft dict or Pydantic model.
    object.__setattr__ bypasses Pydantic's frozen-model guard; safe here because
    we own the instance and are post-processing before it is returned."""
    if isinstance(draft, dict):
        draft[field] = value
    else:
        object.__setattr__(draft, field, value)


def _postprocess_drafts(drafts) -> list:
    """De-duplicate by draft type, apply polish_prose to content + subject_line.
    One draft per type per run — the model occasionally emits two of the same
    type (e.g. two nurture_cadence variants), which floods the rep queue."""
    seen_types: set = set()
    cleaned = []
    for draft in drafts:
        draft_type = _draft_get(draft, "type")
        if draft_type in seen_types:
            log.info("drafter_same_type_dropped", draft_type=draft_type)
            continue
        if draft_type:
            seen_types.add(draft_type)
        _draft_set(draft, "content", polish_prose(_draft_get(draft, "content") or ""))
        subject = _draft_get(draft, "subject_line")
        if subject:
            _draft_set(draft, "subject_line", polish_prose(subject))
        cleaned.append(draft)
    return cleaned


class DrafterAgent(BaseAgent):
    """
    Writes enterprise-quality sales drafts in the sender's voice.
    Every draft type has its own structure and writing methodology.
    """

    async def run(
        self,
        account_name: str,
        current_state: dict,
        prioritiser_result: PrioritiserResult,
        grounding_result: GroundingResult,
        risk_result: RiskResult,
        seller_context: dict | None = None,
        decline_patterns: dict | None = None,
    ) -> DrafterResult:

        settings = get_settings()

        # draft_recommended is set by PrioritiserAgent only when urgency + evidence
        # both cross threshold — filtering here avoids drafting for low-signal actions
        # that would inflate the queue and erode rep trust in surfaced drafts.
        draft_actions = [a for a in prioritiser_result.next_actions if a.draft_recommended]

        if not draft_actions:
            return DrafterResult(drafts=[], drafting_notes="No actions above urgency threshold requiring drafts")

        # Build stakeholder context for personalisation.
        # Stakeholders come verbatim from HubSpot CRM fields — sanitize string values
        # before embedding them in the prompt to prevent injection via crafted CRM data.
        raw_stakeholders = current_state.get("stakeholders", [])
        # _sanitize_crm recurses into nested dicts/lists so injection via nested
        # CRM fields (e.g. stakeholder.notes.body) is also escaped before json.dumps.
        stakeholders = [_sanitize_crm(s) for s in raw_stakeholders] if raw_stakeholders else []
        champion = next((s for s in stakeholders if s.get("role") == "champion"), None)
        economic_buyer = next((s for s in stakeholders if s.get("role") == "economic_buyer"), None)

        # MEDDPICC context for meeting brief
        meddpicc = risk_result.meddpicc
        meddpicc_gaps = meddpicc.gaps if meddpicc else []

        # 3 Whys context
        three_whys = risk_result.three_whys_assessment or {}

        # Stage overrides prevent the model from applying wrong framing (e.g. MEDDPICC
        # urgency on parked accounts, or new-prospect types on existing customers).
        stage = current_state.get("stage", "")
        stage_override = _build_stage_overrides(stage)

        sc = seller_context or {}
        sender_name    = sc.get("sender_name", "")
        sender_title   = sc.get("sender_title", "")
        sender_company = sc.get("sender_company", "")
        product_desc   = sc.get("product_description", "")

        # Voice profile - reinforces system prompt with actual analysed patterns
        voice_section = ""
        voice_profile = sc.get("voice_profile")
        if voice_profile and isinstance(voice_profile, dict) and len(json.dumps(voice_profile)) <= _VOICE_PROFILE_MAX_BYTES:
            openers = ", ".join(f'"{_q(o)}"' for o in voice_profile.get("common_openers", [])[:_VOICE_SAMPLE_OPENERS])
            ctas = ", ".join(f'"{_q(c)}"' for c in voice_profile.get("common_ctas", [])[:_VOICE_SAMPLE_CTAS])
            avoids = ", ".join(_q(a) for a in voice_profile.get("avoids", [])[:_VOICE_SAMPLE_AVOIDS])
            voice_section = (
                f"\n=== ANALYSED WRITING PATTERNS (from {_q(voice_profile.get('emails_analyzed', '?'))} real emails) ===\n"
                f"Tone: {_q(voice_profile.get('tone', ''))}\n"
                f"Avg word count: {_q(voice_profile.get('avg_word_count', '?'))} words\n"
                f"Common openers (use these naturally): {openers or 'varies'}\n"
                f"Common CTAs (use these): {ctas or 'varies'}\n"
                f"Words/phrases to avoid: {avoids or 'none specified'}\n"
                f"Signature style: {_q(voice_profile.get('signature_style', ''))}\n"
            )

        # Rank decline reasons by frequency; top 5 is enough signal for the prompt.
        decline_summary = ", ".join(
            f"{cat} ({n}x)"
            for cat, n in sorted(
                {k: v for k, v in (decline_patterns or {}).items() if k in _DECLINE_KEYS}.items(),
                key=lambda x: -x[1],
            )[:5]
        ) if decline_patterns else ""

        user_message = f"""
=== SENDER (YOU, the person writing these emails) ===
Name:    {_q(sender_name) if sender_name else "Unknown - check workspace settings"}
Title:   {_q(sender_title) if sender_title else "Unknown"}
Company: {_q(sender_company) if sender_company else "Unknown"}
Product: {_q(product_desc) if product_desc else "Unknown - add product_description to workspace settings"}

YOU ARE WRITING AS THE SELLER. {_q(sender_company) if sender_company else "your company"} is selling TO <account>{_q(account_name)}</account>.
All stakeholders listed below are BUYERS at <account>{_q(account_name)}</account>, not your colleagues.
Write entirely in first person. Use "I", "me", "my", "we".
Sign outbound emails as {_q(sender_name) if sender_name else "[configure sender_name in workspace settings]"}.

<deal_context>
Account: {_q(account_name)}
Stage: {_q(current_state.get('stage', 'Unknown'))}
Deal Amount: ${_safe_amount(current_state.get('deal_amount')):,.0f}
Close Date: {_q(str(current_state.get('close_date', 'Not set')))}
Today's Date: {date.today().isoformat()}
Deal Momentum: {_q(str(risk_result.deal_momentum))}
AI POV: {_q(str(risk_result.pov_forecast_category))}
</deal_context>

DATE DISCIPLINE: every date you write (milestones, timelines, follow-up windows)
MUST be in the future relative to Today's Date above. If the CRM Close Date is
already in the past, do NOT plan backward from it — propose a realistic forward
close date and explicitly flag that the CRM date is stale.

=== CHAMPION ===
{json.dumps(champion, indent=2) if champion else 'Not identified'}

=== ECONOMIC BUYER ===
{json.dumps(economic_buyer, indent=2) if economic_buyer else 'Not yet identified'}

=== ALL STAKEHOLDERS ===
{json.dumps(stakeholders, indent=2)}

=== ACTIONS REQUIRING DRAFTS ===
{json.dumps([a.model_dump() for a in draft_actions], indent=2)}

=== VERIFIED INTELLIGENCE (use ONLY these verified facts) ===
{json.dumps([s.model_dump() for s in grounding_result.verified_signals], indent=2)}

=== GOLD DATA POINTS (conflict-resolved facts, highest confidence) ===
{json.dumps({k: v.model_dump(mode="json") for k, v in grounding_result.gold_data_points.items()}, indent=2)}

=== MEDDPICC CONTEXT ===
Gaps to probe: {', '.join(meddpicc_gaps) if meddpicc_gaps else 'None identified'}
3 Whys: why_change={three_whys.get('why_change', {}).get('present', '?')}, why_now={three_whys.get('why_now', {}).get('present', '?')}, why_us={three_whys.get('why_us', {}).get('present', '?')}

=== POV RISKS ===
Risks: {json.dumps(risk_result.pov_risks)}
Competitive risk: {_q(str(risk_result.competition_risk))}

=== REP PROCEDURAL MEMORY ===
{json.dumps(current_state.get('memory', {}).get('procedural', []), indent=2)}

{f"""
=== PAST DECLINE PATTERNS FOR THIS ACCOUNT ===
{decline_summary}
Adjust drafting accordingly: wrong_tone = soften language, reduce urgency language; wrong_content = only verified signals, no speculation; wrong_timing = acknowledge timing in the opening line; hallucination = cite only facts explicitly in the verified intelligence above.
""" if decline_patterns else ""}
Write one draft per action. Maximum 2 drafts total.
For competitive_displacement: champion talking points only, NOT a buyer email.
For executive_alignment: 4-6 sentences, exec-to-exec tone.
For champion_reengagement: warm and curious, specific reference to their world, soft ask. Never accusatory.
Cite all facts to their source.
{stage_override}{voice_section}
"""

        result_dict = await self._call_llm(
            system_prompt=DRAFTER_SYSTEM_PROMPT,
            user_message=user_message,
            tool_name="drafter_result",
            tool_schema=DrafterResult.model_json_schema(),
            max_tokens=5000,
        )

        result = self.parse_output(DrafterResult, result_dict)

        cleaned_drafts = _postprocess_drafts(result.drafts)
        result = DrafterResult(drafts=cleaned_drafts, drafting_notes=result.drafting_notes)

        log.info(
            "drafter_complete",
            account=account_name,
            drafts_written=len(result.drafts),
            draft_types=[d.get("type") if isinstance(d, dict) else d.type for d in result.drafts],
        )
        return result
