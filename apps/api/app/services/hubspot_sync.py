"""
HubSpotSyncService — Full deal sync from HubSpot to accounts table.
Called on: workspace setup, nightly run, manual trigger.
Detects deltas vs existing records — only updates what changed.
"""
import uuid
from datetime import datetime, timezone, date
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import structlog

from app.models.account import Account, AuditLog
from app.models.workspace import Workspace
from app.integrations.hubspot import HubSpotClient, parse_deal_to_raw_account

log = structlog.get_logger()


def _parse_date(value) -> Optional[date]:
    """Parse a HubSpot date string ('2024-05-06') or None into a Python date object."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


class HubSpotSyncService:
    """Syncs HubSpot deals into the accounts table."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def sync_workspace(self, workspace_id: str) -> dict:
        """
        Full HubSpot sync for a workspace.
        Pulls all deals, upserts accounts, logs changes.
        Returns: {created, updated, unchanged, errors}
        """
        # Load workspace
        result = await self.db.execute(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        ws = result.scalar_one_or_none()
        if not ws or not ws.hubspot_access_token:
            raise ValueError("Workspace HubSpot not connected")

        hs = HubSpotClient(ws.hubspot_access_token)

        # Fetch all deals from HubSpot
        log.info("hubspot_sync_started", workspace_id=workspace_id)
        try:
            deals = await hs.get_all_deals()
        except Exception as e:
            log.error("hubspot_sync_fetch_failed", workspace_id=workspace_id, error=str(e))
            raise

        # Fetch stage labels (stage_id → human-readable name)
        stage_labels = await hs.get_pipeline_stages()
        log.info("hubspot_stage_labels_fetched", count=len(stage_labels), sample=list(stage_labels.items())[:3])

        # Load all existing accounts for this workspace (for delta detection)
        existing_result = await self.db.execute(
            select(Account).where(
                Account.workspace_id == workspace_id,
                Account.deleted_at.is_(None),
            )
        )
        existing_accounts = {
            acc.hubspot_deal_id: acc
            for acc in existing_result.scalars().all()
            if acc.hubspot_deal_id
        }

        stats = {"created": 0, "updated": 0, "unchanged": 0, "errors": 0}
        seen_deal_ids = set()

        for deal in deals:
            try:
                raw = parse_deal_to_raw_account(deal)
                deal_id = raw["hubspot_deal_id"]

                # Derive account_type BEFORE stage label mapping (while dealstage is still the raw ID)
                # "closedwon" = existing customer (CS/AM plays); everything else = active prospect
                raw_dealstage = (raw.get("stage") or "").lower()
                raw["account_type"] = "customer" if raw_dealstage == "closedwon" else "prospect"

                # Map raw stage ID to human-readable label if available
                if raw["stage"] and raw["stage"] in stage_labels:
                    raw["stage"] = stage_labels[raw["stage"]]
                elif raw["stage"] and _is_internal_stage_id(raw["stage"]):
                    # Raw internal HubSpot stage ID — couldn't resolve label. Store None
                    # rather than polluting the UI with "1219886089"-style strings.
                    log.debug("stage_id_unresolved", stage_id=raw["stage"], deal_id=deal_id)
                    raw["stage"] = None
                # Fallback: if stage wasn't in pipeline map but is readable, keep it.
                # Only null out purely numeric IDs (e.g. "1219886089") which are
                # opaque and not meaningful in the UI.
                seen_deal_ids.add(deal_id)

                if deal_id in existing_accounts:
                    changed = await self._update_account(
                        existing_accounts[deal_id], raw, workspace_id
                    )
                    if changed:
                        stats["updated"] += 1
                    else:
                        stats["unchanged"] += 1
                else:
                    await self._create_account(raw, workspace_id, ws)
                    stats["created"] += 1

            except Exception as e:
                log.warning("deal_sync_error", deal_id=deal.get("id"), error=str(e))
                stats["errors"] += 1

        # Soft-delete accounts no longer in HubSpot
        for deal_id, account in existing_accounts.items():
            if deal_id not in seen_deal_ids:
                account.deleted_at = datetime.now(timezone.utc)
                log.info("account_soft_deleted", account_id=str(account.id), deal_id=deal_id)

        # Refresh owner-id → name mapping so analytics can show rep names
        # instead of raw HubSpot owner IDs ("Rep #566492").
        try:
            owners = await hs.get_owners()
            if owners:
                settings_dict = dict(ws.settings or {})
                settings_dict["hubspot_owners"] = {
                    o["id"]: {"name": o["name"], "email": o["email"]} for o in owners
                }
                ws.settings = settings_dict
        except Exception as e:
            log.warning("hubspot_owners_sync_failed", workspace_id=workspace_id, error=str(e))

        await self.db.commit()

        log.info(
            "hubspot_sync_complete",
            workspace_id=workspace_id,
            **stats,
        )
        return stats

    async def _create_account(self, raw: dict, workspace_id: str, ws: Workspace) -> Account:
        """Create a new account from a HubSpot deal."""
        account = Account(
            workspace_id=uuid.UUID(workspace_id),
            hubspot_deal_id=raw["hubspot_deal_id"],
            name=raw["name"],
            stage=raw["stage"],
            deal_amount=raw["deal_amount"],
            close_date=_parse_date(raw["close_date"]),
            owner_rep_id=raw["owner_rep_id"],
            state={
                "crm_forecast_category": raw.get("forecast_category"),
                # account_type: "customer" for closed-won deals, "prospect" for active pipeline
                # Used by Plays Engine to route CS/AM vs new-logo plays
                "account_type": raw.get("account_type", "prospect"),
                # CRM metadata stored for researcher context on first run
                "contact_ids": raw.get("contact_ids", []),
                "company_ids": raw.get("company_ids", []),
                "last_contacted": raw.get("last_contacted") or None,
                "next_activity": raw.get("next_activity") or None,
                "deal_created_at": raw.get("deal_created_at") or None,
                "signals": [],
                "pov": {},
                "next_actions": [],
                "gold_data": {},
                "episodic_memory": {"episodes": [], "summary": ""},
                "stakeholders": [],
            },
        )
        self.db.add(account)
        log.debug("account_created", name=raw["name"], deal_id=raw["hubspot_deal_id"])
        return account

    async def _update_account(
        self,
        account: Account,
        raw: dict,
        workspace_id: str,
    ) -> bool:
        """
        Update an existing account if CRM data changed.
        Returns True if any field changed.
        """
        changes = {}

        if account.name != raw["name"]:
            changes["name"] = {"before": account.name, "after": raw["name"]}
            account.name = raw["name"]

        if account.stage != raw["stage"]:
            changes["stage"] = {"before": account.stage, "after": raw["stage"]}
            account.stage = raw["stage"]
            # Deal just closed: clamp urgency so it drops off triage surfaces.
            # The nightly worker skips closed stages, so a stale 0.95 here
            # would otherwise sit at the top of the inbox forever.
            from app.agents.base import CLOSED_STAGES
            if (raw["stage"] or "").strip().lower() in CLOSED_STAGES:
                account.urgency_score = 0.1

        raw_amount = raw.get("deal_amount")
        if raw_amount is not None and float(account.deal_amount or 0) != float(raw_amount):
            changes["deal_amount"] = {"before": float(account.deal_amount or 0), "after": float(raw_amount)}
            account.deal_amount = raw_amount

        if str(account.close_date or "") != str(raw.get("close_date") or ""):
            changes["close_date"] = {"before": str(account.close_date), "after": raw.get("close_date")}
            account.close_date = _parse_date(raw.get("close_date"))

        if account.owner_rep_id != raw.get("owner_rep_id"):
            changes["owner_rep_id"] = {"before": account.owner_rep_id, "after": raw.get("owner_rep_id")}
            account.owner_rep_id = raw.get("owner_rep_id")

        # Update CRM metadata in state (forecast, contact IDs, last activity)
        state = dict(account.state or {})
        state_dirty = False

        if raw.get("forecast_category") and state.get("crm_forecast_category") != raw["forecast_category"]:
            changes["crm_forecast_category"] = {
                "before": state.get("crm_forecast_category"),
                "after": raw["forecast_category"],
            }
            state["crm_forecast_category"] = raw["forecast_category"]
            state_dirty = True

        # Keep account_type in sync (stage change e.g. prospect → closedwon → customer)
        new_account_type = raw.get("account_type", "prospect")
        if state.get("account_type") != new_account_type:
            state["account_type"] = new_account_type
            state_dirty = True

        # Keep contact/company IDs fresh so the pipeline can resolve them
        if raw.get("contact_ids") is not None and state.get("contact_ids") != raw["contact_ids"]:
            state["contact_ids"] = raw["contact_ids"]
            state_dirty = True
        if raw.get("company_ids") is not None and state.get("company_ids") != raw["company_ids"]:
            state["company_ids"] = raw["company_ids"]
            state_dirty = True

        # Keep CRM activity timestamps fresh
        for field in ("last_contacted", "next_activity"):
            new_val = raw.get(field) or None
            if state.get(field) != new_val:
                state[field] = new_val
                state_dirty = True

        # Preserve deal creation date from HubSpot (set once, never overwritten with None)
        if raw.get("deal_created_at") and not state.get("deal_created_at"):
            state["deal_created_at"] = raw["deal_created_at"]
            state_dirty = True

        if state_dirty:
            account.state = state

        if not changes:
            return False

        # Log significant changes to audit trail
        if any(k in changes for k in ("stage", "deal_amount", "close_date")):
            audit = AuditLog(
                workspace_id=uuid.UUID(workspace_id),
                action="crm_sync_update",
                resource_type="account",
                resource_id=str(account.id),
                actor_id="hubspot_sync",
                changes=changes,
            )
            self.db.add(audit)

        log.debug(
            "account_updated",
            account_id=str(account.id),
            name=account.name,
            changed_fields=list(changes.keys()),
        )
        return True


def _is_internal_stage_id(stage: str) -> bool:
    """
    Returns True ONLY for purely numeric HubSpot internal stage IDs (e.g. "1219886089").
    These are opaque custom-pipeline IDs that are meaningless in the UI.

    HubSpot default pipeline IDs like "closedwon", "closedlost",
    "appointmentscheduled" are intentionally kept — they're recognisable
    and better than showing nothing when the pipeline API call fails.
    """
    if not stage:
        return False
    # Purely numeric → custom pipeline internal ID, strip it
    return stage.isdigit()
