"""
Fix: move float MEDDPICC scores from state.pov.pov.meddpicc → state.pov.meddpicc
(The component reads pov?.pov?.meddpicc which maps to state.pov.meddpicc — one level up.)
Also seeds activity_summary with momentum data for the left panel.
"""
import asyncio, json, sys, os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings
settings = get_settings()

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"

# Float scores (0.0-1.0) per account — keyed exactly as component expects
SCORES = {
    "Meridian Health Systems": {
        "metrics": 0.75, "economic_buyer": 1.00, "decision_criteria": 0.75,
        "decision_process": 0.75, "paper_process": 0.25, "implicate_pain": 1.00,
        "champion": 0.00, "competition": 0.25,
        "overall_score": 0.59, "gap_risk": "high",
        "detail": {
            "metrics": "34% reduction in prior-auth denials documented in pilot",
            "economic_buyer": "CFO Dr. Raymond Kirk — approved budget Q1",
            "decision_criteria": "HIPAA compliance, EHR integration, 99.9% uptime SLA",
            "decision_process": "Legal → IT Security → CFO sign-off. 4-week cycle.",
            "paper_process": "MSA redline in legal. BLOCKER.",
            "implicate_pain": "11 FTEs impacted. $2.1M/yr waste — exec-validated.",
            "champion": "Sarah Chen, VP Clinical Ops — SILENT 14 days. Critical gap.",
            "competition": "Veeva Health submitted competing proposal June 18.",
        }
    },
    "Apex Logistics Partners": {
        "metrics": 0.75, "economic_buyer": 0.75, "decision_criteria": 0.75,
        "decision_process": 0.75, "paper_process": 0.00, "implicate_pain": 1.00,
        "champion": 0.25, "competition": 0.00,
        "overall_score": 0.53, "gap_risk": "high",
        "detail": {
            "metrics": "20% reduction in freight billing errors, $400K annual savings",
            "economic_buyer": "COO Maria Santos — budget approved. Not directly engaged.",
            "decision_criteria": "API-first, NetSuite integration, sub-100ms latency SLAs",
            "decision_process": "IT evaluation → COO sign-off. Targeting July 31.",
            "paper_process": "Procurement not yet engaged. BLOCKER.",
            "implicate_pain": "Manual freight reconciliation: 3 FTEs, $180K/yr error rate.",
            "champion": "James Morrow — now evaluating Salesforce. At risk.",
            "competition": "Salesforce Revenue Cloud — webinar attended June 19. CRITICAL.",
        }
    },
    "Blackstone Capital Group": {
        "metrics": 1.00, "economic_buyer": 1.00, "decision_criteria": 1.00,
        "decision_process": 0.75, "paper_process": 0.00, "implicate_pain": 1.00,
        "champion": 0.25, "competition": 0.75,
        "overall_score": 0.72, "gap_risk": "medium",
        "detail": {
            "metrics": "T+2 → T+0 settlement, $3M/yr operational savings — exec-validated",
            "economic_buyer": "CTO David Park — signed LOI March. Full authority.",
            "decision_criteria": "SOC2 Type II, FedRAMP moderate, Bloomberg Terminal integration",
            "decision_process": "Risk committee July 8 → Legal → Board. Timeline slipping.",
            "paper_process": "GDPR Article 44 blocking legal. CRITICAL.",
            "implicate_pain": "Settlement latency: 0.2bps daily = $3M/yr at volume.",
            "champion": "Alexandra Webb — on leave July 15–Aug 5. No delegate. GAP.",
            "competition": "In-house solution inertia only. Manageable with ROI case.",
        }
    },
    "Lumina Retail Group": {
        "metrics": 0.75, "economic_buyer": 0.75, "decision_criteria": 0.50,
        "decision_process": 0.50, "paper_process": 0.00, "implicate_pain": 0.75,
        "champion": 0.00, "competition": 0.50,
        "overall_score": 0.47, "gap_risk": "high",
        "detail": {
            "metrics": "30% SKU attribution error reduction, $220K savings/yr",
            "economic_buyer": "VP Merchandising Tanya Ross — $185K budget approved.",
            "decision_criteria": "Shopify Plus integration, real-time inventory sync, mobile app",
            "decision_process": "IT approval → VP sign-off. Path known, not committed.",
            "paper_process": "Not started — proposal not yet accepted. BLOCKER.",
            "implicate_pain": "SKU errors: 12% overstock, $800K/yr margin impact.",
            "champion": "Marcus Delgado — frustrated with onboarding. Usage dropped 41%.",
            "competition": "Stitch Labs shortlisted. Not evaluated head-to-head yet.",
        }
    },
    "SkyBridge Technologies": {
        "metrics": 0.75, "economic_buyer": 0.75, "decision_criteria": 0.75,
        "decision_process": 0.50, "paper_process": 0.00, "implicate_pain": 1.00,
        "champion": 0.75, "competition": 0.75,
        "overall_score": 0.66, "gap_risk": "medium",
        "detail": {
            "metrics": "60% infra provisioning time reduction, $500K DevOps savings",
            "economic_buyer": "CTO Rachel Kim — purchase authority to $500K. Not yet engaged.",
            "decision_criteria": "Kubernetes-native, multi-cloud, GitOps workflow compatibility",
            "decision_process": "CTO evaluation → CFO rubber-stamp. Not yet structured.",
            "paper_process": "Not started.",
            "implicate_pain": "Manual provisioning: 3 days avg, blocking 6 dev teams.",
            "champion": "Kevin Okafor, VP DevOps — forwarding case study internally. Strong.",
            "competition": "HashiCorp + Terraform incumbent. Cloud-native angle is our wedge.",
        }
    },
    "Cascade Manufacturing": {
        "metrics": 0.50, "economic_buyer": 0.50, "decision_criteria": 0.00,
        "decision_process": 0.00, "paper_process": 0.00, "implicate_pain": 0.75,
        "champion": 0.00, "competition": 0.50,
        "overall_score": 0.28, "gap_risk": "critical",
        "detail": {
            "metrics": "OEE 68% → 82% estimated, $1.8M/yr savings. Not yet validated.",
            "economic_buyer": "COO Brett Holloway — open to follow-up. Not committed.",
            "decision_criteria": "Unknown. Discovery not started.",
            "decision_process": "Expect 4-month cycle. Operations committee → COO → Board.",
            "paper_process": "Not started.",
            "implicate_pain": "Unplanned downtime: $45K/hr, 3.2% annually = $1.3M/yr.",
            "champion": "Not yet identified. Mapping org chart. CRITICAL GAP.",
            "competition": "Rockwell Automation (incumbent), Siemens evaluating.",
        }
    },
    "Orion Analytics": {
        "metrics": 1.00, "economic_buyer": 1.00, "decision_criteria": 1.00,
        "decision_process": 1.00, "paper_process": 1.00, "implicate_pain": 1.00,
        "champion": 1.00, "competition": 1.00,
        "overall_score": 1.00, "gap_risk": "medium",
        "detail": {
            "metrics": "BI query time 8s → 0.3s. Self-serve for 120 analysts.",
            "economic_buyer": "CDO Alex Morgan — signed LOI May. Full authority.",
            "decision_criteria": "dbt, Snowflake native, SOC2 Type II — all verified.",
            "decision_process": "Legal returned 3 minor redlines June 20. Closing this week.",
            "paper_process": "MSA redlines accepted. PO in progress. Near-final.",
            "implicate_pain": "12-week analyst backlog, 6 FTE data eng bottleneck.",
            "champion": "Priya Nair — arranged 3 references, responds same-day.",
            "competition": "Looker considered and eliminated Q1. No active competitor.",
        }
    },
    "NovaCure Biotech": {
        "metrics": 0.75, "economic_buyer": 0.75, "decision_criteria": 1.00,
        "decision_process": 0.75, "paper_process": 0.50, "implicate_pain": 1.00,
        "champion": 0.25, "competition": 0.00,
        "overall_score": 0.62, "gap_risk": "high",
        "detail": {
            "metrics": "Clinical trial data processing: 14 days → 2 days, $380K/trial.",
            "economic_buyer": "CTO Dr. Fumio Hayashi — budget approved, not final sponsor.",
            "decision_criteria": "21 CFR Part 11 compliance, LIMS integration, audit trail.",
            "decision_process": "IT Security → Regulatory → CTO. 6-week standard process.",
            "paper_process": "Security questionnaire in review. Proposal submitted June 15.",
            "implicate_pain": "FDA submission prep: 14-day manual consolidation per phase.",
            "champion": "Sarah Osei — now evaluating Benchling. At risk. ACT NOW.",
            "competition": "Benchling AI regulatory module launched June 20. CRITICAL.",
        }
    },
    "Summit Financial Advisors": {
        "metrics": 1.00, "economic_buyer": 0.75, "decision_criteria": 0.75,
        "decision_process": 0.75, "paper_process": 0.00, "implicate_pain": 1.00,
        "champion": 1.00, "competition": 0.75,
        "overall_score": 0.75, "gap_risk": "medium",
        "detail": {
            "metrics": "SEC reporting: 5 days → 8 hours, 99.9% audit completeness.",
            "economic_buyer": "CFO Linda Zhang — Q3 budget allocated. Not directly engaged.",
            "decision_criteria": "SOX compliance, real-time SEC reporting, multi-custodian data",
            "decision_process": "Compliance → IT Security → CFO sign-off. 6-week process.",
            "paper_process": "Not started — proposal not yet accepted. August risk.",
            "implicate_pain": "SEC filing: 5-day manual process, 2 FTEs, $320K/yr.",
            "champion": "Richard Yuen, CCO — responding consistently, advocating internally.",
            "competition": "Broadridge at parent company. Manageable with compliance depth.",
        }
    },
    "Verdant Energy Solutions": {
        "metrics": 0.50, "economic_buyer": 0.75, "decision_criteria": 0.00,
        "decision_process": 0.00, "paper_process": 0.00, "implicate_pain": 0.75,
        "champion": 0.00, "competition": 0.50,
        "overall_score": 0.31, "gap_risk": "critical",
        "detail": {
            "metrics": "Grid efficiency: 15% loss reduction = $4.2M/yr. Estimated.",
            "economic_buyer": "CEO Elena Marchetti — DOE mandate, engaged, fast decider.",
            "decision_criteria": "Unknown. NERC CIP, SCADA integration expected.",
            "decision_process": "Engineering → Ops committee → CEO. Expect 5 months.",
            "paper_process": "Not started.",
            "implicate_pain": "Unplanned grid outages: 12/yr at $350K each = $4.2M/yr.",
            "champion": "Not yet identified. VP Grid Operations target. CRITICAL GAP.",
            "competition": "GE Vernova (incumbent), AutoGrid. Not yet evaluated.",
        }
    },
}

