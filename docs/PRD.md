# Vantage — Product Requirements Document
**Version:** 1.0  
**Date:** 2026-05-26  
**PM:** John  
**Mode:** ENTERPRISE  
**Competitive basis:** Actively AI reverse engineering (MASTER-BUILD-REPORT-2026-05-26)

---

## 1. Problem Statement

Enterprise sales teams manage 40-100 accounts per rep across 5+ disconnected tools. Context assembly takes 2+ hours/day. Champions go dark undetected. 70% of accounts run on autopilot. Revenue is left on the table — not from lack of effort, but from lack of intelligence at the account level.

**Actively AI** (competitor, $68M raised, ~$250M valuation) has proven product-market fit with 6 confirmed enterprise customers and quantified outcomes: 23-54% pipeline improvements, 2x productivity gains. The market is validated. Their structural weakness is their deployment model (forward-deployed engineers, no self-serve, US-only). That is our wedge.

---

## 2. Product Vision

**One persistent AI agent per account. Works while you sleep. Ships self-serve.**

---

## 3. Target ICP

**Primary:** Head of Sales / VP Sales at B2B SaaS companies
- Company size: 200–5,000 employees
- Sales org: 20–200 reps
- CRM: HubSpot (MVP), Salesforce (v2)
- Call intelligence: Gong (optional for MVP)
- Deal volume per rep: 30–80 accounts
- Pain: Context fragmentation, missed signals, rep productivity ceiling

**Secondary (Watchtower buyer):** Chief Revenue Officer, Sales Manager
- Needs: Portfolio visibility, deal risk early warning, forecast accuracy

**Buyer geography:** Global from day 1 (MENA, APAC, AU, EU, US)

---

## 4. North Star KPI

**Draft Acceptance Rate (DAR)** — percentage of agent-generated drafts that reps approve without modification.

