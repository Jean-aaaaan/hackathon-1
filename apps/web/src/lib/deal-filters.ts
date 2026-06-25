/**
 * Canonical deal filter/sort/rank engine.
 *
 * Every surface that lists deals (Today, Deal Book, future views) must use
 * this — filtering, ranking, and sorting were previously hand-rolled per page
 * with divergent semantics. One engine, one set of thresholds, one behavior.
 */
import type { AccountListItem } from "@/lib/api";

export type DealSortKey =
  | "priority"   // dollar-weighted urgency — the Today queue ranking
  | "urgency"
  | "amount"
  | "close"      // soonest close date first (asc is the natural direction)
  | "health"
  | "swept"      // most recently agent-run first
  | "name";

export type SortDir = "asc" | "desc";
export type HealthBand = "all" | "good" | "fair" | "poor";

export interface DealFilterState {
  q: string;             // free-text search against account name
  stages: string[];      // empty = all stages
  categories: string[];  // empty = all forecast categories
  health: HealthBand;
  draftsOnly: boolean;
  sort: DealSortKey;
  dir: SortDir;
}

export const FORECAST_CATEGORIES = ["Commit", "Best Case", "Pipeline", "Omit"] as const;

export const DEFAULT_FILTERS: DealFilterState = {
  q: "",
  stages: [],
  categories: [],
  health: "all",
  draftsOnly: false,
  sort: "urgency",
  dir: "desc",
};

/**
 * True when any non-default filter is active — used by UIs to show a "clear"
 * affordance only when there is actually something to clear.
 */
export function hasActiveFilters(f: DealFilterState): boolean {
  return Boolean(
    f.q || f.stages.length || f.categories.length || f.health !== "all" || f.draftsOnly
  );
}

/**
 * Dollar-weighted priority: urgency leads, deal size breaks ties and lifts
 * the deals where attention is worth the most. $1M ≈ full weight.
 */
export function dealPriority(a: AccountListItem): number {
  // log10(1_000_000 + 1) ≈ 6 — divisor chosen so a $1 M deal contributes full weight
  const amountFactor = Math.min(1, Math.log10((a.deal_amount ?? 0) + 1) / 6);
  // 0.6/0.4 split: urgency owns the ranking; deal size is a tie-breaker, not the driver.
  // Calibrated so a $250 k deal still rises above a $0 deal at equal urgency.
  return (a.urgency_score ?? 0) * (0.6 + 0.4 * amountFactor);
}

/**
 * Unique stages present in the data, biggest group first — so the most
 * common stages surface at the top of filter dropdowns without manual ordering.
 */
export function stageOptions(accounts: AccountListItem[]): string[] {
  const counts = new Map<string, number>();
  for (const a of accounts) {
    const s = (a.stage ?? "").trim();
    if (!s || /^\d{6,}$/.test(s)) continue; // skip empty + raw HubSpot stage IDs
    counts.set(s, (counts.get(s) ?? 0) + 1);
  }
  return [...counts.entries()].sort((x, y) => y[1] - x[1]).map(([s]) => s);
}

/** Parse an ISO date string to a Unix ms timestamp, returning fallback when absent. */
function toTimestamp(iso: string | null | undefined, fallback: number): number {
  return iso ? new Date(iso).getTime() : fallback;
}

function healthBand(score: number | null | undefined): HealthBand {
  // Returning "all" for a null score is intentional: the filter condition
  // `f.health !== "all"` then short-circuits, so unscored deals always pass
  // through regardless of what band the user selected.
  if (score == null) return "all";
  // 0.7/0.4 thresholds mirror the risk-scanner's own calibration bands — keep in sync
  // with RiskScannerAgent if those bands ever shift.
  if (score >= 0.7) return "good";
  if (score >= 0.4) return "fair";
  return "poor";
}

function getSortValues(
  key: DealSortKey,
  a: AccountListItem,
  b: AccountListItem,
  dir: SortDir
): [number | string, number | string] {
  switch (key) {
    case "priority": return [dealPriority(a), dealPriority(b)];
    case "urgency":  return [a.urgency_score ?? 0, b.urgency_score ?? 0];
    case "amount":   return [a.deal_amount ?? 0, b.deal_amount ?? 0];
    case "close": {
      // missing close dates always sink to the bottom regardless of direction
      const missing = dir === "asc" ? Infinity : -Infinity;
      return [toTimestamp(a.close_date, missing), toTimestamp(b.close_date, missing)];
    }
    // -1 sentinel sinks unscored deals below 0.0 (the lowest valid score) in both directions
    case "health":   return [a.health_score ?? -1, b.health_score ?? -1];
    // 0 sentinel sinks never-run deals to epoch (1970) — below any real run timestamp
    case "swept":    return [toTimestamp(a.last_agent_run_at, 0), toTimestamp(b.last_agent_run_at, 0)];
    case "name":     return [a.name.toLowerCase(), b.name.toLowerCase()];
    default:         return [0, 0]; // exhaustive guard — new DealSortKey values produce stable no-op sort
  }
}

export function filterAndSortDeals(
  accounts: AccountListItem[],
  f: DealFilterState
): AccountListItem[] {
  const query = f.q.trim().toLowerCase();

  const filtered = accounts.filter(a => {
    if (query && !a.name.toLowerCase().includes(query)) return false;
    if (f.stages.length && !f.stages.includes((a.stage ?? "").trim())) return false;
    if (f.categories.length && !f.categories.includes(a.pov_forecast_cat ?? "")) return false;
    if (f.health !== "all" && healthBand(a.health_score) !== f.health) return false;
    if (f.draftsOnly && (a.pending_drafts ?? 0) === 0) return false;
    return true;
  });

  const dirMul = f.dir === "asc" ? 1 : -1;
  return [...filtered].sort((a, b) => {
    const [va, vb] = getSortValues(f.sort, a, b, f.dir);
    if (va < vb) return -1 * dirMul;
    if (va > vb) return 1 * dirMul;
    return 0;
  });
}

/**
 * Natural direction when switching to a sort key — prevents UIs from needing
 * to hard-code per-key defaults. Close and name read most naturally ascending;
 * all score-based keys default descending so the best deals surface first.
 */
export function defaultDirFor(sort: DealSortKey): SortDir {
  return sort === "close" || sort === "name" ? "asc" : "desc";
}

// ── Per-page persistence (sessionStorage — survives navigation, not tabs) ─────

const storageKey = (pageKey: string) => `deal-filters:${pageKey}`;

/**
 * SSR guard + try/catch wrapper for sessionStorage ops; returns fallback on error or server.
 * Errors are intentionally swallowed — corrupted/stale JSON in storage should reset to
 * defaults silently rather than crash the page (private mode also throws on storage access).
 */
function withStorage<T>(op: () => T, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try { return op(); } catch { return fallback; }
}

export function loadFilters(pageKey: string, overrides?: Partial<DealFilterState>): DealFilterState {
  const base = { ...DEFAULT_FILTERS, ...overrides };
  return withStorage(() => {
    const raw = sessionStorage.getItem(storageKey(pageKey));
    if (!raw) return base;
    const parsed = JSON.parse(raw);
    // base spreads first so that any new fields added to DEFAULT_FILTERS
    // (schema evolution) get their defaults before persisted values override.
    return { ...base, ...parsed };
  }, base);
}

export function saveFilters(pageKey: string, state: DealFilterState): void {
  // storage full / private mode — filters just don't persist
  withStorage(() => { sessionStorage.setItem(storageKey(pageKey), JSON.stringify(state)); }, undefined);
}
