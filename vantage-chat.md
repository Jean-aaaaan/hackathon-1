# Vantage Chat — Hackathon Prep Reference
*Saved 2026-06-26, updated 2026-06-27 (afternoon). Say "read vantage-chat.md" in any future session.*

---

## Project at a glance

| | |
|---|---|
| **Path** | `C:\Users\gohje\vantage-hackathon\` (canonical — NOT `hackathon 1\`) |
| **Product** | Per-deal AI agent for HubSpot — monitors signals, builds account context, drafts emails/briefs nightly |
| **Frontend** | `http://localhost:3000` — Today, Watchtower, Deal Book, Forecast, Intelligence, Analytics, Assistant |
| **Backend** | `http://localhost:8000` — 6-agent pipeline, HubSpot/Exa/Fireflies integrations |

### Real agents (not mocked)
Pipeline in `app/agents/orchestrator.py` → unified LLM layer `app/integrations/llm.py` (OpenAI for hackathon; Anthropic optional).

1. **Researcher** (Haiku) — extract intel from signals + context  
2. **Risk Scanner** (Haiku) — MEDDPICC, health, forecast POV  
3. **Grounding** (Haiku) — verify facts, Gold Data audit trail  
4. **Prioritiser** (Sonnet) — rank next actions  
5. **Drafter** (Sonnet) — cited email drafts  
6. **State Writer** (code) — merge → `account.state` in PostgreSQL  

Cost ~**$0.17/deal/run** (~3 min). Trigger: top bar **Run Agents** or War Room **Run Agent** → `POST /v1/accounts/batch-refresh`.

### Demo data (seeded)
- `apps/api/scripts/seed_deals.py` — 10 deals, drafts, signals, interactions  
- `apps/api/scripts/fix_meddpicc_path.py` — MEDDPICC float scores + `detail` text + `activity_summary`  
- Fake HubSpot IDs: `hs_deal_*` (API calls fail quietly; agents use seeded state + interactions)

**Reset anytime:**
```bash
cd apps/api
python scripts/seed_deals.py
python scripts/fix_meddpicc_path.py
```

---

## Agents vs seeded data

| Running agents changes | Stays the same |
|------------------------|----------------|
| Full `account.state` (narrative, MEDDPICC, POV) | Deal name, stage, amount |
| `health_score`, `urgency_score`, forecast cols | Seeded `interactions` table (agent input) |
| Pending drafts → superseded; new drafts added | — |
| New signals inserted | — |

**Demo framing:** Seeded deals = starting line. Live run = proof. One deal only (Meridian), not "Sweep top 20."

---

## Live demo script

1. Seed + fix MEDDPICC  
2. Open **Meridian** War Room → **Intelligence** — show BEFORE  
3. Click **Run Agent** — narrate 6 stages (~30–90s)  
4. Show AFTER: new draft, updated story/MEDDPICC, approve or decline  
5. Optional: **Analytics** (LLM cost), **Assistant** ("why is champion 0%?")  
6. Re-seed after practice runs  

**Requires:** `OPENAI_API_KEY` + `LLM_PROVIDER=openai` + `EXA_API_KEY` in `apps/api/.env`

---

## Session checkpoint (2026-06-27 afternoon)

### 1. Exa integration (replaces Perplexity)
- `apps/api/app/integrations/exa.py` — semantic search client (`research_account`, `check_people_signals`)
- `nightly_worker.py` — Exa only for web research + stakeholder people signals
- `EXA_API_KEY` in `apps/api/.env` (not committed)

### 2. OpenAI switch
- `LLM_PROVIDER=openai` — gpt-4o-mini (bulk) / gpt-4o (quality) via `llm.py`

### 3. Zinc design system
- `globals.css` — zinc-only palette (red = critical only)
- War Room `account/[id]/page.tsx` — brand/gray cleanup
- Today `inbox/page.tsx` — MEDDPICC, risk badges → zinc
- `morning-brief.tsx` — fixed invisible buttons, top **3** accounts only
- `onboarding/` — light theme (`bg-zinc-50`)

### 4. Inbox "deals missing" fix
- Removed auto-switch to Drafts tab (5/11 deals had no drafts and were hidden)
- Morning Brief shows top 3, not all 11

### Current state
| Item | Value |
|------|-------|
| Git | `471d144` on `main` — `Jean-aaaaan/hackathon-1` |
| Deals | 11 seeded |
| Drafts | 19 pending |
| Agent | ~$0.17/run, ~3 min verified |

---

## Dogfood test (2026-06-27) — CHECKPOINT

Expert AE review. Full detail in `.cursor/rules/vantage.mdc` § Dogfood checkpoint.

**Scores:** expert 7/10 · first-time 5/10 · judge demo 8/10 (if you follow the script)

**Works:** Today split panel, draft triage + keyboard shortcuts, War Room depth, Watchtower clusters, ⌘K, Forecast overrides.

