"""
Patch state.pov.meddpicc in all seeded accounts so the War Room
MEDDPICC scoreboard renders properly.

Component expects (account/[id]/page.tsx line 1641):
  { metrics, economic_buyer, decision_criteria, decision_process,
    implicate_pain, champion, competition, paper_process,
    overall_score, gap_risk }
  — all float 0-1.

Run from apps/api/: python scripts/fix_meddpicc_scores.py
"""
import asyncio, json, sys, os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings
settings = get_settings()

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"

# Per-account MEDDPICC floats (0.0–1.0) + text detail
# Keys match exactly what the component iterates over.
MEDDPICC_DATA = {
    "Meridian Health Systems": {
        "metrics":           0.75,   # ROI documented (34% denial reduction), not exec-signed
        "economic_buyer":    1.00,   # CFO Dr. Kirk identified + budget Q1 approved
        "decision_criteria": 0.75,   # HIPAA/EHR criteria clear, not formally scored
        "decision_process":  0.75,   # Legal->IT->CFO path confirmed
        "paper_process":     0.25,   # MSA in legal, 2-week blocker unresolved
        "implicate_pain":    1.00,   # 11 FTEs, $2.1M/yr — quantified + exec-validated
        "champion":          0.00,   # Sarah Chen gone dark 14 days
        "competition":       0.25,   # Veeva counter-proposal unmitigated
        "detail": {
            "metrics":           "34% reduction in prior-auth denials documented in pilot",
            "economic_buyer":    "CFO Dr. Raymond Kirk — approved budget Q1",
            "decision_criteria": "HIPAA compliance, EHR integration, 99.9% uptime SLA",
            "decision_process":  "Legal → IT Security → CFO sign-off. 4-week typical cycle.",
            "paper_process":     "MSA redline in legal. ~2 weeks remaining. BLOCKER.",
            "implicate_pain":    "Manual prior-auth costing 11 FTEs. $2.1M/yr waste.",
            "champion":          "Sarah Chen, VP Clinical Ops — SILENT 14 days. Critical gap.",
            "competition":       "Veeva Health submitted competing proposal June 18.",
        }
    },
    "Apex Logistics Partners": {
        "metrics":           0.75,
        "economic_buyer":    0.75,   # COO confirmed but not directly engaged
        "decision_criteria": 0.75,
        "decision_process":  0.75,
        "paper_process":     0.00,   # Procurement not yet engaged
        "implicate_pain":    1.00,
        "champion":          0.25,   # James Morrow now evaluating Salesforce
        "competition":       0.00,   # Salesforce — critical unmitigated threat
        "detail": {
            "metrics":           "20% reduction in freight billing errors, $400K annual savings",
            "economic_buyer":    "COO Maria Santos — budget approved Feb. Not directly engaged.",
            "decision_criteria": "API-first, NetSuite integration, sub-100ms latency SLAs",
            "decision_process":  "IT evaluation → COO sign-off. Targeting July 31 decision.",
            "paper_process":     "Procurement not yet engaged. BLOCKER.",
            "implicate_pain":    "Manual freight reconciliation: 3 FTEs, $180K/yr error rate.",
            "champion":          "James Morrow, IT Director — now evaluating Salesforce. At risk.",
            "competition":       "Salesforce Revenue Cloud — webinar attended June 19. CRITICAL.",
        }
    },
    "Blackstone Capital Group": {
        "metrics":           1.00,   # T+2→T+0, $3M/yr — quantified and exec-aligned
        "economic_buyer":    1.00,   # CTO David Park, signed LOI March
        "decision_criteria": 1.00,   # SOC2, FedRAMP, Bloomberg — fully documented
        "decision_process":  0.75,   # Risk committee path clear, timeline slipping
        "paper_process":     0.00,   # GDPR Article 44 — hard blocker
        "implicate_pain":    1.00,
        "champion":          0.25,   # Alexandra going on leave July 15
        "competition":       0.75,   # Only in-house inertia — manageable
        "detail": {
            "metrics":           "T+2 → T+0 settlement, $3M/yr operational savings — exec-validated",
            "economic_buyer":    "CTO David Park — signed LOI March. Full authority.",
            "decision_criteria": "SOC2 Type II, FedRAMP moderate, Bloomberg Terminal integration",
            "decision_process":  "Risk committee July 8 → Legal → Board. Timeline slipping.",
            "paper_process":     "GDPR Article 44 cross-border transfer blocking legal. CRITICAL.",
            "implicate_pain":    "Settlement latency: 0.2bps daily = $3M/yr at volume.",
            "champion":          "Alexandra Webb — on leave July 15–Aug 5. No delegate. GAP.",
            "competition":       "In-house solution inertia only. Manageable with ROI case.",
        }
    },
    "Lumina Retail Group": {
        "metrics":           0.75,
        "economic_buyer":    0.75,   # VP Merchandising confirmed, budget approved
        "decision_criteria": 0.50,   # Criteria known, not formally documented
        "decision_process":  0.50,   # IT approval path known, not locked
        "paper_process":     0.00,   # Not started — proposal not accepted
        "implicate_pain":    0.75,
        "champion":          0.00,   # Marcus frustrated — usage at 41% decline
        "competition":       0.50,   # Stitch Labs shortlisted
        "detail": {
            "metrics":           "30% SKU attribution error reduction, $220K savings/yr",
            "economic_buyer":    "VP Merchandising Tanya Ross — $185K budget approved.",
            "decision_criteria": "Shopify Plus integration, real-time inventory sync, mobile app",
            "decision_process":  "IT approval → VP sign-off. Path known, not committed.",
            "paper_process":     "Not started — proposal not yet accepted. BLOCKER.",
            "implicate_pain":    "SKU errors: 12% overstock, $800K/yr margin impact.",
            "champion":          "Marcus Delgado — frustrated with onboarding. Usage dropped 41%. CRITICAL.",
            "competition":       "Stitch Labs shortlisted. Not evaluated head-to-head yet.",
        }
    },
    "SkyBridge Technologies": {
        "metrics":           0.75,
        "economic_buyer":    0.75,   # Rachel Kim has authority, not yet engaged directly
        "decision_criteria": 0.75,
        "decision_process":  0.50,   # CTO eval process not yet structured
        "paper_process":     0.00,
        "implicate_pain":    1.00,
        "champion":          0.75,   # Kevin Okafor engaged, forwarding internally
        "competition":       0.75,   # HashiCorp — known weakness, addressable
        "detail": {
            "metrics":           "60% infra provisioning time reduction, $500K DevOps savings",
            "economic_buyer":    "CTO Rachel Kim — purchase authority to $500K. Not yet engaged.",
            "decision_criteria": "Kubernetes-native, multi-cloud, GitOps workflow compatibility",
            "decision_process":  "CTO evaluation → CFO rubber-stamp. Process not yet structured.",
            "paper_process":     "Not started.",
            "implicate_pain":    "Manual provisioning: 3 days avg, blocking 6 dev teams.",
            "champion":          "Kevin Okafor, VP DevOps — forwarding case study internally. Strong.",
            "competition":       "HashiCorp + Terraform incumbent. Cloud-native angle is our wedge.",
        }
    },
    "Cascade Manufacturing": {
        "metrics":           0.50,   # OEE metrics estimated, not validated
        "economic_buyer":    0.50,   # COO open to meeting, not committed
        "decision_criteria": 0.00,   # Unknown at discovery stage
        "decision_process":  0.00,   # 4-month cycle expected, not mapped
        "paper_process":     0.00,
        "implicate_pain":    0.75,
        "champion":          0.00,   # No champion identified
        "competition":       0.50,   # Rockwell/Siemens — incumbent, not yet competitive
        "detail": {
            "metrics":           "OEE 68% → 82% estimated, $1.8M/yr savings. Not yet validated.",
            "economic_buyer":    "COO Brett Holloway — open to follow-up. Not committed.",
            "decision_criteria": "Unknown. Discovery not started.",
            "decision_process":  "Expect 4-month cycle. Operations committee → COO → Board.",
            "paper_process":     "Not started.",
            "implicate_pain":    "Unplanned downtime: $45K/hr, 3.2% annually = $1.3M/yr.",
            "champion":          "Not yet identified. Mapping org chart. CRITICAL GAP.",
            "competition":       "Rockwell Automation (incumbent), Siemens evaluating.",
        }
    },
    "Orion Analytics": {
        "metrics":           1.00,
        "economic_buyer":    1.00,   # CDO Alex Morgan — signed LOI May
        "decision_criteria": 1.00,
        "decision_process":  1.00,   # Legal returned minor redlines — near-final
        "paper_process":     1.00,   # MSA redline: 3 minor clauses, closing this week
        "implicate_pain":    1.00,
        "champion":          1.00,   # Priya Nair — arranged 3 references, fully committed
        "competition":       1.00,   # Looker eliminated Q1
        "detail": {
            "metrics":           "BI query time 8s → 0.3s. Self-serve for 120 analysts.",
            "economic_buyer":    "CDO Alex Morgan — signed LOI May. Full authority.",
            "decision_criteria": "dbt compatibility, Snowflake native, SOC2 Type II — all verified.",
            "decision_process":  "Legal returned 3 minor redlines June 20. Closing this week.",
            "paper_process":     "MSA redlines accepted. PO in progress. Near-final.",
            "implicate_pain":    "12-week analyst backlog, 6 FTE data eng bottleneck.",
            "champion":          "Priya Nair — arranged 3 references, responds same-day. Fully committed.",
            "competition":       "Looker considered and eliminated Q1. No active competitor.",
        }
    },
    "NovaCure Biotech": {
        "metrics":           0.75,
        "economic_buyer":    0.75,   # CTO Dr. Hayashi with budget, not final sponsor
        "decision_criteria": 1.00,   # 21 CFR Part 11 — precise and documented
        "decision_process":  0.75,
        "paper_process":     0.50,   # Security questionnaire in review
        "implicate_pain":    1.00,
        "champion":          0.25,   # Sarah Osei now evaluating Benchling
        "competition":       0.00,   # Benchling new module — critical threat, < 72h window
        "detail": {
            "metrics":           "Clinical trial data processing: 14 days → 2 days, $380K/trial savings.",
            "economic_buyer":    "CTO Dr. Fumio Hayashi — budget approved, not final sponsor yet.",
            "decision_criteria": "21 CFR Part 11 compliance, LIMS integration, audit trail — fully documented.",
            "decision_process":  "IT Security → Regulatory → CTO. 6-week standard process.",
            "paper_process":     "Security questionnaire in review. Proposal submitted June 15.",
            "implicate_pain":    "FDA submission prep: 14-day manual consolidation per trial phase.",
            "champion":          "Sarah Osei — now evaluating Benchling module. At risk. ACT NOW.",
            "competition":       "Benchling AI regulatory module launched June 20. CRITICAL — 72h window.",
        }
    },
    "Summit Financial Advisors": {
        "metrics":           1.00,
        "economic_buyer":    0.75,   # CFO Linda Zhang allocated budget, not directly engaged
        "decision_criteria": 0.75,
        "decision_process":  0.75,
        "paper_process":     0.00,   # Not started — awaiting proposal acceptance
        "implicate_pain":    1.00,
        "champion":          1.00,   # Richard Yuen fully advocating internally
        "competition":       0.75,   # Broadridge incumbent at parent co — manageable
        "detail": {
            "metrics":           "SEC reporting: 5 days → 8 hours, 99.9% audit completeness, $320K/yr savings.",
            "economic_buyer":    "CFO Linda Zhang — Q3 budget allocated. Not directly engaged.",
            "decision_criteria": "SOX compliance, real-time SEC reporting, multi-custodian data ingestion",
            "decision_process":  "Compliance → IT Security → CFO sign-off. 6-week process.",
            "paper_process":     "Not started — proposal not yet accepted. Risk of August slowdown.",
            "implicate_pain":    "SEC filing: 5-day manual process, 2 FTEs, $320K/yr.",
            "champion":          "Richard Yuen, CCO — responding consistently, advocating internally. Strong.",
            "competition":       "Broadridge at parent company. Manageable with compliance depth.",
        }
    },
    "Verdant Energy Solutions": {
        "metrics":           0.50,   # Grid efficiency ROI estimated, not validated
        "economic_buyer":    0.75,   # CEO Elena Marchetti engaged — early stage
        "decision_criteria": 0.00,   # Criteria unknown
        "decision_process":  0.00,   # 5-month cycle, not mapped
        "paper_process":     0.00,
        "implicate_pain":    0.75,
        "champion":          0.00,   # No champion — CEO too senior for day-to-day
        "competition":       0.50,   # GE Vernova incumbent, not yet evaluated
        "detail": {
            "metrics":           "Grid efficiency: 15% loss reduction = $4.2M/yr savings. Estimated.",
            "economic_buyer":    "CEO Elena Marchetti — DOE mandate, engaged, fast decision-maker.",
            "decision_criteria": "Unknown. NERC CIP, SCADA integration expected. Discovery not started.",
            "decision_process":  "Engineering → Ops committee → CEO. Expect 5 months.",
            "paper_process":     "Not started.",
            "implicate_pain":    "Unplanned grid outages: 12/yr at $350K each = $4.2M/yr.",
            "champion":          "Not yet identified. VP Grid Operations target. CRITICAL GAP.",
            "competition":       "GE Vernova (incumbent grid monitoring), AutoGrid. Not yet evaluated.",
        }
    },
}


