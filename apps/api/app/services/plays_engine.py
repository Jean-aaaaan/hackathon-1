"""
PlaysEngine - Rule-based draft triggers. Human reviews every output.

A Play watches the ASO for a condition. When it fires, it queues a
specific draft type automatically. The rep still approves or declines -
plays just remove the "decide whether to draft" friction.

Built-in plays (MVP - no config UI needed yet):
  CHAMPION_DARK          → champion_reengagement   (cooldown 72h)
  COMPETITION_ACTIVE     → competitive_displacement (cooldown 7d)
  CLOSE_DATE_AT_RISK     → close_plan_proposal      (cooldown 14d)
  EB_MISSING_LATE_STAGE  → executive_alignment      (cooldown 14d)
  RENEWAL_AT_RISK        → renewal_brief            (cooldown 14d, customers only)
  EXPANSION_READY        → expansion_pitch          (cooldown 30d, customers only)

Cost: ~$0.03/play fired (one targeted DrafterAgent call, Sonnet).
No plays fired = zero cost.
"""
import uuid
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
from dataclasses import dataclass
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog


from app.models.account import Account, Draft
from app.config import get_settings
from app.agents.base import DrafterResult
from app.agents.drafter import VISHNU_VOICE_DNA, polish_prose

log = structlog.get_logger()


# ── Play definitions ──────────────────────────────────────────────────────────

@dataclass
class Play:
    name: str
    draft_type: str
    cooldown_hours: int
    description: str  # shown to rep in UI as "Why this was generated"

    def should_fire(self, aso: dict) -> tuple[bool, str]:
        """
        Evaluate whether this play's condition is met.
        Returns (should_fire: bool, reason: str).
        """
        raise NotImplementedError


class ChampionDarkPlay(Play):
    def __init__(self):
        super().__init__(
            name="Champion Dark",
            draft_type="champion_reengagement",
            cooldown_hours=72,
            description="Champion has gone dark - pattern-interrupt reengagement queued automatically.",
        )

    def should_fire(self, aso: dict) -> tuple[bool, str]:
        pov = aso.get("pov", {})
        risk_vectors = pov.get("risk_vectors", {})
        champion_risk = risk_vectors.get("champion", "medium")
        days_since = pov.get("days_since_meaningful_activity")

        if champion_risk in ("critical", "high"):
            days_msg = f"{days_since} days" if days_since else "unknown days"
            return True, f"Champion risk is {champion_risk} ({days_msg} since last meaningful activity)"
        return False, ""


class CompetitionActivePlay(Play):
    def __init__(self):
        super().__init__(
            name="Competition Active",
            draft_type="competitive_displacement",
            cooldown_hours=168,  # 7 days
            description="Competitor is actively evaluating - champion talking points queued.",
        )

    def should_fire(self, aso: dict) -> tuple[bool, str]:
        pov = aso.get("pov", {})
        risk_vectors = pov.get("risk_vectors", {})
        competition_risk = risk_vectors.get("competition", "low")

        if competition_risk in ("critical", "high"):
            return True, f"Competition risk is {competition_risk} - active parallel evaluation detected"
        return False, ""


class CloseDateAtRiskPlay(Play):
    def __init__(self):
        super().__init__(
            name="Close Date At Risk",
            draft_type="close_plan_proposal",
            cooldown_hours=336,  # 14 days
            description="Close date integrity is at-risk with no MAP - close plan draft queued.",
        )

    def should_fire(self, aso: dict) -> tuple[bool, str]:
        pov = aso.get("pov", {})
        close_date_integrity = pov.get("close_date_integrity", "unknown")
        close_date_str = aso.get("close_date")

        if close_date_integrity != "at_risk":
            return False, ""

        # Check if close date is within 45 days
        if close_date_str:
            try:
                close_date = datetime.fromisoformat(close_date_str[:10])
                days_to_close = (close_date - datetime.now()).days
                if days_to_close <= 45:
                    return True, f"Close date integrity is at-risk with {days_to_close} days to close date"
            except (ValueError, TypeError):
                pass

        # Fire anyway if at_risk even without close date math
        return True, "Close date integrity is at-risk - no mutual action plan exists"