**P0 bugs / UX:**
| # | Issue | File hint |
|---|-------|-----------|
| 1 | `4d` on Today cards = drafts not days | `inbox/page.tsx` ~L120 |
| 2 | Queue urgency-first when 19 drafts waiting | default Drafts tab or banner |
| 3 | Run Agents: "queued" toast, no done signal | navbar sweep handler |
| 4 | Help widget describes old UI | `help-assistant.tsx` |
| 5 | MorningBrief not mounted | `morning-brief.tsx` → wire into Today |
| 6 | Assistant not in desktop nav | `navbar.tsx` |

**Top 5 fixes (priority order):** drafts label · drafts-first default · agent completion toast · MorningBrief · nav simplify + Assistant in bar.

**Demo script (dogfood-approved):**
1. Today → Drafts → Meridian Ops → approve (`E`)
2. War Room → MEDDPICC + signals
3. Watchtower → clusters
4. Assistant → portfolio question
5. Live Run Agent on Meridian Ops only

**API audit (same day):** 45/45 GETs OK; fixed `agent_runs.started_at` SQL bug in analytics/overview, cost-trend, workspace/usage.

---

## UX work (this chat)

**Today** (`apps/web/src/app/(app)/inbox/page.tsx`):  
`WarRoomHero` when selected deal has zero pending drafts — full War Room preview, **Open War Room** → `/account/{id}?center=intel`, MEDDPICC + deal story. Left panel narrows when `warRoomFocus`.

---

## Top 10 judge questions

1. Why a company, not a feature? (vs Actively, Gong, HubSpot AI)  
2. What exactly happens on Run Agent? (6 stages, models, DB, failures)  
3. Why would reps use this vs ignoring AI tasks? (60-second morning workflow)  
4. Multi-tenant isolation? (`workspace_id` on every query)  
5. What do agents reason over in the demo? (seeded interactions + state → live LLM)  
6. Monthly burn at 400 deals? (~$0.22 × 400 × 30 ≈ $2.6K/mo LLM; vs 1 saved AE hour)  
7. Prove one citation was grounded? (Audit Panel, `sources_cited`, zero-signal gate)  
8. What's real vs Simulate/Sample theater? (own it)  
9. What changes after decline with reason? (episodic memory → Prioritiser)  
10. 30s pitch to CRO with Gong + Clari who hates AI tools  

---

## vs Actively AI — quick answers

**Position:** Actively validated the market ($68M, 23–54% pipeline lift, FDE model). We attack **deployment + trust**, not the category.

| Actively | Vantage wedge |
|----------|---------------|
| Forward-deployed engineers | Self-serve, <24h to first inbox |
| Gold Data opaque | Audit Panel — source, confidence, conflicts |
| Grounding in beta (`has_grounding_agent_access`) | Grounding GA every run |
| US-focused | Multi-region from day 1 |
| No public pricing | Self-serve tier |

**Per-account agent ≠ cron:** compounding ASO, decline feedback, Gold Data, forecast history, episodic memory.

**Metrics honesty:** No 23–54% claim yet. North star = **DAR** (Draft Acceptance Rate). 90-day target: >50% DAR, >90% nightly coverage, 1 saved deal per design partner.

**30s pitch:**  
*"Actively proved reps pay for AI that works while they sleep — but you need FDEs and months to onboard. Vantage is the same per-deal architecture, self-serve in a day, every fact auditable. They validated the market; we make it deployable for teams that will never get an FDE."*

**HubSpot native AI:** Record-level summaries ≠ cross-source ASO (HubSpot + email + calls + web + memory).

---

## Known gaps (audit + dogfood 2026-06-27)

**Fixed (commits `13fc02d`, `471d144`):** drafts label · drafts-first default · agent completion toast · MorningBrief wired · Assistant in nav · zinc UI pass · inbox shows all deals · morning brief top 3

**Still open:**
- MEDDPICC default-hidden (Intelligence tab; Act is default)  
- `HealthBadge` uses `urgencyScore` not `health_score`  
- Intelligence overlaps Watchtower/Analytics — nav sprawl  
- Approve on Today ≠ Send (Outlook only in War Room)  
- Docker: rebuild API image so `openai` is baked in; WorkOS v8 breaks `/auth/login` (dev bypass OK)

---

## Key files

| File | Role |
|------|------|
| `apps/web/src/app/(app)/inbox/page.tsx` | Today + WarRoomHero |
| `apps/web/src/app/(app)/account/[id]/page.tsx` | War Room |
| `apps/api/app/agents/orchestrator.py` | 6-agent pipeline |
| `apps/api/app/services/nightly_worker.py` | Run orchestration + DB writes |
| `apps/api/app/integrations/exa.py` | Exa semantic search (replaces Perplexity) |
| `apps/api/app/integrations/llm.py` | Unified LLM layer (OpenAI) |
| `apps/api/scripts/seed_deals.py` | Demo seed |
| `apps/api/scripts/fix_meddpicc_path.py` | MEDDPICC fix |