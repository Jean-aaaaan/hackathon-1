"""
Dev-only: seed a synthetic Fireflies transcript entry into one account so the
Conversation Intelligence UI can be verified without a live Fireflies key.
Uses the REAL production helpers (build_transcript_entry / rollup) so the
stored shape is exactly what ingest produces.

Usage: python scripts/seed_conversation_intel.py "account name fragment"
"""
import asyncio
import sys
import time

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.db.database import AsyncSessionLocal
from app.models.workspace import Workspace  # noqa: F401 — mapper registration
from app.models.account import Account
from app.services.conversation_intel import (
    build_transcript_entry, merge_transcript_entries, compute_conversation_rollup,
)

NOW_MS = int(time.time() * 1000)
DAY_MS = 86_400_000

SYNTH = [
    {
        "id": "seed-call-2",
        "title": "Abu Dhabi Municipality x Invigilo — proposal walkthrough",
        "date": NOW_MS - 9 * DAY_MS,
        "duration": 2400,
        "organizer_email": "vishnu@invigilo.sg",
        "participants": ["vishnu@invigilo.sg", "arjun@tenderd.com"],
        "meeting_attendees": [
            {"displayName": "Vishnu Saran", "email": "vishnu@invigilo.sg"},
            {"displayName": "Arjun Patel", "email": "arjun@tenderd.com"},
        ],
        "transcript_url": "https://app.fireflies.ai/view/seed-call-2",
        "summary": {
            "overview": "Walked through the SafeKey proposal for ADM sites. Arjun raised budget timing and asked who signs off on municipal procurement. No economic buyer present.",
            "keywords": ["proposal", "budget", "procurement"],
            "action_items": [
                "**Vishnu** Send ISO 27001 certification pack (18:21)",
                "**Arjun** Confirm the ADM procurement contact by next week (31:05)",
                "**Arjun** Share internal budget timeline (33:40)",
            ],
        },
        "sentences": [
            {"speaker_name": "Vishnu Saran", "text": "Let me walk through the deployment phases.", "start_time": 0, "end_time": 300},
            {"speaker_name": "Vishnu Saran", "text": "Phase one covers the first forty cameras.", "start_time": 300, "end_time": 700},
            {"speaker_name": "Arjun Patel", "text": "Who would handle the on-site maintenance during the pilot?", "start_time": 700, "end_time": 760},
            {"speaker_name": "Vishnu Saran", "text": "We provide that with a local partner.", "start_time": 760, "end_time": 900},
            {"speaker_name": "Arjun Patel", "text": "What does the municipal procurement approval flow look like from your side?", "start_time": 900, "end_time": 980},
            {"speaker_name": "Vishnu Saran", "text": "We have done Ministry approvals in KSA, similar flow.", "start_time": 980, "end_time": 1200},
        ],
    },
    {
        "id": "seed-call-1",
        "title": "Tenderd x Abu Dhabi Municipality — discovery",
        "date": NOW_MS - 38 * DAY_MS,
        "duration": 1800,
        "organizer_email": "vishnu@invigilo.sg",
        "participants": ["vishnu@invigilo.sg", "arjun@tenderd.com", "site.lead@tenderd.com"],
        "meeting_attendees": [
            {"displayName": "Vishnu Saran", "email": "vishnu@invigilo.sg"},
            {"displayName": "Arjun Patel", "email": "arjun@tenderd.com"},
            {"displayName": "Khalid Rahman", "email": "site.lead@tenderd.com"},
        ],
        "transcript_url": "https://app.fireflies.ai/view/seed-call-1",
        "summary": {
            "overview": "Discovery on ADM safety monitoring needs across municipal sites. Strong interest in existing-camera integration.",
            "keywords": ["discovery", "cameras", "safety"],
            "action_items": [
                "**Vishnu** Send case study from KSA NOC deployment (40:12)",
            ],
        },
        "sentences": [
            {"speaker_name": "Vishnu Saran", "text": "Tell me about the current safety setup.", "start_time": 0, "end_time": 100},
            {"speaker_name": "Arjun Patel", "text": "We have CCTV at most sites but no analytics on top.", "start_time": 100, "end_time": 400},
            {"speaker_name": "Khalid Rahman", "text": "Can it detect missing PPE in low light conditions?", "start_time": 400, "end_time": 470},
            {"speaker_name": "Vishnu Saran", "text": "Yes, our models are trained on industrial night footage.", "start_time": 470, "end_time": 900},
        ],
    },
]


async def main():
    fragment = sys.argv[1] if len(sys.argv) > 1 else "abu dhabi"
    async with AsyncSessionLocal() as db:
        acc = (await db.execute(
            select(Account).where(Account.name.ilike(f"%{fragment}%"))
        )).scalars().first()
        if not acc:
            print(f"no account matching {fragment!r}")
            return
        entries = [build_transcript_entry(t) for t in SYNTH]
        state = acc.state or {}
        state["transcripts"] = merge_transcript_entries(state.get("transcripts", []), entries)
        state["conversation_intel"] = compute_conversation_rollup(
            state["transcripts"], state.get("stakeholders", [])
        )
        acc.state = state
        flag_modified(acc, "state")
        await db.commit()
        ci = state["conversation_intel"]
        print(f"seeded {len(entries)} calls into {acc.name}")
        print(f"rollup: calls={ci['calls_total']} 30d={ci['calls_last_30d']} "
              f"talk={ci['avg_talk_ratio_rep']} eb_attended={ci['eb_attendance']} "
              f"buyer_commitments={len(ci['open_buyer_commitments'])}")


asyncio.run(main())
