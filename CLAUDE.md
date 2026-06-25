# Vantage — CLAUDE.md
**Last updated:** 2026-06-25  
**Sprint:** 3 — COMPLETE ✅ All sprints shipped  
**Mode:** HACKATHON (multi-tenant, self-serve onboarding)

## What This Is
Per-Account Agent Platform. One AI agent per HubSpot deal. Monitors signals 24/7, assembles account context, generates drafted emails + meeting briefs nightly. Multi-tenant and self-serve. Any company can sign up and run agents from day one via the onboarding wizard.

## Project Root
`C:\ClaudeProjects\Products\VantageHackathon\`

## Monorepo Structure
```
apps/web/          → Next.js 15 App Router frontend (Vercel)
apps/api/          → Python FastAPI backend (Azure Container Apps)
apps/api/alembic/  → DB migrations (initial schema at versions/20260526_0001_)
packages/mcp-server/ → TypeScript MCP server (npm publishable)
infrastructure/    → Docker Compose + init-db.sql
docs/              → PRD, architecture, security, decisions
_bmad/             → Agent working files (stories, sprint board, live feed)
```

## Build Status (All Sprints)

### Backend — COMPLETE ✅
```
app/config.py                    ✅ All env vars + defaults
app/db/database.py               ✅ Async SQLAlchemy
app/models/workspace.py          ✅ Workspace + WorkspaceUser
app/models/account.py            ✅ Account + Signal + Draft + Interaction + AgentRun + AuditLog + ApiKey
app/agents/base.py               ✅ BaseAgent + all Pydantic output schemas
app/agents/researcher.py         ✅ ResearcherAgent (Haiku 4.5)
app/agents/risk_scanner.py       ✅ RiskScannerAgent (Haiku 4.5) — POV + health
app/agents/grounding.py          ✅ GroundingAgent (Haiku 4.5) — GA from day 1
app/agents/prioritiser.py        ✅ PrioritiserAgent (Sonnet 4.6)
app/agents/drafter.py            ✅ DrafterAgent (Sonnet 4.6) — cited facts
app/agents/orchestrator.py       ✅ Full pipeline, Redis lock, episodic memory
app/integrations/hubspot.py      ✅ HubSpot API v3 + OAuth + HMAC verification
app/integrations/perplexity.py   ✅ sonar-pro research + Q&A
app/integrations/anthropic_embed.py ✅ VoyageAI 1536-dim embeddings
app/middleware/auth.py           ✅ WorkOS JWT + API key auth
app/main.py                      ✅ FastAPI factory + CORS + routers
app/routers/accounts.py          ✅ List/state/pov/actions/search/feedback/batch
app/routers/workspace.py         ✅ Settings/team/API keys/HubSpot OAuth
app/routers/drafts.py            ✅ Review/approve/decline/push-to-HubSpot
app/routers/signals.py           ✅ List/get/acknowledge
app/routers/agent.py             ✅ SSE streaming chat + threads
app/routers/auth.py              ✅ WorkOS login/callback + HubSpot callback
app/routers/webhooks.py          ✅ HubSpot HMAC webhook + Service Bus queuing
app/services/account_service.py  ✅ list/get/semantic_search/batch
app/services/nightly_worker.py   ✅ Full pipeline orchestration + cost tracking
app/services/assistant.py        ✅ Streaming chat + meeting brief + threads
app/services/hubspot_sync.py     ✅ Full deal sync with delta detection
alembic/versions/0001_initial    ✅ All tables + pgvector + seed workspace
```

### Frontend — SPRINT 2 COMPLETE ✅
```
src/app/layout.tsx               ✅ Root layout + Providers
src/app/page.tsx                 ✅ Root redirect
src/app/(app)/layout.tsx         ✅ App shell (sidebar + topbar)
src/app/(app)/inbox/page.tsx     ✅ Agent Inbox + Morning Brief + Suspense
src/app/(app)/watchtower/page.tsx ✅ Signal clusters + radar overlay + War Room links
src/app/(app)/assistant/page.tsx  ✅ SSE chat + pre-seeded ?seed=true + Suspense
src/app/(app)/analytics/page.tsx  ✅ DAR trend + cost dashboard + signal dist + rep table
src/app/(app)/settings/page.tsx   ✅ Workspace + team + integrations + API keys
src/app/(app)/account/[id]/page.tsx ✅ Account War Room (3-col: signals/timeline | POV/drafts/actions | inline chat)
src/app/auth/login/page.tsx      ✅ WorkOS sign-in
src/app/auth/error/page.tsx      ✅ Auth error handler with code-based messages
src/components/layout/sidebar.tsx ✅ 4-tab nav + pending badge + user profile footer
src/components/layout/topbar.tsx  ✅ Semantic search + Run Agents
src/components/inbox/account-card.tsx ✅ Urgency bar + Ask Agent + War Room links
src/components/inbox/draft-review-panel.tsx ✅ Full review flow (approve/edit/decline/push)
src/components/inbox/morning-brief.tsx ✅ Daily intelligence summary (top 3 + one-action)
src/components/inbox/search-results.tsx ✅ Semantic search results
src/components/audit/audit-panel.tsx ✅ Gold Data audit trail (our differentiator)
src/components/ui/skeleton.tsx   ✅
src/components/providers.tsx     ✅ TanStack Query
src/lib/api.ts                   ✅ All API methods + SSE streaming + Analytics types
src/lib/utils.ts                 ✅ cn + formatters
src/middleware.ts                ✅ Session cookie auth guard + onboarding redirect
src/app/onboarding/layout.tsx   ✅ Centered layout (no sidebar)
src/app/onboarding/page.tsx     ✅ 4-step wizard: Company → Product → Integrations → Done
```

### MCP Server — COMPLETE ✅
```
packages/mcp-server/src/index.ts ✅ 6 tools (get_account_context, get_next_actions,
                                          get_pov, get_draft, log_interaction, search_accounts)
                                          stdio transport (Claude Desktop)
