# Vantage

Per-account AI agent platform for enterprise sales teams. One agent per HubSpot deal — monitors signals, assembles account context, and delivers drafted emails, meeting briefs, and risk alerts before the rep opens their laptop.

**Repo:** [github.com/Jean-aaaaan/hackathon-1](https://github.com/Jean-aaaaan/hackathon-1)

---

## What it does

- **Today (Inbox)** — triage urgent deals, review agent drafts, approve or decline with keyboard shortcuts
- **War Room** — deep account view: MEDDPICC, signals, timeline, POV, inline chat
- **Watchtower** — portfolio-level signal clusters and risk radar
- **Assistant** — streaming chat grounded on your deal data, with source citations
- **Forecast & Analytics** — AI forecast categories, DAR trends, agent cost tracking

Every fact the agent cites is traceable to the **Gold Data Layer** — HubSpot, Fireflies, Exa, and more.

---

## Architecture

```
┌─────────────┐     SSE / REST      ┌──────────────────────────────────┐
│  Next.js 15 │ ◄──────────────────► │  FastAPI (Python 3.12)           │
│  apps/web   │                      │  apps/api                        │
└─────────────┘                      │                                  │
                                     │  6-agent pipeline (orchestrator) │
                                     │  Assistant · HubSpot · Exa       │
                                     └──────────┬───────────┬───────────┘
                                                │           │
                                     ┌──────────▼──┐  ┌─────▼─────┐
                                     │ PostgreSQL 16 │  │   Redis   │
                                     │  + pgvector   │  │  sessions │
                                     └───────────────┘  └───────────┘
```

### Agent pipeline

Runs per account via **Run Agent** or nightly sweep (~$0.17/run, ~3 min):

| Agent | Model | Role |
|-------|-------|------|
| Researcher | gpt-4o-mini | Extract intel from signals + context |
| Risk Scanner | gpt-4o-mini | MEDDPICC, health score, forecast POV |
| Grounding | gpt-4o-mini | Verify facts, Gold Data audit trail |
| Prioritiser | gpt-4o | Rank next actions |
| Drafter | gpt-4o | Cited email drafts |
| State Writer | — | Merge results → `account.state` in PostgreSQL |

Web research uses **Exa** (semantic search). Embeddings use **VoyageAI** (`voyage-3-lite`). LLM provider is configurable via `LLM_PROVIDER` (`openai` or `anthropic`).

---

## Tech stack

| Layer | Stack |
|-------|-------|
| Frontend | Next.js 15, React 19, TanStack Query, Tailwind, Radix UI |
| Backend | FastAPI, Pydantic v2, SQLAlchemy 2, Alembic |
| Database | PostgreSQL 16 + pgvector |
| Cache | Redis 7 |
| Auth | WorkOS (Google SSO) |
| CRM | HubSpot API v3 |
| AI | OpenAI gpt-4o / gpt-4o-mini (hackathon default) |
| Research | Exa API |
| Deploy | Docker Compose (local), Azure Container Apps + Vercel (prod) |

---

## Quick start

### Prerequisites

- Docker Desktop
- Node.js 20+
- Python 3.12+ (only if running the API outside Docker)

### 1. Clone and configure

```bash
git clone https://github.com/Jean-aaaaan/hackathon-1.git
cd hackathon-1

# API env
cp apps/api/.env.example apps/api/.env
# Required for agents + assistant:
#   OPENAI_API_KEY=sk-...
#   LLM_PROVIDER=openai
#   EXA_API_KEY=...
# For local dev without WorkOS login:
#   DEBUG=true
#   DEBUG_BYPASS_TOKEN=<generate with: python -c "import secrets; print(secrets.token_hex(32))">

# Web env
cp apps/web/.env.example apps/web/.env.local
# Set NEXT_PUBLIC_API_URL=http://localhost:8000
# Set NEXT_PUBLIC_DEV_BYPASS_TOKEN to match DEBUG_BYPASS_TOKEN above
```

### 2. Start infrastructure

```bash
cd infrastructure
docker compose up -d
```

This starts PostgreSQL (port **5433** on host), Redis, and the API (port **8000**).

> **Note:** Rebuild the API image after pulling dependency changes:
> `docker compose build api && docker compose up -d api`

### 3. Run migrations

```bash
cd apps/api
pip install -r requirements.txt
alembic upgrade head
```

### 4. Seed demo data

```bash
cd apps/api
python scripts/seed_deals.py
python scripts/fix_meddpicc_path.py
```

### 5. Start the frontend

```bash
cd apps/web
npm install
npm run dev
```

Open **http://localhost:3000**

| Service | URL |
|---------|-----|
| Web app | http://localhost:3000 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs (debug mode only) |
| PostgreSQL | `localhost:5433` (user `vantage`, db `vantage`) |

---

## Project structure

```
apps/
  web/              Next.js frontend
  api/              FastAPI backend + agent pipeline
    app/agents/     Researcher, Risk Scanner, Grounding, Prioritiser, Drafter
    app/routers/    REST + SSE endpoints
    app/services/   Assistant, nightly worker, HubSpot sync
    scripts/        Seed data, one-off fixes
infrastructure/
  docker-compose.yml
  init-db.sql
packages/
  mcp-server/       MCP tools for Claude Desktop
  chrome-extension/ HubSpot + LinkedIn sidebar
docs/               PRD, architecture, security
```

---

## Development

### Run agents on a single deal

Open any account **War Room** → click **Run Agent**, or use the top-bar **Run Agents** sweep.

For scripted demos, run agents on **Meridian Ops** only — avoid sweeping all 11 seeded accounts (overwrites MEDDPICC state).

### Auth bypass (local only)

When `DEBUG=true` and matching bypass tokens are set in both `.env` files, the app skips WorkOS login. Never enable in production.

### Tests

```bash
cd apps/web
npm run test:e2e        # Playwright (requires running app)
```

### API rebuild after dependency changes

```bash
cd infrastructure
docker compose build api
docker compose up -d api
```

---

## Environment variables

See `apps/api/.env.example` and `apps/web/.env.example` for the full list.

| Variable | Required | Purpose |
|----------|----------|---------|
| `OPENAI_API_KEY` | Yes (hackathon) | LLM calls for agents + assistant |
| `LLM_PROVIDER` | Yes | `openai` or `anthropic` |
| `EXA_API_KEY` | Recommended | Web research in agent pipeline |
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `REDIS_URL` | Yes | Session cache + agent locks |
| `WORKOS_API_KEY` | Prod | Authentication |
| `DEBUG_BYPASS_TOKEN` | Dev only | Skip WorkOS locally |

---

## Documentation

- [Architecture](docs/architecture.md)
- [PRD](docs/PRD.md)
- [Product narrative](docs/product-narrative.md)
- [Security threat model](docs/security/threat-model.md)

---

## License

Private — hackathon / internal use.