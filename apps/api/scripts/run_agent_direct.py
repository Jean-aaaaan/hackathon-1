"""Run agent pipeline directly on the demo account — shows errors instead of silently failing."""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.db.database import AsyncSessionLocal
from app.services.nightly_worker import NightlyWorker

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
ACCOUNT_ID   = "b116b053-9076-45d4-a3be-449445158749"

async def run():
    settings = get_settings()
    print(f"Anthropic model bulk : {settings.anthropic_model_bulk}")
    print(f"Anthropic model quality: {settings.anthropic_model_quality}")
    print(f"Running agents on account {ACCOUNT_ID}...\n")

    async with AsyncSessionLocal() as db:
        worker = NightlyWorker(db)
        try:
            import uuid as _uuid
            await worker._run_immediate_sync(
                run_id=str(_uuid.uuid4()),
                workspace_id=WORKSPACE_ID,
                account_ids=[ACCOUNT_ID],
            )
            print("\nDone.")
        except Exception as e:
            import traceback
            print(f"\nERROR: {e}")
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run())
