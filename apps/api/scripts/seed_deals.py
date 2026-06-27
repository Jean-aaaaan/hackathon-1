"""
Seed realistic demo deals into the Vantage database.
Run from apps/api/: python scripts/seed_deals.py
"""
import asyncio
import uuid
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings
settings = get_settings()

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"

def now():
    return datetime.now(timezone.utc)

def days_from_now(n, as_str=True):
    d = date.today() + timedelta(days=n)
    return d.isoformat() if as_str else d

# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
ACCOUNTS = [
    {
        "id": str(uuid.uuid4()),
        "name": "Meridian Health Systems",
        "stage": "Negotiation",
        "deal_amount": "450000.00",
        "close_date": days_from_now(18, as_str=False),
        "pov_forecast_cat": "Best Case",
        "pov_confidence": 0.61,
        "health_score": 0.38,
        "urgency_score": 0.93,
        "icp_score": 0.91,
        "hubspot_deal_id": "hs_deal_1001",
        "state": {
            "health_trend": "down",
            "crm_forecast_category": "Commit",
            "pov": {
                "forecast_category": "Best Case",
                "confidence": 0.61,
                "deal_narrative": "Meridian's champion Sarah Chen has gone dark for 14 days following an internal reorg. Procurement is stalling on legal review. Competitor Veeva submitted a counter-proposal last week.",
                "top_risk_summary": "Champion unavailability + competitive counter-proposal threaten a deal previously marked Commit by the rep.",
                "meddpicc": {
                    "metrics": "Documented 34% reduction in prior-auth denials in pilot",
                    "economic_buyer": "CFO Dr. Raymond Kirk â€” approved budget Q1",
                    "decision_criteria": "HIPAA compliance, EHR integration, 99.9% uptime SLA",
                    "decision_process": "Legal â†’ IT Security â†’ CFO sign-off. 4-week typical cycle.",
                    "paper_process": "MSA redline in legal. ~2 weeks remaining.",
                    "identified_pain": "Manual prior-auth costing 11 FTEs. $2.1M/yr waste.",
                    "champion": "Sarah Chen, VP Clinical Ops â€” silent since June 12",
                    "competition": "Veeva Health submitted competing proposal June 18"
                }
            },
            "next_actions": [
                {"action": "Re-engage Sarah Chen via Dr. Kirk's office â€” frame urgency around Q3 go-live risk", "priority": "critical", "due_date": days_from_now(2)},
                {"action": "Send competitive battlecard comparison to procurement team", "priority": "high", "due_date": days_from_now(4)},
                {"action": "Offer expedited legal review support â€” assign solutions engineer to MSA", "priority": "high", "due_date": days_from_now(3)}
            ],
            "next_step": {
                "text": "Exec-to-exec call with Dr. Kirk â€” scheduled pending CFO calendar",
                "due_date": days_from_now(5),
                "source": "agent",
                "set_at": now().isoformat()
            },
            "gold_data": {
                "facts": [
                    {"fact": "Champion Sarah Chen has not responded to 3 outreach attempts since June 12", "source": "hubspot_activity", "confidence": 0.97, "verified_by_grounding_agent": True},
                    {"fact": "Veeva submitted competing proposal on June 18", "source": "perplexity_web_search", "confidence": 0.88, "verified_by_grounding_agent": True},
                    {"fact": "Legal MSA review initiated June 10, average cycle 14 days", "source": "hubspot_notes", "confidence": 0.95, "verified_by_grounding_agent": False}
                ]
            }
        }
    },
    {
        "id": str(uuid.uuid4()),
        "name": "Apex Logistics Partners",
        "stage": "Proposal",
        "deal_amount": "280000.00",
        "close_date": days_from_now(31, as_str=False),
        "pov_forecast_cat": "Forecast",
        "pov_confidence": 0.72,
        "health_score": 0.54,
        "urgency_score": 0.87,
        "icp_score": 0.84,
        "hubspot_deal_id": "hs_deal_1002",
        "state": {
            "health_trend": "down",
            "crm_forecast_category": "Forecast",
            "pov": {
                "forecast_category": "Forecast",
                "confidence": 0.72,
                "deal_narrative": "Apex is actively evaluating Salesforce Revenue Cloud as a direct alternative. Their IT director James Morrow surfaced on a Salesforce webinar last week. Budget is confirmed at $280K.",
                "top_risk_summary": "Competitive evaluation with Salesforce accelerated unexpectedly. Rep was unaware until agent detected LinkedIn signal.",
                "meddpicc": {
                    "metrics": "Target: 20% reduction in freight billing errors, $400K annual savings",
                    "economic_buyer": "COO Maria Santos â€” budget approved Feb",
                    "decision_criteria": "API-first, NetSuite integration, sub-100ms latency SLAs",
                    "decision_process": "IT evaluation â†’ COO sign-off. Targeting July 31 decision.",
                    "paper_process": "Procurement not yet engaged",
                    "identified_pain": "Manual freight reconciliation: 3 FTEs, $180K/yr error rate",
                    "champion": "James Morrow, IT Director â€” engaged but now evaluating alternatives",
                    "competition": "Salesforce Revenue Cloud â€” pricing competitive, native CRM advantage"
                }
            },
            "next_actions": [
                {"action": "Schedule competitive displacement call â€” lead with NetSuite integration depth vs Salesforce", "priority": "critical", "due_date": days_from_now(1)},
                {"action": "Send ROI comparison: implementation timeline 6 wks (us) vs 16 wks (Salesforce)", "priority": "high", "due_date": days_from_now(3)},
                {"action": "Request intro to COO Maria Santos for exec alignment", "priority": "medium", "due_date": days_from_now(7)}
            ],
            "next_step": {
                "text": "Competitive displacement call with James Morrow",
                "due_date": days_from_now(2),
                "source": "agent",
                "set_at": now().isoformat()
            },
            "gold_data": {
                "facts": [
                    {"fact": "James Morrow attended Salesforce Revenue Cloud webinar June 19", "source": "linkedin_activity", "confidence": 0.91, "verified_by_grounding_agent": True},
                    {"fact": "Apex signed Salesforce CRM contract in 2023 â€” existing vendor relationship", "source": "perplexity_web_search", "confidence": 0.86, "verified_by_grounding_agent": True}
                ]
            }
        }
    },
    {
        "id": str(uuid.uuid4()),
        "name": "Blackstone Capital Group",
        "stage": "Negotiation",
        "deal_amount": "1200000.00",
        "close_date": days_from_now(44, as_str=False),
        "pov_forecast_cat": "Best Case",
        "pov_confidence": 0.68,
        "health_score": 0.61,
        "urgency_score": 0.79,
        "icp_score": 0.88,
        "hubspot_deal_id": "hs_deal_1003",
        "state": {
            "health_trend": "stable",
            "crm_forecast_category": "Commit",
            "pov": {
                "forecast_category": "Best Case",
                "confidence": 0.68,
                "deal_narrative": "CRM shows Commit but agent downgraded to Best Case. Close date has slipped 3 times. Key stakeholder Alexandra Webb goes on leave July 15. Legal raised GDPR concerns on data residency clause.",
                "top_risk_summary": "Deal slip pattern + champion leave creates window where deal could stall into Q3.",
                "meddpicc": {
                    "metrics": "Reduce trade settlement T+2 â†’ T+0, $3M/yr operational savings",
                    "economic_buyer": "CTO David Park â€” signed LOI March",
                    "decision_criteria": "SOC2 Type II, FedRAMP moderate, Bloomberg Terminal integration",
                    "decision_process": "Risk committee review (July 8) â†’ Legal â†’ Board approval for 7-figure",
                    "paper_process": "GDPR data residency clause blocking legal sign-off",
                    "identified_pain": "Settlement latency costing 0.2bps daily â€” $3M annually at volume",
                    "champion": "Alexandra Webb, Head of Platform Eng â€” on leave July 15â€“Aug 5",
                    "competition": "Existing in-house solution â€” inertia risk"
                }
            },
            "next_actions": [
                {"action": "Resolve GDPR data residency: propose EU-region data plane configuration", "priority": "critical", "due_date": days_from_now(5)},
                {"action": "Brief David Park directly before Alexandra's leave â€” own the relationship", "priority": "high", "due_date": days_from_now(8)},
                {"action": "Prepare risk committee presentation deck with compliance certifications", "priority": "high", "due_date": days_from_now(6)}
            ],
            "next_step": {
                "text": "Submit GDPR data residency proposal to legal team",
                "due_date": days_from_now(3),
                "source": "agent",
                "set_at": now().isoformat()
            },
            "gold_data": {
                "facts": [
                    {"fact": "Close date slipped 3x: originally Feb 28, then Apr 30, then Jun 30, now Jul 31", "source": "hubspot_history", "confidence": 0.99, "verified_by_grounding_agent": True},
                    {"fact": "Legal flagged GDPR Article 44 cross-border transfer on June 17", "source": "hubspot_notes", "confidence": 0.94, "verified_by_grounding_agent": True}
                ]
            }
        }
    },
    {
        "id": str(uuid.uuid4()),
        "name": "Lumina Retail Group",
        "stage": "Proposal",
        "deal_amount": "185000.00",
        "close_date": days_from_now(52, as_str=False),
        "pov_forecast_cat": "Pipeline",
        "pov_confidence": 0.55,
        "health_score": 0.44,
        "urgency_score": 0.74,
        "icp_score": 0.76,
        "hubspot_deal_id": "hs_deal_1004",
        "state": {
            "health_trend": "down",
            "crm_forecast_category": "Forecast",
            "pov": {
                "forecast_category": "Pipeline",
                "confidence": 0.55,
                "deal_narrative": "Usage in the 60-day pilot dropped 41% over the last 3 weeks. Key user Marcus Delgado flagged onboarding friction in NPS survey. CRM shows Forecast but signals indicate deal is at risk.",
                "top_risk_summary": "Low pilot engagement is the strongest predictor of deal loss. Agent downgraded from Forecast to Pipeline.",
                "meddpicc": {
                    "metrics": "30% reduction in SKU attribution errors, $220K savings/yr",
                    "economic_buyer": "VP Merchandising Tanya Ross â€” budget $185K approved",
                    "decision_criteria": "Shopify Plus integration, real-time inventory sync, mobile app",
                    "decision_process": "IT approval â†’ VP sign-off. No board review needed at this deal size.",
                    "paper_process": "Not started â€” proposal not yet accepted",
                    "identified_pain": "SKU attribution errors causing 12% overstock. Margin impact $800K/yr.",
                    "champion": "Marcus Delgado, Digital Ops Manager â€” frustrated with onboarding",
                    "competition": "Stitch Labs shortlisted alongside us"
                }
            },
            "next_actions": [
                {"action": "Emergency onboarding call with Marcus â€” identify top 3 friction points and resolve same day", "priority": "critical", "due_date": days_from_now(1)},
                {"action": "Assign dedicated CSM to pilot for remaining 30 days", "priority": "high", "due_date": days_from_now(2)},
                {"action": "Send usage re-engagement campaign: highlight ROI metrics from pilot data so far", "priority": "medium", "due_date": days_from_now(3)}
            ],
            "next_step": {
                "text": "Schedule emergency pilot rescue call with Marcus Delgado",
                "due_date": days_from_now(1),
                "source": "agent",
                "set_at": now().isoformat()
            },
            "gold_data": {
                "facts": [
                    {"fact": "Pilot login frequency dropped from 4.2/day to 0.9/day over 3 weeks", "source": "product_analytics", "confidence": 0.98, "verified_by_grounding_agent": True},
                    {"fact": "NPS survey response from Marcus Delgado: 'onboarding took too long, team not fully trained'", "source": "nps_survey", "confidence": 0.96, "verified_by_grounding_agent": False}
                ]
            }
        }
    },
    {
        "id": str(uuid.uuid4()),
        "name": "SkyBridge Technologies",
        "stage": "Discovery",
        "deal_amount": "340000.00",
        "close_date": days_from_now(75, as_str=False),
        "pov_forecast_cat": "Forecast",
        "pov_confidence": 0.71,
        "health_score": 0.73,
        "urgency_score": 0.62,
        "icp_score": 0.89,
        "hubspot_deal_id": "hs_deal_1005",
        "state": {
            "health_trend": "up",
            "crm_forecast_category": "Pipeline",
            "pov": {
                "forecast_category": "Forecast",
                "confidence": 0.71,
                "deal_narrative": "New CTO Rachel Kim joined from AWS in May â€” she's known for fast vendor decisions and has a strong cloud-first mandate. Agent upgraded deal from Pipeline to Forecast. Budget decision expected in August.",
                "top_risk_summary": "Leadership change is a risk AND an opportunity. Move fast to establish executive relationship with Rachel before competitors do.",
                "meddpicc": {
                    "metrics": "Target: 60% reduction in infra provisioning time, $500K DevOps savings",
                    "economic_buyer": "CFO pending â€” Rachel Kim has purchase authority up to $500K",
                    "decision_criteria": "Kubernetes-native, multi-cloud, GitOps workflow compatibility",
                    "decision_process": "CTO evaluation â†’ CFO rubber-stamp at this deal size",
                    "paper_process": "Not started",
                    "identified_pain": "Manual infra provisioning: 3 days average, blocking 6 dev teams",
                    "champion": "VP DevOps Kevin Okafor â€” strong internal advocate",
                    "competition": "HashiCorp + Terraform â€” incumbent tooling they want to replace"
                }
            },
            "next_actions": [
                {"action": "Request intro meeting with Rachel Kim via Kevin â€” 'strategic cloud infrastructure review'", "priority": "high", "due_date": days_from_now(5)},
                {"action": "Send Rachel Kim an AWS â†’ multi-cloud migration case study relevant to her background", "priority": "medium", "due_date": days_from_now(4)},
                {"action": "Prepare technical demo for DevOps team: GitOps + Kubernetes provisioning workflow", "priority": "medium", "due_date": days_from_now(10)}
            ],
            "next_step": {
                "text": "Intro meeting request with Rachel Kim via Kevin Okafor",
                "due_date": days_from_now(5),
                "source": "agent",
                "set_at": now().isoformat()
            },
            "gold_data": {
                "facts": [
                    {"fact": "Rachel Kim joined as CTO May 28, promoted from AWS Principal Solutions Architect", "source": "linkedin_activity", "confidence": 0.97, "verified_by_grounding_agent": True},
                    {"fact": "SkyBridge raised $45M Series C March 2026 â€” infra modernization in stated use-of-funds", "source": "crunchbase_perplexity", "confidence": 0.93, "verified_by_grounding_agent": True}
                ]
            }
        }
    },
    {
        "id": str(uuid.uuid4()),
        "name": "Cascade Manufacturing",
        "stage": "Discovery",
        "deal_amount": "520000.00",
        "close_date": days_from_now(120, as_str=False),
        "pov_forecast_cat": "Pipeline",
        "pov_confidence": 0.58,
        "health_score": 0.79,
        "urgency_score": 0.45,
        "icp_score": 0.82,
        "hubspot_deal_id": "hs_deal_1006",
        "state": {
            "health_trend": "up",
            "crm_forecast_category": "Pipeline",
            "pov": {
                "forecast_category": "Pipeline",
                "confidence": 0.58,
                "deal_narrative": "Strong ICP fit for enterprise manufacturing. Just closed Series C ($72M) with industrial automation in stated use-of-funds. Early discovery stage â€” no budget formally approved yet but financial runway confirms capacity.",
                "top_risk_summary": "Long sales cycle risk. Series C funding creates window to engage now before they select incumbent vendor relationships.",
                "meddpicc": {
                    "metrics": "OEE improvement 68% â†’ 82%, $1.8M annual production savings estimated",
                    "economic_buyer": "COO Brett Holloway â€” evaluating vendors post-funding",
                    "decision_criteria": "ISO 9001 compliance, PLC integration, predictive maintenance AI",
                    "decision_process": "Operations committee â†’ COO â†’ Board for 7-figure. Expect 4-month cycle.",
                    "paper_process": "Not started",
                    "identified_pain": "Line downtime costing $45K/hr. 3.2% unplanned downtime annually.",
                    "champion": "Not yet identified â€” mapping org chart",
                    "competition": "Rockwell Automation (incumbent), Siemens evaluating"
                }
            },
            "next_actions": [
                {"action": "Map org chart: identify Ops or Engineering leader to build champion relationship", "priority": "medium", "due_date": days_from_now(14)},
                {"action": "Send Series C congratulations + relevant manufacturing AI case study to COO", "priority": "medium", "due_date": days_from_now(7)},
                {"action": "Book site visit to manufacturing floor â€” technical discovery with plant manager", "priority": "low", "due_date": days_from_now(30)}
            ],
            "next_step": {
                "text": "Org chart mapping and champion identification",
                "due_date": days_from_now(14),
                "source": "agent",
                "set_at": now().isoformat()
            },
            "gold_data": {
                "facts": [
                    {"fact": "Cascade closed $72M Series C on June 5, 2026 â€” industrial automation use-of-funds stated in press release", "source": "perplexity_web_search", "confidence": 0.96, "verified_by_grounding_agent": True}
                ]
            }
        }
    },
    {
        "id": str(uuid.uuid4()),
        "name": "Orion Analytics",
        "stage": "Commit",
        "deal_amount": "95000.00",
        "close_date": days_from_now(12, as_str=False),
        "pov_forecast_cat": "Commit",
        "pov_confidence": 0.91,
        "health_score": 0.88,
        "urgency_score": 0.38,
        "icp_score": 0.79,
        "hubspot_deal_id": "hs_deal_1007",
        "state": {
            "health_trend": "up",
            "crm_forecast_category": "Commit",
            "pov": {
                "forecast_category": "Commit",
                "confidence": 0.91,
                "deal_narrative": "Strong deal trajectory. Champion Priya Nair is highly engaged â€” 3 reference calls arranged and legal has returned redlined MSA with minor changes only. Agent confirms Commit with high confidence.",
                "top_risk_summary": "Low risk. Only remaining step is final MSA sign-off and PO issuance â€” both in motion.",
                "meddpicc": {
                    "metrics": "Reduce BI query time 8s â†’ 0.3s, enable self-serve for 120 analysts",
                    "economic_buyer": "CDO Alex Morgan â€” signed LOI May",
                    "decision_criteria": "dbt compatibility, Snowflake native, SOC2 Type II",
                    "decision_process": "Legal review complete (minor redlines) â†’ PO â†’ Go-live",
                    "paper_process": "MSA redline returned June 20 â€” 3 minor clauses. Closing this week.",
                    "identified_pain": "BI bottleneck: 12-week backlog for analyst requests, 6 FTE data eng team bottlenecked",
                    "champion": "Priya Nair, Head of Data â€” arranged 3 references, fully committed",
                    "competition": "Looker considered and eliminated in Q1"
                }
            },
            "next_actions": [
                {"action": "Accept MSA redlines and return signed copy by EOD", "priority": "high", "due_date": days_from_now(1)},
                {"action": "Send PO instructions to Priya for procurement initiation", "priority": "medium", "due_date": days_from_now(2)},
                {"action": "Schedule kickoff call for July 7 â€” go-live target July 28", "priority": "medium", "due_date": days_from_now(5)}
            ],
            "next_step": {
                "text": "Return signed MSA to legal â€” accept all 3 redlines",
                "due_date": days_from_now(1),
                "source": "rep",
                "set_at": now().isoformat()
            },
            "gold_data": {
                "facts": [
                    {"fact": "Priya Nair arranged 3 reference calls with existing customers â€” all completed June 14-17", "source": "hubspot_activity", "confidence": 0.98, "verified_by_grounding_agent": True},
                    {"fact": "Legal returned MSA redlines June 20 â€” 3 minor liability cap clauses, no deal-breakers", "source": "hubspot_notes", "confidence": 0.97, "verified_by_grounding_agent": True}
                ]
            }
        }
    },
    {
        "id": str(uuid.uuid4()),
        "name": "NovaCure Biotech",
        "stage": "Proposal",
        "deal_amount": "210000.00",
        "close_date": days_from_now(38, as_str=False),
        "pov_forecast_cat": "Forecast",
        "pov_confidence": 0.66,
        "health_score": 0.57,
        "urgency_score": 0.84,
        "icp_score": 0.86,
        "hubspot_deal_id": "hs_deal_1008",
        "state": {
            "health_trend": "down",
            "crm_forecast_category": "Forecast",
            "pov": {
                "forecast_category": "Forecast",
                "confidence": 0.66,
                "deal_narrative": "Top competitor Benchling announced a biotech-specific AI module targeting FDA submission workflows â€” directly attacking our differentiated value prop. NovaCure's VP Regulatory Sarah Osei mentioned Benchling in last week's call.",
                "top_risk_summary": "Competitor product launch targeting exact use case. Act within 72 hours to counter with our FDA 21 CFR Part 11 compliance depth.",
                "meddpicc": {
                    "metrics": "Reduce clinical trial data processing from 14 days â†’ 2 days, $380K/trial savings",
                    "economic_buyer": "CTO Dr. Fumio Hayashi â€” budget approved pending final evaluation",
                    "decision_criteria": "21 CFR Part 11 compliance, LIMS integration, audit trail completeness",
                    "decision_process": "IT security review â†’ Regulatory affairs sign-off â†’ CTO. 6-week process.",
                    "paper_process": "Security questionnaire in review. Proposal submitted June 15.",
                    "identified_pain": "FDA submission prep: 14-day manual data consolidation per trial phase",
                    "champion": "Sarah Osei, VP Regulatory Affairs â€” now evaluating Benchling",
                    "competition": "Benchling â€” just launched AI module June 20 targeting this exact workflow"
                }
            },
            "next_actions": [
                {"action": "Send 21 CFR Part 11 compliance comparison sheet vs Benchling â€” highlight audit trail depth", "priority": "critical", "due_date": days_from_now(1)},
                {"action": "Schedule product demo with Dr. Hayashi focused on FDA submission workflow automation", "priority": "high", "due_date": days_from_now(3)},
                {"action": "Share reference from Moderna (existing customer) on regulatory audit readiness", "priority": "high", "due_date": days_from_now(2)}
            ],
            "next_step": {
                "text": "Competitive counter-proposal: 21 CFR Part 11 audit trail depth vs Benchling",
                "due_date": days_from_now(1),
                "source": "agent",
                "set_at": now().isoformat()
            },
            "gold_data": {
                "facts": [
                    {"fact": "Benchling launched AI regulatory module June 20 targeting FDA 510k and IND submissions", "source": "perplexity_web_search", "confidence": 0.94, "verified_by_grounding_agent": True},
                    {"fact": "Sarah Osei mentioned Benchling by name in June 19 discovery call recording", "source": "gong_transcript", "confidence": 0.99, "verified_by_grounding_agent": True}
                ]
            }
        }
    },
    {
        "id": str(uuid.uuid4()),
        "name": "Summit Financial Advisors",
        "stage": "Proposal",
        "deal_amount": "380000.00",
        "close_date": days_from_now(60, as_str=False),
        "pov_forecast_cat": "Forecast",
        "pov_confidence": 0.69,
        "health_score": 0.71,
        "urgency_score": 0.58,
        "icp_score": 0.81,
        "hubspot_deal_id": "hs_deal_1009",
        "state": {
            "health_trend": "stable",
            "crm_forecast_category": "Forecast",
            "pov": {
                "forecast_category": "Forecast",
                "confidence": 0.69,
                "deal_narrative": "Stable deal with a clear path to close. Summit was featured in WSJ article on fintech compliance spending â€” confirms budget priority alignment. Champion Richard Yuen is actively engaged. Main risk is a procurement process slowdown in August.",
                "top_risk_summary": "Procurement typically slows in August. Push for committed timeline by July 15 to avoid slippage.",
                "meddpicc": {
                    "metrics": "SEC reporting time reduction 5 days â†’ 8 hours, 99.9% audit trail completeness",
                    "economic_buyer": "CFO Linda Zhang â€” Q3 budget allocated",
                    "decision_criteria": "SOX compliance, real-time SEC reporting, multi-custodian data ingestion",
                    "decision_process": "Compliance review â†’ IT security â†’ CFO sign-off. Standard 6-week process.",
                    "paper_process": "Not started â€” awaiting proposal acceptance",
                    "identified_pain": "SEC filing preparation: 5-day manual process, 2 FTEs, $320K annual cost",
                    "champion": "Richard Yuen, Chief Compliance Officer â€” strongly advocating internally",
                    "competition": "Broadridge Financial Solutions â€” incumbent at parent company"
                }
            },
            "next_actions": [
                {"action": "Leverage WSJ article mention â€” send congratulations and frame urgency around compliance modernization timing", "priority": "medium", "due_date": days_from_now(3)},
                {"action": "Push for procurement timeline commitment by July 15 â€” avoid August slowdown", "priority": "high", "due_date": days_from_now(14)},
                {"action": "Schedule technical deep-dive with IT security team on SOX controls", "priority": "medium", "due_date": days_from_now(10)}
            ],
            "next_step": {
                "text": "Timeline commitment call with Richard Yuen before July 15",
                "due_date": days_from_now(14),
                "source": "agent",
                "set_at": now().isoformat()
            },
            "gold_data": {
                "facts": [
                    {"fact": "Summit Financial featured in WSJ June 21 article on fintech compliance modernization investments", "source": "perplexity_web_search", "confidence": 0.95, "verified_by_grounding_agent": True}
                ]
            }
        }
    },
    {
        "id": str(uuid.uuid4()),
        "name": "Verdant Energy Solutions",
        "stage": "Discovery",
        "deal_amount": "750000.00",
        "close_date": days_from_now(140, as_str=False),
        "pov_forecast_cat": "Pipeline",
        "pov_confidence": 0.52,
        "health_score": 0.82,
        "urgency_score": 0.28,
        "icp_score": 0.93,
        "hubspot_deal_id": "hs_deal_1010",
        "state": {
            "health_trend": "up",
            "crm_forecast_category": "Pipeline",
            "pov": {
                "forecast_category": "Pipeline",
                "confidence": 0.52,
                "deal_narrative": "Highest ICP score in the pipeline at 0.93. Verdant is a greenfield opportunity â€” perfect fit for grid intelligence platform. CEO Elena Marchetti is a former McKinsey partner known for fast, data-driven decisions. Early stage but worth prioritizing for Q4.",
                "top_risk_summary": "Long sales cycle. Risk of budget freeze if energy market softens. Prioritize champion identification and exec relationship.",
                "meddpicc": {
                    "metrics": "Grid efficiency: 15% energy loss reduction = $4.2M/yr savings at current throughput",
                    "economic_buyer": "CEO Elena Marchetti â€” controls strategic capex",
                    "decision_criteria": "NERC CIP compliance, SCADA integration, real-time grid analytics",
                    "decision_process": "Engineering eval â†’ Operations committee â†’ CEO. Expect 5-month cycle.",
                    "paper_process": "Not started",
                    "identified_pain": "Grid loss events: 12 unplanned outages last year at $350K each",
                    "champion": "Not yet identified â€” targeting VP Grid Operations",
                    "competition": "GE Vernova (incumbent grid monitoring), AutoGrid"
                }
            },
            "next_actions": [
                {"action": "Request introductory call via mutual connection at DOE â€” cite IRA grid modernization funding angle", "priority": "medium", "due_date": days_from_now(21)},
                {"action": "Prepare Verdant-specific energy grid case study with NERC CIP compliance angle", "priority": "low", "due_date": days_from_now(28)},
                {"action": "Identify VP Grid Operations as potential champion â€” LinkedIn research + warm intro request", "priority": "medium", "due_date": days_from_now(14)}
            ],
            "next_step": {
                "text": "Champion identification: VP Grid Operations at Verdant",
                "due_date": days_from_now(14),
                "source": "agent",
                "set_at": now().isoformat()
            },
            "gold_data": {
                "facts": [
                    {"fact": "Verdant awarded $28M DOE grid modernization grant April 2026 â€” mandates vendor evaluation by Q4", "source": "perplexity_web_search", "confidence": 0.92, "verified_by_grounding_agent": True},
                    {"fact": "Elena Marchetti is a McKinsey alum known for 90-day vendor selection processes", "source": "linkedin_bio", "confidence": 0.85, "verified_by_grounding_agent": False}
                ]
            }
        }
    },

    # ── Real companies — Exa can research these ──────────────────────────────

    {
        "id": str(uuid.uuid4()),
        "name": "Snowflake",
        "stage": "Negotiation",
        "deal_amount": "620000.00",
        "close_date": days_from_now(22, as_str=False),
        "pov_forecast_cat": "Best Case",
        "pov_confidence": 0.65,
        "health_score": 0.44,
        "urgency_score": 0.91,
        "icp_score": 0.96,
        "hubspot_deal_id": "hs_deal_2001",
        "state": {
            "health_trend": "down",
            "crm_forecast_category": "Commit",
            "pov": {
                "forecast_category": "Best Case",
                "confidence": 0.65,
                "deal_narrative": "Snowflake's sales team has expanded aggressively post-IPO but rep productivity metrics are declining. New CEO Sridhar Ramaswamy (formerly Google) is under pressure to improve sales efficiency. Our champion Marcus Holloway (VP Revenue Operations) has internal buy-in but the CFO Mike Scarpelli is pushing back on new tooling spend following recent restructuring.",
                "top_risk_summary": "CFO cost scrutiny + CEO transition uncertainty. Champion needs exec air cover before deal can close.",
                "meddpicc": {
                    "metrics": "Target: 23% increase in rep quota attainment, 18% reduction in CRM hygiene time",
                    "economic_buyer": "CFO Mike Scarpelli — scrutinizing all new SaaS spend post-restructuring",
                    "decision_criteria": "HubSpot-native integration, SOC2 Type II, <500ms API response, GDPR compliant",
                    "decision_process": "RevOps eval -> IT security -> CFO approval. Targeting August 15 board sign-off.",
                    "paper_process": "Legal DPA in review. MSA redline started June 20.",
                    "identified_pain": "400+ enterprise reps with avg 31% of time on manual CRM updates. $8M/yr productivity loss.",
                    "champion": "Marcus Holloway, VP Revenue Operations — strong internal advocate, needs CFO alignment",
                    "competition": "Clari (incumbent for forecasting), Gong (partial overlap on call intelligence)"
                }
            },
            "next_actions": [
                {"action": "Prepare CFO-ready ROI model — quantify $8M productivity loss vs $620K investment", "priority": "critical", "due_date": days_from_now(2)},
                {"action": "Request exec sponsor call with CEO Sridhar Ramaswamy — frame as sales efficiency mandate", "priority": "high", "due_date": days_from_now(5)},
                {"action": "Accelerate legal DPA review — assign dedicated solutions engineer to unblock", "priority": "high", "due_date": days_from_now(3)}
            ],
            "next_step": {
                "text": "CFO briefing with Mike Scarpelli — ROI model delivery",
                "due_date": days_from_now(4),
                "source": "agent",
                "set_at": now().isoformat()
            },
            "gold_data": {
                "facts": [
                    {"fact": "Snowflake announced restructuring and headcount reduction in February 2024 alongside CEO transition", "source": "exa_web_search", "confidence": 0.96, "verified_by_grounding_agent": True},
                    {"fact": "Sridhar Ramaswamy joined as CEO in February 2024, replacing Frank Slootman", "source": "exa_web_search", "confidence": 0.99, "verified_by_grounding_agent": True}
                ]
            }
        }
    },
    {
        "id": str(uuid.uuid4()),
        "name": "Figma",
        "stage": "Proposal",
        "deal_amount": "310000.00",
        "close_date": days_from_now(38, as_str=False),
        "pov_forecast_cat": "Forecast",
        "pov_confidence": 0.71,
        "health_score": 0.62,
        "urgency_score": 0.79,
        "icp_score": 0.88,
        "hubspot_deal_id": "hs_deal_2002",
        "state": {
            "health_trend": "up",
            "crm_forecast_category": "Forecast",
            "pov": {
                "forecast_category": "Forecast",
                "confidence": 0.71,
                "deal_narrative": "Figma is aggressively hiring sales reps following the collapse of the Adobe acquisition and their subsequent $1B independent funding round. New VP Sales Kris Rasmussen is building out a full enterprise motion from scratch and explicitly stated 'we need AI-native tooling across the stack'. Champion relationship is strong and budget is freshly allocated.",
                "top_risk_summary": "Competitive evaluation with Outreach.io. Rep needs to accelerate timeline before Figma's Q3 hiring surge locks in competitor contracts.",
                "meddpicc": {
                    "metrics": "Target: onboard 200 new enterprise reps in 90 days with 60% quota attainment in month 3",
                    "economic_buyer": "VP Sales Kris Rasmussen — has full discretionary budget for sales stack",
                    "decision_criteria": "AI-native, fast deployment (<2 weeks), HubSpot + Salesforce compatible",
                    "decision_process": "VP Sales evaluation -> Legal -> sign-off. Flat, fast process.",
                    "paper_process": "Not started — waiting on proposal acceptance",
                    "identified_pain": "Standing up enterprise sales motion from scratch — no existing tooling or playbooks",
                    "champion": "Kris Rasmussen, VP Sales — is also the economic buyer",
                    "competition": "Outreach.io — submitted competing proposal June 18"
                }
            },
            "next_actions": [
                {"action": "Differentiate from Outreach.io — send AI grounding agent demo focused on new rep ramp speed", "priority": "critical", "due_date": days_from_now(1)},
                {"action": "Propose 2-week pilot with 10 reps — reduce perceived risk of full deployment", "priority": "high", "due_date": days_from_now(3)},
                {"action": "Reference call: connect Kris with similar VP Sales who onboarded 150+ reps in 60 days", "priority": "high", "due_date": days_from_now(5)}
            ],
            "next_step": {
                "text": "Competitive displacement: AI demo vs Outreach.io with Kris Rasmussen",
                "due_date": days_from_now(2),
                "source": "agent",
                "set_at": now().isoformat()
            },
            "gold_data": {
                "facts": [
                    {"fact": "Adobe's $20B acquisition of Figma was blocked by EU regulators and abandoned in December 2023", "source": "exa_web_search", "confidence": 0.99, "verified_by_grounding_agent": True},
                    {"fact": "Figma raised $1B in new funding at $12.5B valuation following Adobe deal collapse", "source": "exa_web_search", "confidence": 0.97, "verified_by_grounding_agent": True}
                ]
            }
        }
    },
    {
        "id": str(uuid.uuid4()),
        "name": "Databricks",
        "stage": "Discovery",
        "deal_amount": "890000.00",
        "close_date": days_from_now(95, as_str=False),
        "pov_forecast_cat": "Pipeline",
        "pov_confidence": 0.55,
        "health_score": 0.74,
        "urgency_score": 0.52,
        "icp_score": 0.94,
        "hubspot_deal_id": "hs_deal_2003",
        "state": {
            "health_trend": "up",
            "crm_forecast_category": "Pipeline",
            "pov": {
                "forecast_category": "Pipeline",
                "confidence": 0.55,
                "deal_narrative": "Databricks is in hypergrowth following their $10B Series J at a $62B valuation. Their 1,200+ sales team is expanding globally and leadership has publicly committed to AI-native go-to-market. Entry point is via Ali Ghodsi's (CEO) office — he made a public statement about requiring every GTM tool to have an AI backbone. Early stage but extremely high ICP fit.",
                "top_risk_summary": "Long enterprise sales cycle. Key risk is getting lost in their massive vendor evaluation queue. Need to land a strong champion in RevOps fast.",
                "meddpicc": {
                    "metrics": "Target: 30% improvement in pipeline coverage ratio across 8 global sales regions",
                    "economic_buyer": "CRO — not yet identified or engaged",
                    "decision_criteria": "Enterprise-grade security, multi-region deployment, Salesforce CRM integration, AI-native",
                    "decision_process": "RevOps eval -> Security review -> CRO -> legal. Expect 12-16 week process.",
                    "paper_process": "Not started",
                    "identified_pain": "1,200 reps across 8 regions — no unified AI layer for pipeline intelligence. Rep burnout on CRM hygiene.",
                    "champion": "Target: Head of Revenue Operations — intro pending via mutual connection",
                    "competition": "Clari (strong incumbent), Salesforce Einstein (native advantage)"
                }
            },
            "next_actions": [
                {"action": "Secure intro to Databricks Head of RevOps via LinkedIn mutual connection — personalize outreach around Ali Ghodsi's AI-native GTM mandate", "priority": "high", "due_date": days_from_now(7)},
                {"action": "Prepare Databricks-specific pitch deck — lead with multi-region agent deployment and Salesforce CRM integration", "priority": "medium", "due_date": days_from_now(10)},
                {"action": "Research recent Databricks earnings and sales hiring announcements for conversation hooks", "priority": "medium", "due_date": days_from_now(3)}
            ],
            "next_step": {
                "text": "Champion identification: secure RevOps intro via mutual connection",
                "due_date": days_from_now(7),
                "source": "agent",
                "set_at": now().isoformat()
            },
            "gold_data": {
                "facts": [
                    {"fact": "Databricks raised $10B Series J at $62B valuation in December 2024", "source": "exa_web_search", "confidence": 0.98, "verified_by_grounding_agent": True},
                    {"fact": "Databricks CEO Ali Ghodsi has publicly committed to AI-native go-to-market tooling across all GTM functions", "source": "exa_web_search", "confidence": 0.82, "verified_by_grounding_agent": False}
                ]
            }
        }
    }
]

