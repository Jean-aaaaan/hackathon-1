"""
TimelineService - generates and manages TimelineAction rows per deal.

The agent calls gap_fill() after every pipeline run. It inspects the deal's
current state, activity history, and MEDDPICC scores, then inserts the
minimum set of actions needed to keep the deal moving - never more than
MAX_UPCOMING per deal at once.

Triggers that create actions:
  agent_gap_fill     - nightly pipeline (this service)
  fireflies_action_item - webhook fires when a call transcript arrives
  signal_trigger     - high-urgency signal created
  calendar_match     - upcoming meeting needs prep
  rep_created        - rep adds a manual action
"""
import uuid
from datetime import date, timedelta, datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import structlog

from app.models.account import Account, TimelineAction, Interaction

log = structlog.get_logger()

MAX_UPCOMING = 3        # never queue more than this many upcoming actions per deal
CHECKIN_GAP_DAYS = 7    # inject a check-in if no action planned within this window
CHAMPION_DARK_DAYS = 14  # treat as urgent if no outbound contact in this many days
CLOSE_PUSH_WINDOW = 30  # inject close-push if close date is within this many days
MEDDPICC_GAP_THRESHOLD = 0.35  # component score below this triggers an action
ACTION_COOLDOWN = {     # don't re-create same action_type within N days
    "champion_checkin":   5,
    "close_push":         7,
    "stakeholder_intro":  10,
    "email":              3,
    "escalation":         2,
    "proposal_follow":    5,
    "call_prep":          3,
    "meeting_prep":       1,
}


