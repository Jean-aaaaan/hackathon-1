/**
 * Vantage API client - thin wrapper around fetch.
 * All requests go through /api/* (proxied by Next.js to FastAPI).
 */

const BASE = process.env.NEXT_PUBLIC_API_URL || "";
// Dev bypass: only active when NODE_ENV=development AND NEXT_PUBLIC_DEV_BYPASS_TOKEN is set.
// Token must match DEBUG_BYPASS_TOKEN in apps/api/.env. Backend startup refuses DEBUG=true in prod.
const DEV_BYPASS_TOKEN = process.env.NEXT_PUBLIC_DEV_BYPASS_TOKEN || "";
const DEV_BYPASS = process.env.NODE_ENV === "development" && !!DEV_BYPASS_TOKEN;

// Auth headers for raw fetch calls that bypass request() (SSE token fetch, streams).
// In dev this injects the bypass token; in production it returns {} (cookie auth).
export function devAuthHeaders(): Record<string, string> {
  return DEV_BYPASS ? { Authorization: `Bearer ${DEV_BYPASS_TOKEN}` } : {};
}

/** Build a query string from a params object, omitting null and undefined values. */
function buildQuery(params: Record<string, unknown> | undefined): string {
  if (!params) return "";
  const qs = new URLSearchParams(
    Object.fromEntries(
      Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== null)
        .map(([k, v]) => [k, String(v)])
    )
  ).toString();
  return qs ? `?${qs}` : "";
}

export function getPreferredWorkspace(): string | null {
  if (typeof localStorage === "undefined") return null;
  return localStorage.getItem("preferred_workspace_id");
}

export function setPreferredWorkspace(id: string | null): void {
  if (typeof localStorage === "undefined") return;
  if (id) localStorage.setItem("preferred_workspace_id", id);
  else localStorage.removeItem("preferred_workspace_id");
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const preferredWs = getPreferredWorkspace();
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      // Dev bypass: inject token so FastAPI's debug auth passes without WorkOS.
      // Token matches DEBUG_BYPASS_TOKEN in apps/api/.env. Never active in production (startup check).
      ...(DEV_BYPASS ? { Authorization: `Bearer ${DEV_BYPASS_TOKEN}` } : {}),
      // Multi-workspace: backend scopes queries to this workspace when present; omitted for single-workspace installs.
      ...(preferredWs ? { "X-Preferred-Workspace": preferredWs } : {}),
      ...options.headers,
    },
    credentials: "include",  // sends session cookie
  });

  if (res.status === 401 && typeof window !== "undefined") {
    // Guard against redirect-loops: middleware itself lives on /auth/* and must not
    // re-redirect, and the stale cookie must be cleared so Next.js middleware won't
    // immediately bounce the login page back to /auth/login again.
    if (!window.location.pathname.startsWith("/auth")) {
      // WorkOS sets the authoritative cookie as HttpOnly; the SameSite=Lax copy is JS-accessible.
      document.cookie = "vantage_session=; Max-Age=0; path=/; SameSite=Lax";
      window.location.href = "/auth/login";
    }
    throw new Error("Session expired");
  }

  if (!res.ok) {
    const error = await res.json().catch(() => ({ error: { message: res.statusText } }));
    throw new Error(error?.error?.message || error?.detail || res.statusText);
  }

  return res.json();
}

// ── Accounts ──────────────────────────────────────────────────────────────────

