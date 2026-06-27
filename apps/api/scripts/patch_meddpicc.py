"""
Patch all seeded accounts with numeric MEDDPICC scores in state.pov.meddpicc.
The seed data has text strings which render as 0% in the War Room.
This patches them to numeric float scores matching the RiskScannerAgent output format.
Run from apps/api/: python scripts/patch_meddpicc.py
"""
import asyncio
import json
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings
settings = get_settings()

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"

MEDDPICC_PATCHES = {
    "Meridian Health Systems": {
        "deal_narrative": "Meridian's champion Sarah Chen has gone dark for 14 days following an internal reorg. Procurement is stalling on legal review while Veeva Health submitted a counter-proposal last week. CRM shows Commit but agent downgraded to Best Case. A deal with strong MEDDPICC documentation (metrics proven in pilot, budget approved) is at risk purely from champion unavailability. Executive escalation through Dr. Kirk is required this week.",
        "meddpicc": {
            "metrics": 0.85,
            "economic_buyer": 0.60,
            "decision_criteria": 0.80,
            "decision_process": 0.75,
            "implicate_pain": 0.90,
            "champion": 0.25,
            "competition": 0.45,
            "paper_process": 0.65,
            "overall_score": 0.61,
            "gap_risk": "high",
            "gaps": ["Champion Sarah Chen dark 14 days — single thread risk", "Veeva counter-proposal threatens positioning"]
        },
        "risk_vectors": {
            "champion": "critical", "competition": "high",
            "timeline": "high", "economic": "medium", "stakeholder": "high"
        },
        "deal_momentum": "stalling",
        "win_probability": 0.42,
        "three_whys": {
            "why_change": {"present": True, "evidence": "Manual prior-auth costing 11 FTEs, $2.1M/yr — pilot documented 34% reduction"},
            "why_now": {"present": True, "evidence": "Q3 go-live window closes July 15 — next slot September"},
            "why_us": {"present": True, "evidence": "Only HIPAA-compliant solution with EHR integration depth Meridian requires"}
        }
    },
    "Apex Logistics Partners": {
        "meddpicc": {
            "metrics": 0.75,
            "economic_buyer": 0.70,
            "decision_criteria": 0.70,
            "decision_process": 0.65,
            "implicate_pain": 0.80,
            "champion": 0.55,
            "competition": 0.35,
            "paper_process": 0.20,
            "overall_score": 0.59,
            "gap_risk": "high",
            "gaps": ["Competitive evaluation with Salesforce Revenue Cloud active", "Paper process not started — procurement at risk"]
        },
        "risk_vectors": {
            "champion": "medium", "competition": "critical",
            "timeline": "high", "economic": "low", "stakeholder": "medium"
        },
        "deal_momentum": "stalling",
        "win_probability": 0.46,
        "three_whys": {
            "why_change": {"present": True, "evidence": "Manual freight reconciliation: 3 FTEs, $180K/yr error rate"},
            "why_now": {"present": True, "evidence": "July 31 decision target set by COO"},
            "why_us": {"present": False, "evidence": "James Morrow now evaluating Salesforce — differentiation not established"}
        }
    },
    "Blackstone Capital Group": {
        "meddpicc": {
            "metrics": 0.85,
            "economic_buyer": 0.75,
            "decision_criteria": 0.85,
            "decision_process": 0.70,
            "implicate_pain": 0.80,
            "champion": 0.65,
            "competition": 0.60,
            "paper_process": 0.40,
            "overall_score": 0.70,
            "gap_risk": "medium",
            "gaps": ["GDPR data residency blocking legal sign-off", "Champion Alexandra Webb on leave July 15"]
        },
        "risk_vectors": {
            "champion": "medium", "competition": "low",
            "timeline": "high", "economic": "low", "stakeholder": "medium"
        },
        "deal_momentum": "neutral",
        "win_probability": 0.58,
        "three_whys": {
            "why_change": {"present": True, "evidence": "Settlement latency costing 0.2bps daily — $3M annually"},
            "why_now": {"present": True, "evidence": "Risk committee review July 8 — must have legal resolved before"},
            "why_us": {"present": True, "evidence": "SOC2 Type II + FedRAMP moderate + Bloomberg integration — only compliant option"}
        }
    },
    "Lumina Retail Group": {
        "meddpicc": {
            "metrics": 0.70,
            "economic_buyer": 0.65,
            "decision_criteria": 0.65,
            "decision_process": 0.60,
            "implicate_pain": 0.75,
            "champion": 0.30,
            "competition": 0.55,
            "paper_process": 0.10,
            "overall_score": 0.53,
            "gap_risk": "high",
            "gaps": ["Champion Marcus Delgado frustrated — pilot engagement down 41%", "Paper process not started"]
        },
        "risk_vectors": {
            "champion": "high", "competition": "medium",
            "timeline": "medium", "economic": "low", "stakeholder": "high"
        },
        "deal_momentum": "declining",
        "win_probability": 0.38,
        "three_whys": {
            "why_change": {"present": True, "evidence": "SKU attribution errors causing 12% overstock, $800K margin impact"},
            "why_now": {"present": False, "evidence": "Pilot stalling — no urgency trigger established"},
            "why_us": {"present": False, "evidence": "Stitch Labs shortlisted — differentiation unclear to Marcus"}
        }
    },
    "SkyBridge Technologies": {
        "meddpicc": {
            "metrics": 0.60,
            "economic_buyer": 0.55,
            "decision_criteria": 0.65,
            "decision_process": 0.50,
            "implicate_pain": 0.70,
            "champion": 0.70,
            "competition": 0.55,
            "paper_process": 0.05,
            "overall_score": 0.55,
            "gap_risk": "medium",
            "gaps": ["Economic buyer relationship not established with Rachel Kim", "Paper process not started — Discovery stage"]
        },
        "risk_vectors": {
            "champion": "low", "competition": "medium",
            "timeline": "low", "economic": "medium", "stakeholder": "medium"
        },
        "deal_momentum": "accelerating",
        "win_probability": 0.52,
        "three_whys": {
            "why_change": {"present": True, "evidence": "Manual infra provisioning: 3-day average blocking 6 dev teams"},
            "why_now": {"present": True, "evidence": "New CTO Rachel Kim from AWS — fast vendor decisions mandate"},
            "why_us": {"present": False, "evidence": "Rachel Kim intro not yet secured — differentiation not established"}
        }
    },
    "Cascade Manufacturing": {
        "meddpicc": {
            "metrics": 0.50,
            "economic_buyer": 0.35,
            "decision_criteria": 0.40,
            "decision_process": 0.30,
            "implicate_pain": 0.65,
            "champion": 0.10,
            "competition": 0.40,
            "paper_process": 0.05,
            "overall_score": 0.33,
            "gap_risk": "high",
            "gaps": ["No champion identified — org chart mapping in progress", "Economic buyer not formally engaged", "Decision process unknown"]
        },
        "risk_vectors": {
            "champion": "critical", "competition": "medium",
            "timeline": "low", "economic": "medium", "stakeholder": "high"
        },
        "deal_momentum": "neutral",
        "win_probability": 0.30,
        "three_whys": {
            "why_change": {"present": True, "evidence": "Line downtime at $45K/hr, 3.2% unplanned downtime annually"},
            "why_now": {"present": True, "evidence": "$72M Series C with industrial automation in use-of-funds"},
            "why_us": {"present": False, "evidence": "Champion not identified — value differentiation not established"}
        }
    },
    "Orion Analytics": {
        "meddpicc": {
            "metrics": 0.95,
            "economic_buyer": 0.90,
            "decision_criteria": 0.90,
            "decision_process": 0.90,
            "implicate_pain": 0.95,
            "champion": 0.95,
            "competition": 0.80,
            "paper_process": 0.85,
            "overall_score": 0.91,
            "gap_risk": "low",
            "gaps": ["Minor MSA redline clauses pending sign-off"]
        },
        "risk_vectors": {
            "champion": "low", "competition": "low",
            "timeline": "low", "economic": "low", "stakeholder": "low"
        },
        "deal_momentum": "accelerating",
        "win_probability": 0.91,
        "three_whys": {
            "why_change": {"present": True, "evidence": "12-week analyst backlog, 6 FTE data eng team bottlenecked"},
            "why_now": {"present": True, "evidence": "MSA redline returned — PO in motion, July go-live at risk if delayed"},
            "why_us": {"present": True, "evidence": "Looker evaluated and eliminated Q1 — Priya arranged 3 references"}
        }
    },
    "NovaCure Biotech": {
        "meddpicc": {
            "metrics": 0.80,
            "economic_buyer": 0.65,
            "decision_criteria": 0.85,
            "decision_process": 0.65,
            "implicate_pain": 0.85,
            "champion": 0.50,
            "competition": 0.30,
            "paper_process": 0.45,
            "overall_score": 0.62,
            "gap_risk": "high",
            "gaps": ["Benchling competitive threat — champion evaluating alternative", "Competition risk elevated by direct module launch"]
        },
        "risk_vectors": {
            "champion": "high", "competition": "critical",
            "timeline": "medium", "economic": "low", "stakeholder": "medium"
        },
        "deal_momentum": "stalling",
        "win_probability": 0.46,
        "three_whys": {
            "why_change": {"present": True, "evidence": "FDA submission prep: 14-day manual consolidation per trial, $380K/trial"},
            "why_now": {"present": True, "evidence": "Benchling launch threatens — must displace before Sarah Osei commits"},
            "why_us": {"present": True, "evidence": "21 CFR Part 11 audit trail depth — Benchling does not have this yet"}
        }
    },
    "Summit Financial Advisors": {
        "meddpicc": {
            "metrics": 0.80,
            "economic_buyer": 0.70,
            "decision_criteria": 0.75,
            "decision_process": 0.65,
            "implicate_pain": 0.80,
            "champion": 0.80,
            "competition": 0.60,
            "paper_process": 0.20,
            "overall_score": 0.68,
            "gap_risk": "medium",
            "gaps": ["Paper process not started — August procurement slowdown risk"]
        },
        "risk_vectors": {
            "champion": "low", "competition": "medium",
            "timeline": "medium", "economic": "low", "stakeholder": "low"
        },
        "deal_momentum": "neutral",
        "win_probability": 0.62,
        "three_whys": {
            "why_change": {"present": True, "evidence": "SEC reporting: 5-day manual process, 2 FTEs, $320K annual cost"},
            "why_now": {"present": True, "evidence": "July 15 commitment needed to avoid August procurement freeze"},
            "why_us": {"present": True, "evidence": "SOX compliance + real-time SEC reporting + multi-custodian — Broadridge cannot match"}
        }
    },
    "Verdant Energy Solutions": {
        "meddpicc": {
            "metrics": 0.50,
            "economic_buyer": 0.40,
            "decision_criteria": 0.35,
            "decision_process": 0.30,
            "implicate_pain": 0.60,
            "champion": 0.10,
            "competition": 0.40,
            "paper_process": 0.05,
            "overall_score": 0.33,
            "gap_risk": "high",
            "gaps": ["No champion identified — VP Grid Operations target not reached", "Economic buyer Elena Marchetti not formally engaged"]
        },
        "risk_vectors": {
            "champion": "critical", "competition": "medium",
            "timeline": "low", "economic": "medium", "stakeholder": "high"
        },
        "deal_momentum": "neutral",
        "win_probability": 0.28,
        "three_whys": {
            "why_change": {"present": True, "evidence": "12 unplanned outages at $350K each = $4.2M grid loss annually"},
            "why_now": {"present": True, "evidence": "$28M DOE grant mandates vendor evaluation by Q4 2026"},
            "why_us": {"present": False, "evidence": "Champion not established — NERC CIP differentiation not presented"}
        }
    },
    "Snowflake": {
        "deal_narrative": "Snowflake's sales team has expanded aggressively post-IPO but rep productivity metrics are declining. New CEO Sridhar Ramaswamy is under pressure to improve sales efficiency. Champion Marcus Holloway has internal buy-in but CFO Mike Scarpelli is blocking new SaaS spend following restructuring. This is a Best Case deal that needs a CFO-ready ROI model delivered this week to maintain deal momentum.",
        "meddpicc": {
            "metrics": 0.80,
            "economic_buyer": 0.45,
            "decision_criteria": 0.80,
            "decision_process": 0.70,
            "implicate_pain": 0.85,
            "champion": 0.65,
            "competition": 0.55,
            "paper_process": 0.50,
            "overall_score": 0.64,
            "gap_risk": "high",
            "gaps": ["CFO Mike Scarpelli blocking new SaaS spend — ROI model required", "Clari incumbent renewal discussions active"]
        },
        "risk_vectors": {
            "champion": "medium", "competition": "high",
            "timeline": "high", "economic": "critical", "stakeholder": "medium"
        },
        "deal_momentum": "stalling",
        "win_probability": 0.48,
        "three_whys": {
            "why_change": {"present": True, "evidence": "400+ enterprise reps spending 31% of time on manual CRM updates — $8M/yr productivity loss"},
            "why_now": {"present": True, "evidence": "CEO transition audit reviewing all vendor contracts — window to position as efficiency solution"},
            "why_us": {"present": True, "evidence": "HubSpot-native integration + SOC2 + GDPR — Clari cannot match AI grounding layer"}
        }
    },
    "Figma": {
        "deal_narrative": "Figma is aggressively hiring sales reps following the Adobe acquisition collapse and their $1B independent funding round. VP Sales Kris Rasmussen is building out a full enterprise motion from scratch and has full discretionary budget. The champion IS the economic buyer — a fast decision maker. Critical risk is Outreach.io's competing proposal submitted June 18. Accelerate the pilot proposal now before Q3 hiring decisions lock in.",
        "meddpicc": {
            "metrics": 0.70,
            "economic_buyer": 0.80,
            "decision_criteria": 0.75,
            "decision_process": 0.75,
            "implicate_pain": 0.80,
            "champion": 0.85,
            "competition": 0.40,
            "paper_process": 0.25,
            "overall_score": 0.70,
            "gap_risk": "medium",
            "gaps": ["Outreach.io competing proposal — must differentiate on AI and deployment speed", "Paper process not started"]
        },
        "risk_vectors": {
            "champion": "low", "competition": "high",
            "timeline": "medium", "economic": "low", "stakeholder": "low"
        },
        "deal_momentum": "accelerating",
        "win_probability": 0.62,
        "three_whys": {
            "why_change": {"present": True, "evidence": "Building enterprise sales motion from scratch — no existing AI tooling or playbooks"},
            "why_now": {"present": True, "evidence": "200 new enterprise reps being onboarded Q3 — tooling decision needed in 30 days"},
            "why_us": {"present": True, "evidence": "AI-native grounding + <2 week deploy vs Outreach.io 6-week implementation"}
        }
    },
    "Databricks": {
        "deal_narrative": "Databricks is in hypergrowth following their $10B Series J at $62B valuation. CEO Ali Ghodsi has publicly committed to AI-native go-to-market across all GTM functions. Early stage — no champion confirmed and CRO not identified. The opportunity is large ($890K) but qualification is thin. Key risk is getting lost in their massive vendor evaluation queue. Clari and Salesforce Einstein have incumbent advantage. Must land a RevOps champion fast.",
        "meddpicc": {
            "metrics": 0.45,
            "economic_buyer": 0.25,
            "decision_criteria": 0.50,
            "decision_process": 0.40,
            "implicate_pain": 0.65,
            "champion": 0.20,
            "competition": 0.35,
            "paper_process": 0.05,
            "overall_score": 0.36,
            "gap_risk": "high",
            "gaps": ["CRO not identified or engaged — no economic buyer", "Champion not confirmed — RevOps intro pending", "Clari strong incumbent with deep roots"]
        },
        "risk_vectors": {
            "champion": "critical", "competition": "high",
            "timeline": "low", "economic": "critical", "stakeholder": "high"
        },
        "deal_momentum": "neutral",
        "win_probability": 0.32,
        "three_whys": {
            "why_change": {"present": True, "evidence": "1,200 reps across 8 global regions — no unified AI layer, rep burnout on CRM hygiene"},
            "why_now": {"present": True, "evidence": "Ali Ghodsi AI-native GTM mandate — CEO stated all tools must have AI backbone"},
            "why_us": {"present": False, "evidence": "Champion not established — Clari and Salesforce Einstein have incumbent advantage"}
        }
    },
}