# ---------------------------------------------------------------------------
# Signals  (2-3 per account, keyed by account name for lookup)
# ---------------------------------------------------------------------------
def make_signals(accounts_by_name):
    rows = []
    s = lambda account_name, **kw: {
        "id": str(uuid.uuid4()),
        "account_id": accounts_by_name[account_name],
        "workspace_id": WORKSPACE_ID,
        "processed": True,
        "processed_at": now(),
        "pushed_to_inbox": True,
        "acknowledged": False,
        "detected_at": now() - timedelta(hours=kw.pop("hours_ago", 4)),
        "created_at": now() - timedelta(hours=kw.pop("created_hours_ago", 4)),
        **kw
    }

    rows += [
        s("Meridian Health Systems",
          type="champion_dark", urgency="high", urgency_score=0.94,
          detail="Sarah Chen (VP Clinical Ops) has not responded to 3 outreach attempts over 14 days. Last activity: viewed proposal June 12.",
          source="hubspot", confidence=0.97,
          gold_resolution="Champion confirmed dark â€” no email opens, no CRM activity, no LinkedIn engagement since June 12.",
          gold_confidence=0.97, gold_sources=[{"source": "hubspot_activity", "raw_value": "0 opens in 14d", "confidence": 0.97, "weight": 1.0}],
          hours_ago=6, created_hours_ago=6),
        s("Meridian Health Systems",
          type="competitive_mention", urgency="high", urgency_score=0.88,
          detail="Veeva Health submitted a competing proposal to Meridian procurement on June 18.",
          source="perplexity", confidence=0.88,
          gold_resolution="Veeva proposal confirmed via procurement contact and company LinkedIn posts.",
          gold_confidence=0.88, gold_sources=[{"source": "perplexity_web_search", "raw_value": "Veeva-Meridian partnership announcement draft seen", "confidence": 0.88, "weight": 1.0}],
          hours_ago=48, created_hours_ago=48),

        s("Apex Logistics Partners",
          type="competitive_mention", urgency="high", urgency_score=0.91,
          detail="James Morrow (IT Director) registered for Salesforce Revenue Cloud webinar June 19. Duration attended: 47 minutes.",
          source="linkedin", confidence=0.91,
          gold_resolution="LinkedIn event attendance confirmed. Salesforce Revenue Cloud is directly competitive at this deal size.",
          gold_confidence=0.91, gold_sources=[{"source": "linkedin_activity", "raw_value": "Event attendance: Salesforce Revenue Cloud Deep Dive", "confidence": 0.91, "weight": 1.0}],
          hours_ago=72, created_hours_ago=72),
        s("Apex Logistics Partners",
          type="deal_slip", urgency="medium", urgency_score=0.68,
          detail="Decision timeline extended from June 30 to July 31 â€” COO cited 'expanded evaluation scope' in email.",
          source="hubspot", confidence=0.96,
          gold_resolution="Timeline slip confirmed. Expanded evaluation likely includes Salesforce.",
          gold_confidence=0.94, gold_sources=[{"source": "hubspot_notes", "raw_value": "Email from Maria Santos Jun 17: extending eval to Jul 31", "confidence": 0.96, "weight": 1.0}],
          hours_ago=120, created_hours_ago=120),

        s("Blackstone Capital Group",
          type="deal_slip", urgency="high", urgency_score=0.82,
          detail="Close date slipped for the third time â€” now July 31. GDPR legal review blocking final sign-off.",
          source="hubspot", confidence=0.99,
          gold_resolution="Third slip confirmed in HubSpot history. GDPR Article 44 data residency clause is the documented blocker.",
          gold_confidence=0.99, gold_sources=[{"source": "hubspot_history", "raw_value": "Close date modified 3x in deal history", "confidence": 0.99, "weight": 1.0}],
          hours_ago=36, created_hours_ago=36),
        s("Blackstone Capital Group",
          type="champion_dark", urgency="medium", urgency_score=0.71,
          detail="Alexandra Webb (Head of Platform Eng) going on leave July 15. No handoff plan established.",
          source="hubspot", confidence=0.88,
          gold_resolution="Leave confirmed via OOO calendar invite received by rep. No delegate champion identified.",
          gold_confidence=0.88, gold_sources=[{"source": "hubspot_notes", "raw_value": "OOO: Alexandra Webb Jul 15 - Aug 5", "confidence": 0.88, "weight": 1.0}],
          hours_ago=24, created_hours_ago=24),

        s("Lumina Retail Group",
          type="usage_drop", urgency="high", urgency_score=0.89,
          detail="Pilot platform usage dropped 41% over 3 weeks. Daily active users down from 12 to 4.",
          source="hubspot", confidence=0.98,
          gold_resolution="Usage drop confirmed via analytics export. Primary users Marcus Delgado team not logging in.",
          gold_confidence=0.98, gold_sources=[{"source": "product_analytics", "raw_value": "DAU: 12 â†’ 7 â†’ 5 â†’ 4 over weeks 1-4", "confidence": 0.98, "weight": 1.0}],
          hours_ago=18, created_hours_ago=18),

        s("SkyBridge Technologies",
          type="leadership_change", urgency="medium", urgency_score=0.66,
          detail="New CTO Rachel Kim joined May 28 from AWS. Known for fast vendor decisions and cloud-first mandates.",
          source="linkedin", confidence=0.97,
          gold_resolution="Confirmed via LinkedIn announcement and SkyBridge press release. AWS background creates cloud-native bias favorable to our position.",
          gold_confidence=0.97, gold_sources=[{"source": "linkedin_activity", "raw_value": "Rachel Kim CTO announcement post", "confidence": 0.97, "weight": 1.0}],
          hours_ago=480, created_hours_ago=480),

        s("Cascade Manufacturing",
          type="funding_event", urgency="medium", urgency_score=0.51,
          detail="Cascade Manufacturing closed $72M Series C on June 5. Industrial automation stated as primary use-of-funds.",
          source="perplexity", confidence=0.96,
          gold_resolution="Series C confirmed via Crunchbase and TechCrunch coverage. Use-of-funds explicitly mentions vendor evaluation.",
          gold_confidence=0.96, gold_sources=[{"source": "perplexity_web_search", "raw_value": "Cascade Manufacturing Series C press release June 5", "confidence": 0.96, "weight": 1.0}],
          hours_ago=504, created_hours_ago=504),

        s("NovaCure Biotech",
          type="competitive_mention", urgency="high", urgency_score=0.93,
          detail="Benchling launched AI regulatory module June 20 targeting FDA 510k / IND submissions â€” directly competitive with our core value prop.",
          source="perplexity", confidence=0.94,
          gold_resolution="Benchling product launch confirmed. Sarah Osei mentioned Benchling by name in June 19 Gong call recording.",
          gold_confidence=0.96, gold_sources=[
              {"source": "perplexity_web_search", "raw_value": "Benchling AI regulatory launch announcement", "confidence": 0.94, "weight": 0.6},
              {"source": "gong_transcript", "raw_value": "Sarah Osei: 'We're also looking at Benchling's new module'", "confidence": 0.99, "weight": 0.4}
          ],
          hours_ago=30, created_hours_ago=30),

        s("Summit Financial Advisors",
          type="news_mention", urgency="low", urgency_score=0.41,
          detail="Summit Financial featured in WSJ article (June 21) on fintech firms increasing compliance tech spend in 2026.",
          source="perplexity", confidence=0.95,
          gold_resolution="WSJ article confirms budget priority for compliance modernization â€” aligns directly with our product positioning.",
          gold_confidence=0.95, gold_sources=[{"source": "perplexity_web_search", "raw_value": "WSJ: Summit Financial compliance modernization investment", "confidence": 0.95, "weight": 1.0}],
          hours_ago=96, created_hours_ago=96),

        s("Verdant Energy Solutions",
          type="funding_event", urgency="low", urgency_score=0.39,
          detail="Verdant awarded $28M DOE grid modernization grant April 2026. Vendor evaluation mandated by Q4 2026.",
          source="perplexity", confidence=0.92,
          gold_resolution="DOE grant confirmed via federal grants database. Q4 vendor mandate creates natural buying window.",
          gold_confidence=0.92, gold_sources=[{"source": "perplexity_web_search", "raw_value": "DOE grid modernization grant Verdant Energy April 2026", "confidence": 0.92, "weight": 1.0}],
          hours_ago=1200, created_hours_ago=1200),

        s("Snowflake",
          type="leadership_change", urgency="high", urgency_score=0.88,
          detail="Snowflake CEO transition: Frank Slootman stepped down, Sridhar Ramaswamy (ex-Google) named CEO Feb 2024. New leadership is auditing all vendor contracts.",
          source="exa", confidence=0.99,
          gold_resolution="CEO transition confirmed via Snowflake press release and SEC filing. All major vendor relationships under review per new CTO directive.",
          gold_confidence=0.99, gold_sources=[{"source": "exa_web_search", "raw_value": "Snowflake CEO Frank Slootman steps down, Sridhar Ramaswamy named CEO", "confidence": 0.99, "weight": 1.0}],
          hours_ago=12, created_hours_ago=12),
        s("Snowflake",
          type="competitive_mention", urgency="high", urgency_score=0.82,
          detail="Clari (incumbent forecasting tool) is pitching expanded AI features to Snowflake's RevOps team — direct overlap with our pipeline intelligence module.",
          source="exa", confidence=0.84,
          gold_resolution="Clari-Snowflake renewal discussions confirmed via LinkedIn post by Snowflake RevOps analyst. Competitive risk is real.",
          gold_confidence=0.84, gold_sources=[{"source": "exa_web_search", "raw_value": "Clari Snowflake renewal enterprise forecasting platform", "confidence": 0.84, "weight": 1.0}],
          hours_ago=36, created_hours_ago=36),

        s("Figma",
          type="funding_event", urgency="medium", urgency_score=0.74,
          detail="Figma raised $1B at $12.5B valuation following Adobe acquisition collapse. Actively building enterprise sales team from scratch — 80+ open sales roles posted.",
          source="exa", confidence=0.98,
          gold_resolution="Funding confirmed via TechCrunch and SEC filing. 83 open sales roles confirmed on LinkedIn Jobs as of June 2026.",
          gold_confidence=0.98, gold_sources=[{"source": "exa_web_search", "raw_value": "Figma $1B funding round $12.5B valuation 2024", "confidence": 0.98, "weight": 1.0}],
          hours_ago=48, created_hours_ago=48),
        s("Figma",
          type="competitive_mention", urgency="high", urgency_score=0.87,
          detail="Outreach.io submitted competing proposal to Figma VP Sales June 18. Outreach is pitching their AI SDR module as 'Figma's full sales stack in one platform'.",
          source="exa", confidence=0.79,
          gold_resolution="Outreach-Figma evaluation confirmed via LinkedIn mutual connection at Figma RevOps. Competing on deployment speed and AI differentiation.",
          gold_confidence=0.81, gold_sources=[{"source": "exa_web_search", "raw_value": "Outreach.io enterprise proposal Figma sales team", "confidence": 0.79, "weight": 1.0}],
          hours_ago=72, created_hours_ago=72),

        s("Databricks",
          type="funding_event", urgency="medium", urgency_score=0.61,
          detail="Databricks closed $10B Series J at $62B valuation Dec 2024. CEO stated all GTM tools must be AI-native. Budget for 2026 sales stack refresh confirmed at board level.",
          source="exa", confidence=0.98,
          gold_resolution="Series J funding confirmed via Databricks press release and Bloomberg. AI-native GTM mandate sourced from CEO keynote at Data+AI Summit.",
          gold_confidence=0.97, gold_sources=[{"source": "exa_web_search", "raw_value": "Databricks $10B Series J $62B valuation December 2024", "confidence": 0.98, "weight": 1.0}],
          hours_ago=240, created_hours_ago=240),
    ]
    return rows


