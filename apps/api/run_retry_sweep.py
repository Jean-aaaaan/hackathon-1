"""Re-run only the 9 accounts that failed in the first Proposal sweep."""
import os
import sys

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

FAILED_ACCOUNT_IDS = [
    "10314bde-bc0f-438a-875a-c6a80490f3fe",  # SQLAlchemy concurrent session
    "143a255e-6e8d-4752-81ad-4b5ca31c2f2e",  # MPA — DrafterResult drafts as string
    "27986a6f-553b-4d34-a496-0e15be8d01ad",  # NoneType format (deal_amount=None)
    "35519c67-b564-4e87-a374-5fe93d230c8b",  # NoneType format
    "3a3d1986-2ab0-4d4c-9281-764e22ab0c57",  # NoneType format
    "6b5db735-11b3-44fe-99b0-d428578f69d2",  # NoneType format
    "7de0685c-f5be-4c98-bff3-7a7077bbaa59",  # LRBGA — NoneType format
    "82939b78-ad13-4a32-8c1b-84f8d30eb07e",  # NoneType format
    "e54f306b-c1cd-463b-a746-66303be91d53",  # Halliburton — GoldDataPoint not serializable
]


async def main():
    run_id = str(uuid.uuid4())
    print(f"[retry] run_id={run_id}  accounts={len(FAILED_ACCOUNT_IDS)}", flush=True)

    async with AsyncSessionLocal() as db:
        worker = NightlyWorker(db)
        await worker._run_immediate_sync(
            run_id=run_id,
            workspace_id=WORKSPACE_ID,
            account_ids=FAILED_ACCOUNT_IDS,
        )

    print(f"[retry] DONE run_id={run_id}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
