"""
Webhooks router — HubSpot inbound webhook handler.
POST /webhooks/hubspot  — receive deal/contact events, queue for processing
"""
import json
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Request, HTTPException, Header, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import Depends
import structlog

from app.db.database import get_db
from app.config import get_settings
from app.integrations.hubspot import verify_hubspot_webhook_signature
from app.models.workspace import Workspace

log = structlog.get_logger()
router = APIRouter()

# HubSpot event types we care about
RELEVANT_EVENTS = {
    "deal.propertyChange",
    "deal.creation",
    "deal.deletion",
    "contact.propertyChange",
    "contact.creation",
}

# Properties that trigger immediate re-analysis
HIGH_URGENCY_PROPERTIES = {
    "dealstage", "closedate", "amount", "hs_forecast_category",
    "hubspot_owner_id", "notes_last_contacted",
}


@router.post("/hubspot")
async def hubspot_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    x_hubspot_signature: str = Header(None, alias="X-HubSpot-Signature"),
    x_hubspot_signature_v3: str = Header(None, alias="X-HubSpot-Signature-v3"),
    x_hubspot_request_timestamp: str = Header(None, alias="X-HubSpot-Request-Timestamp"),
):
    """
    HubSpot webhook receiver.
    Validates HMAC signature, classifies events, queues high-urgency ones
    for immediate agent refresh via Azure Service Bus.
    Low-urgency events are batched for the nightly run.
    """
    settings = get_settings()
    body = await request.body()

    # Verify HMAC signature — require v3 (includes timestamp, prevents replay attacks)
    # v2 is accepted as fallback only if v3 is absent, but logged as degraded
    if x_hubspot_signature_v3 and x_hubspot_request_timestamp:
        sig = x_hubspot_signature_v3
        timestamp = x_hubspot_request_timestamp
    elif x_hubspot_signature:
        # v2 has no replay protection — always reject
        log.warning("hubspot_webhook_v2_rejected", environment=settings.environment)
        raise HTTPException(status_code=400, detail="HubSpot webhook v3 signature required. Upgrade your HubSpot app settings.")
    else:
        log.warning("hubspot_webhook_no_signature")
        raise HTTPException(status_code=401, detail="Missing webhook signature")

    if not verify_hubspot_webhook_signature(
        request_body=body,
        signature=sig,
        client_secret=settings.hubspot_client_secret,
        timestamp=timestamp,
        request_url=str(request.url),
    ):
        log.warning("hubspot_webhook_signature_invalid", sig_version="v3" if x_hubspot_signature_v3 else "v2")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Parse events
    try:
        events = json.loads(body)
        if not isinstance(events, list):
            events = [events]
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    log.info("hubspot_webhook_received", event_count=len(events))

    # Process each event
    high_urgency_accounts = set()
    low_urgency_accounts = set()

    for event in events:
        event_type = event.get("subscriptionType", "")
        portal_id = str(event.get("portalId", ""))
        object_id = str(event.get("objectId", ""))
        changed_property = event.get("propertyName", "")

        if event_type not in RELEVANT_EVENTS:
            continue

        # Find the workspace this portal belongs to
        ws = await _find_workspace_by_portal(db, portal_id)
        if not ws:
            log.debug("webhook_no_workspace", portal_id=portal_id)
            continue

        if "deal" in event_type:
            if changed_property in HIGH_URGENCY_PROPERTIES or event_type == "deal.deletion":
                high_urgency_accounts.add((str(ws.id), object_id, event_type, changed_property))
            else:
                low_urgency_accounts.add((str(ws.id), object_id))

    # Stage changes → immediate partial pipeline (Loop 2)
    stage_change_deals = [
        (ws_id, deal_id) for ws_id, deal_id, evt, prop in high_urgency_accounts
        if prop == "dealstage"
    ]
    for ws_id, deal_id in stage_change_deals:
        background_tasks.add_task(_run_partial_pipeline, ws_id, deal_id)

    # Other high-urgency events → queue via Service Bus (existing path)
    non_stage_urgent = {
        (ws_id, deal_id, evt, prop) for ws_id, deal_id, evt, prop in high_urgency_accounts
        if prop != "dealstage"
    }
    if non_stage_urgent:
        await _queue_immediate_refresh(non_stage_urgent, settings)

    # Low-urgency: just flag accounts as dirty (picked up by nightly run)
    if low_urgency_accounts:
        await _mark_accounts_dirty(low_urgency_accounts, db)

    return Response(status_code=200)


async def _run_partial_pipeline(workspace_id: str, hubspot_deal_id: str) -> None:
    """Background task: partial pipeline (Researcher + RiskScanner) on stage change."""
    try:
        from app.db.database import AsyncSessionLocal
        from app.services.nightly_worker import NightlyWorker
        async with AsyncSessionLocal() as db:
            worker = NightlyWorker(db)
            await worker.run_partial_pipeline_for_deal(
                workspace_id=workspace_id,
                hubspot_deal_id=hubspot_deal_id,
                trigger_type="webhook_stage_change",
            )
    except Exception as e:
        log.error("partial_pipeline_bg_failed", workspace_id=workspace_id, deal_id=hubspot_deal_id, error=str(e))


async def _find_workspace_by_portal(db: AsyncSession, portal_id: str) -> Workspace | None:
    """Find workspace by HubSpot portal ID."""
    result = await db.execute(
        select(Workspace).where(Workspace.hubspot_portal_id == portal_id)
    )
    return result.scalar_one_or_none()


async def _queue_immediate_refresh(
    account_events: set,
    settings,
) -> None:
    """
    Queue deal IDs for immediate agent refresh via Azure Service Bus.
    These are high-urgency events (stage change, close date change, etc.)
    that should not wait for the nightly run.
    """
    try:
        from azure.servicebus.aio import ServiceBusClient
        from azure.servicebus import ServiceBusMessage

        async with ServiceBusClient.from_connection_string(
            settings.azure_service_bus_connection_string
        ) as client:
            async with client.get_queue_sender("vantage-immediate-refresh") as sender:
                for workspace_id, hubspot_deal_id, event_type, changed_property in account_events:
                    msg = ServiceBusMessage(
                        body=json.dumps({
                            "workspace_id": workspace_id,
                            "hubspot_deal_id": hubspot_deal_id,
                            "trigger": "webhook",
                            "event_type": event_type,
                            "changed_property": changed_property,
                            "queued_at": datetime.now(timezone.utc).isoformat(),
                        }),
                        content_type="application/json",
                    )
                    await sender.send_messages(msg)

        log.info("webhook_events_queued", count=len(account_events))
    except Exception as e:
        # Don't fail the webhook response — events will be caught in nightly run
        log.error("service_bus_queue_failed", error=str(e), count=len(account_events))


async def _mark_accounts_dirty(
    account_refs: set,
    db: AsyncSession,
) -> None:
    """
    Mark accounts as needing refresh (set last_modified_at).
    These will be picked up by the next nightly run.
    """
    from app.models.account import Account
    from sqlalchemy import update

    for workspace_id, hubspot_deal_id in account_refs:
        try:
            await db.execute(
                update(Account)
                .where(
                    Account.hubspot_deal_id == hubspot_deal_id,
                    Account.workspace_id == workspace_id,
                )
                .values(hubspot_last_modified=datetime.now(timezone.utc))
            )
        except Exception as e:
            log.warning("mark_dirty_failed", hubspot_deal_id=hubspot_deal_id, error=str(e))

    await db.commit()
