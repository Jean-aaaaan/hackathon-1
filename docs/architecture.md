# Vantage — System Architecture
**Version:** 1.0  
**Date:** 2026-05-26  
**Architect:** Winston  
**Competitive basis:** Actively AI reverse-engineering (MASTER-BUILD-REPORT)

---

## 1. Architecture Overview

```
                    ┌──────────────────────────────────────────────┐
                    │          FRONTEND (Vercel)                    │
                    │        Next.js 15 App Router                  │
                    │  TanStack Query v5 · Zod v3 · Radix UI       │
                    │  Tailwind CSS · Sonner · NProgress            │
                    │                                               │
                    │  /inbox      → Agent Inbox                    │
                    │  /watchtower → Portfolio Monitor              │
                    │  /assistant  → Chat Interface                 │
                    │  /settings   → Workspace Config               │
                    │  /api-docs   → Scalar (dev portal)           │
                    └──────────────┬───────────────────────────────┘
                                   │ REST + SSE
                    ┌──────────────▼───────────────────────────────┐
                    │       API GATEWAY (Azure Container Apps)      │
                    │      Python FastAPI + Pydantic v2             │
                    │   WorkOS JWT middleware · Rate limiter        │
                    │   Tenant isolation · Request correlation IDs  │
                    │                                               │
                    │  /v1/accounts/*  /v1/workspace/*             │
                    │  /v1/signals/*   /v1/drafts/*                │
                    │  /v1/agent/*     /v1/integrations/*          │
                    └──┬───────────────┬──────────────────────────┘
                       │               │
          ┌────────────▼──────┐ ┌──────▼────────────────────────┐
          │  PostgreSQL        │ │    Azure Service Bus           │
          │  (Azure Flexible)  │ │  Queue: nightly.agent.runs    │
          │  + pgvector 1536   │ │  Queue: webhook.events        │
          │  + Redis Cache     │ │  Queue: signal.urgent         │
          │  (Azure Cache)     │ │  Dead Letter Queues for all   │
          └────────────────────┘ └───────────────────────────────┘
                                              │ dequeued by
                                 ┌────────────▼───────────────────┐
                                 │   AGENT WORKERS                 │
                                 │  Azure Container Apps           │
                                 │  (scale-to-zero, parallel)      │
                                 │  Max 50 concurrent workers      │
                                 │                                 │
                                 │  ResearcherAgent               │
                                 │  RiskScannerAgent              │
                                 │  GroundingAgent (GA day 1)     │
                                 │  PrioritiserAgent              │
                                 │  DrafterAgent                  │
                                 │  StateWriterAgent              │
                                 └─────────────────────────────────┘
                                           │
                    ┌──────────────────────┼───────────────────────┐
         ┌──────────▼──────┐  ┌────────────▼──┐  ┌───────────────▼┐
         │  Claude API     │  │  Perplexity   │  │  HubSpot API   │
         │  Haiku 4.5 (bulk│  │  sonar-pro    │  │  + Webhooks    │
         │  Sonnet 4.6 qual│  │  Web research │  │  Gong API      │
         └─────────────────┘  └───────────────┘  └────────────────┘

OBSERVABILITY:
  PostHog (product analytics + LLM tracing)
  Sentry (error tracking)
  Azure Monitor (infra metrics + alerts)
  OpenTelemetry (distributed tracing, correlation IDs)
```

---

## 2. Technology Decisions