```

### Infrastructure — COMPLETE ✅
```
infrastructure/docker-compose.yml  ✅ PostgreSQL 16 + pgvector + Redis + API
infrastructure/init-db.sql         ✅ Extensions + app role + audit_log permissions
infrastructure/azure/main.bicep    ✅ Bicep IaC: ACR + Container Apps + Nightly Job
infrastructure/azure/parameters.prod.json ✅ Prod parameter template
apps/api/Dockerfile                ✅ Multi-stage production image (builder → runtime, non-root uid 1001)
apps/api/Dockerfile.dev            ✅ Dev image
apps/api/nightly_job.py            ✅ Azure Container Job entrypoint (SIGTERM-safe)
apps/api/alembic.ini               ✅ Alembic config
apps/api/alembic/env.py            ✅ Async migration environment
apps/api/.env.example              ✅
apps/web/.env.example              ✅
.github/workflows/deploy-api.yml   ✅ test → build (ACR) → deploy (az containerapp update)
.github/workflows/deploy-web.yml   ✅ tsc + lint → Vercel deploy
apps/web/playwright.config.ts      ✅ Auth setup project + chromium project
apps/web/tests/e2e/auth.setup.ts   ✅ WorkOS auth (UI flow + bypass mode)
apps/web/tests/e2e/inbox.spec.ts   ✅ Inbox: cards, Morning Brief, draft badge, War Room link
apps/web/tests/e2e/draft-review.spec.ts ✅ Approve/edit/decline/push flows
apps/web/tests/e2e/assistant.spec.ts ✅ Pre-seeded chat, SSE streaming, citations
apps/web/tests/e2e/war-room.spec.ts ✅ 3-col layout, signals, chat auto-seed, tabs
apps/web/tests/e2e/analytics.spec.ts ✅ KPI cards, DAR chart (pure SVG), 30/60/90d toggle
```

### Sprint 3 Integrations — COMPLETE ✅
```
apps/api/app/integrations/fireflies.py ✅ GraphQL client + webhook HMAC + transcript→interaction
apps/api/app/integrations/teams.py     ✅ Adaptive Cards v1.5 (signal alerts + morning brief + draft ready)
apps/api/app/routers/fireflies_webhook.py ✅ POST /webhooks/fireflies — fuzzy account match + Interaction insert
apps/api/app/config.py                 ✅ Fireflies + Teams settings added
apps/api/app/services/nightly_worker.py ✅ Fireflies ingest + Teams signal alerts + morning brief
```

### Chrome Extension — COMPLETE ✅
```
packages/chrome-extension/manifest.json          ✅ MV3, storage + activeTab + scripting
packages/chrome-extension/src/background.ts      ✅ Service worker: deal detection, account lookup
packages/chrome-extension/src/content-hubspot.ts ✅ Fixed 320px sidebar, urgency/health HUD
packages/chrome-extension/src/content-linkedin.ts ✅ Company extraction, floating badge, sidebar
packages/chrome-extension/src/popup.html         ✅ API URL + key settings
packages/chrome-extension/scripts/bundle.js      ✅ esbuild: 4 entry points → dist/
```

## Key Tech
- Frontend: Next.js 15 + TanStack Query v5 + Zod + Radix UI + Tailwind
- Backend: Python 3.12 + FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic
- DB: PostgreSQL 16 + pgvector 1536-dim (voyage-3-lite) + Redis
- Queue: Azure Service Bus
- AI: Claude Haiku 4.5 (bulk) + Claude Sonnet 4.6 (quality/chat)
- Embeddings: VoyageAI voyage-3-lite (1536-dim)
- Search: Perplexity sonar-pro
- Auth: WorkOS (Google SSO)
- CRM: HubSpot API v3

## Running Locally
```bash
# 1. Start DB + Redis
cd infrastructure && docker compose up -d