# ---------------------------------------------------------------------------
# Drafts (for high-urgency accounts)
# ---------------------------------------------------------------------------
def make_drafts(accounts_by_name):
    rows = []
    d = lambda account_name, **kw: {
        "id": str(uuid.uuid4()),
        "account_id": accounts_by_name[account_name],
        "workspace_id": WORKSPACE_ID,
        "status": "pending",
        "pushed_to_crm": False,
        "sources_cited": kw.pop("sources_cited", []),
        "gold_data_used": kw.pop("gold_data_used", {}),
        "created_at": now() - timedelta(hours=kw.pop("hours_ago", 2)),
        "expires_at": now() + timedelta(hours=kw.pop("expires_in_hours", 46)),
        **kw
    }

    rows += [
        d("Meridian Health Systems",
          type="email_followup",
          subject_line="Re: Your Q3 go-live â€” a thought on next steps",
          target_contact="sarah.chen@meridianhealth.com",
          content="""Hi Sarah,

I wanted to reach out personally â€” I know things get busy during reorgs, and I want to make sure we don't lose the momentum you've built with your clinical ops team around the prior-auth improvements.

I did want to flag one thing directly: our Q3 implementation window closes July 15. If we miss that, the next available slot pushes to September, which puts your ROI realization at risk heading into your budget cycle.

Given where we are in legal (MSA is close â€” three minor clauses), I'd love 20 minutes with you and Dr. Kirk to align on a path forward. I can have our implementation lead on the call to confirm the go-live timeline.

Would Thursday or Friday this week work?

Looking forward to reconnecting,
[Rep Name]""",
          confidence=0.87,
          sources_cited=[
              {"fact": "Sarah Chen has not responded in 14 days", "source": "hubspot_activity", "source_id": "sig_meridian_1", "confidence": 0.97, "verified_by_grounding_agent": True},
              {"fact": "Q3 implementation window closes July 15", "source": "internal_ops_calendar", "source_id": "ops_cal_q3", "confidence": 0.99, "verified_by_grounding_agent": False}
          ],
          hours_ago=3, expires_in_hours=45),

        d("Apex Logistics Partners",
          type="email_followup",
          subject_line="Apex + [Product]: Implementation timeline vs Salesforce Revenue Cloud",
          target_contact="james.morrow@apexlogistics.com",
          content="""Hi James,

I saw you attended the Salesforce Revenue Cloud webinar last week â€” totally fair to be doing your research at this stage.

I wanted to share one data point that often surprises people at this stage of evaluation: our NetSuite integration goes live in 6 weeks. Salesforce Revenue Cloud's average implementation for a freight billing workflow like yours is 16â€“20 weeks based on three recent customer migrations I'm aware of.

Given your July 31 decision target, the timeline math matters. I'd love to put together a side-by-side with our implementation lead on the call so you have apples-to-apples.

Worth 30 minutes this week?

[Rep Name]""",
          confidence=0.84,
          sources_cited=[
              {"fact": "James Morrow attended Salesforce webinar June 19", "source": "linkedin_activity", "source_id": "sig_apex_1", "confidence": 0.91, "verified_by_grounding_agent": True},
              {"fact": "Our NetSuite integration: 6-week go-live", "source": "internal_implementation_data", "source_id": "impl_netsuite", "confidence": 0.97, "verified_by_grounding_agent": False}
          ],
          hours_ago=5, expires_in_hours=43),

        d("Lumina Retail Group",
          type="email_followup",
          subject_line="Quick check-in on your pilot â€” can we jump on a call?",
          target_contact="marcus.delgado@luminaretail.com",
          content="""Hi Marcus,

I noticed login activity on the platform has been lower over the past few weeks, and I want to make sure we're solving the right problems for your team.

From what I can see, the SKU attribution workflow is configured and the Shopify sync is running â€” but I suspect the onboarding might not have been as smooth as it should have been for your broader team.

I'd love to jump on a 30-minute call to identify the top 2-3 friction points and resolve them on the spot. I'll bring our solutions engineer. We can also run through the attribution accuracy report so you can see the ROI we've already generated from the pilot data.

Does tomorrow afternoon work?

[Rep Name]""",
          confidence=0.89,
          sources_cited=[
              {"fact": "Pilot DAU dropped from 12 to 4 over 3 weeks", "source": "product_analytics", "source_id": "sig_lumina_1", "confidence": 0.98, "verified_by_grounding_agent": True},
              {"fact": "NPS response: onboarding friction cited", "source": "nps_survey", "source_id": "nps_lumina_jun", "confidence": 0.96, "verified_by_grounding_agent": False}
          ],
          hours_ago=2, expires_in_hours=46),

        d("NovaCure Biotech",
          type="email_followup",
          subject_line="Benchling's new module vs our 21 CFR Part 11 compliance depth",
          target_contact="sarah.osei@novacurebiotech.com",
          content="""Hi Sarah,

Following up on our conversation â€” I know you mentioned evaluating Benchling's new AI regulatory module, and I think it's worth a direct comparison on the dimension that matters most for your FDA submissions.

The core difference: Benchling's new module processes regulatory documents but doesn't yet have 21 CFR Part 11-compliant audit trails. Every action in our platform generates a timestamped, cryptographically signed audit record â€” that's the standard your validation team will require for IND submissions.

I've attached a one-page comparison. We also have a reference at Moderna who went through an FDA inspection last quarter with our audit trail as their primary evidence package â€” happy to connect you with their VP Regulatory Affairs directly.

Would a 20-minute call with Dr. Hayashi and your team make sense this week?

[Rep Name]""",
          confidence=0.91,
          sources_cited=[
              {"fact": "Benchling launched AI regulatory module June 20 without 21 CFR Part 11 audit trails", "source": "perplexity_web_search", "source_id": "sig_novacure_1", "confidence": 0.94, "verified_by_grounding_agent": True},
              {"fact": "Sarah Osei mentioned Benchling in June 19 Gong call", "source": "gong_transcript", "source_id": "gong_novacure_jun19", "confidence": 0.99, "verified_by_grounding_agent": True}
          ],
          hours_ago=1, expires_in_hours=47),

        d("Blackstone Capital Group",
          type="risk_summary",
          subject_line=None,
          target_contact=None,
          content="""RISK SUMMARY â€” Blackstone Capital Group
Generated: June 26, 2026

DEAL STATUS: Best Case (agent downgraded from Commit)
RISK LEVEL: High â€” immediate action required

PRIMARY RISKS:
1. GDPR Data Residency Block â€” Legal raised Article 44 cross-border transfer concern June 17. No resolution proposed yet. Estimated delay if unresolved: 3â€“4 weeks.
2. Champion Leave Window â€” Alexandra Webb (Head of Platform Eng) on leave July 15 â€“ Aug 5. No delegate champion identified. Deal will stall without executive relationship with David Park.
3. Third Close Date Slip â€” Pattern of slippage increases probability of Q3 loss. CRM shows Commit; agent confidence 0.68.

RECOMMENDED ACTIONS (next 5 days):
1. Propose EU-region data plane configuration to legal â€” eliminate Article 44 concern. Have solutions architect draft technical proposal.
2. Schedule 1:1 with CTO David Park before July 15 â€” own the relationship directly, not through Alexandra.
3. Prepare risk committee deck with SOC2 Type II, FedRAMP moderate, and GDPR compliance certifications.

MEDDPICC GAP: Paper process is the critical path. Legal is the only blocker on an otherwise well-qualified deal.""",
          confidence=0.88,
          sources_cited=[
              {"fact": "Close date slipped 3 times", "source": "hubspot_history", "source_id": "sig_blackstone_1", "confidence": 0.99, "verified_by_grounding_agent": True},
              {"fact": "GDPR Article 44 flagged by legal June 17", "source": "hubspot_notes", "source_id": "hs_blackstone_legal", "confidence": 0.94, "verified_by_grounding_agent": True}
          ],
          hours_ago=4, expires_in_hours=44),
    ]
    return rows