class TimelineService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Public API ────────────────────────────────────────────────────────────

    async def gap_fill(
        self,
        account: Account,
        pov: dict,
        new_signals: list[dict],
        resolved_signal_types: list[str] | None = None,
    ) -> int:
        """
        Inspect this deal's timeline and fill gaps.
        resolved_signal_types: signal types the ResearcherAgent identified as already
            resolved from the full email/call context. Actions for these signal types
            are auto-completed and not re-created.
        Returns the number of new TimelineActions created.
        """
        today = date.today()
        created = 0
        resolved = set(resolved_signal_types or [])

        existing = await self._load_active_actions(account.id)
        await self._refresh_statuses(existing, today)

        # Auto-complete stale signal_trigger actions two ways:
        # 1. LLM path: ResearcherAgent marked the signal type as resolved
        # 2. Interaction path: there's been outbound activity AFTER the action was created
        #    (catches cases like "DPA signed + email sent" that the LLM might miss)
        for action in existing:
            if action.status == "done":
                continue
            if action.source != "signal_trigger":
                continue

            # LLM path
            sig_type = _action_type_to_signal_type(action.action_type, action.source)
            if sig_type and sig_type in resolved:
                action.status = "done"
                action.completed_at = datetime.now(timezone.utc)
                action.completed_notes = "Auto-resolved: agent confirmed this was handled."
                log.info("action_auto_resolved_llm", account=account.name, signal_type=sig_type)
                continue

            # Interaction path: was there an outbound email/call after this action was created?
            if action.created_at:
                acted = await self._acted_after_signal(account.id, action.created_at)
                if acted:
                    action.status = "done"
                    action.completed_at = datetime.now(timezone.utc)
                    action.completed_notes = "Auto-resolved: outbound activity recorded after this action was created."
                    log.info("action_auto_resolved_interaction", account=account.name,
                             action_type=action.action_type)

        # Derive timing context from recent interactions
        days_since_outbound = await self._days_since_outbound(account.id)

        # Retire "Vantage Sweep not yet run" placeholders now that a real sweep has run.
        # They block all slots and prevent real intelligence-backed actions from appearing.
        if days_since_outbound < 999:
            for action in existing:
                if action.status in ("today", "upcoming") and action.title and (
                    "Vantage Sweep not yet run" in action.title          # legacy copy
                    or "no outbound activity recorded" in action.title
                ):
                    action.status = "done"
                    action.completed_at = datetime.now(timezone.utc)
                    action.completed_notes = "Superseded by Vantage Sweep."
                    log.info("placeholder_action_retired", account=account.name, title=action.title)

        active_count = len([a for a in existing if a.status in ("today", "upcoming")])
        slots = MAX_UPCOMING - active_count
        if slots <= 0:
            return 0
        next_planned = self._next_planned_date(existing)
        days_to_next = (next_planned - today).days if next_planned else 999

        meddpicc = pov.get("meddpicc") or {}

        # ── Rule 1: Close-push window ────────────────────────────────────────
        if account.close_date and slots > 0:
            days_to_close = (account.close_date - today).days
            if 0 < days_to_close <= CLOSE_PUSH_WINDOW:
                if not self._cooldown_active(existing, "close_push"):
                    self.db.add(self._make(
                        account, "close_push",
                        f"Close push - {days_to_close}d to target date",
                        f"Close date is {account.close_date}. Confirm commit or agree on extension before the date passes.",
                        today + timedelta(days=1), 0.85, "agent_gap_fill",
                        meddpicc_component="paper_process",
                    ))
                    created += 1
                    slots -= 1

        # ── Rule 2: Champion dark ────────────────────────────────────────────
        if slots > 0 and days_since_outbound > CHAMPION_DARK_DAYS:
            if not self._cooldown_active(existing, "champion_checkin"):
                name = self._champion_name(pov)
                # days_since_outbound >= 999 means "no outbound activity recorded",
                # NOT "sweep never ran" — the old copy claimed the latter on deals
                # that had visibly been analyzed, which reads as the tool lying.
                no_outbound_recorded = days_since_outbound >= 999
                title = (
                    f"Re-engage {name or 'champion'} - no outbound activity recorded"
                    if no_outbound_recorded else
                    f"Re-engage {name or 'champion'} - {days_since_outbound}d no contact"
                )
                reasoning = (
                    "No outbound emails or calls are recorded for this deal yet. "
                    "Reach out to establish contact, or sync HubSpot/Outlook so past activity is counted."
                    if no_outbound_recorded else
                    f"No outbound contact in {days_since_outbound} days. Champion going dark is the leading indicator of deal loss."
                )
                self.db.add(self._make(
                    account, "champion_checkin",
                    title, reasoning,
                    today, 0.9, "agent_gap_fill",
                    meddpicc_component="champion",
                ))
                created += 1
                slots -= 1

        # ── Rule 3: Upcoming gap > threshold ────────────────────────────────
        if slots > 0 and days_to_next > CHECKIN_GAP_DAYS:
            if not self._cooldown_active(existing, "champion_checkin"):
                name = self._champion_name(pov)
                self.db.add(self._make(
                    account, "champion_checkin",
                    f"Check in with {name or 'deal contact'}",
                    # days_to_next is a 999 sentinel when nothing is planned —
                    # never let that leak into rep-facing copy.
                    (
                        "Nothing is on the calendar for this deal. Regular contact prevents it going cold."
                        if days_to_next >= 999 else
                        f"No action planned for {days_to_next} days. Regular contact prevents the deal going cold."
                    ),
                    today + timedelta(days=3), 0.5, "agent_gap_fill",
                    meddpicc_component="champion",
                ))
                created += 1
                slots -= 1

        # ── Rule 4: MEDDPICC gaps → targeted actions ─────────────────────────
        gap_map = {
            "economic_buyer": (
                "stakeholder_intro",
                "Identify Economic Buyer",
                "No economic buyer confirmed. This MEDDPICC gap blocks close - find the budget owner.",
                0.70,
            ),
            "decision_criteria": (
                "email",
                "Send decision criteria alignment brief",
                "Decision criteria weakly mapped. Send a brief showing how your company meets their evaluation framework.",
                0.60,
            ),
            "implicate_pain": (
                "call_prep",
                "Quantify the pain - book an ROI conversation",
                "Pain is not yet quantified. A focused ROI conversation converts intent to urgency.",
                0.60,
            ),
        }
        for component, (action_type, title, reasoning, priority) in gap_map.items():
            if slots <= 0:
                break
            score = meddpicc.get(component, 1.0) if isinstance(meddpicc, dict) else 1.0
            if isinstance(score, (int, float)) and score < MEDDPICC_GAP_THRESHOLD:
                if not self._cooldown_active_by_meddpicc(existing, component):
                    self.db.add(self._make(
                        account, action_type, title, reasoning,
                        today + timedelta(days=5), priority, "agent_gap_fill",
                        meddpicc_component=component,
                    ))
                    created += 1
                    slots -= 1

        # ── Rule 5: Critical signal → immediate action ───────────────────────
        # Skip if: (a) researcher marked this signal type resolved, or
        #          (b) an outbound interaction already exists after the signal fired.
        critical = [
            s for s in new_signals
            if (s.get("urgency_score") or 0) >= 0.85
            and s.get("type") not in resolved
        ]
        if slots > 0 and critical:
            sig = critical[0]
            sig_type = sig.get("type", "signal")
            sig_created_at = sig.get("created_at")  # datetime or None

            already_acted = await self._acted_after_signal(account.id, sig_created_at)
            if not already_acted:
                type_map = {
                    "champion_dark":       "champion_checkin",
                    "champion_departure":  "champion_checkin",
                    "competitive_threat":  "email",
                    "budget_risk":         "stakeholder_intro",
                    "deal_stalling":       "escalation",
                }
                action_type = type_map.get(sig_type, "email")
                # Short imperative titles — the full detail lives in reasoning.
                # Cramming detail[:80] into the title truncated mid-sentence.
                title_map = {
                    "champion_dark":       "Re-engage champion",
                    "champion_departure":  "Champion departed — find a new champion",
                    "competitive_threat":  "Respond to competitive threat",
                    "budget_risk":         "Address budget risk",
                    "deal_stalling":       "Unstick stalled deal",
                }
                if not self._cooldown_active(existing, action_type, days=2):
                    a = self._make(
                        account, action_type,
                        title_map.get(sig_type, f"Act on {sig_type.replace('_', ' ')}"),
                        sig.get("detail", "High-urgency signal requires immediate response."),
                        today, 1.0, "signal_trigger",
                        source_ref_id=str(sig.get("id", "")),
                    )
                    a.status = "today"
                    self.db.add(a)
                    created += 1
                    slots -= 1

        return created

    async def create_from_fireflies(
        self,
        account: Account,
        action_items: list[str],
        transcript_date: datetime,
        source_ref_id: str,
    ) -> int:
        """
        Convert Fireflies action items into TimelineActions.
        Each item becomes one action due in 5 business days.
        """
        if not action_items:
            return 0

        existing = await self._load_active_actions(account.id)
        slots = MAX_UPCOMING - len([a for a in existing if a.status in ("today", "upcoming")])
        created = 0
        due = _add_business_days(date.today(), 5)

        for item in action_items[:3]:  # max 3 per transcript
            if slots <= 0:
                break
            item = item.strip()
            if not item or len(item) < 10:
                continue
            # Avoid duplicating an existing open action with similar title
            if any(item[:40].lower() in (a.title or "").lower() for a in existing):
                continue
            a = self._make(
                account, "email",
                item[:200],
                f"Action item from call on {transcript_date.strftime('%b %-d')}: \"{item[:120]}\"",
                due, 0.65, "fireflies_action_item",
                source_ref_id=source_ref_id,
            )
            self.db.add(a)
            created += 1
            slots -= 1

        return created

    async def create_from_calendar(
        self,
        account: Account,
        meeting_title: str,
        meeting_start: datetime,
        calendar_event_id: str,
    ) -> int:
        """
        Create a meeting-prep action T-24h before a matched calendar event.
        """
        prep_due = (meeting_start - timedelta(days=1)).date()
        if prep_due < date.today():
            prep_due = date.today()

        existing = await self._load_active_actions(account.id)
        # Don't create duplicate prep for same event
        if any(calendar_event_id in (a.source_ref_id or "") for a in existing):
            return 0

        a = self._make(
            account, "meeting_prep",
            f"Meeting prep: {meeting_title[:100]}",
            f"Call at {meeting_start.strftime('%H:%M')} on {meeting_start.strftime('%b %-d')}. Review signals, POV, and key questions before joining.",
            prep_due, 0.75, "calendar_match",
            source_ref_id=calendar_event_id,
        )
        self.db.add(a)
        return 1

    async def complete(self, action_id: str, workspace_id: str, notes: Optional[str] = None) -> bool:
        result = await self.db.execute(
            select(TimelineAction).where(
                TimelineAction.id == uuid.UUID(action_id),
                TimelineAction.workspace_id == uuid.UUID(workspace_id),
            )
        )
        action = result.scalar_one_or_none()
        if not action:
            return False
        action.status = "done"
        action.completed_at = datetime.now(timezone.utc)
        action.completed_notes = notes
        return True

    async def skip(self, action_id: str, workspace_id: str) -> bool:
        result = await self.db.execute(
            select(TimelineAction).where(
                TimelineAction.id == uuid.UUID(action_id),
                TimelineAction.workspace_id == uuid.UUID(workspace_id),
            )
        )
        action = result.scalar_one_or_none()
        if not action:
            return False
        action.status = "upcoming"  # resurface - don't remove, just defer
        action.due_date = date.today() + timedelta(days=2)
        action.skipped_at = datetime.now(timezone.utc)
        action.skip_count = (action.skip_count or 0) + 1
        if action.skip_count >= 3:
            # Escalate: agent skipped 3 times, mark overdue so it stays visible
            action.status = "overdue"
        return True

    async def reschedule(self, action_id: str, workspace_id: str, new_due: date) -> bool:
        result = await self.db.execute(
            select(TimelineAction).where(
                TimelineAction.id == uuid.UUID(action_id),
                TimelineAction.workspace_id == uuid.UUID(workspace_id),
            )
        )
        action = result.scalar_one_or_none()
        if not action:
            return False
        action.due_date = new_due
        action.status = "upcoming" if new_due > date.today() else "today"
        return True

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _load_active_actions(self, account_id) -> list[TimelineAction]:
        result = await self.db.execute(
            select(TimelineAction).where(
                TimelineAction.account_id == account_id,
                TimelineAction.status.in_(["upcoming", "today", "overdue"]),
            ).order_by(TimelineAction.due_date)
        )
        return result.scalars().all()

    async def _refresh_statuses(self, actions: list[TimelineAction], today: date) -> None:
        for a in actions:
            if a.due_date < today and a.status == "upcoming":
                a.status = "overdue"
            elif a.due_date == today and a.status == "upcoming":
                a.status = "today"

    async def _acted_after_signal(self, account_id, signal_created_at: Optional[datetime]) -> bool:
        """
        Returns True if there's been an outbound interaction (email/call/meeting)
        after the signal was created - meaning the rep already acted on it.
        If signal_created_at is unknown, fall back to checking the last 7 days.
        """
        cutoff = signal_created_at or (datetime.now(timezone.utc) - timedelta(days=7))
        result = await self.db.execute(
            select(Interaction.id)
            .where(
                Interaction.account_id == account_id,
                Interaction.type.in_(["email_sent", "call", "meeting"]),
                Interaction.occurred_at > cutoff,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _days_since_outbound(self, account_id) -> int:
        result = await self.db.execute(
            select(Interaction.occurred_at)
            .where(
                Interaction.account_id == account_id,
                Interaction.type.in_(["email_sent", "call", "meeting"]),
                Interaction.occurred_at.is_not(None),
            )
            .order_by(Interaction.occurred_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if not row:
            return 999
        return (datetime.now(timezone.utc) - row).days

    def _next_planned_date(self, actions: list[TimelineAction]) -> Optional[date]:
        upcoming = [a.due_date for a in actions if a.status in ("upcoming", "today")]
        return min(upcoming) if upcoming else None

    def _cooldown_active(self, actions: list[TimelineAction], action_type: str, days: int = 0) -> bool:
        cutoff_days = days or ACTION_COOLDOWN.get(action_type, 5)
        cutoff = date.today() - timedelta(days=cutoff_days)
        return any(
            a.action_type == action_type
            and a.created_at
            and a.created_at.date() >= cutoff
            for a in actions
        )

    def _cooldown_active_by_meddpicc(self, actions: list[TimelineAction], component: str) -> bool:
        cutoff = date.today() - timedelta(days=14)
        return any(
            a.meddpicc_component == component
            and a.created_at
            and a.created_at.date() >= cutoff
            for a in actions
        )

    def _champion_name(self, pov: dict) -> Optional[str]:
        for s in (pov.get("stakeholders") or []):
            if isinstance(s, dict) and s.get("role") in ("champion", "primary_contact"):
                return s.get("name")
        return None

    def _make(
        self,
        account: Account,
        action_type: str,
        title: str,
        reasoning: str,
        due_date: date,
        priority: float,
        source: str,
        meddpicc_component: str = None,
        source_ref_id: str = None,
    ) -> TimelineAction:
        today = date.today()
        return TimelineAction(
            account_id=account.id,
            workspace_id=account.workspace_id,
            action_type=action_type,
            title=title,
            reasoning=reasoning,
            due_date=due_date,
            priority=priority,
            source=source,
            source_ref_id=source_ref_id,
            meddpicc_component=meddpicc_component,
            deal_stage_at_creation=account.stage,
            status="today" if due_date <= today else "upcoming",
        )


def _action_type_to_signal_type(action_type: str, source: str) -> str | None:
    """
    Map a TimelineAction back to the signal type it was created from.
    Used to auto-resolve actions when the researcher marks that signal resolved.
    Only applies to signal_trigger actions - agent_gap_fill actions use different logic.
    """
    if source != "signal_trigger":
        return None
    return {
        "champion_checkin":   "champion_dark",
        "email":              "legal_review_started",
        "stakeholder_intro":  "budget_risk",
        "escalation":         "deal_stalling",
        "call_prep":          "competitive_evaluation_active",
    }.get(action_type)


def _add_business_days(start: date, days: int) -> date:
    d = start
    added = 0
    while added < days:
        d += timedelta(days=1)
        if d.weekday() < 5:  # Mon–Fri
            added += 1
    return d
