"""
HubSpot Integration — OAuth, deal sync, webhook processing.
Uses hubspot-api-client v11.
"""
import hashlib
import hmac
import time as _time
from datetime import date as _date, datetime, timezone
from typing import Optional
import httpx
import structlog

from app.config import get_settings

log = structlog.get_logger()

HUBSPOT_DEAL_PROPERTIES = [
    "dealname", "dealstage", "closedate", "amount",
    "hs_last_modified_date", "hubspot_owner_id",
    "hs_deal_stage_probability", "hs_pipeline",
    "hs_forecast_amount", "hs_forecast_category",
    "notes_last_contacted", "notes_next_activity_date",
    "hs_deal_stage_probability_shadow_roll_up_amount",
    "createdate",  # When was this deal first created in HubSpot
]

HUBSPOT_CONTACT_PROPERTIES = [
    "firstname", "lastname", "email", "phone",
    "jobtitle", "company", "linkedin_bio",
    "hs_email_last_send_date", "hs_email_last_reply_date",
    "hs_email_open_date",
]

HUBSPOT_COMPANY_PROPERTIES = [
    "name", "domain", "industry", "annualrevenue", "numberofemployees",
    "description", "country", "city", "phone",
]

# HubSpot API hard limits — changing these without checking the docs will cause 4xx errors.
_HS_NOTE_BODY_MAX = 10_000      # HubSpot note character cap
_HS_TASK_TITLE_MAX = 250        # hs_task_subject max length
_HS_TASK_BODY_MAX = 1_000       # hs_task_body max length
_HS_NOTE_BATCH_LIMIT = 100      # batch/read endpoint accepts at most 100 inputs per call
_HS_NOTE_FALLBACK_CAP = 20      # per-request fallback: cap at 20 to bound serial latency


