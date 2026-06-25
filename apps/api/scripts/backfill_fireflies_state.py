"""
One-off: pull Fireflies transcripts and populate state["transcripts"] +
state["conversation_intel"] for every matched account.

The interactions table already has call notes from past ingests; this fills
the UI/agent-visible state layer that the (now fixed) wipe + hollow-map bugs
kept empty. Idempotent: entries merge by transcript id.

Usage: PYTHONPATH=. python scripts/backfill_fireflies_state.py
"""
import asyncio

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.config import get_settings
from app.db.database import AsyncSessionLocal
from app.models.workspace import Workspace  # noqa: F401 — mapper registration
from app.models.account import Account
from app.integrations.fireflies import FirefliesClient, backfill_all_transcripts
from app.services.conversation_intel import (
    merge_transcript_entries, compute_conversation_rollup,
)


async def main():
    settings = get_settings()
    if not settings.fireflies_api_key:
        print("FIREFLIES_API_KEY not set")
        return

    async with AsyncSessionLocal() as db:
        accounts = (await db.execute(
            select(Account).where(Account.deleted_at.is_(None))
        )).scalars().all()
        print(f"{len(accounts)} accounts loaded")

        # Calendar events give the +4 DEFINITIVE match (transcript time ±15min
        # vs an Outlook meeting already linked to an account). Without them,
        # matching falls back to name words — which cross-attached Shell Crux
        # calls to every Shell-branded deal.
        from app.models.account import Interaction
        cal_rows = (await db.execute(
            select(Interaction.account_id, Interaction.occurred_at).where(
                Interaction.source == "outlook",
                Interaction.type == "meeting",
                Interaction.occurred_at.is_not(None),
            )
        )).all()
        calendar_events = [
            {"account_id": str(r.account_id), "occurred_at": r.occurred_at}
            for r in cal_rows
        ]
        print(f"{len(calendar_events)} calendar events loaded for time-matching")

        account_dicts = [
            {"id": a.id, "workspace_id": a.workspace_id, "name": a.name,
             "created_at": a.created_at, "close_date": a.close_date}
            for a in accounts
        ]
        ff = FirefliesClient(api_key=settings.fireflies_api_key)
        matched = await backfill_all_transcripts(
            ff, account_dicts, limit=200, calendar_events=calendar_events
        )
        print(f"{len(matched)} transcript-account matches")

        by_account: dict[str, list[dict]] = {}
        for m in matched:
            entry = m.get("entry")
            if entry and entry.get("id"):
                by_account.setdefault(m["account_id"], []).append(entry)

        accounts_by_id = {str(a.id): a for a in accounts}
        updated = 0
        for aid, entries in by_account.items():
            acc = accounts_by_id.get(aid)
            if not acc:
                continue
            state = acc.state or {}
            state["transcripts"] = merge_transcript_entries(
                state.get("transcripts", []), entries
            )
            state["conversation_intel"] = compute_conversation_rollup(
                state["transcripts"], state.get("stakeholders", [])
            )
            acc.state = state
            flag_modified(acc, "state")
            updated += 1

        await db.commit()
        print(f"state updated on {updated} accounts")

        # Coverage summary
        total_calls = sum(len(e) for e in by_account.values())
        with_ratio = sum(
            1 for entries in by_account.values()
            for e in entries if e.get("talk_ratio_rep") is not None
        )
        print(f"{total_calls} calls stored | {with_ratio} with talk-time stats")


asyncio.run(main())
