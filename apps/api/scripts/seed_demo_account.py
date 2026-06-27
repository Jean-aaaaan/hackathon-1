"""
Seed one rich demo account for live agent demo.
The agents read from current_state — no HubSpot or Perplexity needed.
Run this, note the account ID, then POST to /v1/accounts/batch-refresh with that ID.
"""
import asyncio, json, sys, os
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings
settings = get_settings()

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"

# Rich deal context — agents synthesize signals + MEDDPICC from this
DEMO_STATE = {
    "name": "Meridian Ops",
    "stage": "Proposal",
    "deal_amount": 420000,
    "close_date": (datetime.now(timezone.utc) + timedelta(days=22)).strftime("%Y-%m-%d"),

    # Product context for the drafter — what we sell
    "seller_context": {
        "product": "AI-powered sales intelligence platform",
        "value_prop": "Cuts deal review time by 70%, surfaces at-risk deals before reps notice"
    },

    # Stakeholders — the people in this deal
    "stakeholders": [
        {
            "name": "Priya Nair",
            "title": "VP Revenue Operations",
            "role": "champion",
            "email": "priya.nair@meridianops.com",
            "engagement_level": "warm",
            "last_contacted": (datetime.now(timezone.utc) - timedelta(days=8)).strftime("%Y-%m-%d"),
            "notes": "Initiated the evaluation. Ran our pilot. Showed ROI to team. Has gone quiet last 8 days — unusual for her."
        },
        {
            "name": "Daniel Chu",
            "title": "CFO",
            "role": "economic_buyer",
            "email": "dchu@meridianops.com",
            "engagement_level": "cold",
            "last_contacted": None,
            "notes": "Controls $500K+ spend. Has not been introduced to us yet. Priya said he needs to approve any contract over $200K."
        },
        {
            "name": "Marcus Webb",
            "title": "Head of IT Security",
            "role": "blocker",
            "email": "mwebb@meridianops.com",
            "engagement_level": "neutral",
            "last_contacted": (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d"),
            "notes": "Security questionnaire sent June 20 — no response yet. Last time he flagged data residency concerns."
        }
    ],

    # Deal narrative for researcher context
    "summary": (
        "Meridian Ops (120-person RevOps consultancy) evaluating sales intelligence platform. "
        "Pain: 3 hours/rep/week lost to manual deal review and CRM hygiene. $1.2M/yr estimated cost. "
        "Priya Nair (VP RevOps) is champion — ran our pilot, 3 reps, 6-week trial, liked results. "
        "Sent proposal June 14 ($420K ARR). Priya went silent 8 days ago after we sent contract. "
        "CFO Daniel Chu has not been engaged directly — Priya owns relationship. "
        "Competitor Clari also submitted a proposal June 17 (learned from LinkedIn). "
        "Security review with Marcus Webb stalled — data residency Q unanswered. "
        "Close date July 18 — 3 weeks. Deal is at risk."
    ),

    # CRM-style notes — researcher extracts signals from these
    "crm_notes": [
        {
            "date": (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d"),
            "author": "AE",
            "content": (
                "Discovery call with Priya Nair (VP RevOps). 12 reps spending avg 3hr/week "
                "on manual deal status updates and CRM hygiene. Estimated $1.2M/yr in lost "
                "selling time. Priya has exec air cover — CRO Jake Singh is pushing for Q3 fix. "
                "No formal decision criteria yet. Agreed on 6-week pilot with 3 reps."
            )
        },
        {
            "date": (datetime.now(timezone.utc) - timedelta(days=18)).strftime("%Y-%m-%d"),
            "author": "AE",
            "content": (
                "Pilot debrief with Priya. Results: 2.4hr/week saved per rep, CRM data completeness "
                "up 34%. Priya presented to CRO Jake Singh — he loved it, gave budget approval signal. "
                "Priya mentioned CFO Daniel Chu needs to sign anything over $200K. "
                "She said she would get us a meeting with Daniel 'this week' — hasn't happened yet."
            )
        },
        {
            "date": (datetime.now(timezone.utc) - timedelta(days=12)).strftime("%Y-%m-%d"),
            "author": "AE",
            "content": (
                "Sent proposal: $420K ARR (3-yr), $340K ARR (1-yr). Priya said she prefers 3-yr. "
                "She also mentioned Clari reached out — 'just checking what else is out there.' "
                "She said she's our champion and to not worry. Sent SOC2 cert and security docs "
                "to Marcus Webb (IT Security) for review."
            )
        },
        {
            "date": (datetime.now(timezone.utc) - timedelta(days=8)).strftime("%Y-%m-%d"),
            "author": "AE",
            "content": (
                "Followed up with Priya — no response. Sent contract redline. No response. "
                "Checked LinkedIn: Priya liked a Clari post 3 days ago. "
                "Still no intro to CFO Daniel Chu. Marcus Webb sent one email asking about "
                "data residency in EU — replied same day, waiting on his response."
            )
        }
    ],

    # Activity summary for context
    "activity_summary": {
        "emails_sent_30d": 6,
        "total_emails_sent": 6,
        "total_emails_received": 4,
        "email_exchange_count": 10,
        "days_since_last_inbound": 8,
        "last_inbound_reply_date": (datetime.now(timezone.utc) - timedelta(days=8)).strftime("%Y-%m-%d"),
        "total_meetings": 3,
        "momentum": "declining"
    },

    # Seed minimal pov so researcher has baseline
    "pov": {
        "forecast_category": "pipeline",
        "deal_momentum": "declining",
        "health_score": 0.44,
    }
}


async def run():
    db_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Update workspace settings so drafter has real product context
        await session.execute(text("""
            UPDATE workspaces
            SET settings = settings || CAST(:patch AS JSONB)
            WHERE id = :wid
        """), {
            "patch": json.dumps({
                "sender_name": "Alex Rivera",
                "sender_title": "Account Executive",
                "sender_company": "Vantage",
                "product_description": (
                    "Vantage is a per-deal AI agent platform for enterprise sales teams. "
                    "One AI agent per deal — monitors signals 24/7, scores MEDDPICC automatically, "
                    "and drafts follow-up emails grounded in verified deal intelligence. "
                    "Reps spend time selling, not reviewing CRM data."
                ),
            }),
            "wid": WORKSPACE_ID
        })

        # Delete existing demo account if re-running
        await session.execute(
            text("DELETE FROM accounts WHERE workspace_id = :wid AND name = 'Meridian Ops'"),
            {"wid": WORKSPACE_ID}
        )

        import uuid
        account_id = str(uuid.uuid4())

        close_date = (datetime.now(timezone.utc) + timedelta(days=22)).date()

        await session.execute(text("""
            INSERT INTO accounts (
                id, workspace_id, name, hubspot_deal_id, stage,
                deal_amount, close_date, state,
                health_score, urgency_score,
                created_at, updated_at
            ) VALUES (
                :id, :wid, :name, :hs_id, :stage,
                :amount, :close_date, CAST(:state AS JSONB),
                :health, :urgency,
                NOW(), NOW()
            )
        """), {
            "id": account_id,
            "wid": WORKSPACE_ID,
            "name": "Meridian Ops",
            "hs_id": f"demo_{account_id[:8]}",
            "stage": "Proposal",
            "amount": 420000,
            "close_date": close_date,
            "state": json.dumps(DEMO_STATE),
            "health": 0.44,
            "urgency": 0.72,
        })

        await session.commit()

    await engine.dispose()

    print(f"\nOK  Demo account created: Meridian Ops")
    print(f"    Account ID: {account_id}")
    print(f"\n--- STEP 2: Trigger the agent run ---")
    print(f'curl -s -X POST http://localhost:8000/v1/accounts/batch-refresh -H "Content-Type: application/json" -H "Authorization: Bearer ba1bc0c0fa242a23cba2f876d3690571291d1bc36cff6fce9a8d9f2e3e036277" -d \'{{"account_ids": ["{account_id}"]}}\'')
    print(f"\n--- STEP 3: Check results after ~30 seconds ---")
    print(f'curl -s http://localhost:8000/v1/accounts/{account_id}/pov -H "Authorization: Bearer ba1bc0c0fa242a23cba2f876d3690571291d1bc36cff6fce9a8d9f2e3e036277"')
    print(f"\n    War Room URL: http://localhost:3000/account/{account_id}")
    print(f"\nNOTE: Agents will find 3-4 signals and draft a re-engagement email to Priya Nair.")
    print(f"      Signals to expect: champion silence (8 days), economic buyer not engaged, Clari competitor.\n")


if __name__ == "__main__":
    asyncio.run(run())
