"""
Nightly Container Job entrypoint — runs once per Azure Container Job invocation.

Azure Container Apps Jobs trigger this script at 02:00 UTC via a cron schedule.
The job:
  1. Connects to the database
  2. Runs the full agent pipeline for all accounts in all workspaces
  3. Sends the Teams morning brief
  4. Exits cleanly (Container Job expects exit code 0)

Usage (local test):
  python nightly_job.py

Azure Container Job command override:
  ["python", "nightly_job.py"]

Environment variables: same as the API (DATABASE_URL, ANTHROPIC_API_KEY, etc.)
"""
import asyncio
import sys
import signal
import structlog
from datetime import datetime, timezone

log = structlog.get_logger()


async def main():
    start = datetime.now(timezone.utc)
    log.info("nightly_job_started", timestamp=start.isoformat())

    # Import here so settings are loaded from env first
    from app.config import get_settings
    from app.db.database import AsyncSessionLocal
    from app.services.nightly_worker import NightlyWorker
    from sqlalchemy import text

    settings = get_settings()

    async with AsyncSessionLocal() as db:
        # Get all active workspaces
        result = await db.execute(
            text("SELECT id FROM workspaces WHERE deleted_at IS NULL ORDER BY created_at")
        )
        workspace_ids = [str(row.id) for row in result.fetchall()]

        if not workspace_ids:
            log.warning("nightly_job_no_workspaces")
            return

        log.info("nightly_job_workspaces", count=len(workspace_ids))

        worker = NightlyWorker(db=db)

        for workspace_id in workspace_ids:
            try:
                run_id = await worker.run_workspace(workspace_id)
                log.info("nightly_job_workspace_done", workspace_id=workspace_id, run_id=run_id)
            except Exception as e:
                log.error(
                    "nightly_job_workspace_failed",
                    workspace_id=workspace_id,
                    error=str(e),
                    exc_info=True,
                )
                # Don't abort — continue with remaining workspaces

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    log.info("nightly_job_complete", elapsed_s=round(elapsed, 1))


def handle_sigterm(sig, frame):
    """Graceful shutdown on SIGTERM (Azure sends this before killing the container)."""
    log.info("nightly_job_sigterm_received")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_sigterm)

    try:
        asyncio.run(main())
        sys.exit(0)
    except KeyboardInterrupt:
        log.info("nightly_job_interrupted")
        sys.exit(0)
    except Exception as e:
        log.error("nightly_job_fatal", error=str(e), exc_info=True)
        sys.exit(1)