class EBMissingPlay(Play):
    def __init__(self):
        super().__init__(
            name="Economic Buyer Missing",
            draft_type="executive_alignment",
            cooldown_hours=336,  # 14 days
            description="Economic buyer is not engaged in a late-stage deal - exec alignment draft queued.",
        )

    def should_fire(self, aso: dict) -> tuple[bool, str]:
        pov = aso.get("pov", {})
        risk_vectors = pov.get("risk_vectors", {})
        economic_risk = risk_vectors.get("economic", "low")
        stage = aso.get("stage", "").lower()

        late_stage_keywords = ["proposal", "negotiate", "decision", "contract", "closing", "commit"]
        is_late_stage = any(kw in stage for kw in late_stage_keywords)

        meddpicc = pov.get("meddpicc", {})
        eb_score = meddpicc.get("economic_buyer", 0.5) if isinstance(meddpicc, dict) else 0.5

        if is_late_stage and economic_risk in ("critical", "high") and eb_score < 0.4:
            return True, f"Economic buyer engagement is {economic_risk} risk in a late-stage deal (EB score: {eb_score:.0%})"
        return False, ""


class RenewalAtRiskPlay(Play):
    def __init__(self):
        super().__init__(
            name="Renewal At Risk",
            draft_type="renewal_brief",
            cooldown_hours=336,  # 14 days
            description="Customer renewal is at risk - renewal call brief queued automatically.",
        )

    def should_fire(self, aso: dict) -> tuple[bool, str]:
        # Only fires for customer accounts
        account_type = aso.get("account_type", "prospect")
        if account_type != "customer":
            return False, ""

        health_score = aso.get("health_score", 0.5) or 0.5
        renewal_date_str = aso.get("renewal_date")

        if health_score >= 0.5:
            return False, ""  # Not at risk

        if renewal_date_str:
            try:
                renewal_date = datetime.fromisoformat(renewal_date_str[:10])
                days_to_renewal = (renewal_date - datetime.now()).days
                if days_to_renewal <= 90:
                    return True, f"Customer health is {health_score:.0%} with renewal in {days_to_renewal} days"
            except (ValueError, TypeError):
                pass

        # Low health customer, unknown renewal date
        if health_score < 0.35:
            return True, f"Customer health critically low at {health_score:.0%}"
        return False, ""


class ExpansionReadyPlay(Play):
    def __init__(self):
        super().__init__(
            name="Expansion Opportunity",
            draft_type="expansion_pitch",
            cooldown_hours=720,  # 30 days
            description="Strong expansion signals detected - upsell email draft queued.",
        )

    def should_fire(self, aso: dict) -> tuple[bool, str]:
        account_type = aso.get("account_type", "prospect")
        if account_type != "customer":
            return False, ""

        signals = aso.get("signals", [])
        expansion_signals = [
            s for s in signals
            if s.get("type") in ("expansion_opportunity", "usage_growth_detected", "new_team_adoption")
        ]

        if expansion_signals:
            return True, f"Expansion signal detected: {expansion_signals[0].get('detail', '')[:100]}"
        return False, ""


# All built-in plays
BUILT_IN_PLAYS: list[Play] = [
    ChampionDarkPlay(),
    CompetitionActivePlay(),
    CloseDateAtRiskPlay(),
    EBMissingPlay(),
    RenewalAtRiskPlay(),
    ExpansionReadyPlay(),
]


# ── System prompt for play-triggered drafts ───────────────────────────────────

PLAY_DRAFTER_SYSTEM_PROMPT = """You write sales drafts AS the sender identified in the SENDER section of the user message,
because an automated play was triggered. The play fired because a condition was met in the deal intelligence.

Write exactly the draft type requested:
- Sound like a real person, not like a sales playbook or an AI (voice rules below are mandatory)
- Reference the exact trigger condition and evidence
- Cite your sources
- For EMAIL types (champion_reengagement, executive_alignment, expansion_pitch):
  the FIRST line must be exactly "Subject: <subject line>", then a blank line,
  then the email body. Subject: specific and short, never "Following up".

For champion_reengagement: warm-direct check-in, 3-5 sentences, one soft ask. Curious, never accusatory.
For competitive_displacement: champion talking points format, not a buyer email
For close_plan_proposal: proposed milestone table with dates and owners
For executive_alignment: 4-6 sentences, exec-to-exec, peer tone
For renewal_brief: structured scannable format (see meeting_brief pattern)
For expansion_pitch: 3-4 sentences, usage hook, one light ask
""" + VISHNU_VOICE_DNA