# Activity summary data per account (for left panel engagement section)
ACTIVITY = {
    "Meridian Health Systems":     {"emails_sent_30d": 3, "emails_opened_30d": 0, "calls_30d": 0, "last_response_days": 14, "momentum": "declining"},
    "Apex Logistics Partners":     {"emails_sent_30d": 4, "emails_opened_30d": 2, "calls_30d": 1, "last_response_days": 12, "momentum": "declining"},
    "Blackstone Capital Group":    {"emails_sent_30d": 5, "emails_opened_30d": 3, "calls_30d": 1, "last_response_days": 10, "momentum": "stalled"},
    "Lumina Retail Group":         {"emails_sent_30d": 6, "emails_opened_30d": 1, "calls_30d": 1, "last_response_days": 14, "momentum": "declining"},
    "SkyBridge Technologies":      {"emails_sent_30d": 3, "emails_opened_30d": 3, "calls_30d": 1, "last_response_days": 3,  "momentum": "positive"},
    "Cascade Manufacturing":       {"emails_sent_30d": 2, "emails_opened_30d": 2, "calls_30d": 1, "last_response_days": 6,  "momentum": "positive"},
    "Orion Analytics":             {"emails_sent_30d": 4, "emails_opened_30d": 4, "calls_30d": 2, "last_response_days": 1,  "momentum": "positive"},
    "NovaCure Biotech":            {"emails_sent_30d": 5, "emails_opened_30d": 3, "calls_30d": 2, "last_response_days": 7,  "momentum": "declining"},
    "Summit Financial Advisors":   {"emails_sent_30d": 3, "emails_opened_30d": 3, "calls_30d": 1, "last_response_days": 5,  "momentum": "stable"},
    "Verdant Energy Solutions":    {"emails_sent_30d": 2, "emails_opened_30d": 2, "calls_30d": 1, "last_response_days": 4,  "momentum": "positive"},
}