Target milestones:
- Week 4: >40% DAR (agent is directionally right)
- Week 8: >60% DAR (agent understands the customer's motion)
- Week 16: >75% DAR (agent is operating at near-rep quality)

Supporting KPIs:
- Time-to-first-value: <24 hours from HubSpot connect to first Inbox populated
- Account coverage: % of active deals processed by agent nightly
- Signal detection rate: # of signals surfaced per account per week
- Rep time saved: estimated hours/week recovered (self-reported via onboarding survey)

---

## 5. MVP Scope (10 Weeks)

### What's IN

| Module | Feature | Priority |
|--------|---------|---------|
| **Agent Inbox** | Morning queue of agent-completed work per account | P0 |
| **Agent Inbox** | Draft review + one-click approve → HubSpot | P0 |
| **Agent Inbox** | Decline with reason → episodic memory training signal | P0 |
| **Watchtower** | Account health grid (all accounts, colour-coded) | P0 |
| **Watchtower** | Risk feed (champion dark, competitive mention, deal slip) | P0 |
| **Watchtower** | Aggregate forecast view (POV vs CRM delta) | P1 |
| **Assistant** | Chat grounded strictly on account ASO | P0 |
| **Assistant** | Source citations + Audit Panel (our differentiator) | P0 |
| **Assistant** | Persistent chat history per account | P1 |
| **API Platform** | REST API with API key auth | P1 |
| **API Platform** | Scalar documentation (AI-searchable) | P1 |
| **MCP Server** | 5 tools: get_context, get_actions, get_pov, get_draft, log_interaction | P1 |
| **MCP Server** | search_accounts (semantic search — differentiator) | P1 |
| **Auth** | WorkOS (Google SSO minimum, SAML for enterprise) | P0 |
| **Onboarding** | HubSpot OAuth → workspace created → nightly job scheduled | P0 |
| **Onboarding** | <24h time-to-first-value (self-serve, no sales call) | P0 |
| **Integrations** | HubSpot (full sync + webhooks) | P0 |
| **Integrations** | Gong (call transcript + competitive mention detection) | P1 |
| **Integrations** | Perplexity sonar-pro (news enrichment per account) | P1 |

### What's OUT (MVP)

| Feature | When |
|---------|------|
| Salesforce integration | v2 (Sprint 11-12) |
| Browserbase LinkedIn signals | v2 (once stable) |
| Training Gym (agent self-improvement) | v3 |
| Territory management | v3 |
| Campaign builder | v3 |
| Fine-tuned model | v4 (when 10K+ approved/rejected drafts exist) |
| Cross-customer analytics | v3 |

---

## 6. User Stories (Epic Level)

### Epic 1: Core Infrastructure (Weeks 1-2)
- **E1-S1:** As a workspace admin, I can connect my HubSpot account via OAuth and have all my active deals imported automatically in <5 minutes
- **E1-S2:** As the system, I run the nightly agent pipeline (Researcher → Risk Scanner → Grounding → Prioritiser → Drafter → State Writer) for every account in a workspace
- **E1-S3:** As the system, I process urgent HubSpot webhook events (deal stage changes) in real-time and trigger immediate risk scans when threshold crossed
- **E1-S4:** As a developer, I can query `GET /v1/accounts/{id}/state` and receive the full Account State Object JSON

### Epic 2: Agent Inbox (Weeks 3-4)
- **E2-S1:** As a sales rep, I see my accounts sorted by urgency score with health indicators on login
- **E2-S2:** As a sales rep, I can expand any account card to see the agent-drafted email, meeting brief, and recommended action with cited reason
- **E2-S3:** As a sales rep, I can approve a draft (optionally editing inline) and have it appear as a draft in HubSpot
- **E2-S4:** As a sales rep, I can decline a draft with a reason, and that reason trains the agent to improve future output

### Epic 3: Watchtower (Weeks 5-6)
- **E3-S1:** As a sales manager, I see a real-time health grid of all accounts colour-coded by health score
- **E3-S2:** As a sales manager, I see a chronological risk feed of agent-detected events (champion dark, competitive mention, deal slip)
- **E3-S3:** As a sales manager, I receive Slack notifications when an account crosses an urgency threshold >0.85
- **E3-S4:** As a sales manager, I can click into any account to see the full ASO + add a coaching note visible to the assigned rep

### Epic 4: Assistant (Weeks 5-6)
- **E4-S1:** As a sales rep, I can open the Assistant, select an account, and ask any question — the response is grounded strictly on the ASO for that account
- **E4-S2:** As a sales rep, every fact in the Assistant response includes a source citation (HubSpot deal ID, Gong call timestamp, signal detection time)
- **E4-S3:** As a sales rep, I can click the Audit Panel on any fact to see the source, confidence score, and conflict resolution history
- **E4-S4:** As a sales rep, my chat history with any account persists across sessions and updates the account's episodic memory

### Epic 5: API + MCP (Weeks 7-8)
- **E5-S1:** As a developer, I can create an API key, call `GET /v1/accounts/{id}/state`, and receive the full ASO
- **E5-S2:** As a developer, I can `POST /v1/accounts/{id}/feedback` to update the account's episodic memory from my own tool
- **E5-S3:** As a Claude Desktop user, I can install the Vantage MCP server and ask "prep me for my Acme Corp call" to get grounded account context
- **E5-S4:** As a Claude Desktop user, I can `search_accounts` semantically across my entire workspace

### Epic 6: Scale and Intelligence (Weeks 9-10)
- **E6-S1:** As a rep, I can search across all accounts semantically ("find accounts with competitive risk this quarter")
- **E6-S2:** As an admin, I can see LLM spend per month, account coverage rate, and draft acceptance rate in a usage dashboard
- **E6-S3:** As the system, Perplexity news enrichment runs nightly per account and surfaces funding/leadership/product signals
- **E6-S4:** As the system, the agent feedback loop processes rep corrections into episodic memory and measurably improves DAR sprint-over-sprint

---

## 7. Success Criteria (Definition of Done — Product Level)

1. Self-serve onboarding: HubSpot connected → first Inbox populated in <24 hours, no sales call required
2. Draft Acceptance Rate >60% by Week 8
3. Agent processes 100% of active accounts nightly
4. Zero-downtime nightly pipeline for workspaces with up to 500 accounts
5. SOC2 Type II audit evidence package current (Carol owns)
6. API docs live and AI-searchable (Scalar)
7. MCP server published on npm
8. All E2E user flows pass Stacey's button-by-button test (zero broken flows)
9. <2s response time for Assistant chat (Responder fast path)
10. <50ms account state retrieval from Redis cache

---

## 8. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| HubSpot API rate limits (150 req/10s) | Medium | High | Batch sync, exponential backoff, webhook-first |
| Perplexity API cost at scale | Medium | Medium | Cache results 24h; deduplicate queries across similar accounts |
| LLM hallucination in drafts | High | Medium | Grounding Agent (GA from day 1, not beta) verifies every fact |
| Azure Service Bus reliability | Low | High | DLQ + retry with exponential backoff; nightly cron has 4h window |
| WorkOS pricing at scale | Low | Low | $49/org/month — acceptable at $2K+ pricing |
| pgvector performance at 50K+ accounts | Medium | Medium | ivfflat index + proactive `VACUUM ANALYZE` |

---

## 9. Product KPIs Dashboard

```
North Star:    Draft Acceptance Rate (DAR)     Target: >60% by Week 8
Acquisition:   HubSpot connects per week       Target: 3+ by Week 6
Activation:    % workspaces with >5 approved   Target: >70% within 7 days
Retention:     Weekly active reps              Target: >80% week-2 retention
Revenue:       MRR                             Target: $10K by Week 12
Health:        Nightly pipeline success rate   Target: >99%
Health:        Assistant p95 latency           Target: <2s
Health:        API p99 latency                 Target: <500ms
```

---

*PRD v1.0 — approved for architecture phase. John.*
