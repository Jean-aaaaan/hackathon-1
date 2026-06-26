"""
Enrich seeded deals with:
  - MEDDPICC per-letter scores (1-4 scale)
  - ICP profile: Digitalisation/AI Managers
  - Momentum: trend, emails sent, last contact
Run from apps/api/: python scripts/update_deal_enrichment.py
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
def now(): return datetime.now(timezone.utc)
def dago(d): return (now() - timedelta(days=d)).isoformat()

# ICP definition — same for all accounts, score varies per deal
ICP_PROFILE = {
    "name": "Digitalisation / AI Managers",
    "description": (
        "VP/Director of Digital Transformation, AI Strategy Manager, Chief Digital Officer, "
        "or Head of Innovation at a mid-market to enterprise company (200-5000 employees) "
        "actively running or budgeting an AI or digitalisation programme. "
        "Owns or strongly influences a $100K+ technology budget. Pain: legacy process inefficiency, "
        "data silos, or pressure from leadership to show measurable AI ROI."
    ),
    "criteria": {
        "title_keywords": ["Digital", "AI", "Innovation", "Transformation", "Automation", "Data"],
        "company_size": "200-5000 employees",
        "budget_authority": ">= $100K",
        "active_initiative": True,
        "pain_themes": ["process automation", "AI ROI", "data integration", "legacy modernisation"]
    }
}

# Per-account enrichment: MEDDPICC scores (1=weak/unknown, 2=partial, 3=solid, 4=strong/verified)
# + momentum data
ENRICHMENTS = {
    "Meridian Health Systems": {
        "icp_score": 0.91,
        "icp_fit_rationale": "VP Clinical Ops overseeing prior-auth digitalisation — exact ICP title. EHR integration pain = AI/digitalisation initiative. Budget $450K confirmed.",
        "meddpicc_scores": {
            "M_metrics":           3,  # ROI documented (34% denial reduction) but not exec-signed-off
            "E_economic_buyer":    4,  # CFO Dr. Kirk identified, approved budget Q1
            "D1_decision_criteria": 3, # HIPAA/EHR criteria clear but not formally scored
            "D2_decision_process": 3,  # Legal->IT->CFO path confirmed, 4-week cycle documented
            "P_paper_process":     2,  # MSA in legal, blocker unresolved
            "I_identify_pain":     4,  # 11 FTEs, $2.1M/yr waste — quantified and exec-validated
            "C1_champion":         1,  # Champion gone dark — weakest letter
            "C2_competition":      2,  # Veeva counter-proposal — competitive threat unmitigated
        },
        "meddpicc_overall": 2,  # 1-4 overall
        "momentum": {
            "trend": "declining",
            "score": 0.22,
            "emails_sent_30d": 3,
            "emails_opened_30d": 0,
            "calls_30d": 0,
            "last_outreach": dago(8),
            "last_response": dago(14),
            "rep_note": "Champion Sarah Chen silent 14 days. Sent 3 follow-ups, no response.",
            "risk_flag": "champion_dark"
        }
    },
    "Apex Logistics Partners": {
        "icp_score": 0.84,
        "icp_fit_rationale": "IT Director running NetSuite/freight-billing digitalisation initiative. Confirmed $280K budget. Pain is process automation — core ICP theme.",
        "meddpicc_scores": {
            "M_metrics":           3,
            "E_economic_buyer":    3,  # COO confirmed but not directly engaged
            "D1_decision_criteria": 3,
            "D2_decision_process": 3,
            "P_paper_process":     1,  # Procurement not yet engaged
            "I_identify_pain":     4,
            "C1_champion":         2,  # Champion now evaluating Salesforce
            "C2_competition":      1,  # Salesforce competitive threat — critical gap
        },
        "meddpicc_overall": 2,
        "momentum": {
            "trend": "declining",
            "score": 0.31,
            "emails_sent_30d": 4,
            "emails_opened_30d": 2,
            "calls_30d": 1,
            "last_outreach": dago(7),
            "last_response": dago(12),
            "rep_note": "James mentioned 'looking at alternatives' — agent detected Salesforce webinar attendance.",
            "risk_flag": "competitive_threat"
        }
    },
    "Blackstone Capital Group": {
        "icp_score": 0.88,
        "icp_fit_rationale": "Head of Platform Engineering driving trade settlement digitalisation (T+2->T+0). Classic AI/data infrastructure initiative. CTO as economic buyer with 7-figure authority.",
        "meddpicc_scores": {
            "M_metrics":           4,  # T+2->T+0, $3M/yr savings quantified and exec-aligned
            "E_economic_buyer":    4,  # CTO David Park, signed LOI March
            "D1_decision_criteria": 4,  # SOC2, FedRAMP, Bloomberg integration — fully documented
            "D2_decision_process": 3,  # Risk committee path clear but timeline slipping
            "P_paper_process":     1,  # GDPR Article 44 blocking — hard blocker
            "I_identify_pain":     4,
            "C1_champion":         2,  # Alexandra going on leave July 15
            "C2_competition":      3,  # Only in-house inertia — manageable
        },
        "meddpicc_overall": 3,
        "momentum": {
            "trend": "stalled",
            "score": 0.41,
            "emails_sent_30d": 5,
            "emails_opened_30d": 3,
            "calls_30d": 1,
            "last_outreach": dago(4),
            "last_response": dago(10),
            "rep_note": "Deal stalled on legal. Alexandra going on leave. Need exec relationship with David Park.",
            "risk_flag": "deal_slip"
        }
    },
    "Lumina Retail Group": {
        "icp_score": 0.76,
        "icp_fit_rationale": "Digital Ops Manager running Shopify/SKU attribution digitalisation. AI/automation initiative with confirmed budget. ICP score lower — champion frustrated, engagement dropping.",
        "meddpicc_scores": {
            "M_metrics":           3,
            "E_economic_buyer":    3,  # VP Merchandising confirmed, budget approved
            "D1_decision_criteria": 2,  # Criteria known but not formally documented
            "D2_decision_process": 2,  # IT approval path known, not locked
            "P_paper_process":     1,  # Not started — proposal not accepted
            "I_identify_pain":     3,
            "C1_champion":         1,  # Champion frustrated — usage dropped 41%
            "C2_competition":      2,  # Stitch Labs shortlisted
        },
        "meddpicc_overall": 2,
        "momentum": {
            "trend": "declining",
            "score": 0.18,
            "emails_sent_30d": 6,
            "emails_opened_30d": 1,
            "calls_30d": 1,
            "last_outreach": dago(3),
            "last_response": dago(14),
            "rep_note": "Marcus responded once re: onboarding friction. Usage at 0.9/day. Pilot rescue needed urgently.",
            "risk_flag": "usage_drop"
        }
    },
    "SkyBridge Technologies": {
        "icp_score": 0.89,
        "icp_fit_rationale": "New CTO from AWS driving cloud infra modernisation — perfect AI/digitalisation ICP. Series C funding = budget. VP DevOps as day-to-day champion. High growth = urgency.",
        "meddpicc_scores": {
            "M_metrics":           3,
            "E_economic_buyer":    3,  # New CTO Rachel Kim — authority confirmed, not yet engaged
            "D1_decision_criteria": 3,
            "D2_decision_process": 2,  # CTO evaluation process not yet structured
            "P_paper_process":     1,
            "I_identify_pain":     4,
            "C1_champion":         3,  # Kevin Okafor engaged, forwarding internally
            "C2_competition":      3,  # HashiCorp incumbent — known weakness
        },
        "meddpicc_overall": 3,
        "momentum": {
            "trend": "positive",
            "score": 0.68,
            "emails_sent_30d": 3,
            "emails_opened_30d": 3,
            "calls_30d": 1,
            "last_outreach": dago(2),
            "last_response": dago(3),
            "rep_note": "Kevin forwarded our case study internally. New CTO = opportunity. Moving fast.",
            "risk_flag": None
        }
    },
    "Cascade Manufacturing": {
        "icp_score": 0.82,
        "icp_fit_rationale": "Series C industrial automation = AI/digitalisation initiative at scale. COO as buyer, $520K in stated use-of-funds. ICP criteria met but champion not yet identified.",
        "meddpicc_scores": {
            "M_metrics":           2,  # OEE metrics estimated, not yet validated with customer
            "E_economic_buyer":    2,  # COO Brett Holloway open to meeting, not committed
            "D1_decision_criteria": 1,  # Criteria unknown at this stage
            "D2_decision_process": 1,  # 4-month cycle expected — not yet mapped
            "P_paper_process":     1,
            "I_identify_pain":     3,
            "C1_champion":         1,  # No champion identified yet
            "C2_competition":      2,  # Rockwell/Siemens incumbents — not yet competitive
        },
        "meddpicc_overall": 1,
        "momentum": {
            "trend": "positive",
            "score": 0.52,
            "emails_sent_30d": 2,
            "emails_opened_30d": 2,
            "calls_30d": 1,
            "last_outreach": dago(5),
            "last_response": dago(6),
            "rep_note": "COO open to follow-up after cold outreach. Series C creates window — moving to champion mapping.",
            "risk_flag": None
        }
    },
    "Orion Analytics": {
        "icp_score": 0.79,
        "icp_fit_rationale": "Head of Data running BI/analytics modernisation (dbt + Snowflake). Classic data digitalisation ICP. CDO as buyer. Close to close — champion fully committed.",
        "meddpicc_scores": {
            "M_metrics":           4,
            "E_economic_buyer":    4,  # CDO Alex Morgan signed LOI
            "D1_decision_criteria": 4,  # dbt, Snowflake, SOC2 — fully documented
            "D2_decision_process": 4,  # Legal returned minor redlines — near-final
            "P_paper_process":     4,  # MSA redline returned, 3 minor clauses only
            "I_identify_pain":     4,
            "C1_champion":         4,  # Priya Nair arranged 3 references — fully committed
            "C2_competition":      4,  # Looker eliminated in Q1
        },
        "meddpicc_overall": 4,
        "momentum": {
            "trend": "positive",
            "score": 0.94,
            "emails_sent_30d": 4,
            "emails_opened_30d": 4,
            "calls_30d": 2,
            "last_outreach": dago(1),
            "last_response": dago(1),
            "rep_note": "Priya responding same-day. MSA in final stages. On track to close by July 8.",
            "risk_flag": None
        }
    },
    "NovaCure Biotech": {
        "icp_score": 0.86,
        "icp_fit_rationale": "VP Regulatory Affairs + CTO running FDA submission workflow AI automation. Exact ICP — AI initiative in regulated environment. $210K budget confirmed.",
        "meddpicc_scores": {
            "M_metrics":           3,
            "E_economic_buyer":    3,  # CTO Dr. Hayashi with budget, not final sponsor yet
            "D1_decision_criteria": 4,  # 21 CFR Part 11 — precise and documented
            "D2_decision_process": 3,
            "P_paper_process":     2,  # Security questionnaire in review
            "I_identify_pain":     4,
            "C1_champion":         2,  # Sarah Osei now evaluating Benchling
            "C2_competition":      1,  # Benchling new module — critical competitive threat
        },
        "meddpicc_overall": 3,
        "momentum": {
            "trend": "declining",
            "score": 0.39,
            "emails_sent_30d": 5,
            "emails_opened_30d": 3,
            "calls_30d": 2,
            "last_outreach": dago(1),
            "last_response": dago(7),
            "rep_note": "Sarah mentioned Benchling on last call. Need to counter within 72h with compliance depth.",
            "risk_flag": "competitive_threat"
        }
    },
    "Summit Financial Advisors": {
        "icp_score": 0.81,
        "icp_fit_rationale": "Chief Compliance Officer leading SEC reporting digitalisation. Data/compliance AI initiative with $380K budget. Structured buyer — will follow process.",
        "meddpicc_scores": {
            "M_metrics":           4,
            "E_economic_buyer":    3,  # CFO Linda Zhang allocated budget, not directly engaged
            "D1_decision_criteria": 3,
            "D2_decision_process": 3,
            "P_paper_process":     1,  # Not started
            "I_identify_pain":     4,
            "C1_champion":         4,  # Richard Yuen fully advocating internally
            "C2_competition":      3,  # Broadridge incumbent at parent co — manageable
        },
        "meddpicc_overall": 3,
        "momentum": {
            "trend": "stable",
            "score": 0.61,
            "emails_sent_30d": 3,
            "emails_opened_30d": 3,
            "calls_30d": 1,
            "last_outreach": dago(4),
            "last_response": dago(5),
            "rep_note": "Richard responding consistently. Shared proposal internally. Push for timeline commitment by Jul 15.",
            "risk_flag": None
        }
    },
    "Verdant Energy Solutions": {
        "icp_score": 0.93,
        "icp_fit_rationale": "CEO with DOE AI grid modernisation mandate — highest ICP fit. AI-driven grid intelligence = perfect fit. $28M DOE grant = guaranteed budget. Only risk is long cycle.",
        "meddpicc_scores": {
            "M_metrics":           2,  # Grid efficiency ROI estimated, not yet validated
            "E_economic_buyer":    3,  # CEO Elena Marchetti engaged — early stage
            "D1_decision_criteria": 1,  # Criteria unknown — discovery not started
            "D2_decision_process": 1,  # 5-month cycle expected, not mapped
            "P_paper_process":     1,
            "I_identify_pain":     3,
            "C1_champion":         1,  # No champion — CEO is too senior for day-to-day
            "C2_competition":      2,  # GE Vernova incumbent, not yet evaluated
        },
        "meddpicc_overall": 2,
        "momentum": {
            "trend": "positive",
            "score": 0.57,
            "emails_sent_30d": 2,
            "emails_opened_30d": 2,
            "calls_30d": 1,
            "last_outreach": dago(3),
            "last_response": dago(4),
            "rep_note": "Elena engaged and responsive — DOE mandate creates real urgency. Need to find VP Grid Ops as champion.",
            "risk_flag": None
        }
    }
}

async def run():
    db_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Fetch all seeded accounts
        result = await session.execute(
            text("SELECT id, name, state FROM accounts WHERE workspace_id = :wid AND hubspot_deal_id LIKE 'hs_deal_%'"),
            {"wid": WORKSPACE_ID}
        )
        rows = result.fetchall()
        print(f"Found {len(rows)} seeded accounts to enrich.")

        for row in rows:
            acct_id, name, state = str(row[0]), row[1], row[2] or {}
            enrich = ENRICHMENTS.get(name)
            if not enrich:
                print(f"  SKIP {name} — no enrichment defined")
                continue

            # Merge enrichment into state
            state["icp"] = {
                **ICP_PROFILE,
                "fit_score": enrich["icp_score"],
                "fit_rationale": enrich["icp_fit_rationale"]
            }
            state["meddpicc_scores"] = enrich["meddpicc_scores"]
            state["meddpicc_overall"] = enrich["meddpicc_overall"]
            state["momentum"] = enrich["momentum"]

            # Fix MEDDPICC spelling in pov.meddpicc if present (key stays lowercase as-is,
            # but add a display-name field)
            if "pov" in state and "meddpicc" in state["pov"]:
                state["pov"]["meddpicc_label"] = "MEDDPICC"

            await session.execute(
                text("UPDATE accounts SET state = CAST(:state AS JSONB), icp_score = :icp WHERE id = :id"),
                {"state": json.dumps(state), "icp": enrich["icp_score"], "id": acct_id}
            )
            print(f"  ✅ {name:35s}  MEDDPICC overall: {enrich['meddpicc_overall']}/4  momentum: {enrich['momentum']['trend']:10s}  emails_sent_30d: {enrich['momentum']['emails_sent_30d']}")

        await session.commit()
        print("\nAll accounts enriched.")

    await engine.dispose()

    print("\nSummary:")
    print("  ICP Profile: Digitalisation / AI Managers")
    print("  MEDDPICC scores: per-letter 1-4, overall 1-4")
    print("  Momentum: trend + emails_sent_30d + emails_opened_30d + calls_30d + last_outreach")
    print("\nDistribution:")
    for name, e in ENRICHMENTS.items():
        print(f"  {e['meddpicc_overall']}/4  {e['momentum']['trend']:10s}  {name}")

if __name__ == "__main__":
    asyncio.run(run())
