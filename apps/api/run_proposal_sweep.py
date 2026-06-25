"""One-shot script: run Vantage sweep for Proposal-stage accounts.
Set PYTHONUTF8=1 before importing anything — fixes Windows cp1252 UnicodeEncodeError
when HubSpot data contains Arabic / accented characters.
"""
import os
import sys

# Force UTF-8 I/O on Windows before any other imports touch stdout/stderr
os.environ.setdefault("PYTHONUTF8", "1")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import asyncio
import uuid

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from app.db.database import AsyncSessionLocal
from app.services.nightly_worker import NightlyWorker

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"

# Full 36 Proposal accounts — completed ones will be re-run (idempotent),
# previously failed ones will now succeed with UTF-8 encoding fixed.
PROPOSAL_ACCOUNT_IDS = [
    "03a5a641-6429-41fe-8c75-25c5bf649ef1",
    "e54f306b-c1cd-463b-a746-66303be91d53",
    "b8215dd3-77c5-4146-86fb-73e01f9f9763",
    "0bbafbe7-8804-4ad7-a76e-5d8285aa664c",
    "10314bde-bc0f-438a-875a-c6a80490f3fe",
    "57e188bb-fc7d-4fec-9668-65982268e0e2",
    "1bce5de4-0c30-480d-8249-2453f7536f3d",
    "82939b78-ad13-4a32-8c1b-84f8d30eb07e",
    "1501fec9-5391-4e43-8c6e-2ebdf74ecb89",
    "7de0685c-f5be-4c98-bff3-7a7077bbaa59",
    "41ce3ef1-dfc2-4189-93ad-2cffbae8ce00",
    "63900e56-2efa-47bf-a373-5b69ccf69ab1",
    "4e23159a-9abe-439f-b740-c305694cafbe",
    "28918f73-fe6e-4519-9245-0d6a21047740",
    "673b99a0-c59a-48b5-a734-5e3cff8d3935",
    "30619cd5-1340-412f-b0f6-43ea883ab3ab",
    "72824a77-395e-41c4-b60f-2aa25b7b4883",
    "36a8a454-85bd-4b89-9005-654caf5fa661",
    "6108a3cc-ec3d-4fd3-b013-9000c4cdaaef",
    "63b910c5-3af1-4802-af55-5b13b7642446",
    "143a255e-6e8d-4752-81ad-4b5ca31c2f2e",
    "6dc4d2fa-7732-4230-89fa-aa0e51ded2f7",
    "27986a6f-553b-4d34-a496-0e15be8d01ad",
    "a91e56cf-caac-4c73-9440-a9a8568a1a11",
    "b06133dc-8584-4ed3-9de9-5c151ff02b8d",
    "aca35bb5-7eeb-4a2c-b168-0f9a0109b485",
    "b11ba699-f827-48a2-95c4-3e7cc597c73a",
    "0df04391-cb83-4fc1-af85-27a8a4c6c421",
    "cd9c109b-ce5b-42c2-9707-3a0e73fbe343",
    "de35d7ac-539b-47e2-9a34-682f80352352",
    "6b5db735-11b3-44fe-99b0-d428578f69d2",
    "35519c67-b564-4e87-a374-5fe93d230c8b",
    "3a3d1986-2ab0-4d4c-9281-764e22ab0c57",
    "b830794a-01d4-45f2-b75f-78ed5e7f5e18",
    "f8f21d5f-0b74-47fd-b42d-8c7d6f4b1810",
    "fcdd5eaf-9d73-45b8-a336-1e1b827d5431",
]


async def main():
    run_id = str(uuid.uuid4())
    print(f"[sweep] run_id={run_id}  accounts={len(PROPOSAL_ACCOUNT_IDS)}", flush=True)

    async with AsyncSessionLocal() as db:
        worker = NightlyWorker(db)
        await worker._run_immediate_sync(
            run_id=run_id,
            workspace_id=WORKSPACE_ID,
            account_ids=PROPOSAL_ACCOUNT_IDS,
        )

    print(f"[sweep] DONE run_id={run_id}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
