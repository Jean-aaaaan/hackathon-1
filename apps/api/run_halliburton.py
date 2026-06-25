import os, sys
os.environ.setdefault("PYTHONUTF8", "1")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import asyncio, uuid
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
from app.db.database import AsyncSessionLocal
from app.services.nightly_worker import NightlyWorker

async def main():
    run_id = str(uuid.uuid4())
    print(f"[halliburton] run_id={run_id}", flush=True)
    async with AsyncSessionLocal() as db:
        worker = NightlyWorker(db)
        await worker._run_immediate_sync(run_id=run_id, workspace_id="00000000-0000-0000-0000-000000000001",
            account_ids=["e54f306b-c1cd-463b-a746-66303be91d53"])
    print(f"[halliburton] DONE", flush=True)

asyncio.run(main())