# ── PlaysEngine ───────────────────────────────────────────────────────────────

class PlaysEngine:
    """
    Evaluates built-in play conditions against an updated ASO.
    Fires targeted DrafterAgent calls for triggered plays.
    All output is status=pending - rep always reviews.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()

    async def evaluate_and_fire(
        self,
        account: Account,
        updated_aso: dict,
        run_id: str,
    ) -> list[Draft]:
        """
        Evaluate all plays against the updated ASO.
        For each play that should fire, generate a draft and persist it.
        Returns list of newly created Draft objects.
        """
        fired_drafts = []

        # Nurture deals are parked: the policy is ONE warm touchpoint per cycle
        # (written by the DrafterAgent), never re-engagement or closing pressure.
        # Without this guard a 151-day-dark champion on a nurture deal fired
        # Champion Dark + Close Date At Risk and flooded the queue.
        if (account.stage or "").strip().lower() in ("to nurture", "nurture"):
            log.info("plays_skipped_nurture_stage", account=account.name)
            return []

        # The session runs autoflush=False: drafts the DrafterAgent just added
        # in this same run are invisible to the cooldown SELECT until flushed —
        # which let a play create a same-type draft seconds after the drafter did.
        await self.db.flush()

        for play in BUILT_IN_PLAYS:
            try:
                should_fire, reason = play.should_fire(updated_aso)
                if not should_fire:
                    continue

                # Check cooldown - don't fire if a recent draft of this type exists
                in_cooldown = await self._check_cooldown(
                    account_id=account.id,
                    draft_type=play.draft_type,
                    cooldown_hours=play.cooldown_hours,
                )
                if in_cooldown:
                    log.info(
                        "play_in_cooldown",
                        play=play.name,
                        account=account.name,
                        draft_type=play.draft_type,
                    )
                    continue

                log.info(
                    "play_fired",
                    play=play.name,
                    account=account.name,
                    draft_type=play.draft_type,
                    reason=reason,
                )

                # Generate the draft
                draft_content = await self._generate_play_draft(
                    play=play,
                    account=account,
                    aso=updated_aso,
                    trigger_reason=reason,
                )

                if not draft_content:
                    continue

                # Pull the "Subject: …" first line into subject_line; synthesize
                # one if the model skipped it — an email draft without a subject
                # is unsendable from the review panel.
                subject_line = None
                first_line, _, rest = draft_content.partition("\n")
                if first_line.strip().lower().startswith("subject:"):
                    subject_line = first_line.split(":", 1)[1].strip()[:200]
                    draft_content = rest.lstrip("\n")
                elif play.draft_type in ("champion_reengagement", "executive_alignment", "expansion_pitch"):
                    subject_line = f"{account.name.split(' - ')[0].strip()} — {play.name.lower()}"[:200]

                # Persist with play metadata in gold_data_used
                draft = Draft(
                    account_id=account.id,
                    workspace_id=account.workspace_id,
                    type=play.draft_type,
                    subject_line=subject_line,
                    content=draft_content,
                    sources_cited=[],
                    gold_data_used={
                        "play_triggered": True,
                        "play_name": play.name,
                        "play_reason": reason,
                        "play_description": play.description,
                        "trigger_source": "plays_engine",
                    },
                    status="pending",
                    expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                    agent_run_id=uuid.UUID(run_id),
                )
                self.db.add(draft)
                fired_drafts.append(draft)

                # Create a TimelineAction so the play surfaces in the Action Queue
                try:
                    from app.models.account import TimelineAction
                    from datetime import date
                    tl_action = TimelineAction(
                        account_id=account.id,
                        workspace_id=account.workspace_id,
                        action_type="email",
                        title=f"{play.name} — review AI draft",
                        reasoning=play.description,
                        due_date=date.today(),
                        priority=0.8,
                        source="signal_trigger",
                        draft_id=draft.id,
                        deal_stage_at_creation=account.stage,
                        status="today",
                    )
                    self.db.add(tl_action)
                except Exception as _tl_e:
                    log.debug("play_timeline_action_failed", error=str(_tl_e))

            except Exception as e:
                log.error(
                    "play_evaluation_failed",
                    play=play.name,
                    account=account.name,
                    error=str(e),
                )
                continue

        if fired_drafts:
            await self.db.flush()  # get IDs without committing (caller commits)
            log.info(
                "plays_engine_complete",
                account=account.name,
                plays_fired=len(fired_drafts),
                draft_types=[d.type for d in fired_drafts],
            )

        return fired_drafts

    async def _check_cooldown(
        self,
        account_id: uuid.UUID,
        draft_type: str,
        cooldown_hours: int,
    ) -> bool:
        """Returns True if a draft of this type was created within the cooldown window."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)
        result = await self.db.execute(
            select(Draft)
            .where(
                Draft.account_id == account_id,
                Draft.type == draft_type,
                Draft.created_at >= cutoff,
                Draft.status != "declined",  # declined drafts don't count - rep can re-trigger
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _generate_play_draft(
        self,
        play: Play,
        account: Account,
        aso: dict,
        trigger_reason: str,
    ) -> Optional[str]:
        """
        Call DrafterAgent with targeted context for this specific play.
        Returns draft content string, or None on failure.
        """
        pov = aso.get("pov", {})
        stakeholders = aso.get("stakeholders", [])
        champion = next((s for s in stakeholders if s.get("role") == "champion"), None)
        eb = next((s for s in stakeholders if s.get("role") == "economic_buyer"), None)
        signals = aso.get("signals", [])[:5]

        from datetime import date as _date
        user_message = f"""
Play triggered: {play.name}
Trigger reason: {trigger_reason}
Draft type to generate: {play.draft_type}

Account: {account.name}
Stage: {aso.get('stage', 'Unknown')}
Deal Amount: ${(aso.get('deal_amount') or 0):,.0f}
Close Date: {aso.get('close_date') or aso.get('renewal_date', 'Not set')}
Today's Date: {_date.today().isoformat()}
Account Type: {aso.get('account_type', 'prospect')}
AI Forecast: {pov.get('forecast_category', 'Unknown')}
Health Score: {aso.get('health_score') or 0:.0%}

DATE DISCIPLINE: every date you write (milestones, timelines, follow-up windows)
MUST be in the future relative to Today's Date. If the Close Date above is
already in the past, do NOT plan backward from it — propose a realistic forward
close date and explicitly flag that the CRM date is stale.

Champion: {json.dumps(champion) if champion else 'Not identified'}
Economic Buyer: {json.dumps(eb) if eb else 'Not identified'}

Recent signals:
{json.dumps(signals, indent=2)}

MEDDPICC gaps: {', '.join(pov.get('meddpicc', {}).get('gaps', [])[:3]) if isinstance(pov.get('meddpicc'), dict) else 'Unknown'}
Top risks: {', '.join(pov.get('risks', [])[:3]) if pov.get('risks') else 'None identified'}

Write one {play.draft_type} draft. Reference the trigger condition specifically.
"""

        try:
            from app.integrations.llm import complete_text, quality_model
            response = await complete_text(
                system_prompt=PLAY_DRAFTER_SYSTEM_PROMPT,
                user_message=user_message,
                model=quality_model(),
                max_tokens=1500,
            )
            text = polish_prose(response.text.strip())
            # Raw-text path (no tool schema): strip "Here is the draft:" preambles
            import re
            text = re.sub(r"^(Here is|Here's)[^\n]*:\s*\n+", "", text, flags=re.IGNORECASE)
            return text
        except Exception as e:
            log.error("play_draft_generation_failed", play=play.name, account=account.name, error=str(e))
            return None