def gap_risk(scores: dict) -> str:
    vals = [v for k, v in scores.items() if k != "detail"]
    avg = sum(vals) / len(vals) if vals else 0
    if avg < 0.4:  return "critical"
    if avg < 0.65: return "high"
    return "medium"

def overall_score(scores: dict) -> float:
    vals = [v for k, v in scores.items() if k != "detail"]
    return round(sum(vals) / len(vals), 2) if vals else 0.0


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
        print(f"Patching MEDDPICC scores in {len(rows)} accounts...\n")

        for row in rows:
            acct_id, name, state = str(row[0]), row[1], row[2] or {}
            data = MEDDPICC_DATA.get(name)
            if not data:
                print(f"  SKIP {name}")
                continue

            # Extract detail, build float-score dict
            detail = data.pop("detail", {})
            scores = {k: v for k, v in data.items()}
            ov = overall_score(scores)
            gr = gap_risk(scores)

            # Build meddpicc payload the component expects
            meddpicc_payload = {
                **scores,
                "overall_score": ov,
                "gap_risk": gr,
                "detail": detail,      # kept for future tooltip/detail use
            }

            # Patch into state.pov.meddpicc
            if "pov" not in state:
                state["pov"] = {}
            if "pov" not in state["pov"]:
                state["pov"]["pov"] = {}
            # state.pov is the AccountPOV object; state.pov.pov is the nested pov data
            # The page reads: pov?.pov?.meddpicc  where pov = state.pov (AccountPOV)
            # So we need state["pov"]["pov"]["meddpicc"] = meddpicc_payload
            if isinstance(state.get("pov"), dict):
                inner = state["pov"].get("pov")
                if not isinstance(inner, dict):
                    state["pov"]["pov"] = {}
                state["pov"]["pov"]["meddpicc"] = meddpicc_payload

            await session.execute(
                text("UPDATE accounts SET state = CAST(:state AS JSONB) WHERE id = :id"),
                {"state": json.dumps(state), "id": acct_id}
            )

            # Pretty-print bar
            bar = " ".join(
                f"{k[0].upper()}={'█' * round(v*4):<4}"
                for k, v in scores.items()
            )
            print(f"  {name[:32]:32s}  overall={ov:.0%}  gap={gr:8s}  |{bar}|")

            # Put detail back for next account (we popped it)
            data["detail"] = detail

        await session.commit()
        print("\nAll accounts patched. Refresh War Room to see MEDDPICC scoreboard.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