# ---------------------------------------------------------------------------
# Interactions (history)
# ---------------------------------------------------------------------------
def make_interactions(accounts_by_name):
    rows = []
    i = lambda account_name, **kw: {
        "id": str(uuid.uuid4()),
        "account_id": accounts_by_name[account_name],
        "workspace_id": WORKSPACE_ID,
        "is_training_signal": False,
        "created_at": now() - timedelta(days=kw.pop("days_ago", 7)),
        "occurred_at": now() - timedelta(days=kw.pop("occurred_days_ago", 7)),
        **kw
    }

    rows += [
        i("Meridian Health Systems", type="call", source="hubspot", notes="Discovery call with Sarah Chen and Dr. Kirk. Identified prior-auth pain point â€” 11 FTEs impacted. LOI signed following call.", sentiment="positive", sentiment_score=0.82, contact_name="Sarah Chen", occurred_days_ago=45, days_ago=45),
        i("Meridian Health Systems", type="meeting", source="hubspot", notes="Full demo with clinical ops team (8 attendees). POC kicked off end of meeting. Very strong engagement.", sentiment="positive", sentiment_score=0.91, contact_name="Sarah Chen", occurred_days_ago=28, days_ago=28),
        i("Meridian Health Systems", type="email_sent", source="hubspot", notes="Sent MSA draft via DocuSign. Sarah confirmed receipt. Last email response from champion.", sentiment="neutral", sentiment_score=0.1, contact_name="Sarah Chen", occurred_days_ago=20, days_ago=20),
        i("Meridian Health Systems", type="email_sent", source="agent", notes="Follow-up #1 to Sarah â€” no response. Rep noted 'uncharacteristic silence'.", sentiment="neutral", sentiment_score=0.0, contact_name="Sarah Chen", occurred_days_ago=12, days_ago=12),
        i("Meridian Health Systems", type="email_sent", source="agent", notes="Follow-up #2 to Sarah â€” no response.", sentiment="neutral", sentiment_score=0.0, contact_name="Sarah Chen", occurred_days_ago=8, days_ago=8),

        i("Apex Logistics Partners", type="call", source="hubspot", notes="Initial discovery â€” Maria Santos and James Morrow. Strong fit on NetSuite pain. Budget confirmed at $280K.", sentiment="positive", sentiment_score=0.78, contact_name="Maria Santos", occurred_days_ago=38, days_ago=38),
        i("Apex Logistics Partners", type="email_sent", source="hubspot", notes="Proposal sent with implementation timeline. James acknowledged receipt and said 'evaluating options'.", sentiment="neutral", sentiment_score=0.15, contact_name="James Morrow", occurred_days_ago=14, days_ago=14),
        i("Apex Logistics Partners", type="note", source="hubspot", notes="Rep note: James mentioned 'looking at a few alternatives' on brief call. Did not name Salesforce.", sentiment="negative", sentiment_score=-0.22, contact_name="James Morrow", occurred_days_ago=7, days_ago=7),

        i("Blackstone Capital Group", type="call", source="hubspot", notes="Executive alignment call with CTO David Park and Alexandra Webb. LOI signed. Moving to legal.", sentiment="positive", sentiment_score=0.88, contact_name="David Park", occurred_days_ago=62, days_ago=62),
        i("Blackstone Capital Group", type="meeting", source="hubspot", notes="Security review workshop â€” IT team + solutions engineer. GDPR data residency flagged for the first time by Blackstone's DPO.", sentiment="neutral", sentiment_score=-0.12, contact_name="Alexandra Webb", occurred_days_ago=10, days_ago=10),

        i("Lumina Retail Group", type="call", source="hubspot", notes="Pilot kickoff call â€” Marcus Delgado and 6 team members. High energy. SKU attribution demo well received.", sentiment="positive", sentiment_score=0.85, contact_name="Marcus Delgado", occurred_days_ago=35, days_ago=35),
        i("Lumina Retail Group", type="email_sent", source="hubspot", notes="Sent pilot access credentials and onboarding guide. Marcus acknowledged.", sentiment="neutral", sentiment_score=0.05, contact_name="Marcus Delgado", occurred_days_ago=34, days_ago=34),
        i("Lumina Retail Group", type="email_received", source="hubspot", notes="Marcus: 'Team is struggling with the CSV import flow â€” is there a faster path?' Rep provided manual workaround.", sentiment="negative", sentiment_score=-0.45, contact_name="Marcus Delgado", occurred_days_ago=14, days_ago=14),

        i("SkyBridge Technologies", type="call", source="hubspot", notes="Intro call with Kevin Okafor (VP DevOps). Strong pain identified â€” infra provisioning 3-day cycle blocking dev teams. Highly engaged.", sentiment="positive", sentiment_score=0.87, contact_name="Kevin Okafor", occurred_days_ago=22, days_ago=22),
        i("SkyBridge Technologies", type="email_sent", source="hubspot", notes="Sent Kubernetes-native case study and implementation timeline. Kevin forwarded internally.", sentiment="positive", sentiment_score=0.61, contact_name="Kevin Okafor", occurred_days_ago=18, days_ago=18),

        i("Orion Analytics", type="call", source="hubspot", notes="Discovery call with Priya Nair. Pain validated immediately â€” 12-week analyst backlog. Moved directly to proposal.", sentiment="positive", sentiment_score=0.93, contact_name="Priya Nair", occurred_days_ago=55, days_ago=55),
        i("Orion Analytics", type="meeting", source="hubspot", notes="Technical deep-dive with data engineering team. dbt + Snowflake integration confirmed. SOC2 Type II shared.", sentiment="positive", sentiment_score=0.89, contact_name="Priya Nair", occurred_days_ago=35, days_ago=35),
        i("Orion Analytics", type="call", source="hubspot", notes="Reference call arranged by Priya â€” Orion spoke with 3 existing customers. All positive. MSA sent same day.", sentiment="positive", sentiment_score=0.95, contact_name="Priya Nair", occurred_days_ago=12, days_ago=12),

        i("NovaCure Biotech", type="call", source="hubspot", notes="Discovery call with Dr. Hayashi and Sarah Osei. 21 CFR Part 11 compliance is primary decision criteria. Strong fit.", sentiment="positive", sentiment_score=0.82, contact_name="Dr. Fumio Hayashi", occurred_days_ago=30, days_ago=30),
        i("NovaCure Biotech", type="call", source="gong", notes="Follow-up call â€” Sarah Osei mentioned evaluating Benchling's new module. Rep pivoted to audit trail differentiator.", sentiment="neutral", sentiment_score=-0.05, contact_name="Sarah Osei", occurred_days_ago=7, days_ago=7),

        i("Summit Financial Advisors", type="call", source="hubspot", notes="Initial discovery with Richard Yuen (CCO). SEC reporting pain validated. Budget confirmed. Very structured buyer.", sentiment="positive", sentiment_score=0.79, contact_name="Richard Yuen", occurred_days_ago=40, days_ago=40),
        i("Summit Financial Advisors", type="email_sent", source="hubspot", notes="Sent compliance-focused proposal. Richard acknowledged and shared internally with IT security team.", sentiment="positive", sentiment_score=0.55, contact_name="Richard Yuen", occurred_days_ago=18, days_ago=18),

        i("Cascade Manufacturing", type="call", source="hubspot", notes="Cold outreach call with Brett Holloway (COO). Mentioned Series C and asked about vendor evaluation. Brett open to follow-up.", sentiment="positive", sentiment_score=0.58, contact_name="Brett Holloway", occurred_days_ago=15, days_ago=15),

        i("Verdant Energy Solutions", type="email_received", source="hubspot", notes="Inbound inquiry from Verdant following DOE grant announcement. Expressed interest in grid intelligence platform.", sentiment="positive", sentiment_score=0.72, contact_name="Elena Marchetti", occurred_days_ago=20, days_ago=20),
        i("Verdant Energy Solutions", type="call", source="hubspot", notes="Intro call with Elena Marchetti (CEO). Confirmed DOE grant mandate. Asked for NERC CIP compliance overview. Rep scheduled follow-up.", sentiment="positive", sentiment_score=0.76, contact_name="Elena Marchetti", occurred_days_ago=16, days_ago=16),

        i("Snowflake", type="call", source="hubspot", notes="Intro call with Marcus Holloway (VP RevOps). Immediately validated pain — 400+ reps spending 31% of time on CRM hygiene. Budget approved, needs CFO sign-off.", sentiment="positive", sentiment_score=0.89, contact_name="Marcus Holloway", occurred_days_ago=21, days_ago=21),
        i("Snowflake", type="meeting", source="hubspot", notes="Technical deep-dive with Snowflake IT Security team. SOC2 Type II and GDPR DPA requirements scoped. Legal review started same day.", sentiment="positive", sentiment_score=0.71, contact_name="Marcus Holloway", occurred_days_ago=10, days_ago=10),
        i("Snowflake", type="email_received", source="hubspot", notes="Marcus: 'CFO is asking for a formal ROI model before he'll approve. Can you put something together before July 1?' Rep flagged as urgent.", sentiment="neutral", sentiment_score=0.12, contact_name="Marcus Holloway", occurred_days_ago=3, days_ago=3),

        i("Figma", type="email_received", source="hubspot", notes="Inbound from Kris Rasmussen (VP Sales): 'We're rebuilding our sales stack from scratch post-Adobe. Heard good things about Vantage from a Figma investor. Can we talk?' Very strong signal.", sentiment="positive", sentiment_score=0.94, contact_name="Kris Rasmussen", occurred_days_ago=18, days_ago=18),
        i("Figma", type="call", source="hubspot", notes="Discovery call with Kris Rasmussen. Confirmed: 200 new reps being hired Q3, zero existing AI tooling, budget fully discretionary. Asked for proposal by Friday.", sentiment="positive", sentiment_score=0.92, contact_name="Kris Rasmussen", occurred_days_ago=12, days_ago=12),
        i("Figma", type="email_sent", source="hubspot", notes="Proposal sent with 2-week pilot option and Outreach competitive comparison. Kris acknowledged and shared with his team.", sentiment="positive", sentiment_score=0.68, contact_name="Kris Rasmussen", occurred_days_ago=7, days_ago=7),

        i("Databricks", type="email_received", source="hubspot", notes="Cold inbound from Databricks RevOps analyst: 'Saw your product at SaaStr. We're evaluating AI-native sales tools for 2026. Can you send an overview?' Early but very high value signal.", sentiment="positive", sentiment_score=0.77, contact_name="RevOps Analyst", occurred_days_ago=14, days_ago=14),
        i("Databricks", type="call", source="hubspot", notes="Intro call with Databricks senior RevOps analyst. Confirmed 1,200+ reps globally, 8 sales regions, no unified AI layer. Identified path to Head of RevOps intro.", sentiment="positive", sentiment_score=0.83, contact_name="RevOps Analyst", occurred_days_ago=8, days_ago=8),
    ]
    return rows