class HubSpotClient:
    """Async HubSpot API client."""

    BASE_URL = "https://api.hubapi.com"

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    async def get_all_deals(self) -> list[dict]:
        """Fetch all active deals with properties and associations."""
        deals = []
        after = None

        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                params = {
                    "limit": 100,
                    "properties": ",".join(HUBSPOT_DEAL_PROPERTIES),
                    "associations": "contacts,companies",
                }
                if after:
                    params["after"] = after

                resp = await client.get(
                    f"{self.BASE_URL}/crm/v3/objects/deals",
                    headers=self.headers,
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()

                deals.extend(data.get("results", []))

                paging = data.get("paging", {}).get("next")
                if not paging:
                    break
                after = paging.get("after")

        log.info("hubspot_deals_fetched", count=len(deals))
        return deals

    async def get_owners(self) -> list[dict]:
        """Fetch all deal owners (id, email, name) for rep-name resolution."""
        owners = []
        after = None
        async with httpx.AsyncClient(timeout=15.0) as client:
            while True:
                params = {"limit": 100}
                if after:
                    params["after"] = after
                resp = await client.get(
                    f"{self.BASE_URL}/crm/v3/owners",
                    headers=self.headers,
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
                for o in data.get("results", []):
                    name = " ".join(p for p in (o.get("firstName"), o.get("lastName")) if p)
                    owners.append({
                        "id": str(o.get("id")),
                        "email": o.get("email"),
                        "name": name or o.get("email"),
                    })
                paging = data.get("paging", {}).get("next")
                if not paging:
                    break
                after = paging.get("after")
        log.info("hubspot_owners_fetched", count=len(owners))
        return owners

    async def get_contact(self, contact_id: str) -> Optional[dict]:
        """Fetch a single contact with properties."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.BASE_URL}/crm/v3/objects/contacts/{contact_id}",
                headers=self.headers,
                params={"properties": ",".join(HUBSPOT_CONTACT_PROPERTIES)},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    async def create_email_draft(
        self,
        deal_id: str,
        to_email: str,
        subject: str,
        body: str,
        owner_id: str,
    ) -> dict:
        """Create a draft email associated with a deal in HubSpot."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            payload = {
                "properties": {
                    "hs_email_subject": subject,
                    "hs_email_html": body.replace("\n", "<br>"),
                    "hs_email_text": body,
                    "hs_email_to_email": to_email,
                    "hubspot_owner_id": owner_id,
                    "hs_email_status": "DRAFT",
                    "hs_email_direction": "EMAIL",
                },
                "associations": [
                    {
                        "to": {"id": deal_id},
                        # 210 = HubSpot built-in "email→deal" association type
                        "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 210}],
                    }
                ],
            }
            resp = await client.post(
                f"{self.BASE_URL}/crm/v3/objects/emails",
                headers=self.headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_pipeline_stages(self) -> dict[str, str]:
        """
        Fetch all deal pipeline stages and return a mapping of stage_id → stage_label.
        Queries all pipelines; HubSpot private apps see all accessible pipelines.
        """
        stage_map: dict[str, str] = {}
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(
                    f"{self.BASE_URL}/crm/v3/pipelines/deals",
                    headers=self.headers,
                )
                resp.raise_for_status()
                for pipeline in resp.json().get("results", []):
                    for stage in pipeline.get("stages", []):
                        stage_map[stage["id"]] = stage["label"]
            except Exception as e:
                log.warning("hubspot_pipeline_stages_failed", error=str(e))
        return stage_map

    async def get_deal_activity(self, deal_id: str, since_days: int = 365) -> list[dict]:
        """
        Get ALL notes associated with a deal, with full note body content.
        Fetches up to 100 note IDs and batch-reads all of them.
        No date filter — we want the full history so the agent has complete deal context.

        NOTE: `since_days` is intentionally unused. HubSpot's notes association endpoint
        offers no server-side date filter, so we always fetch full history. The parameter
        is kept for API compatibility with callers that pass it.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1: get ALL note IDs (paginate up to _HS_NOTE_BATCH_LIMIT).
            # Capping at the batch/read limit means step 2 always executes in one call;
            # fetching more would require multiple batch calls without improving agent context.
            note_ids = []
            after = None
            while len(note_ids) < _HS_NOTE_BATCH_LIMIT:
                params: dict = {"limit": _HS_NOTE_BATCH_LIMIT}
                if after:
                    params["after"] = after
                resp = await client.get(
                    f"{self.BASE_URL}/crm/v3/objects/deals/{deal_id}/associations/notes",
                    headers=self.headers,
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
                note_ids.extend(r["id"] for r in data.get("results", []))
                paging = data.get("paging", {}).get("next")
                if not paging or len(note_ids) >= _HS_NOTE_BATCH_LIMIT:
                    break
                after = paging.get("after")

            if not note_ids:
                return []

            # Step 2: batch-read all note bodies (HubSpot batch limit = _HS_NOTE_BATCH_LIMIT).
            # Because note_ids is already capped above, this loop executes exactly once;
            # the range/chunk structure is kept for future cap increases.
            all_notes = []
            for chunk_start in range(0, len(note_ids), _HS_NOTE_BATCH_LIMIT):
                chunk = note_ids[chunk_start:chunk_start + _HS_NOTE_BATCH_LIMIT]
                batch_resp = await client.post(
                    f"{self.BASE_URL}/crm/v3/objects/notes/batch/read",
                    headers=self.headers,
                    json={
                        "inputs": [{"id": nid} for nid in chunk],
                        "properties": ["hs_note_body", "hs_timestamp", "hubspot_owner_id"],
                    },
                )
                if batch_resp.status_code == 200:
                    all_notes.extend(batch_resp.json().get("results", []))
                else:
                    # Fallback: serial fetch. Cap at _HS_NOTE_FALLBACK_CAP to bound latency —
                    # each request is sequential; 20 × ~200ms ≈ 4s, acceptable for a degraded path.
                    for nid in chunk[:_HS_NOTE_FALLBACK_CAP]:
                        try:
                            nr = await client.get(
                                f"{self.BASE_URL}/crm/v3/objects/notes/{nid}",
                                headers=self.headers,
                                params={"properties": "hs_note_body,hs_timestamp"},
                            )
                            if nr.status_code == 200:
                                all_notes.append(nr.json())
                        except Exception:
                            pass
            return all_notes

    async def get_deal_contacts(self, deal_id: str) -> list[dict]:
        """
        Fetch all contacts associated with a deal, with full properties.
        Returns name, email, title, and engagement timestamps.
        """
        contacts = []
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                resp = await client.get(
                    f"{self.BASE_URL}/crm/v3/objects/deals/{deal_id}/associations/contacts",
                    headers=self.headers,
                    params={"limit": 10},
                )
                if resp.status_code != 200:
                    return []
                contact_ids = [r["id"] for r in resp.json().get("results", [])]
                # Cap at 5 to avoid ballooning agent context; primary + champion is usually 2-3.
                for cid in contact_ids[:5]:
                    contact = await self.get_contact(cid)
                    if contact:
                        contacts.append(contact)
            except Exception as e:
                log.warning("hubspot_deal_contacts_failed", deal_id=deal_id, error=str(e))
        return contacts

    async def get_deal_emails(self, deal_id: str, limit: int = 10) -> list[dict]:
        """
        Fetch email engagements associated with a deal.
        Returns subject, direction, timestamp, and preview body.
        Requires HubSpot email integration to be enabled on the portal.

        Uses batch/read (single round-trip) rather than serial per-ID GETs,
        matching the pattern in get_deal_activity.
        """
        email_props = [
            "hs_email_subject", "hs_email_text", "hs_email_direction",
            "hs_timestamp", "hs_email_from_email", "hs_email_to_email", "hs_email_status",
        ]
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                resp = await client.get(
                    f"{self.BASE_URL}/crm/v3/objects/deals/{deal_id}/associations/emails",
                    headers=self.headers,
                    params={"limit": limit},
                )
                if resp.status_code != 200:
                    return []
                email_ids = [r["id"] for r in resp.json().get("results", [])]
                if not email_ids:
                    return []

                # Batch-read all email objects in one request instead of N serial GETs.
                batch_resp = await client.post(
                    f"{self.BASE_URL}/crm/v3/objects/emails/batch/read",
                    headers=self.headers,
                    json={
                        "inputs": [{"id": eid} for eid in email_ids],
                        "properties": email_props,
                    },
                )
                if batch_resp.status_code == 200:
                    return batch_resp.json().get("results", [])

                # Batch endpoint unavailable (e.g. portal scope missing) — serial fallback.
                # Cap at limit to bound latency; each GET ≈ 200ms so limit=10 → ≤2s.
                emails = []
                props_str = ",".join(email_props)
                for eid in email_ids:
                    try:
                        er = await client.get(
                            f"{self.BASE_URL}/crm/v3/objects/emails/{eid}",
                            headers=self.headers,
                            params={"properties": props_str},
                        )
                        if er.status_code == 200:
                            emails.append(er.json())
                    except Exception:
                        pass
                return emails
            except Exception as e:
                log.warning("hubspot_deal_emails_failed", deal_id=deal_id, error=str(e))
                return []

    async def get_deal_engagements(self, deal_id: str, limit: int = 50) -> list[dict]:
        """
        Fetch all engagement activity for a deal via the v1 Engagements API.
        Covers EMAIL (logged threads from Gmail/Outlook), CALL (call notes),
        MEETING (meeting notes), and NOTE types. Much more comprehensive than
        the CRM v3 emails endpoint which only covers HubSpot-sent emails.
        """
        engagements: list[dict] = []
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                offset = 0
                while True:
                    resp = await client.get(
                        f"{self.BASE_URL}/engagements/v1/engagements/associated/deal/{deal_id}/paged",
                        headers=self.headers,
                        params={"limit": min(limit, 100), "offset": offset},
                    )
                    if resp.status_code != 200:
                        break
                    data = resp.json()
                    batch = data.get("results", [])
                    engagements.extend(batch)
                    if not data.get("hasMore") or len(engagements) >= limit:
                        break
                    offset += len(batch)
            except Exception as e:
                log.warning("hubspot_engagements_failed", deal_id=deal_id, error=str(e))
        return engagements[:limit]

    async def get_deal_company(self, deal_id: str) -> Optional[dict]:
        """
        Fetch the primary company associated with a deal.
        Returns company properties: name, domain, industry, revenue, employee count.
        Used to enrich the agent pipeline with firmographic context.
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                # Step 1: get company association IDs
                resp = await client.get(
                    f"{self.BASE_URL}/crm/v3/objects/deals/{deal_id}/associations/companies",
                    headers=self.headers,
                    params={"limit": 1},
                )
                if resp.status_code != 200:
                    return None
                company_ids = [r["id"] for r in resp.json().get("results", [])]
                if not company_ids:
                    return None

                # Step 2: fetch company properties
                company_resp = await client.get(
                    f"{self.BASE_URL}/crm/v3/objects/companies/{company_ids[0]}",
                    headers=self.headers,
                    params={"properties": ",".join(HUBSPOT_COMPANY_PROPERTIES)},
                )
                if company_resp.status_code == 200:
                    return company_resp.json()
            except Exception as e:
                log.warning("hubspot_deal_company_failed", deal_id=deal_id, error=str(e))
        return None

    async def create_deal_note(self, deal_id: str, body: str) -> dict:
        """
        Create a note on a HubSpot deal via the v1 Engagements API.
        Used by the nightly write-back to log Vantage AI run summaries.
        """
        body = body[:_HS_NOTE_BODY_MAX]  # HubSpot note length cap
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.BASE_URL}/engagements/v1/engagements",
                headers=self.headers,
                json={
                    "engagement": {"active": True, "type": "NOTE"},
                    "associations": {"dealIds": [int(deal_id)]},
                    "metadata": {"body": body},
                },
            )
            resp.raise_for_status()
            log.info("hubspot_note_created", deal_id=deal_id, body_len=len(body))
            return resp.json()

    async def create_deal_task(
        self,
        deal_id: str,
        title: str,
        due_date: Optional[str],
        owner_id: Optional[str] = None,
        body: Optional[str] = None,
    ) -> dict:
        """
        Create a task on a HubSpot deal via the CRM v3 Tasks API.
        Used by the nightly write-back when top action urgency is critical.
        due_date: ISO date string "YYYY-MM-DD"
        """
        props: dict = {
            "hs_task_subject": title[:_HS_TASK_TITLE_MAX],
            "hs_task_status": "NOT_STARTED",
            "hs_task_type": "TODO",
        }
        if body:
            props["hs_task_body"] = body[:_HS_TASK_BODY_MAX]
        if due_date:
            # HubSpot tasks use epoch ms for hs_timestamp.
            # 9 AM UTC is used as the intra-day anchor so tasks surface at the start of
            # the business day in US-East (5 AM) through Europe (10-11 AM) without feeling stale.
            try:
                d = _date.fromisoformat(due_date)
                props["hs_timestamp"] = int(
                    datetime(d.year, d.month, d.day, 9, 0, 0, tzinfo=timezone.utc).timestamp() * 1000
                )
            except Exception:
                pass
        if owner_id:
            props["hubspot_owner_id"] = owner_id

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.BASE_URL}/crm/v3/objects/tasks",
                headers=self.headers,
                json={
                    "properties": props,
                    "associations": [
                        {
                            "to": {"id": deal_id},
                            # 216 = HubSpot built-in "task→deal" association type
                            "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 216}],
                        }
                    ],
                },
            )
            resp.raise_for_status()
            log.info("hubspot_task_created", deal_id=deal_id, title=title[:60])
            return resp.json()

    async def update_deal_properties(self, deal_id: str, properties: dict) -> dict:
        """
        Update HubSpot deal properties.
        Used by Smart Fields write-back when a rep accepts an AI suggestion.

        Example properties: {"hs_forecast_category": "Best Case", "closedate": "2026-09-30"}
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.patch(
                f"{self.BASE_URL}/crm/v3/objects/deals/{deal_id}",
                headers=self.headers,
                json={"properties": properties},
            )
            resp.raise_for_status()
            log.info("hubspot_deal_updated", deal_id=deal_id, fields=list(properties.keys()))
            return resp.json()

    async def _oauth_token_post(self, extra_fields: dict) -> dict:
        """
        POST to HubSpot OAuth token endpoint with form-encoded data.
        HubSpot rejects JSON here — `data=` (not `json=`) is mandatory.
        """
        settings = get_settings()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.BASE_URL}/oauth/v1/token",
                data={
                    "client_id": settings.hubspot_client_id,
                    "client_secret": settings.hubspot_client_secret,
                    **extra_fields,
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def exchange_code(self, code: str, redirect_uri: str) -> dict:
        """Exchange OAuth authorization code for tokens."""
        return await self._oauth_token_post({
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": code,
        })

    async def refresh_token(self, refresh_token: str) -> dict:
        """Refresh an expired access token."""
        return await self._oauth_token_post({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })


def parse_deal_to_raw_account(deal: dict) -> dict:
    """
    Convert HubSpot deal response to our internal RawAccount format.
    Schema contract: consumed by hubspot_sync.py → account_service.upsert_raw_account().
    Field names here must stay in sync with the RawAccount TypedDict in account_service.py.
    """
    props = deal.get("properties", {})

    assocs = deal.get("associations", {})
    contact_ids = [a.get("id") for a in assocs.get("contacts", {}).get("results", [])]
    company_ids = [a.get("id") for a in assocs.get("companies", {}).get("results", [])]

    return {
        "hubspot_deal_id": deal.get("id"),
        "name": props.get("dealname", "Unnamed Deal"),
        "stage": props.get("dealstage", ""),
        "deal_amount": _parse_float(props.get("amount")),
        "close_date": props.get("closedate", "")[:10] if props.get("closedate") else None,
        "owner_rep_id": props.get("hubspot_owner_id", ""),
        "contact_ids": contact_ids,
        "company_ids": company_ids,
        "last_modified": props.get("hs_last_modified_date", ""),
        "forecast_category": props.get("hs_forecast_category", "Pipeline"),
        "pipeline": props.get("hs_pipeline", ""),
        "stage_probability": _parse_float(props.get("hs_deal_stage_probability")),
        "last_contacted": props.get("notes_last_contacted", ""),
        "next_activity": props.get("notes_next_activity_date", ""),
        "deal_created_at": props.get("createdate", "")[:10] if props.get("createdate") else None,
    }


def verify_hubspot_webhook_signature(
    request_body: bytes,
    signature: str,
    client_secret: str,
    timestamp: Optional[str] = None,
    request_url: str = "",
) -> bool:
    """
    Verify HubSpot webhook HMAC-SHA256 signature (v3: timestamp + URL + body).
    Validates timestamp freshness (5-minute window) before computing HMAC.

    v3 requires the full request URL (scheme + host + path + query). Omitting it
    previously produced a silently wrong HMAC via the "https://" fallback; we now
    reject early so callers fail loudly rather than pass a bogus signature check.
    """
    if not signature or not client_secret:
        return False

    # v3 validation (timestamp + body)
    if timestamp:
        # Reject if the URL is missing — source string would be wrong and HMAC would pass
        # only by accident (attacker knows we use "https://" as placeholder).
        if not request_url:
            log.error("hubspot_webhook_v3_missing_url", note="request_url required for v3 signature; rejecting")
            return False
        try:
            # Guard against absurdly long inputs before int() parse; epoch ms is ≤ 13 digits.
            if len(timestamp) > 20:
                return False
            ts_seconds = int(timestamp) / 1000  # HubSpot sends milliseconds
            age = abs(_time.time() - ts_seconds)
            if age > 300:  # 5 minute window
                return False
        except (ValueError, TypeError):
            return False

        source_string = f"POST\n{request_url}\n{timestamp}\n{request_body.decode()}"
        expected = hmac.new(
            client_secret.encode(), source_string.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected)

    # v2 fallback (body only) — weaker: no timestamp, no URL binding.
    # HubSpot only sends v2 for portals that haven't upgraded; log so we notice.
    log.warning("hubspot_webhook_v2_signature", note="no timestamp header; replay attack risk elevated")
    source_string = client_secret + request_body.decode()
    expected = hashlib.sha256(source_string.encode()).hexdigest()
    return hmac.compare_digest(signature, expected)


def _parse_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