| Layer | Technology | Decision Rationale | 10x Scale? |
|-------|-----------|-------------------|------------|
| Frontend | Next.js 15 App Router | RSC for fast loads; matches Actively's proven approach; zero-config Vercel | Yes — CDN-served, no server scaling needed |
| Frontend hosting | Vercel | Zero-config, preview deployments, edge functions | Yes — CDN scales automatically |
| Backend | Python FastAPI + Pydantic v2 | Async, validated, LLM-native; matches Actively's proven stack | Yes — stateless, horizontal |
| Backend hosting | Azure Container Apps | Scale-to-zero workers; existing Azure infra; revision-based deployments | Yes — auto-scale 0→N |
| Primary DB | PostgreSQL 16 (Azure Flexible) | JSONB for ASO; pgvector for embeddings; ACID; already on Azure | Yes with read replicas |
| Vector search | pgvector extension | Avoids new vendor; co-located with operational data; ivfflat index | Yes to ~10M vectors |
| Cache | Azure Cache for Redis | Pre-computed ASOs at <50ms; session data; rate limiting | Yes — cluster mode |
| Message queue | Azure Service Bus | Durable job orchestration; DLQ; 7-day message retention; AT-LEAST-ONCE delivery | Yes — partitioned queues |
| LLMs (bulk) | Claude Haiku 4.5 | Cheapest capable model with structured outputs; $0.25/M input tokens | Yes — API scales |
| LLMs (quality) | Claude Sonnet 4.6 | Best reasoning for drafter + assistant; $3/M input tokens | Yes — API scales |
| Web search | Perplexity sonar-pro | 0.930 SimpleQA (proven best-in-class by Actively's own evals) | Yes — API scales |
| Auth | WorkOS | SSO, SCIM, passkeys, impossible travel detection; enterprise-grade from day 1 | Yes |
| CRM v1 | HubSpot direct API | Skip Merge.dev; direct = simpler; add Merge.dev in v2 | Yes — rate limits managed |
| Vector store | pgvector in PostgreSQL | Already have PG; ivfflat index sufficient to 10M+ rows | Yes to 10M; beyond: Pinecone |
| Observability | PostHog + Sentry + Azure Monitor | PostHog handles LLM tracing + feature flags + analytics in one; Sentry for errors | Yes |
| API docs | Scalar | Same as Actively; modern, AI-searchable, interactive | Yes |
| MCP transport | stdio + HTTP | stdio for local Claude Desktop; HTTP for web tools | Yes |

**ADR-001:** Using Azure Service Bus over Temporal.io  
*Reason:* Actively uses Temporal for durable workflow orchestration. We're on Azure. Azure Service Bus + Container Apps gives us AT-LEAST-ONCE delivery with DLQs at a fraction of the operational complexity of running Temporal. At 10x scale (5,000+ workspaces), we add Temporal if retry/saga complexity warrants it. Trigger: >100 failed nightly runs/day.

**ADR-002:** pgvector over Pinecone for MVP  
*Reason:* Same database, fewer vendors, no additional cost. Performance sufficient to 10M vectors. Trigger for migration: query latency >500ms at 80th percentile.

**ADR-003:** Gold Data Layer is always visible  
*Reason:* Actively's Gold Data Layer is opaque (their weakness). Every resolved fact in our system includes source, weight, confidence, and conflict resolution history. This is a trust signal for enterprise procurement.

---

## 3. Database Schema (Production-Ready)

```sql
-- === EXTENSIONS ===
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- === WORKSPACES ===
CREATE TABLE workspaces (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                    TEXT NOT NULL,
    slug                    TEXT NOT NULL UNIQUE,
    
    -- CRM credentials (encrypted at rest via Azure Key Vault references)
    hubspot_portal_id       TEXT,
    hubspot_access_token_ref TEXT,   -- Azure Key Vault secret reference
    hubspot_refresh_token_ref TEXT,
    hubspot_token_expires_at TIMESTAMPTZ,
    
    -- Call intelligence
    gong_workspace_id       TEXT,
    gong_api_key_ref        TEXT,    -- Azure Key Vault reference
    
    -- Enrichment
    perplexity_api_key_ref  TEXT,    -- Azure Key Vault reference
    
    -- Notifications
    slack_webhook_url       TEXT,
    teams_webhook_url       TEXT,
    
    -- Billing
    stripe_customer_id      TEXT,
    plan                    TEXT DEFAULT 'trial',  -- trial | starter | growth | enterprise
    
    -- Settings (JSONB for flexible config without migrations)
    settings                JSONB DEFAULT '{}',
    
    -- Audit
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW(),
    deleted_at              TIMESTAMPTZ  -- soft delete
);

-- === WORKSPACE USERS ===
CREATE TABLE workspace_users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    workos_user_id  TEXT NOT NULL,
    email           TEXT NOT NULL,
    name            TEXT,
    role            TEXT DEFAULT 'rep',  -- rep | manager | admin | owner
    hubspot_owner_id TEXT,               -- Maps to HubSpot owner
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(workspace_id, workos_user_id)
);

-- === ACCOUNTS ===
CREATE TABLE accounts (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id        UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    
    -- CRM identifiers
    hubspot_deal_id     TEXT,
    hubspot_company_id  TEXT,
    
    -- Core display fields (denormalised from ASO for performance)
    name                TEXT NOT NULL,
    stage               TEXT,
    deal_amount         NUMERIC(15, 2),
    close_date          DATE,
    owner_rep_id        TEXT,   -- HubSpot owner ID
    owner_user_id       UUID REFERENCES workspace_users(id),
    
    -- Full Account State Object (the ASO — agent-maintained)
    state               JSONB DEFAULT '{}',
    
    -- Quick-access columns (derived from state for fast WHERE/ORDER BY)
    health_score        FLOAT CHECK (health_score BETWEEN 0 AND 1),
    urgency_score       FLOAT CHECK (urgency_score BETWEEN 0 AND 1),
    pov_forecast_cat    TEXT,   -- Pipeline | Forecast | Best Case | Commit
    pov_confidence      FLOAT,
    
    -- Agent tracking
    last_agent_run_at   TIMESTAMPTZ,
    agent_run_count     INTEGER DEFAULT 0,
    
    -- Vector embedding (1536-dim, text-embedding-3-small compatible)
    embedding           vector(1536),
    
    -- Timestamps
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(workspace_id, hubspot_deal_id)
);

-- Performance indexes
CREATE INDEX idx_accounts_workspace_urgency 
    ON accounts(workspace_id, urgency_score DESC NULLS LAST) 
    WHERE deleted_at IS NULL;
    
CREATE INDEX idx_accounts_workspace_health 
    ON accounts(workspace_id, health_score ASC NULLS LAST) 
    WHERE deleted_at IS NULL;
    
CREATE INDEX idx_accounts_workspace_owner 
    ON accounts(workspace_id, owner_user_id);
    
CREATE INDEX idx_accounts_updated 
    ON accounts(workspace_id, updated_at DESC);

-- Vector search index (ivfflat, lists tuned for expected row count)
CREATE INDEX idx_accounts_embedding 
    ON accounts USING ivfflat (embedding vector_cosine_ops) 
    WITH (lists = 100);

-- Add soft delete column
ALTER TABLE accounts ADD COLUMN deleted_at TIMESTAMPTZ;

-- === SIGNALS ===
CREATE TABLE signals (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id      UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    workspace_id    UUID NOT NULL REFERENCES workspaces(id),
    
    -- Signal classification
    type            TEXT NOT NULL,
    -- champion_activity | competitive_mention | champion_dark | deal_slip 
    -- | usage_drop | champion_role_change | leadership_change | funding_event
    -- | product_launch | news_mention | gong_call | hubspot_change
    
    urgency         TEXT NOT NULL CHECK (urgency IN ('high', 'medium', 'low')),
    urgency_score   FLOAT NOT NULL CHECK (urgency_score BETWEEN 0 AND 1),
    
    detail          TEXT,
    source          TEXT,       -- gong:call/456 | linkedin | hubspot:deal/123 | perplexity:news
    source_url      TEXT,
    confidence      FLOAT CHECK (confidence BETWEEN 0 AND 1),
    
    -- Gold Data fields (audit trail)
    gold_sources    JSONB,      -- [{source, value, confidence, updated_at}, ...]
    gold_resolution TEXT,       -- How the conflict was resolved
    
    -- Processing state
    processed           BOOLEAN DEFAULT FALSE,
    processed_at        TIMESTAMPTZ,
    pushed_to_inbox     BOOLEAN DEFAULT FALSE,
    notification_sent   BOOLEAN DEFAULT FALSE,
    
    -- Link to agent run
    agent_run_id    UUID,
    
    detected_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_signals_account_unprocessed 
    ON signals(account_id, detected_at DESC) 
    WHERE processed = FALSE;
    
CREATE INDEX idx_signals_workspace_recent 
    ON signals(workspace_id, detected_at DESC);
    
CREATE INDEX idx_signals_urgent 
    ON signals(workspace_id, urgency_score DESC) 
    WHERE pushed_to_inbox = FALSE AND processed = FALSE;

-- === DRAFTS ===
CREATE TABLE drafts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id      UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    workspace_id    UUID NOT NULL REFERENCES workspaces(id),
    
    type            TEXT NOT NULL CHECK (type IN (
        'email_followup', 'meeting_brief', 'outreach_sequence', 
        'risk_summary', 'coaching_note'
    )),
    
    content         TEXT NOT NULL,
    content_html    TEXT,
    
    -- Metadata
    target_contact  TEXT,       -- Who the email is addressed to
    subject_line    TEXT,       -- For email drafts
    
    -- Sources cited in this draft (for Audit Panel)
    sources_cited   JSONB DEFAULT '[]',
    -- [{source, fact, confidence, url}, ...]
    
    -- Gold Data used (audit trail)
    gold_data_used  JSONB DEFAULT '{}',
    
    -- Review outcome
    status          TEXT DEFAULT 'pending' CHECK (status IN (
        'pending', 'approved', 'approved_modified', 'declined', 'expired', 'superseded'
    )),
    
    reviewer_id     UUID REFERENCES workspace_users(id),
    reviewer_notes  TEXT,       -- Decline reason → episodic memory training signal
    final_content   TEXT,       -- Approved content (may differ from original)
    reviewed_at     TIMESTAMPTZ,
    
    -- CRM sync
    pushed_to_crm       BOOLEAN DEFAULT FALSE,
    crm_draft_id        TEXT,
    crm_pushed_at       TIMESTAMPTZ,
    
    -- Agent run provenance
    agent_run_id    UUID,
    
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '72 hours')
);

CREATE INDEX idx_drafts_account_pending 
    ON drafts(account_id, created_at DESC) 
    WHERE status = 'pending';

CREATE INDEX idx_drafts_workspace_pending 
    ON drafts(workspace_id, created_at DESC) 
    WHERE status = 'pending';

-- === INTERACTIONS (Episodic Memory) ===
CREATE TABLE interactions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id      UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    workspace_id    UUID NOT NULL REFERENCES workspaces(id),
    
    type            TEXT NOT NULL,
    -- call | email_sent | email_received | meeting | note | 
    -- agent_draft_approved | agent_draft_declined | chat_query | api_feedback
    
    source          TEXT,       -- hubspot | gong | manual | agent | mcp | api
    
    -- Content
    notes           TEXT,
    outcome         TEXT,
    
    -- Sentiment
    sentiment       TEXT CHECK (sentiment IN ('positive', 'neutral', 'negative', 'mixed')),
    sentiment_score FLOAT,
    
    -- Metadata
    rep_id          UUID REFERENCES workspace_users(id),
    contact_name    TEXT,
    contact_email   TEXT,
    
    -- Training signal (from declined drafts)
    is_training_signal  BOOLEAN DEFAULT FALSE,
    training_category   TEXT,   -- wrong_tone | wrong_timing | wrong_content | hallucination | other
    
    occurred_at     TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_interactions_account_time 
    ON interactions(account_id, occurred_at DESC);
    
CREATE INDEX idx_interactions_training 
    ON interactions(workspace_id, is_training_signal) 
    WHERE is_training_signal = TRUE;

-- === AGENT RUNS ===
CREATE TABLE agent_runs (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id        UUID NOT NULL REFERENCES workspaces(id),
    
    trigger             TEXT NOT NULL,
    -- nightly_cron | webhook_deal_change | webhook_contact_activity 
    -- | manual_refresh | signal_threshold | api_batch_refresh
    
    started_at          TIMESTAMPTZ DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    status              TEXT DEFAULT 'running' CHECK (status IN (
        'running', 'completed', 'failed', 'partial', 'cancelled'
    )),
    
    -- Progress tracking
    accounts_total      INTEGER DEFAULT 0,
    accounts_processed  INTEGER DEFAULT 0,
    accounts_failed     INTEGER DEFAULT 0,
    signals_detected    INTEGER DEFAULT 0,
    drafts_created      INTEGER DEFAULT 0,
    
    -- Cost tracking (LLM usage per run)
    total_prompt_tokens         INTEGER DEFAULT 0,
    total_completion_tokens     INTEGER DEFAULT 0,
    total_cost_usd              NUMERIC(10, 6) DEFAULT 0,
    
    -- Error summary for debugging
    error_summary       JSONB,
    
    -- Metadata
    triggered_by_user   UUID REFERENCES workspace_users(id)
);

CREATE INDEX idx_agent_runs_workspace 
    ON agent_runs(workspace_id, started_at DESC);

-- === API KEYS ===
CREATE TABLE api_keys (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id    UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    
    name            TEXT NOT NULL,
    key_prefix      TEXT NOT NULL,          -- First 8 chars (vnt_live_...)
    key_hash        TEXT NOT NULL UNIQUE,   -- bcrypt hash of full key
    
    scopes          TEXT[] DEFAULT ARRAY['read'],  -- read | write | admin
    
    last_used_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    
    created_by      UUID REFERENCES workspace_users(id),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    revoked_at      TIMESTAMPTZ
);

-- === AUDIT LOG (SOC2 requirement) ===
CREATE TABLE audit_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id    UUID,
    user_id         UUID,
    
    action          TEXT NOT NULL,
    -- workspace.created | account.state.updated | draft.approved | 
    -- api_key.created | api_key.revoked | integration.connected |
    -- integration.disconnected | user.invited | user.role_changed
    
    resource_type   TEXT,
    resource_id     UUID,
    
    changes         JSONB,   -- {before, after} diff for state changes
    metadata        JSONB,   -- IP, user agent, request ID, etc.
    
    occurred_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_audit_log_workspace 
    ON audit_log(workspace_id, occurred_at DESC);
    
CREATE INDEX idx_audit_log_user 
    ON audit_log(user_id, occurred_at DESC);
```

---

## 4. API Contract

### Base URL
```
Production:  https://api.vantage.app/v1
Staging:     https://api-staging.vantage.app/v1
```

### Authentication
```
Header: Authorization: Bearer vnt_live_<key>    (API key)
Header: Authorization: Bearer <workos_jwt>      (user session)
```

### Core Endpoints

```
ACCOUNTS
GET    /v1/accounts                              List accounts (paginated, filtered)
GET    /v1/accounts/{account_id}                 Get account metadata
GET    /v1/accounts/{account_id}/state           Full ASO JSON
GET    /v1/accounts/{account_id}/next-actions    Prioritised actions
GET    /v1/accounts/{account_id}/pov             AI Point of View
GET    /v1/accounts/{account_id}/drafts          List drafts (filtered by status)
GET    /v1/accounts/{account_id}/signals         Recent signals
GET    /v1/accounts/{account_id}/interactions    Episodic memory
POST   /v1/accounts/{account_id}/feedback        Log interaction (update episodic memory)
POST   /v1/accounts/search                       Semantic search (body: {query, limit})
POST   /v1/accounts/batch-refresh                Trigger immediate agent run

WORKSPACE
GET    /v1/workspace                             Workspace settings + integrations status
GET    /v1/workspace/health                      Aggregate portfolio health
GET    /v1/workspace/usage                       LLM costs, coverage, DAR by week
PATCH  /v1/workspace                             Update settings

DRAFTS
GET    /v1/drafts/{draft_id}                     Single draft with full audit trail
PATCH  /v1/drafts/{draft_id}                     Approve/decline (body: {status, notes, final_content})
POST   /v1/drafts/{draft_id}/push-to-crm        Push approved draft to HubSpot

SIGNALS
GET    /v1/signals                               List signals (filtered, paginated)
PATCH  /v1/signals/{signal_id}/acknowledge       Mark as seen

AGENT CHAT
POST   /v1/agent/chat                            Start chat (body: {account_id, message})
GET    /v1/agent/chat/{thread_id}                Get thread history
POST   /v1/agent/chat/{thread_id}               Continue thread (SSE streaming)
```

### Response Format (Standard)
```json
{
  "data": {...},
  "meta": {
    "request_id": "req_01abc...",
    "workspace_id": "ws_01abc...",
    "timestamp": "2026-05-26T09:00:00Z"
  },
  "pagination": {
    "cursor": "...",
    "has_more": true,
    "total": 247
  }
}
```

### Error Format (Standard)
```json
{
  "error": {
    "code": "account_not_found",
    "message": "Account with ID '...' not found in this workspace",
    "request_id": "req_01abc...",
    "docs_url": "https://docs.vantage.app/errors/account_not_found"
  }
}
```

---

## 5. Agent Pipeline Architecture

```
TRIGGER: Azure Service Bus message (nightly_cron or webhook)
  │
  ▼
WORKER: AgentOrchestrator (Azure Container App, scale-to-zero)
  │
  ├── Fetches workspace + account batch from PostgreSQL
  ├── Acquires processing lock (Redis SET NX, 4h TTL) per account
  ├── For each account, spawns agent chain:
  │
  ├─► [1] ResearcherAgent (Haiku 4.5)
  │       Input: raw signals (HubSpot delta, Gong calls, Perplexity news)
  │       Output: ResearchResult (new_signals, stakeholder_updates, summary_delta)
  │       Cost: ~$0.02/account
  │
  ├─► [2] RiskScannerAgent (Haiku 4.5)
  │       Input: account state + ResearchResult
  │       Output: RiskResult (risks: [{type, urgency, urgency_score, detail, source}])
  │       Cost: ~$0.02/account
  │
  ├─► [3] GroundingAgent (Haiku 4.5) ← GA FROM DAY 1 (not beta)
  │       Input: ResearchResult + RiskResult
  │       Task: verify every claimed fact against cited source
  │       Output: GroundingResult (verified_facts, unverified_claims, confidence_map)
  │       Cost: ~$0.02/account
  │
  ├─► [4] PrioritiserAgent (Sonnet 4.6)
  │       Input: GroundingResult + deal_stage + rep_bandwidth + account_age
  │       Output: PrioritiserResult (next_actions: [{action, reason, priority, urgency_score}])
  │       Cost: ~$0.05/account
  │
  ├─► [5] DrafterAgent (Sonnet 4.6)
  │       Input: PrioritiserResult (for actions above urgency threshold 0.7)
  │       Output: DrafterResult (drafts: {email_followup?, meeting_brief?})
  │       Cost: ~$0.10/account
  │
  └─► [6] StateWriter
          Input: all agent outputs + previous ASO
          Task: merge into new ASO, update health_score, urgency_score, embedding
          Output: updated ASO → PostgreSQL, embedding → pgvector
          Cost: ~$0.01 (embedding via Anthropic)
          
NIGHTLY TOTAL: ~$0.22/account (500 accounts = ~$110/night)
```

---

## 6. Front-End Route Structure

```
app/
├── (auth)/
│   ├── login/                  → WorkOS redirect
│   └── callback/               → WorkOS OAuth callback
│
├── (onboarding)/
│   ├── connect/               → HubSpot OAuth
│   └── setup/                 → Workspace configuration
│
├── (app)/
│   ├── layout.tsx             → Auth guard, sidebar, header
│   ├── inbox/                 → Agent Inbox
│   │   └── [accountId]/       → Account card expanded
│   ├── watchtower/            → Portfolio grid + risk feed
│   │   └── [accountId]/       → Account detail + ASO view
│   ├── assistant/             → Chat interface
│   │   └── [threadId]/        → Conversation thread
│   ├── settings/              → Workspace settings
│   │   ├── integrations/      → HubSpot, Gong status
│   │   ├── api-keys/          → API key management
│   │   ├── team/              → User management
│   │   └── billing/           → Plan + usage
│   └── docs/                  → API docs (Scalar embedded)
│
└── api/
    ├── auth/callback/         → WorkOS OAuth handler
    ├── webhooks/hubspot/      → HubSpot webhook receiver
    └── webhooks/gong/         → Gong webhook receiver
```

---

## 7. Security Architecture (Carol co-authored)

### Authentication Model
- All routes: WorkOS JWT required (validated server-side via middleware)
- API access: Bearer token (API key), hashed with bcrypt, stored only as hash
- Webhook endpoints: HMAC signature validation (HubSpot secret, Gong secret)

### Data Isolation
- Every database query includes `workspace_id = <current_workspace>` filter
- Row-level security (PostgreSQL RLS) on all tables as defense-in-depth
- API keys scoped per workspace — no cross-workspace access possible

### Secrets Management
- Azure Key Vault for all third-party API credentials (no secrets in env vars or DB)
- Key Vault references in Container Apps environment — rotatable without code change

### Encryption
- At rest: Azure storage encryption (AES-256)
- In transit: TLS 1.3 minimum (Azure enforced)
- Sensitive fields: API keys stored as bcrypt hashes only (never reversible)

### Audit Logging (SOC2 requirement)
- Every write operation to accounts/drafts/workspace produces an audit_log entry
- Audit log is append-only (no DELETE permission on audit_log table)
- Log retention: 7 years (Azure Blob Archive storage)

---

## 8. Scale Analysis (Winston's Mandate: 10x and 100x)

| Scenario | Accounts | Workspaces | Nightly Runtime | Cost/night |
|---------|---------|-----------|----------------|-----------|
| MVP launch | 500 | 1 | ~15 min | ~$110 |
| 10x | 5,000 | 10 | ~30 min parallel | ~$1,100 |
| 100x | 50,000 | 100 | ~1 hr (batch-parallel) | ~$11,000 |

**At 10x:** No schema changes needed. Add read replica. Increase Container App max instances to 200. Add Azure Service Bus partitioning.

**At 100x:** Add Temporal.io for saga management. Migrate to Pinecone if pgvector latency degrades. Consider dedicated DB per enterprise workspace.

**Single points of failure eliminated:**
- API: Azure Container Apps auto-fail-over across zones
- DB: PostgreSQL HA with automatic failover standby
- Queue: Azure Service Bus geo-redundant replication
- Cache: Azure Cache Redis with geo-replication enabled

---

*Architecture v1.0 — Winston. Reviewed by Carol (security). Approved for PRD alignment.*