# 2. Run migrations
cd apps/api
cp .env.example .env  # fill in your keys
pip install -r requirements.txt
alembic upgrade head

# 3. Start API
uvicorn app.main:app --reload --port 8000
# Docs: http://localhost:8000/docs (debug mode only)

# 4. Start Frontend
cd apps/web
cp .env.example .env.local
npm install
npm run dev  # http://localhost:3000

# 5. MCP Server (optional — for Claude Desktop integration)
cd packages/mcp-server
npm install && npm run build
# Add to Claude Desktop config:
# {"mcpServers": {"vantage": {"command": "node", "args": ["dist/index.js"],
#   "env": {"VANTAGE_API_KEY": "vnt_live_...", "VANTAGE_API_URL": "http://localhost:8000"}}}}
```

## Active Sprint
All Sprints 1-3 COMPLETE ✅

## Ready to Deploy (Diego's Checklist)
Before running `az deployment group create`:
1. Create Azure Container Registry + resource group (see `infrastructure/azure/main.bicep`)
2. Set GitHub Actions secrets: `ACR_LOGIN_SERVER`, `ACR_USERNAME`, `ACR_PASSWORD`,
   `AZURE_CREDENTIALS`, `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`
3. Set Vercel project env vars: `NEXT_PUBLIC_API_URL` pointing to Container App FQDN
4. Register Fireflies webhook: Fireflies.ai → Settings → Webhooks →
   `POST https://api.vantage.ai/webhooks/fireflies`
5. Create Teams incoming webhook in the sales channel, copy URL to `TEAMS_WEBHOOK_URL`
6. Load Chrome Extension: chrome://extensions → Developer mode → Load unpacked → `packages/chrome-extension/dist/`

## Deferred (Sprint 4+)
- "Smart Fields" — AI suggests HubSpot field updates from signal context
- Embedded HubSpot trigger buttons (1-click Run Agent from inside HubSpot sidebar)
- Training signal loop UI — declined draft reasons visible in Analytics
- Workspace switcher UI (schema + creation ready; multi-workspace dropdown in sidebar not yet built)
- Mobile-responsive Inbox (currently desktop-first)

## North Star KPI
Draft Acceptance Rate (DAR) > 60% by Week 8

## Key Decisions
- ADR-001: Azure Service Bus over Temporal (simpler at MVP scale)
- ADR-002: pgvector over Pinecone (same DB, no extra vendor)
- ADR-003: Gold Data Layer always visible (Audit Panel — differentiator vs Actively AI)
- ADR-004: Multi-tenant by default — any company can onboard via the self-serve wizard; schema supports unlimited workspaces
- ADR-005: VoyageAI voyage-3-lite for embeddings (1536-dim, matches OpenAI dim, no dependency on OpenAI)

## Differentiators vs Actively AI
1. **Grounding Agent GA** — Actively has it in beta behind feature flag `has_grounding_agent_access`. Ours is GA from day 1.
2. **Audit Panel** — Our Gold Data is fully visible. Every fact shows source, confidence, conflict resolution. Actively's is opaque.
3. **Semantic search** — `POST /v1/accounts/search` — Actively doesn't have this in their public API.
4. **pgvector** — No Pinecone vendor. Semantic search lives in the same DB. Zero extra latency.
5. **Self-serve HubSpot OAuth** — Connect in 30 seconds. No Salesforce or Gong required to start.
6. **Training signal loop** — Declined drafts with reason codes improve future agent output. Documented feedback path.
7. **MCP Server** — Works natively in Claude Desktop. Reps can query account context without opening the app.