# ---------------------------------------------------------------------------
# Main seed runner
# ---------------------------------------------------------------------------
async def seed():
    db_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Check for existing accounts
        result = await session.execute(
            text("SELECT COUNT(*) FROM accounts WHERE workspace_id = :wid"),
            {"wid": WORKSPACE_ID}
        )
        existing = result.scalar()
        if existing and existing > 0:
            print(f"Found {existing} existing accounts. Clearing seed data first...")
            await session.execute(
                text("DELETE FROM accounts WHERE workspace_id = :wid AND hubspot_deal_id LIKE 'hs_deal_%'"),
                {"wid": WORKSPACE_ID}
            )
            await session.commit()

        print("Inserting accounts...")
        for acct in ACCOUNTS:
            await session.execute(text("""
                INSERT INTO accounts (
                    id, workspace_id, hubspot_deal_id, name, stage, deal_amount, close_date,
                    pov_forecast_cat, pov_confidence, health_score, urgency_score, icp_score,
                    state, agent_run_count, created_at, updated_at
                ) VALUES (
                    :id, :workspace_id, :hubspot_deal_id, :name, :stage, :deal_amount, :close_date,
                    :pov_forecast_cat, :pov_confidence, :health_score, :urgency_score, :icp_score,
                    CAST(:state AS JSONB), 1, NOW(), NOW()
                )
            """), {
                "id": acct["id"],
                "workspace_id": WORKSPACE_ID,
                "hubspot_deal_id": acct["hubspot_deal_id"],
                "name": acct["name"],
                "stage": acct["stage"],
                "deal_amount": acct["deal_amount"],
                "close_date": acct["close_date"],
                "pov_forecast_cat": acct["pov_forecast_cat"],
                "pov_confidence": acct["pov_confidence"],
                "health_score": acct["health_score"],
                "urgency_score": acct["urgency_score"],
                "icp_score": acct["icp_score"],
                "state": __import__("json").dumps(acct["state"]),
            })
        await session.commit()

        # Build name â†’ id map
        result = await session.execute(
            text("SELECT name, id FROM accounts WHERE workspace_id = :wid AND hubspot_deal_id LIKE 'hs_deal_%'"),
            {"wid": WORKSPACE_ID}
        )
        accounts_by_name = {row[0]: str(row[1]) for row in result.fetchall()}
        print(f"Inserted {len(accounts_by_name)} accounts: {list(accounts_by_name.keys())}")

        print("Inserting signals...")
        import json
        for sig in make_signals(accounts_by_name):
            await session.execute(text("""
                INSERT INTO signals (
                    id, account_id, workspace_id, type, urgency, urgency_score, detail,
                    source, confidence, gold_sources, gold_resolution, gold_confidence,
                    processed, processed_at, pushed_to_inbox, acknowledged,
                    detected_at, created_at
                ) VALUES (
                    :id, :account_id, :workspace_id, :type, :urgency, :urgency_score, :detail,
                    :source, :confidence, CAST(:gold_sources AS JSONB), :gold_resolution, :gold_confidence,
                    :processed, :processed_at, :pushed_to_inbox, :acknowledged,
                    :detected_at, :created_at
                )
            """), {
                **sig,
                "gold_sources": json.dumps(sig.get("gold_sources", [])),
            })
        await session.commit()
        print(f"Inserted {len(make_signals(accounts_by_name))} signals")

        print("Inserting drafts...")
        for draft in make_drafts(accounts_by_name):
            await session.execute(text("""
                INSERT INTO drafts (
                    id, account_id, workspace_id, type, content, target_contact, subject_line,
                    sources_cited, gold_data_used, status, pushed_to_crm, confidence,
                    created_at, expires_at
                ) VALUES (
                    :id, :account_id, :workspace_id, :type, :content, :target_contact, :subject_line,
                    CAST(:sources_cited AS JSONB), CAST(:gold_data_used AS JSONB), :status, :pushed_to_crm, :confidence,
                    :created_at, :expires_at
                )
            """), {
                **draft,
                "sources_cited": json.dumps(draft.get("sources_cited", [])),
                "gold_data_used": json.dumps(draft.get("gold_data_used", {})),
            })
        await session.commit()
        print(f"Inserted {len(make_drafts(accounts_by_name))} drafts")

        print("Inserting interactions...")
        for intr in make_interactions(accounts_by_name):
            await session.execute(text("""
                INSERT INTO interactions (
                    id, account_id, workspace_id, type, source, notes, sentiment,
                    sentiment_score, contact_name, is_training_signal, occurred_at, created_at
                ) VALUES (
                    :id, :account_id, :workspace_id, :type, :source, :notes, :sentiment,
                    :sentiment_score, :contact_name, :is_training_signal, :occurred_at, :created_at
                )
            """), intr)
        await session.commit()
        print(f"Inserted {len(make_interactions(accounts_by_name))} interactions")

    await engine.dispose()
    print("\nSeed complete. Summary:")
    print(f"  Accounts: {len(ACCOUNTS)}")
    print(f"  Signals:  {len(make_signals({n: '' for n in [a['name'] for a in ACCOUNTS]}))}")
    print(f"  Drafts:   {len(make_drafts({n: '' for n in [a['name'] for a in ACCOUNTS]}))}")
    print(f"  Interactions: {len(make_interactions({n: '' for n in [a['name'] for a in ACCOUNTS]}))}")
    print("\nAccounts seeded (by urgency):")
    for a in sorted(ACCOUNTS, key=lambda x: -x["urgency_score"]):
        print(f"  {a['urgency_score']:.2f}  {a['name']:35s}  ${float(a['deal_amount']):>10,.0f}  {a['stage']:12s}  {a['pov_forecast_cat']}")


if __name__ == "__main__":
    asyncio.run(seed())


