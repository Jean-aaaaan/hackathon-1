"""
RulesEngine - User-defined automation rules.
Replaces and extends PlaysEngine for configurable triggers + actions.

Triggers: signal_detected, health_drop, stage_changed, close_date_passed
Actions: create_draft, send_teams_alert, fire_play, set_next_step, run_agent_now

Rules are stored in workspace.settings["automation_rules"] as a list of rule dicts:
{
    "id": "rule-uuid",
    "name": "Champion went dark",
    "enabled": true,
    "cooldown_hours": 24,
    "trigger": {"type": "signal_detected", "signal_type": "champion_dark"},
    "action": {"type": "create_draft", "draft_type": "champion_reengagement"}
}
"""
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.models.account import Account, Draft
from app.config import get_settings

log = structlog.get_logger()


class RulesEngine:
    """
    Evaluates workspace-defined automation rules against the updated ASO.
    Rules are stored in workspace.settings["automation_rules"].
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()

    async def evaluate(
        self,
        account: Account,
        updated_aso: dict,
        workspace_settings: dict,
        run_id: str,
    ) -> list[str]:
        """
        Evaluate all enabled rules. Returns list of action descriptions for logging.
        """
        rules = workspace_settings.get("automation_rules", [])
        if not rules:
            return []

        results = []
        for rule in rules:
            if not rule.get("enabled", True):
                continue
            try:
                fired = await self._evaluate_rule(rule, account, updated_aso, run_id)
                if fired:
                    results.append(f"Rule '{rule.get('name')}' fired")
            except Exception as e:
                log.warning("rules_engine_rule_failed", rule=rule.get("name"), error=str(e))

        return results

    async def _evaluate_rule(
        self, rule: dict, account: Account, aso: dict, run_id: str
    ) -> bool:
        trigger = rule.get("trigger", {})
        action = rule.get("action", {})
        trigger_type = trigger.get("type")
        cooldown_hours = rule.get("cooldown_hours", 24)

        # Check cooldown
        if await self._in_cooldown(account.id, rule.get("id", rule.get("name", "")), cooldown_hours):
            return False

        # Evaluate trigger
        if trigger_type == "signal_detected":
            signal_type = trigger.get("signal_type")
            signals = aso.get("signals", [])
            if not any(s.get("type") == signal_type for s in signals):
                return False

        elif trigger_type == "health_drop":
            threshold = trigger.get("threshold", 0.15)
            prev_health = (account.state or {}).get("health_score") if account.state else None
            new_health = aso.get("health_score")
            if prev_health is None or new_health is None:
                return False
            if (float(prev_health) - float(new_health)) < threshold:
                return False

        elif trigger_type == "close_date_passed":
            from datetime import date
            close = account.close_date
            stage = account.stage or ""
            if close and close < date.today():
                pass  # trigger condition met
            else:
                return False
            if stage.lower() in ("closed won", "closed lost", "won", "lost"):
                return False

        elif trigger_type == "stage_changed":
            old_stage = (account.state or {}).get("stage")
            new_stage = aso.get("stage") or account.stage
            if old_stage == new_stage:
                return False

        else:
            return False

        # Execute action
        action_type = action.get("type")

        if action_type == "create_draft":
            draft_type = action.get("draft_type", "email_followup")

            # Don't pile onto the drafter/plays output: if a live draft of this
            # type already exists for the account (created this run or earlier),
            # the rule's intent is already served. flush() first — the session
            # runs autoflush=False, so same-run drafts are invisible otherwise.
            await self.db.flush()
            existing = await self.db.execute(
                select(Draft.id).where(
                    Draft.account_id == account.id,
                    Draft.type == draft_type,
                    Draft.status.in_(("pending", "queued")),
                ).limit(1)
            )
            if existing.scalar_one_or_none():
                log.info(
                    "rule_draft_skipped_existing",
                    rule=rule.get("name"),
                    draft_type=draft_type,
                    account_id=str(account.id),
                )
                return True

            draft = Draft(
                account_id=account.id,
                workspace_id=account.workspace_id,
                type=draft_type,
                content=(
                    f"[Auto-generated by rule '{rule.get('name')}' - "
                    "agent will fill content on next run]"
                ),
                gold_data_used={
                    "play_triggered": True,
                    "play_name": rule.get("id", rule.get("name", "")),
                    "play_reason": f"Automation rule triggered: {trigger_type}",
                    "trigger_source": "rules_engine",
                },
                # "queued" — placeholder awaiting agent content. Never "pending":
                # pending drafts are approvable, and approving placeholder text
                # would push "[Auto-generated by rule...]" to a customer.
                status="queued",
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                agent_run_id=uuid.UUID(run_id),
            )
            self.db.add(draft)

        elif action_type == "send_teams_alert":
            from app.integrations.teams import TeamsWebhookClient
            from app.config import get_settings as _gs
            s = _gs()
            if s.teams_webhook_url:
                teams = TeamsWebhookClient(s.teams_webhook_url)
                try:
                    await teams.send_signal_alert(
                        account_name=account.name,
                        account_id=str(account.id),
                        signal_type=f"rule:{rule.get('name')}",
                        detail=(
                            f"Automation rule '{rule.get('name')}' triggered ({trigger_type})"
                        ),
                        urgency="high",
                        urgency_score=0.85,
                        frontend_url=s.frontend_url,
                    )
                except Exception as e:
                    log.warning("rules_engine_teams_failed", error=str(e))

        elif action_type == "set_next_step":
            from sqlalchemy.orm.attributes import flag_modified
            state = dict(account.state or {})
            state["next_step"] = {
                "text": action.get(
                    "next_step_text",
                    f"Follow up - rule '{rule.get('name')}' triggered",
                ),
                "source": "rules_engine",
                "set_at": datetime.now(timezone.utc).isoformat(),
            }
            account.state = state
            flag_modified(account, "state")

        log.info(
            "rules_engine_action_fired",
            account=account.name,
            rule=rule.get("name"),
            action_type=action_type,
        )
        return True

    async def _in_cooldown(
        self, account_id, rule_id: str, cooldown_hours: int
    ) -> bool:
        """Return True if this rule fired within the cooldown window for this account."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)
        result = await self.db.execute(
            select(Draft).where(
                Draft.account_id == account_id,
                Draft.gold_data_used["play_name"].astext == rule_id,
                Draft.created_at >= cutoff,
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None