async def patch():
    db_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(
            text("SELECT name, id, state FROM accounts WHERE workspace_id = :wid AND hubspot_deal_id LIKE 'hs_deal_%'"),
            {"wid": WORKSPACE_ID}
        )
        rows = result.fetchall()
        print(f"Found {len(rows)} accounts to patch")

        patched = 0
        for name, account_id, state in rows:
            patch = MEDDPICC_PATCHES.get(name)
            if not patch:
                print(f"  SKIP {name} — no patch defined")
                continue

            state = state or {}
            pov = state.get("pov", {})

            # Apply numeric MEDDPICC + additional agent-output fields to pov
            pov["meddpicc"] = patch["meddpicc"]
            pov["risk_vectors"] = patch["risk_vectors"]
            pov["deal_momentum"] = patch["deal_momentum"]
            pov["win_probability"] = patch["win_probability"]
            # Restore deal_narrative if agent wiped it
            if not pov.get("deal_narrative") and patch.get("deal_narrative"):
                pov["deal_narrative"] = patch["deal_narrative"]
            pov["three_whys"] = patch["three_whys"]
            state["pov"] = pov

            await session.execute(
                text("UPDATE accounts SET state = CAST(:state AS JSONB), updated_at = NOW() WHERE id = :id"),
                {"state": json.dumps(state), "id": str(account_id)}
            )
            print(f"  PATCHED {name} — MEDDPICC overall={patch['meddpicc']['overall_score']:.0%}, momentum={patch['deal_momentum']}")
            patched += 1

        await session.commit()
        print(f"\nPatch complete: {patched}/{len(rows)} accounts updated")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(patch())