async def run():
    db_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(
            text("SELECT id, name, state FROM accounts WHERE workspace_id = :wid AND hubspot_deal_id LIKE 'hs_deal_%'"),
            {"wid": WORKSPACE_ID}
        )
        rows = result.fetchall()
        print(f"Fixing MEDDPICC path for {len(rows)} accounts...\n")

        for row in rows:
            acct_id, name, state = str(row[0]), row[1], row[2] or {}
            scores = SCORES.get(name)
            activity = ACTIVITY.get(name, {})
            if not scores:
                print(f"  SKIP {name}")
                continue

            # Write float scores directly to state.pov.meddpicc
            # (component reads: pov?.pov?.meddpicc where pov = state["pov"])
            if "pov" not in state:
                state["pov"] = {}
            state["pov"]["meddpicc"] = scores

            # Clean up the wrong-path data from previous scripts
            if "pov" in state["pov"] and isinstance(state["pov"]["pov"], dict):
                state["pov"]["pov"].pop("meddpicc", None)

            # Seed activity_summary so the engagement panel has data
            state["activity_summary"] = {
                "emails_sent_30d": activity.get("emails_sent_30d", 0),
                "total_emails_sent": activity.get("emails_sent_30d", 0),
                "total_emails_received": activity.get("emails_opened_30d", 0),
                "email_exchange_count": activity.get("emails_sent_30d", 0) + activity.get("emails_opened_30d", 0),
                "days_since_last_inbound": activity.get("last_response_days"),
                "last_inbound_reply_date": None,
                "total_meetings": activity.get("calls_30d", 0),
                "total_fireflies_transcripts": 0,
                "deal_created_at": None,
                "momentum": activity.get("momentum", "stable"),
            }

            await session.execute(
                text("UPDATE accounts SET state = CAST(:state AS JSONB) WHERE id = :id"),
                {"state": json.dumps(state), "id": acct_id}
            )

            ov = scores["overall_score"]
            gr = scores["gap_risk"]
            bar = "█" * round(ov * 8)
            print(f"  {name[:32]:32s}  {ov:.0%}  {gr:8s}  [{bar:<8}]  momentum: {activity.get('momentum','?')}")

        await session.commit()
        print("\nDone. Refresh the War Room to see correct MEDDPICC scores.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
