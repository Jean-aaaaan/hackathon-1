"""
Outlook / Microsoft Graph Integration
Handles OAuth 2.0 for Mail.Send + Mail.Read, email sending, and sent folder access.

OAuth flow:
1. GET /v1/workspace/integrations/outlook/connect → redirect to Microsoft login
2. POST /v1/workspace/integrations/outlook/callback → exchange code for tokens
3. POST /v1/workspace/integrations/outlook/disconnect → revoke

Required Azure App Registration:
- Redirect URI: {FRONTEND_URL}/auth/outlook/callback
- API permissions (delegated): Mail.Send, Mail.ReadBasic, User.Read, offline_access
"""
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
import httpx
import structlog

from app.config import get_settings

log = structlog.get_logger()

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
def _get_authority() -> str:
    """Return tenant-specific or common authority based on config."""
    from app.config import get_settings
    tenant = get_settings().outlook_tenant_id or "common"
    return f"https://login.microsoftonline.com/{tenant}"
SCOPES = "Mail.ReadWrite Calendars.Read User.Read offline_access"


class OutlookClient:
    """Microsoft Graph API client for Outlook operations."""

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    async def get_user_profile(self) -> dict:
        """Get the authenticated user's profile (name, email)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{GRAPH_BASE}/me", headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    async def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[str] = None,
    ) -> dict:
        """
        Create a draft email in the rep's Outlook Drafts folder via Microsoft Graph.
        Does NOT send — the rep opens Outlook, reviews, and sends themselves.
        Returns the draft message ID and web link.
        """
        message: dict = {
            "subject": subject,
            "body": {
                "contentType": "Text",
                "content": body,
            },
            "toRecipients": [{"emailAddress": {"address": to}}],
            "isDraft": True,
        }
        if cc:
            message["ccRecipients"] = [{"emailAddress": {"address": a.strip()}} for a in cc.split(",") if a.strip()]

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{GRAPH_BASE}/me/messages",
                headers=self.headers,
                json=message,
            )
            resp.raise_for_status()
            data = resp.json()
            log.info("outlook_draft_created", to=to, subject=subject[:60], message_id=data.get("id", "")[:20])
            return {
                "draft_created": True,
                "message_id": data.get("id"),
                "web_link": data.get("webLink"),
                "to": to,
                "subject": subject,
            }

    async def get_sent_emails(self, limit: int = 50) -> list[dict]:
        """
        Fetch last N sent emails from the Sent Items folder.
        Used for voice profile analysis.
        Returns: list of {subject, bodyPreview, sentDateTime, toRecipients}
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{GRAPH_BASE}/me/mailFolders/SentItems/messages",
                headers=self.headers,
                params={
                    "$select": "subject,bodyPreview,sentDateTime,toRecipients,body",
                    "$top": str(limit),
                    "$orderby": "sentDateTime desc",
                    "$filter": "isDraft eq false",
                },
            )
            resp.raise_for_status()
            msgs = resp.json().get("value", [])
            log.info("outlook_sent_emails_fetched", count=len(msgs))
            return msgs

    async def get_calendar_events(
        self,
        days_back: int = 0,
        days_ahead: int = 7,
    ) -> list[dict]:
        """
        Fetch calendar events in a window [now - days_back, now + days_ahead].
        Pass days_back=90 to retrieve 90 days of history for Fireflies matching.
        Returns list of {subject, start, end, attendees, organizer, body_preview, online_meeting_url}
        """
        from datetime import timezone as _tz
        now = datetime.now(_tz.utc)
        start_dt = now - timedelta(days=days_back)
        end_dt   = now + timedelta(days=days_ahead)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{GRAPH_BASE}/me/calendarView",
                headers=self.headers,
                params={
                    "startDateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "endDateTime":   end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "$select": "subject,start,end,attendees,organizer,bodyPreview,onlineMeeting,isOrganizer",
                    "$orderby": "start/dateTime asc",
                    "$top": "200",
                },
            )
            if resp.status_code == 403:
                log.warning("outlook_calendar_permission_denied", note="Add Calendars.Read scope")
                return []
            if resp.status_code != 200:
                log.warning("outlook_calendar_failed", status=resp.status_code)
                return []
            events = resp.json().get("value", [])
            log.info("outlook_calendar_fetched", count=len(events), days_back=days_back, days_ahead=days_ahead)
            return [
                {
                    "subject": e.get("subject", ""),
                    "start": e.get("start", {}).get("dateTime"),
                    "end": e.get("end", {}).get("dateTime"),
                    "attendees": [
                        a.get("emailAddress", {}).get("address", "").lower()
                        for a in e.get("attendees", [])
                        if a.get("emailAddress", {}).get("address")
                    ],
                    "organizer": e.get("organizer", {}).get("emailAddress", {}).get("address", ""),
                    "body_preview": e.get("bodyPreview", "")[:300],
                    "online_meeting_url": (e.get("onlineMeeting") or {}).get("joinUrl"),
                    "is_organizer": e.get("isOrganizer", False),
                }
                for e in events
            ]

    async def get_upcoming_meetings(self, days_ahead: int = 7) -> list[dict]:
        """Backward-compatible alias — fetches upcoming meetings only."""
        return await self.get_calendar_events(days_back=0, days_ahead=days_ahead)

    async def get_message_thread(self, message_id: str) -> list[dict]:
        """Get all messages in a conversation thread."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            # First get the conversationId
            msg_resp = await client.get(
                f"{GRAPH_BASE}/me/messages/{message_id}",
                headers=self.headers,
                params={"$select": "conversationId"},
            )
            msg_resp.raise_for_status()
            conversation_id = msg_resp.json().get("conversationId")
            if not conversation_id:
                return []

            thread_resp = await client.get(
                f"{GRAPH_BASE}/me/messages",
                headers=self.headers,
                params={
                    "$filter": f"conversationId eq '{conversation_id}'",
                    "$select": "subject,bodyPreview,sentDateTime,from,toRecipients,isDraft",
                    "$orderby": "sentDateTime asc",
                    "$top": "50",
                },
            )
            thread_resp.raise_for_status()
            return thread_resp.json().get("value", [])


async def exchange_code(code: str, redirect_uri: str) -> dict:
    """Exchange OAuth authorization code for access + refresh tokens."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{_get_authority()}/oauth2/v2.0/token",
            data={
                "grant_type": "authorization_code",
                "client_id": settings.outlook_client_id,
                "client_secret": settings.outlook_client_secret,
                "redirect_uri": redirect_uri,
                "code": code,
                "scope": SCOPES,
            },
        )
        if not resp.is_success:
            log.error("outlook_token_exchange_failed",
                      status=resp.status_code,
                      body=resp.text[:500])
            resp.raise_for_status()
        return resp.json()


async def refresh_access_token(refresh_token: str) -> dict:
    """Refresh an expired Outlook access token."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{_get_authority()}/oauth2/v2.0/token",
            data={
                "grant_type": "refresh_token",
                "client_id": settings.outlook_client_id,
                "client_secret": settings.outlook_client_secret,
                "refresh_token": refresh_token,
                "scope": SCOPES,
            },
        )
        resp.raise_for_status()
        return resp.json()


def get_auth_url(state: str) -> str:
    """Build the Microsoft OAuth authorization URL."""
    settings = get_settings()
    params = {
        "client_id": settings.outlook_client_id,
        "response_type": "code",
        "redirect_uri": f"{settings.frontend_url}/auth/outlook/callback",
        "scope": SCOPES,
        "state": state,
        "prompt": "select_account",
    }
    from urllib.parse import urlencode
    return f"{_get_authority()}/oauth2/v2.0/authorize?{urlencode(params)}"
