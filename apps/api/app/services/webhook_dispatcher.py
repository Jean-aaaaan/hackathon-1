"""
WebhookDispatcher — Sends outbound webhook events to subscriber URLs.
Events are signed with HMAC-SHA256 using a per-subscription secret.
Retry policy: 3 attempts with exponential backoff (1s, 2s, 4s).

Supported events:
  signal.critical, signal.high, draft.created, draft.approved,
  draft.declined, health.dropped, agent.run_complete,
  account.stage_changed, play.fired
"""
import asyncio
import hashlib
import hmac
import ipaddress
import json
import socket
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
import structlog

log = structlog.get_logger()

SUPPORTED_EVENTS = {
    "signal.critical",
    "signal.high",
    "draft.created",
    "draft.approved",
    "draft.declined",
    "health.dropped",
    "agent.run_complete",
    "account.stage_changed",
    "play.fired",
}


class WebhookDispatcher:
    """Dispatch outbound webhook events to subscriber URLs with retry + HMAC signing."""

    @staticmethod
    def _sign(payload: str, secret: str) -> str:
        """Sign payload with HMAC-SHA256. Returns hex digest."""
        return hmac.new(
            secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    async def dispatch(
        self,
        event_type: str,
        account_id: str,
        account_name: str,
        workspace_id: str,
        workspace_settings: dict,
        data: dict,
    ) -> None:
        """
        Dispatch event to all matching webhook subscriptions.
        Non-blocking — failures are logged but not raised.
        """
        if event_type not in SUPPORTED_EVENTS:
            return

        subscriptions = workspace_settings.get("webhook_subscriptions", [])
        if not subscriptions:
            return

        payload = {
            "event": event_type,
            "account_id": account_id,
            "account_name": account_name,
            "workspace_id": workspace_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        payload_str = json.dumps(payload, default=str)

        for sub in subscriptions:
            url = sub.get("url")
            if not url:
                continue

            events = sub.get("events", ["all"])
            secret = sub.get("secret")
            if not secret:
                log.warning("webhook_subscription_missing_secret", url=url[:60])
                continue

            if "all" not in events and event_type not in events:
                continue

            signature = self._sign(payload_str, secret)
            await self._send_with_retry(url, payload_str, signature)

    @staticmethod
    def _is_safe_url(url: str) -> bool:
        """Re-validate URL target at dispatch time to prevent DNS rebinding SSRF.
        Uses getaddrinfo to check ALL returned IPs (not just the first A record)."""
        try:
            hostname = urlparse(url).hostname
            if not hostname:
                return False
            infos = socket.getaddrinfo(hostname, None)
            for info in infos:
                try:
                    addr = ipaddress.ip_address(info[4][0])
                except ValueError:
                    continue
                if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast:
                    return False
            return True
        except Exception:
            return False

    async def _send_with_retry(self, url: str, payload: str, signature: str) -> None:
        """Send webhook with exponential backoff retry (max 3 attempts)."""
        loop = asyncio.get_event_loop()
        safe = await loop.run_in_executor(None, self._is_safe_url, url)
        if not safe:
            log.warning("webhook_ssrf_blocked", url=url[:60])
            return
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        url,
                        content=payload,
                        headers={
                            "Content-Type": "application/json",
                            "X-Vantage-Signature": signature,
                            "X-Vantage-Event-Id": str(uuid.uuid4()),
                        },
                    )
                    if resp.status_code < 300:
                        log.info(
                            "webhook_delivered",
                            url=url[:60],
                            status=resp.status_code,
                        )
                        return
                    log.warning(
                        "webhook_bad_status",
                        url=url[:60],
                        status=resp.status_code,
                        attempt=attempt,
                    )
            except Exception as e:
                log.warning(
                    "webhook_attempt_failed",
                    url=url[:60],
                    attempt=attempt,
                    error=str(e),
                )

            # Exponential backoff: 1s, 2s, 4s
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
