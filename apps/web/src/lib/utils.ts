import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

// clsx builds the class string (handles conditionals/arrays); twMerge resolves
// Tailwind conflicts so later classes always win (e.g. "p-4 p-2" → "p-2").
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Shared null/undefined guard used by every formatter below.
// Formatters return "-" (not "" or "0") so empty cells are visually distinct
// from zero — callers must not short-circuit with inline `!= null` checks.
function isNullish(v: unknown): v is null | undefined {
  return v === null || v === undefined;
}

export function formatCurrency(amount: number | null | undefined, currency = "USD"): string {
  if (isNullish(amount)) return "-";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(amount);
}

export function formatCompactCurrency(amount: number | null | undefined): string {
  if (isNullish(amount)) return "-";
  const abs = Math.abs(amount);
  // abs drives the tier comparison so negatives hit the right bucket;
  // amount (signed) is then used in the template so "-$2K" renders correctly.
  if (abs >= 1_000_000) return `$${(amount / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (abs >= 1_000) return `$${Math.round(amount / 1_000)}K`;
  return `$${Math.round(amount)}`;
}

// Expects a 0–1 fraction (e.g. 0.75 → "75%"). Passing a 0–100 integer will
// produce values like "7500%" — callers must normalise before calling.
export function formatPct(value: number | null | undefined): string {
  if (isNullish(value)) return "-";
  return `${Math.round(value * 100)}%`;
}

/**
 * Strips CRM boilerplate suffixes from deal names for display
 * ("Sibanye-Stillwater - New Deal" → "Sibanye-Stillwater").
 * Display-only — search and API calls still use the full name.
 */
export function cleanDealName(name: string | null | undefined): string {
  if (!name) return "";
  // `|| name` preserves the original if trim() yields an empty string
  // (e.g. the name was literally " - New Deal"), preventing a blank display.
  return name.replace(/\s*[-–—~]\s*new deal\s*$/i, "").trim() || name;
}

/**
 * One date style across the app: "Jun 3" (current year) / "Jun 3, 2025".
 * Replaces the mix of raw ISO strings, toLocaleDateString variants, and
 * hand-built labels that put three date formats on one screen.
 */
export function formatDate(value: string | Date | null | undefined): string {
  if (!value) return "-";
  const d = typeof value === "string" ? new Date(value) : value;
  // Invalid date: echo the raw string so the caller sees what arrived rather than
  // a silent "-" that hides a bad ISO value coming from the API.
  if (isNaN(d.getTime())) return typeof value === "string" ? value : "-";
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

// ── Signal / draft type display labels ───────────────────────────────────────

const SIGNAL_LABEL_MAP: Record<string, string> = {
  // MEDDPICC
  meddpicc_gap:                  "MEDDPICC Gap",
  metrics_gap:                   "Metrics Gap",
  // Champion
  champion_dark:                 "Champion Dark",
  champion_departure:            "Champion Departure",
  champion_activity:             "Champion Activity",
  // Competitive
  competitive_threat:            "Competitive Threat",
  competitive_mention:           "Competitive Mention",
  competitive_evaluation_active: "Competitive Evaluation Active",
  competitive_win_risk:          "Competitive Win Risk",
  // Deal health
  deal_stalling:                 "Deal Slip", // intentional alias — backend emits both; UI unifies to one label
  deal_slip:                     "Deal Slip",
  stage_mismatch:                "Stage Mismatch",
  budget_risk:                   "Budget Risk",
  budget_confirmed:              "Budget Confirmed",
  close_plan_missing:            "Close Plan Missing",
  close_plan_stale:              "Close Plan Stale",
  blocker_identified:            "Blocker Identified",
  engagement_trend_declining:    "Engagement Trend Declining",
  single_thread_risk:            "Single Thread Risk",
  decision_criteria_undefined:   "Decision Criteria Undefined",
  // EB / stakeholder
  economic_buyer_dark:           "Economic Buyer Dark",
  economic_buyer_identified:     "Economic Buyer Identified",
  economic_buyer_engaged:        "Economic Buyer Engaged",
  new_stakeholder_added:         "New Stakeholder Added",
  buying_committee_expanded:     "Buying Committee Expanded",
  // Legal / process
  legal_review_started:          "Legal Review Started",
  procurement_engaged:           "Procurement Engaged",
  paper_process_delay:           "Paper Process Delay",
  mutual_action_plan_created:    "Mutual Action Plan Created",
  decision_timeline_set:         "Decision Timeline Set",
  // Positive signals
  expansion_opportunity:         "Expansion Opportunity",
  pilot_success:                 "Pilot Success",
  roi_case_built:                "ROI Case Built",
  implicate_pain:                "Implicate Pain",
  implicate_pain_confirmed:      "Implicate Pain Confirmed",
  evaluation_started:            "Evaluation Started",
  reference_requested:           "Reference Requested",
  product_launch:                "Product Launch",
  acquisition_news:              "Acquisition News",
  // QBR / renewal
  qbr_overdue:                   "QBR Overdue",
  renewal_risk:                  "Renewal Risk",
  contract_expiring_90d:         "Contract Expiring 90d",
  usage_drop:                    "Usage Drop",
  usage_decline_30d:             "Usage Decline 30d",
  deal_velocity_signals:         "Deal Velocity Signals",
};

// Canonical urgency buckets — every surface must use the same thresholds.
// (Divergent copies once labelled a 0.65 deal "high" on one page and "medium"
// on another.) Matches backend config: 0.85 alert threshold, 0.7 agent threshold.
export type UrgencyLevel = "critical" | "high" | "medium" | "low";

// Thresholds mirror backend constants (ALERT_THRESHOLD=0.85, AGENT_THRESHOLD=0.7
// in app/config.py) — keep in sync if backend values change.
export function urgencyLevel(score: number | null | undefined): UrgencyLevel {
  const s = score ?? 0;
  if (s >= 0.85) return "critical";
  if (s >= 0.7) return "high";
  if (s >= 0.5) return "medium";
  return "low";
}

export function signalLabel(type: string): string {
  if (!type) return "";
  return SIGNAL_LABEL_MAP[type] ?? snakeToTitle(type);
}

const DRAFT_TYPE_LABEL_MAP: Record<string, string> = {
  email_followup:              "Email Follow-up",
  meeting_brief:               "Meeting Brief",
  roi_business_case:           "ROI Business Case",
  outreach_sequence:           "Outreach Sequence",
  nurture_cadence:             "Nurture Cadence",
  champion_reengagement:       "Champion Re-engagement",
  competitive_displacement:    "Competitive Displacement",
  close_plan_proposal:         "Close Plan Proposal",
  executive_alignment:         "Executive Alignment",
  renewal_brief:               "Renewal Brief",
  expansion_pitch:             "Expansion Pitch",
  follow_up:                   "Follow-up",
  meeting_prep:                "Meeting Prep",
  intro_email:                 "Intro Email",
  proposal_follow_up:          "Proposal Follow-up",
  discovery_summary:           "Discovery Summary",
  account_brief:               "Account Brief",
};

// Title-casing snake_case produces wrong casing for known acronyms; fix them after.
// IMPORTANT: the regex keys below ("Crm", "Ai", …) are the Title-Cased forms produced
// by the first replace pass and must stay in sync if you add entries to ACRONYM_FIX.
const ACRONYM_FIX: Record<string, string> = { Crm: "CRM", Ai: "AI", Qbr: "QBR", Roi: "ROI" };
const ACRONYM_RE = new RegExp(`\\b(${Object.keys(ACRONYM_FIX).join("|")})\\b`, "g");

/** Converts snake_case to Title Case, then restores known acronyms. */
function snakeToTitle(s: string): string {
  return s
    .replace(/_/g, " ")
    .replace(/\b\w/g, c => c.toUpperCase())
    .replace(ACRONYM_RE, m => ACRONYM_FIX[m] ?? m);
}

export function draftTypeLabel(type: string): string {
  if (!type) return "";
  // Strip "internal_" prefix, then apply shared snake → Title Case conversion.
  return DRAFT_TYPE_LABEL_MAP[type] ?? snakeToTitle(type.replace(/^internal_/i, ""));
}
