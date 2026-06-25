"""
Microsoft Teams Integration — Incoming webhook for signal alerts + daily briefs.
Uses Teams incoming webhook (no bot registration required).

Cards use Adaptive Cards schema v1.5 — supported in Teams desktop + mobile.

Configure: In Teams channel → Connectors → Incoming Webhook → copy URL → set TEAMS_WEBHOOK_URL env var.
"""
from datetime import datetime, timezone
from typing import Optional
import httpx
import structlog

log = structlog.get_logger()


class TeamsWebhookClient:
    """Send Adaptive Card messages to a Teams channel via incoming webhook."""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def __repr__(self) -> str:
        return "TeamsWebhookClient(webhook_url=<redacted>)"

    async def send_card(self, card: dict) -> bool:
        """POST an Adaptive Card payload to the Teams webhook."""
        if not self.webhook_url:
            log.debug("teams_webhook_not_configured")
            return False

        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "contentUrl": None,
                    "content": card,
                }
            ],
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    self.webhook_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    return True
                log.warning("teams_webhook_failed", status=resp.status_code, body=resp.text[:200])
                return False
        except Exception as e:
            log.error("teams_webhook_error", error=str(e))
            return False

    async def send_signal_alert(
        self,
        account_name: str,
        account_id: str,
        signal_type: str,
        detail: str,
        urgency: str,
        urgency_score: float,
        frontend_url: str,
    ) -> bool:
        """Send a critical signal alert card to Teams."""
        urgency_color = {
            "critical": "attention",
            "high":     "warning",
            "medium":   "accent",
            "low":      "good",
        }.get(urgency, "default")

        urgency_emoji = {
            "critical": "🚨",
            "high":     "⚠️",
            "medium":   "📊",
            "low":      "ℹ️",
        }.get(urgency, "•")

        card = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.5",
            "body": [
                {
                    "type": "TextBlock",
                    "text": f"{urgency_emoji} Signal Alert: {account_name}",
                    "weight": "Bolder",
                    "size": "Medium",
                    "color": urgency_color,
                },
                {
                    "type": "FactSet",
                    "facts": [
                        {"title": "Signal", "value": signal_type.replace("_", " ").title()},
                        {"title": "Urgency", "value": f"{urgency.title()} ({int(urgency_score * 100)}%)"},
                        {"title": "Time", "value": datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")},
                    ],
                },
                {
                    "type": "TextBlock",
                    "text": detail,
                    "wrap": True,
                    "spacing": "Medium",
                },
            ],
            "actions": [
                {
                    "type": "Action.OpenUrl",
                    "title": "Open War Room",
                    "url": f"{frontend_url}/account/{account_id}",
                    "style": "positive",
                },
                {
                    "type": "Action.OpenUrl",
                    "title": "Review in Inbox",
                    "url": f"{frontend_url}/inbox",
                },
            ],
        }
        return await self.send_card(card)

    async def send_morning_brief(
        self,
        workspace_name: str,
        top_accounts: list[dict],
        pending_drafts: int,
        dar_pct: float,
        frontend_url: str,
    ) -> bool:
        """
        Send daily morning brief card to Teams.
        Called by the nightly worker after all accounts are processed.
        Shows top 3 urgent accounts + DAR + pending drafts.
        """
        account_rows = []
        for i, acc in enumerate(top_accounts[:3]):
            urgency_pct = int((acc.get("urgency_score") or 0) * 100)
            account_rows.append({
                "title": f"{i+1}. {acc.get('name', 'Unknown')}",
                "value": f"Urgency {urgency_pct}% · {acc.get('stage', 'No stage')}",
            })

        card = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.5",
            "body": [
                {
                    "type": "TextBlock",
                    "text": f"⚡ Vantage Morning Brief: {workspace_name}",
                    "weight": "Bolder",
                    "size": "Large",
                },
                {
                    "type": "TextBlock",
                    "text": datetime.now(timezone.utc).strftime("%A, %d %B %Y"),
                    "isSubtle": True,
                    "spacing": "None",
                },
                {"type": "separator"},
                {
                    "type": "FactSet",
                    "facts": [
                        {"title": "DAR (30d)", "value": f"{dar_pct:.1f}% (target 60%)"},
                        {"title": "Drafts to review", "value": str(pending_drafts)},
                    ],
                    "spacing": "Medium",
                },
                {
                    "type": "TextBlock",
                    "text": "🔥 Top Accounts Today",
                    "weight": "Bolder",
                    "spacing": "Medium",
                },
                {
                    "type": "FactSet",
                    "facts": account_rows or [{"title": "-", "value": "No accounts"}],
                },
            ],
            "actions": [
                {
                    "type": "Action.OpenUrl",
                    "title": "Open Vantage",
                    "url": frontend_url,
                    "style": "positive",
                },
                {
                    "type": "Action.OpenUrl",
                    "title": "Review Drafts",
                    "url": f"{frontend_url}/inbox",
                },
            ],
        }

        # Monday: the Weekly Pipeline Review is fresh — link it first
        if datetime.now(timezone.utc).weekday() == 0:
            card["body"].insert(3, {
                "type": "TextBlock",
                "text": "📋 Your Weekly Pipeline Review is ready — moved, stalled, and slipped deals with evidence.",
                "wrap": True,
                "spacing": "Medium",
            })
            card["actions"].insert(0, {
                "type": "Action.OpenUrl",
                "title": "Weekly Pipeline Review",
                "url": f"{frontend_url}/watchtower",
                "style": "positive",
            })

        return await self.send_card(card)

    async def send_draft_ready(
        self,
        account_name: str,
        account_id: str,
        draft_type: str,
        rep_email: Optional[str],
        frontend_url: str,
    ) -> bool:
        """Notify when a new draft is ready for review."""
        card = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.5",
            "body": [
                {
                    "type": "TextBlock",
                    "text": f"📝 New Draft Ready: {account_name}",
                    "weight": "Bolder",
                    "size": "Medium",
                },
                {
                    "type": "FactSet",
                    "facts": [
                        {"title": "Type", "value": draft_type.replace("_", " ").title()},
                        {"title": "For", "value": rep_email or "Unassigned"},
                    ],
                },
                {
                    "type": "TextBlock",
                    "text": "Review and approve this AI-drafted communication before sending.",
                    "wrap": True,
                    "isSubtle": True,
                },
            ],
            "actions": [
                {
                    "type": "Action.OpenUrl",
                    "title": "Review Draft",
                    "url": f"{frontend_url}/account/{account_id}",
                    "style": "positive",
                },
            ],
        }
        return await self.send_card(card)