export const accountsApi = {
  list: (params?: {
    page?: number;
    limit?: number;
    sort_by?: string;
    sort_dir?: string;
    stage?: string;
    min_urgency?: number;
    min_amount?: number;
    close_before?: string;       // YYYY-MM-DD - deals closing on/before this date
    has_pending_drafts?: boolean;
  }) =>
    request<{ data: AccountListItem[]; pagination: Pagination; meta: Meta & { available_stages?: string[] } }>(
      `/v1/accounts${buildQuery(params)}`
    ),

  getState: (id: string) =>
    request<{ data: Record<string, unknown>; meta: Meta }>(`/v1/accounts/${id}/state`),

  getPov: (id: string) =>
    request<{ data: PovData; meta: Meta }>(`/v1/accounts/${id}/pov`),

  getNextActions: (id: string) =>
    request<{ data: { next_actions: NextAction[]; urgency_score: number }; meta: Meta }>(
      `/v1/accounts/${id}/next-actions`
    ),

  search: (body: { query: string; limit?: number; min_urgency?: number; stage?: string }) =>
    request<{ data: AccountSearchResult[]; meta: Meta }>("/v1/accounts/search", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  logFeedback: (id: string, body: FeedbackBody) =>
    request<{ data: { interaction_id: string }; meta: Meta }>(`/v1/accounts/${id}/feedback`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  batchRefresh: (account_ids?: string[], stage_filter?: string) =>
    request<{ data: { run_id: string; status: string }; meta: Meta }>("/v1/accounts/batch-refresh", {
      method: "POST",
      body: JSON.stringify({ account_ids, stage_filter }),
    }),

  getNotes: (id: string) =>
    request<{ data: AccountNote[]; meta: Meta }>(`/v1/accounts/${id}/notes`),

  getSmartFields: (id: string) =>
    request<{ data: SmartFieldsData; meta: Meta }>(`/v1/accounts/${id}/smart-fields`),

  dismissSmartField: (id: string, body: { field_name: string; suggested_value: string }) =>
    request<{ data: { dismissed: boolean; field_name: string }; meta: Meta }>(
      `/v1/accounts/${id}/smart-fields/dismiss`,
      { method: "POST", body: JSON.stringify(body) }
    ),

  setNextStep: (id: string, body: { text: string; due_date?: string }) =>
    request<{ data: { next_step: { text: string; due_date?: string; source: string } }; meta: Meta }>(
      `/v1/accounts/${id}/next-step`,
      { method: "POST", body: JSON.stringify(body) }
    ),

  overridePov: (id: string, body: { override_category: string; reason: string }) =>
    request<{ data: { applied: boolean; ai_category: string; override_category: string }; meta: Meta }>(
      `/v1/accounts/${id}/pov/override`,
      { method: "POST", body: JSON.stringify(body) }
    ),

  getPlays: (id: string) =>
    request<{ data: { fired: PlayEntry[]; available: PlayEntry[] }; meta: Meta }>(
      `/v1/accounts/${id}/plays`
    ),

  getTranscripts: (id: string, page?: number) =>
    request<{ data: Transcript[]; intel?: ConversationIntel; pagination: Pagination; meta: Meta }>(
      // page=1 is the backend default; omit it to avoid a redundant cache-busting param
      `/v1/accounts/${id}/transcripts${buildQuery(page && page > 1 ? { page } : undefined)}`
    ),

  getTrainingInsights: (id: string) =>
    request<{ data: TrainingInsights; meta: Meta }>(`/v1/accounts/${id}/training-insights`),

  captureWinLoss: (id: string, body: {
    outcome: "won" | "lost";
    reason: string;
    competitor?: string;
    notes?: string;
  }) =>
    request<{ data: { captured: boolean; outcome: string }; meta: Meta }>(
      `/v1/accounts/${id}/win-loss`,
      { method: "POST", body: JSON.stringify(body) }
    ),

  createShareLink: (id: string) =>
    request<{ data: { share_url: string; token: string; expires_at: string }; meta: Meta }>(
      `/v1/accounts/${id}/share`,
      { method: "POST" }
    ),

  getSharedBrief: (token: string) =>
    request<{ data: SharedBriefData; meta: Meta }>(`/v1/accounts/share/${token}`),
};

// ── Drafts ────────────────────────────────────────────────────────────────────

export const draftsApi = {
  list: (params?: { status?: string; account_id?: string; page?: number; limit?: number }) =>
    request<{ data: Draft[]; pagination: Pagination; meta: Meta }>(`/v1/drafts${buildQuery(params)}`),

  get: (id: string) =>
    request<{ data: DraftDetail; meta: Meta }>(`/v1/drafts/${id}`),

  review: (id: string, body: { action: string; modified_content?: string; reviewer_notes?: string; training_category?: string }) =>
    request<{ data: { draft_id: string; status: string; training_signal_logged: boolean }; meta: Meta }>(
      `/v1/drafts/${id}`,
      { method: "PATCH", body: JSON.stringify(body) }
    ),

  sendViaOutlook: (id: string, body: { to: string; subject: string; cc?: string }) =>
    request<{ data: { draft_id: string; status: string; to: string; subject: string }; meta: Meta }>(
      `/v1/drafts/${id}/send`,
      { method: "POST", body: JSON.stringify(body) }
    ),
};

// ── Signals ───────────────────────────────────────────────────────────────────

export const signalsApi = {
  list: (params?: { account_id?: string; min_urgency?: number; type?: string; page?: number; limit?: number }) =>
    request<{ data: Signal[]; pagination: Pagination; meta: Meta }>(`/v1/signals${buildQuery(params)}`),

  acknowledge: (id: string) =>
    request<{ data: { acknowledged: boolean }; meta: Meta }>(`/v1/signals/${id}/acknowledge`, {
      method: "POST",
    }),
};

// ── Workspace ─────────────────────────────────────────────────────────────────

export const workspaceApi = {
  get: () => request<{ data: WorkspaceData; meta: Meta }>("/v1/workspace"),
  getUsage: () => request<{ data: UsageData; meta: Meta }>("/v1/workspace/usage"),
  getTeam: () => request<{ data: TeamMember[]; meta: Meta }>("/v1/workspace/team"),
  updateSettings: (body: Record<string, unknown>) =>
    request<{ data: Record<string, unknown>; meta: Meta }>("/v1/workspace/settings", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  syncHubspot: () =>
    request<{ data: { synced: boolean; created: number; updated: number; unchanged: number; errors: number }; meta: Meta }>(
      "/v1/workspace/integrations/hubspot/sync",
      { method: "POST" }
    ),
  analyzeVoiceProfile: () =>
    request<{ data: { voice_profile: VoiceProfile; emails_analyzed: number; source: string }; meta: Meta }>(
      "/v1/workspace/voice-profile/analyze",
      { method: "POST" }
    ),
  addWebhook: (body: { url: string; events: string[] }) =>
    request<{ data: WebhookSubscription; meta: Meta }>("/v1/workspace/webhooks", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteWebhook: (id: string) =>
    request<{ data: { deleted: boolean }; meta: Meta }>(`/v1/workspace/webhooks/${id}`, {
      method: "DELETE",
    }),
  syncCalendar: () =>
    request<{ data: { meetings_found: number; matched: number }; meta: Meta }>(
      "/v1/workspace/integrations/outlook/sync-calendar",
      { method: "POST" }
    ),
  getHealthScore: () =>
    request<{
      data: {
        score: number;
        max: number;
        status: string;
        checks: { name: string; ok: boolean; weight: number; fix: string }[];
        missing: { name: string; ok: boolean; weight: number; fix: string }[];
      };
      meta: Meta;
    }>("/v1/workspace/health-score"),
  getRulesLog: () =>
    request<{ data: RulesLogEntry[]; meta: Meta }>("/v1/workspace/rules-log"),
  getStatus: () =>
    request<{ data: WorkspaceStatus; meta: Meta }>("/v1/workspace/status"),

  uploadProposalTemplate: (templateB64: string, templateName: string) =>
    request<{ data: { uploaded: boolean; size_bytes: number; name: string } }>(
      "/v1/workspace/documents/template",
      { method: "POST", body: JSON.stringify({ template_b64: templateB64, template_name: templateName }) }
    ),

  deleteProposalTemplate: () =>
    request<{ data: { deleted: boolean } }>("/v1/workspace/documents/template", { method: "DELETE" }),

  setup: (body: {
    sender_name: string;
    sender_title?: string;
    sender_company: string;
    product_name: string;
    product_description: string;
    seller_domains?: string[];
    icp_industries?: string[];
    icp_regions?: string[];
    typical_deal_size?: string;
    sales_cycle_months?: string;
    differentiators?: string[];
    competitors?: string[];
    pain_points?: string[];
  }) =>
    request<{ status: string; workspace_id: string }>("/v1/workspace/setup", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  create: (body: {
    company_name: string;
    slug: string;
    sender_name?: string;
    sender_title?: string;
    seller_domains?: string[];
  }) =>
    request<{ id: string; name: string; slug: string }>("/v1/workspace/create", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

// ── Auth ──────────────────────────────────────────────────────────────────────

export const authApi = {
  me: () => request<{ data: CurrentUser; meta: Meta }>("/auth/me"),
  logout: () => request<{ data: { logged_out: boolean }; meta: Meta }>("/auth/logout", { method: "POST" }),
  workspaces: () => request<{ data: WorkspaceSummary[]; meta: { count: number } }>("/auth/workspaces"),
};

// ── Analytics ─────────────────────────────────────────────────────────────────

export const analyticsApi = {
  overview: () => request<{ data: AnalyticsOverview; meta: Meta }>("/v1/analytics/overview"),

  darTrend: (days: number = 30) =>
    request<{ data: DarTrendPoint[]; meta: Meta }>(`/v1/analytics/dar-trend${buildQuery({ days })}`),

  costTrend: (days: number = 30) =>
    request<{ data: CostTrendPoint[]; meta: Meta }>(`/v1/analytics/cost-trend${buildQuery({ days })}`),

  signalTypes: () =>
    request<{ data: SignalTypeData[]; meta: Meta }>("/v1/analytics/signal-types"),

  repPerformance: () =>
    request<{ data: RepPerformanceRow[]; meta: Meta }>("/v1/analytics/rep-performance"),

  accountTimeline: (accountId: string, limit: number = 50) =>
    request<{ data: TimelineEvent[]; meta: Meta }>(
      `/v1/analytics/accounts/${accountId}/timeline${buildQuery({ limit })}`
    ),

  stalledDeals: (limit: number = 10) =>
    request<{ data: { deals: StalledDeal[]; total_at_risk: number; count: number }; meta: Meta }>(
      `/v1/analytics/stalled${buildQuery({ limit })}`
    ),

  competitiveLeaderboard: () =>
    request<{ data: { competitors: CompetitorEntry[]; total_competitive_deals: number }; meta: Meta }>(
      "/v1/analytics/competitive"
    ),

  draftPerformance: () =>
    request<{ data: DraftTypePerf[]; meta: Meta }>("/v1/analytics/draft-performance"),

  trainingFeedback: () =>
    request<{ data: TrainingFeedbackRow[]; meta: Meta }>("/v1/analytics/training-feedback"),

  forecastAccuracy: () =>
    request<{ data: ForecastAccuracyRow[]; meta: Meta }>("/v1/analytics/forecast-accuracy"),

  executionRate: () =>
    request<{ data: ExecutionRateData; meta: Meta }>("/v1/analytics/execution-rate"),

  pipelineMovement: (days?: number) =>
    request<{ data: PipelineMovementData; meta: Meta }>(
      `/v1/analytics/pipeline-movement${buildQuery({ days })}`
    ),

  agentRoi: () =>
    request<{ data: AgentRoiData; meta: Meta }>("/v1/analytics/agent-roi"),
  replyRate: (days?: number) =>
    request<{ data: ReplyRateData; meta: Meta }>(`/v1/analytics/reply-rate${buildQuery({ days })}`),
  dealVelocity: () =>
    request<{ data: DealVelocityData; meta: Meta }>("/v1/analytics/deal-velocity"),
  stageFunnel: () =>
    request<{ data: StageFunnelData; meta: Meta }>("/v1/analytics/stage-funnel"),
  watcherDelta: () =>
    request<{ data: WatcherDeltaData; meta: Meta }>("/v1/analytics/watchtower-delta"),

  pipelineReview: () =>
    request<{ data: PipelineReview; meta: Meta }>("/v1/analytics/pipeline-review"),
};

// ── Forecast ──────────────────────────────────────────────────────────────────

export const forecastApi = {
  rollup: (rep?: string) =>
    request<{ data: ForecastRollup; meta: Meta }>(`/v1/forecast/rollup${buildQuery({ rep })}`),
  // Forecast category override — also available as accountsApi.overridePov (preferred name)
  override: (accountId: string, category: string, reason: string) =>
    request<{ data: { applied: boolean; ai_category: string; override_category: string }; meta: Meta }>(
      `/v1/accounts/${accountId}/pov/override`,
      { method: "POST", body: JSON.stringify({ override_category: category, reason }) }
    ),
};

// ── Timeline ──────────────────────────────────────────────────────────────────

export const timelineApi = {
  getForAccount: (accountId: string, includeDone = false) =>
    request<{
      data: {
        upcoming: TimelineAction[];
        overdue: TimelineAction[];
        history: TimelineAction[];
      };
      meta: Meta;
    }>(`/v1/accounts/${accountId}/timeline-actions${buildQuery(includeDone ? { include_done: true } : undefined)}`),

  create: (accountId: string, body: {
    action_type: string;
    title: string;
    reasoning?: string;
    due_date: string;
    priority?: number;
  }) =>
    request<{ data: TimelineAction; meta: Meta }>(`/v1/accounts/${accountId}/timeline-actions`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  patch: (actionId: string, body: {
    action: "complete" | "skip" | "reschedule" | "edit";
    notes?: string;
    outcome?: "sent_email" | "had_call" | "got_response" | "meeting_booked" | "not_relevant" | "done";
    new_due_date?: string;
    new_title?: string;
  }) =>
    request<{ data: TimelineAction; meta: Meta }>(`/v1/timeline-actions/${actionId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  remove: (actionId: string) =>
    request<{ data: { deleted: boolean }; meta: Meta }>(`/v1/timeline-actions/${actionId}`, {
      method: "DELETE",
    }),

  getActionQueue: () =>
    request<{
      data: {
        today_and_overdue: TimelineAction[];
        focus: TimelineAction[];
        upcoming_this_week: TimelineAction[];
        counts: { overdue: number; today: number; this_week: number };
      };
      meta: Meta;
    }>("/v1/workspace/action-queue"),

  backfillTimeline: () =>
    request<{ data: { accounts_processed: number; actions_created: number }; meta: Meta }>(
      "/v1/workspace/backfill-timeline",
      { method: "POST" }
    ),

  getActivityHistory: () =>
    request<{ data: ActivityWeek[]; meta: { total: number } }>("/v1/workspace/activity-history"),
};

// ── Agent ─────────────────────────────────────────────────────────────────────

export const agentApi = {
  refreshUrgent: () =>
    request<{ data: { queued: number; message: string }; meta: Meta }>("/v1/agent/refresh-urgent", {
      method: "POST",
    }),

  getMeetingBrief: (accountId: string, meetingContext?: string) =>
    request<{
      data: {
        account_name: string;
        stage: string | null;
        deal_amount: number | null;
        ai_forecast: string | null;
        ai_confidence: number | null;
        health_score: number | null;
        top_signals: Array<{ type: string; urgency: string; detail: string }>;
        next_actions: Array<{ action: string; reason: string; urgency_score: number }>;
        stakeholders: Array<{ name: string; title?: string; role?: string; sentiment?: string }>;
        brief: string;
        generated_at: string;
      };
      meta: Meta;
    }>(`/v1/agent/${accountId}/prepare`, {
      method: "POST",
      body: JSON.stringify({ meeting_context: meetingContext ?? null }),
    }),
};

// ── SSE shared byte-loop ──────────────────────────────────────────────────────

/**
 * Drains a Server-Sent Events response body, yielding parsed JSON objects with
 * the SSE event type injected as `type`. The `stream: true` decoder option
 * preserves internal state so multi-byte chars split across chunks decode correctly.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function* drainSSE(res: Response): AsyncGenerator<Record<string, any>> {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let currentEvent = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (line.startsWith("event: ")) {
        // "event:" always precedes its paired "data:" line in the SSE spec
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        try {
          const data = JSON.parse(line.slice(6));
          // Inject event type so consumers don't need to parse event lines themselves
          yield { ...data, type: currentEvent };
        } catch {
          // skip malformed events
        }
      }
    }
  }
}

// ── SSE helpers ───────────────────────────────────────────────────────────────

// SSE paths bypass request() so they need auth headers injected manually (no cookie-only fallback for streams).
async function fetchSSE(path: string, body: unknown): Promise<Response> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...devAuthHeaders() },
    credentials: "include",
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) throw new Error(`SSE stream failed: ${path}`);
  return res;
}

// ── SSE Chat ──────────────────────────────────────────────────────────────────

export async function* streamChat(body: {
  message: string;
  account_id?: string;
  thread_id?: string;
  use_perplexity?: boolean;
}) {
  yield* drainSSE(await fetchSSE("/v1/agent/chat", body));
}


// ── Help / support assistant ──────────────────────────────────────────────────

export async function* streamHelpChat(message: string, page?: string) {
  yield* drainSSE(await fetchSSE("/v1/help/chat", { message, page: page ?? "" }));
}


// ── Type definitions ──────────────────────────────────────────────────────────

export interface AccountListItem {
  id: string;
  name: string;
  stage: string | null;
  deal_amount: number | null;
  close_date: string | null;
  health_score: number | null;
  urgency_score: number | null;
  pov_forecast_cat: string | null;
  pov_confidence: number | null;
  pending_drafts: number;
  last_agent_run_at: string | null;
  signals_summary: { type: string; urgency: string; detail: string }[];
  next_step?: { text: string; due_date?: string; source: string } | null;
  icp_score?: number | null;
  deal_narrative?: string | null;
  top_risk_summary?: string | null;
}

export interface AccountSearchResult extends AccountListItem {
  similarity: number;
  relevance_score: number;
}

export interface PovData {
  pov: Record<string, unknown>;
  health_score: number | null;
  urgency_score: number | null;
  crm_stage: string | null;
  crm_close_date: string | null;
  crm_amount: number | null;
  // AI-predicted fields (read from pov.pov_amount / pov.pov_close_date in the component)
  pov_amount: number | null;
  pov_close_date: string | null;
  delta: { ai_category: string; crm_category: string; ai_vs_crm: string };
  gold_data: Record<string, unknown>;
  grounding_confidence: number | null;
  grounding_summary: string | null;
}

export interface NextAction {
  action: string;
  reason: string;           // backend field name
  /** @deprecated Backend renamed to `reason`; kept for backward-compat with pre-v1.2 responses. */
  rationale?: string;
  urgency_score: number;
  priority: number;
  target_contact?: string | null;
  deadline?: string | null;
  draft_recommended: boolean;
  // MEDDPICC-driven fields (added in framework upgrade)
  draft_type?: string | null;
  meddpicc_component?: string | null;
  framework_rationale?: string | null;
}

export interface Draft {
  id: string;
  type: string;
  status: string;
  content: string;
  confidence?: number | null;
  subject_line?: string | null;
  target_contact?: string | null;
  sources_cited?: Array<{ fact: string; source: string; confidence?: number }>;
  account: { id: string; name: string; stage: string | null; urgency_score: number | null };
  expires_at: string | null;
  created_at: string | null;
  reviewed_at: string | null;
  reviewer_notes: string | null;
  hubspot_email_id: string | null;
  // Play metadata
  play_triggered: boolean;
  play_name: string | null;
  play_reason: string | null;
}

export interface DraftDetail extends Draft {
  sources_cited: Array<{ fact: string; source: string; confidence: number }>;
  gold_data_used: Record<string, unknown>;
}

export interface Signal {
  id: string;
  type: string;
  urgency: string;
  urgency_score: number;
  detail: string;
  source: string;
  account: { id: string; name: string; stage: string | null };
  pushed_to_inbox: boolean;
  acknowledged: boolean;
  created_at: string | null;
}

export interface FeedbackBody {
  interaction_type: string;
  notes: string;
  outcome?: string;
  is_training_signal?: boolean;
  training_category?: string;
}

export interface AccountNote {
  id: string;
  type: string;
  notes: string;
  outcome: string | null;
  source: string | null;
  occurred_at: string | null;
}

export interface WorkspaceData {
  id: string;
  name: string;
  slug: string;
  plan: string;
  settings: Record<string, unknown>;
  integrations: {
    hubspot: { connected: boolean; portal_id: string | null };
    outlook: { connected: boolean; user_email: string | null };
    gong: { connected: boolean };
    perplexity: { connected: boolean };
  };
}

export interface UsageData {
  accounts: { total: number; covered: number; coverage_pct: number };
  drafts: { total: number; approved: number; dar: number; dar_target: number; dar_status: string };
  llm_costs_30d: { total_usd: number; run_count: number; cost_per_run: number };
}

export interface TeamMember {
  id: string;
  email: string;
  role: string;
  hubspot_owner_id: string | null;
}

export interface CurrentUser {
  user_id: string;
  email: string;
  role: string;
  workspace_id: string;
  scopes: string[];
  is_manager: boolean;
}

export interface WorkspaceSummary {
  workspace_id: string;
  name: string;
  role: string;
  is_current: boolean;
}

export interface WorkspaceStatus {
  integrations: {
    hubspot: { connected: boolean; portal_id: string | null };
    outlook: { connected: boolean; user_email: string | null };
    fireflies: { configured: boolean };
    teams: { configured: boolean };
    perplexity: { configured: boolean };
  };
  last_nightly_run: {
    completed_at: string | null;
    accounts_processed: number;
    drafts_created: number;
    signals_detected: number;
  };
  pipeline: {
    total_accounts: number;
    critical_accounts: number;
    at_risk_accounts: number;
    synced_last_24h: number;
    pending_drafts: number;
    dar_pct_30d: number;
  };
}

export interface Pagination {
  page: number;
  limit: number;
  total: number;
  has_more: boolean;
}

export interface Meta {
  workspace_id?: string;
  [key: string]: unknown;
}

// ── Analytics types ────────────────────────────────────────────────────────────

export interface AnalyticsOverview {
  accounts: {
    total: number;
    covered: number;
    coverage_pct: number;
    total_pipeline: number;
    avg_urgency: number;
    avg_health: number;
  };
  drafts: {
    total: number;
    approved: number;
    pending: number;
    dar: number;
    dar_pct: number;
    dar_target: number;
    dar_vs_target: number;
  };
  cost_30d_usd: number;
}

export interface DarTrendPoint {
  date: string;
  generated: number;
  approved: number;
  dar_pct: number;
}

export interface CostTrendPoint {
  date: string;
  cost_usd: number;
  prompt_tokens: number;
  completion_tokens: number;
  runs: number;
  nightly_runs: number;
  manual_runs: number;
}

export interface SignalTypeData {
  type: string;
  total: number;
  by_urgency: Record<string, number>;
}

export interface RepPerformanceRow {
  rep_id: string;
  rep_email?: string;
  rep_name?: string;
  total_drafts: number;
  approved: number;
  declined: number;
  pending: number;
  dar_pct: number;
  avg_account_urgency: number;
  accounts_with_drafts: number;
}

export interface SmartFieldSuggestion {
  field_name: string;
  field_label: string;
  current_value: string | null;
  suggested_value: string;
  reason: string;
  source: string;
  confidence: number;
  meddpicc_component: string | null;
  impact: "low" | "medium" | "high";
  status: "pending" | "applied" | "dismissed";
  generated_at: string | null;
  applied_at?: string | null;
  dismissed_at?: string | null;
}

export interface SmartFieldsData {
  suggestions: SmartFieldSuggestion[];
  total: number;
  pending: number;
}

export interface TimelineEvent {
  occurred_at: string | null;
  event_type: string;
  subtype: string | null;
  description: string | null;
  urgency: string | null;
  score: number | null;
  source: string | null;
  event_id: string;
}

export interface ForecastRollup {
  categories: Record<string, { count: number; total_amount: number; accounts: ForecastAccount[] }>;
  ai_vs_crm_deltas: AiVsCrmDelta[];
  week_deltas: WeekDelta[];
  reps: RepRollup[];
  total_pipeline: number;
  overridden_count: number;
  accounts_analyzed: number;
  accounts_total: number;
}

export interface WeekDelta {
  account_id: string;
  name: string;
  amount: number;
  from_category: string;
  to_category: string;
  as_of: string | null;
  reason: string | null;
  owner_rep_id: string | null;
}

export interface RepRollup {
  id: string;
  name: string;
  count: number;
  total_amount: number;
}

export interface ForecastAccount {
  id: string;
  name: string;
  amount: number;
  health_score: number | null;
  confidence: number;
  overridden: boolean;
}

export interface AiVsCrmDelta {
  account_id: string;
  name: string;
  amount: number;
  ai_category: string;
  crm_category: string;
  ai_confidence: number;
  delta: string;
  overridden: boolean;
}

export interface ActivitySummary {
  deal_created_at: string | null;
  first_contact_date: string | null;
  last_meaningful_activity_date: string | null;
  last_inbound_reply_date: string | null;
  last_outbound_email_date: string | null;
  last_meeting_date: string | null;
  days_since_last_activity: number | null;
  days_since_last_inbound: number | null;
  days_since_last_outbound: number | null;
  total_emails_sent: number;
  total_emails_received: number;
  total_meetings: number;
  total_calls: number;
  email_exchange_count: number;
  engagement_depth: "deep" | "active" | "light" | "none" | null;
  total_fireflies_transcripts: number;
  recent_email_history: Array<{ direction: string; date: string; subject: string }>;
}

export interface StalledDeal {
  id: string;
  name: string;
  stage: string | null;
  deal_amount: number | null;
  momentum: string | null;
  days_stuck: number | null;
  urgency_score: number;
  last_agent_run_at: string | null;
}

export interface CompetitorEntry {
  competitor: string;
  deal_count: number;
  total_amount_at_risk: number;
  account_count: number;
}

export interface PlayEntry {
  draft_id?: string;
  play_name: string;
  draft_type: string;
  play_reason?: string;
  /** @deprecated Use `play_reason` instead. */
  reason?: string;
  play_description?: string;
  /** @deprecated Use `play_description` instead. */
  description?: string;
  status?: string;
  created_at?: string | null;
  cooldown_hours?: number;
}

export interface VoiceProfile {
  tone: string;
  avg_word_count: number;
  avg_sentence_length: number;
  common_openers: string[];
  common_ctas: string[];
  avoids: string[];
  signature_style: string;
  analyzed_at: string;
  emails_analyzed: number;
  source: string;
}

export interface TranscriptCommitment {
  text: string;
  owner: "us" | "buyer" | "unknown";
  owner_name: string | null;
}

export interface Transcript {
  id: string | null;
  date: number | string | null;
  title: string | null;
  transcript_url?: string | null;
  participants: string[];
  attendees?: { name: string; email: string }[];
  duration_minutes: number | null;
  summary: string | null;
  keywords?: string[];
  action_items: string[];
  speaker_stats: Record<string, { words?: number; talk_time_pct?: number; sentences?: number }>;
  talk_ratio_rep?: number | null;
  buyer_questions?: { speaker: string; text: string }[];
  buyer_question_count?: number;
  commitments?: TranscriptCommitment[];
}

export interface ConversationIntel {
  calls_total: number;
  calls_last_30d: number;
  last_call_date: number | null;
  days_since_last_call: number | null;
  avg_talk_ratio_rep: number | null;
  eb_identified: boolean;
  eb_attendance: boolean;
  open_buyer_commitments: (TranscriptCommitment & { call_title?: string; call_date?: number })[];
  open_our_commitments: (TranscriptCommitment & { call_title?: string; call_date?: number })[];
  computed_at: string;
}

export interface SharedBriefData {
  account_name: string;
  stage: string | null;
  deal_amount: number | null;
  health_score: number | null;
  ai_forecast: string | null;
  ai_confidence: number | null;
  top_signals: Array<{ type: string; urgency: string; detail: string }>;
  next_actions: Array<{ action: string; reason: string; urgency_score: number }>;
  stakeholders: Array<{ name: string; title?: string; role?: string; sentiment?: string }>;
  meddpicc_overall: number | null;
}

export interface DraftTypePerf {
  type: string;
  total: number;
  approved: number;
  dar_pct: number;
}

export interface TrainingFeedbackRow {
  training_category: string;
  count: number;
}

export interface ForecastAccuracyRow {
  category: string;
  total: number;
  correct: number;
  accuracy_pct: number;
  avg_amount_delta: number;
}

export interface AutomationRule {
  id: string;
  name: string;
  trigger: { type: string; signal_type?: string; threshold?: number };
  action: { type: string; draft_type?: string; next_step_text?: string };
  enabled: boolean;
  cooldown_hours: number;
}

export interface WebhookSubscription {
  id: string;
  url: string;
  events: string[];
  secret: string;
  created_at: string;
}

export interface AiField {
  id: string;
  question: string;
  key: string;
}

export interface TimelineAction {
  id: string;
  account_id: string;
  account_name?: string | null;
  account_stage?: string | null;
  action_type: string;
  title: string;
  reasoning: string | null;
  due_date: string;
  priority: number;
  status: "upcoming" | "today" | "overdue" | "done" | "skipped" | "superseded";
  skip_count: number;
  draft_id: string | null;
  prepared_content: Record<string, unknown> | null;
  source: string | null;
  meddpicc_component: string | null;
  deal_stage_at_creation: string | null;
  created_at: string | null;
  completed_at: string | null;
  completed_notes: string | null;
}

export interface SignalTheme {
  theme: string;
  severity: "critical" | "high" | "medium" | "low";
  summary: string;
  signal_count: number;
  signals: string[];
}

export interface ActivityWeek {
  week: string;
  label: string;
  actions: (TimelineAction & { completed_week: string; completed_date: string })[];
}

export interface WorkspaceHealthCheck {
  name: string;
  ok: boolean;
  weight: number;
  fix: string;
}

export interface WorkspaceHealthScore {
  score: number;
  max: number;
  checks: WorkspaceHealthCheck[];
  missing: WorkspaceHealthCheck[];
  status: "excellent" | "good" | "needs_setup";
}

export interface RulesLogEntry {
  id: string;
  occurred_at: string | null;
  rule_name: string;
  account_name: string;
  account_id: string;
  action_taken: string | null;
}

export interface ExecutionRateWeek {
  week_start: string | null;
  week_label: string;
  total_generated: number;
  completed: number;
  rate_pct: number;
  pending: number;
  skipped: number;
}

export interface ExecutionRateData {
  weeks: ExecutionRateWeek[];
  overall_rate_pct: number;
  total_generated: number;
  total_completed: number;
  target_pct: number;
}

export interface PipelineMovement {
  account_id: string;
  account_name: string;
  deal_amount: number | null;
  from_stage: string;
  to_stage: string;
  direction: "advanced" | "regressed" | "lateral";
  changed_at: string | null;
}

export interface PipelineMovementData {
  movements: PipelineMovement[];
  advanced_count: number;
  regressed_count: number;
  advanced_value: number;
  regressed_value: number;
}

export interface AgentRoiData {
  cost_30d_usd: number;
  run_count_30d: number;
  deals_advanced_30d: number;
  deals_won_90d: number;
  cost_per_deal_advanced_usd: number | null;
  cost_per_deal_won_usd: number | null;
}

export interface ReplyRateData {
  emails_sent: number;
  accounts_contacted: number;
  accounts_replied: number;
  reply_rate_pct: number;
  target_pct: number;
  weekly: { week_start: string | null; week_label: string; sent: number }[];
}

export interface DealVelocityDeal {
  account_id: string;
  name: string;
  stage: string;
  deal_amount: number;
  days_in_stage: number;
  avg_days_for_stage: number;
  days_over_avg: number | null;
  stalled: boolean;
}

export interface DealVelocityData {
  stage_averages: Record<string, { avg_days: number; sample_size: number }>;
  deals: DealVelocityDeal[];
  stalled_count: number;
}

export interface StageFunnelStage {
  stage: string;
  deal_count: number;
  total_value: number;
  avg_health: number;
  avg_urgency: number;
  critical_count: number;
  pct_of_pipeline: number;
}

export interface StageFunnelData {
  stages: StageFunnelStage[];
  total_pipeline: number;
  total_deals: number;
}

export interface WatcherDeltaData {
  signals: { this_week: number; last_week: number; delta: number; critical_this_week: number };
  stage_moves: { this_week: number; last_week: number; delta: number };
  top_urgent_accounts: { account_id: string; name: string; health_score: number; stage: string; urgency_score: number }[];
}

export interface PipelineReviewDeal {
  account_id: string;
  name: string;
  stage: string | null;
  amount: number;
  owner_rep_id: string | null;
  from_category?: string;
  to_category?: string;
  reason?: string | null;
  momentum?: string;
  days_since_buyer_activity?: number | null;
  close_date?: string;
  days_overdue?: number;
  overall_score?: number;
  gaps?: string[];
}

export interface PipelineReviewSection {
  count: number;
  total_amount: number;
  deals: PipelineReviewDeal[];
}

export interface PipelineReview {
  generated_at: string;
  week_of: string;
  moved: PipelineReviewSection;
  stalled: PipelineReviewSection;
  slipped: PipelineReviewSection;
  meddpicc_gaps: PipelineReviewSection;
  no_next_step: PipelineReviewSection;
}

export interface IcpProfile {
  product_name?: string;
  product_description?: string;
  ideal_customer?: string;
  industries?: string[];
  pain_points?: string[];
  differentiators?: string[];
  competitors?: string[];
  reference_stories?: Array<{ industry: string; challenge: string; outcome: string }>;
}

export interface TrainingInsights {
  patterns: Array<{ category: string; count: number }>;
  recent_declines: Array<{ date: string | null; category: string; notes: string }>;
  total_declines: number;
  top_category: string | null;
  top_category_label: string | null;
  learning_summary: string | null;
  category_labels: Record<string, string>;
}

// ── Documents ─────────────────────────────────────────────────────────────────

export type DocType =
  | "proposal"
  | "sales_deck"
  | "battle_card"
  | "business_case"
  | "roi_calculator"
  | "mutual_action_plan";

export interface GeneratedDocument {
  id: string;
  account_id: string;
  doc_type: DocType;
  status: "generating" | "ready" | "failed";
  title: string;
  file_name: string;
  file_format: "docx" | "pptx";
  file_size_bytes: number | null;
  generated_by: string;
  generation_context: Record<string, unknown>;
  grounding_confidence: number | null;
  error_message: string | null;
  created_at: string | null;
}

export const DOC_TYPE_LABELS: Record<DocType, string> = {
  proposal: "Proposal (.docx)",
  sales_deck: "Sales Deck (.pptx)",
  battle_card: "Battle Card (.docx)",
  business_case: "Business Case (.docx)",
  roi_calculator: "ROI Calculator (.docx)",
  mutual_action_plan: "Mutual Action Plan (.docx)",
};

export const documentsApi = {
  list: (accountId: string): Promise<{ data: GeneratedDocument[] }> =>
    request(`/v1/documents?account_id=${accountId}`),

  generate: (accountId: string, docType: DocType): Promise<{ data: { document_id: string; status: string; file_name: string } }> =>
    request("/v1/documents/generate", {
      method: "POST",
      body: JSON.stringify({ account_id: accountId, doc_type: docType }),
    }),

  download: async (documentId: string): Promise<Blob> => {
    // Uses module-level BASE (not a local env re-read) so the URL stays consistent with all other endpoints.
    const res = await fetch(`${BASE}/v1/documents/${documentId}/download`, {
      headers: { ...devAuthHeaders() },
      credentials: "include",
    });
    if (!res.ok) throw new Error(`Download failed: ${res.status}`);
    return res.blob();
  },

  delete: (documentId: string): Promise<{ data: { deleted: boolean } }> =>
    request(`/v1/documents/${documentId}`, { method: "DELETE" }),
};
