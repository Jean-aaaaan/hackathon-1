"use client";

import React, { Suspense, useState, useEffect, useMemo, useCallback } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import {
  accountsApi, draftsApi, signalsApi, timelineApi,
  type AccountListItem, type Draft, type TimelineAction,
} from "@/lib/api";
import { SearchResults } from "@/components/inbox/search-results";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Search, Zap, CheckCircle, ChevronDown, ArrowUpRight,
  AlertTriangle, Clock, X, ExternalLink, BarChart3, Sparkles, BookOpen,
} from "lucide-react";
import { cn, signalLabel, draftTypeLabel, formatCompactCurrency, cleanDealName, urgencyLevel, formatPct } from "@/lib/utils";
import { DealFilterBar } from "@/components/deal-filter-bar";
import { type DealFilterState, filterAndSortDeals, loadFilters, saveFilters, hasActiveFilters, dealPriority } from "@/lib/deal-filters";
import { MarkdownContent } from "@/components/markdown-content";
import { toast } from "sonner";

// ── Urgency helpers ───────────────────────────────────────────────────────────


const URGENCY_DOT: Record<string, string> = {
  critical: "bg-red-500 animate-[urgency-pulse_2s_ease-in-out_infinite]",
  high:     "bg-orange-400",
  medium:   "bg-amber-400",
  low:      "bg-emerald-400",
};

const URGENCY_TEXT: Record<string, string> = {
  critical: "text-red-600",
  high:     "text-orange-600",
  medium:   "text-amber-700",
  low:      "text-emerald-700",
};

const DECLINE_CATEGORIES = [
  { value: "wrong_tone",    label: "Wrong tone" },
  { value: "wrong_timing",  label: "Wrong timing" },
  { value: "already_sent",  label: "Already sent" },
  { value: "wrong_content", label: "Wrong content" },
  { value: "not_relevant",  label: "Not relevant" },
  { value: "other",         label: "Other" },
];

const MEDDPICC_KEYS = [
  "metrics", "economic_buyer", "decision_criteria", "decision_process",
  "implicate_pain", "champion", "competition", "paper_process",
] as const;

const MEDDPICC_SHORT: Record<string, string> = {
  metrics: "Metrics",
  economic_buyer: "Econ. Buyer",
  decision_criteria: "Dec. Criteria",
  decision_process: "Dec. Process",
  implicate_pain: "Pain",
  champion: "Champion",
  competition: "Competition",
  paper_process: "Paper",
};

const FORECAST_STYLES: Record<string, string> = {
  Commit: "bg-emerald-50 text-emerald-700 border-emerald-200",
  "Best Case": "bg-sky-50 text-sky-700 border-sky-200",
  Pipeline: "bg-violet-50 text-violet-700 border-violet-200",
  Omit: "bg-gray-100 text-gray-500 border-gray-200",
};

function meddpiccBarColor(score: number) {
  if (score >= 0.6) return "bg-emerald-400";
  if (score >= 0.3) return "bg-amber-400";
  return "bg-red-400";
}

// ── Deal card (left panel) ───────────────────────────────────────────────────

function daysToClose(closeDate: string | null): number | null {
  if (!closeDate) return null;
  const d = Math.ceil((new Date(closeDate).getTime() - Date.now()) / 86_400_000);
  return Number.isFinite(d) ? d : null;
}

function DealCard({
  account,
  isSelected,
  onClick,
  queueRank,
}: {
  account: AccountListItem;
  isSelected: boolean;
  onClick: () => void;
  queueRank?: number;
}) {
  const urgency = account.urgency_score ?? 0;
  const level = urgencyLevel(urgency);
  const topSignal = account.signals_summary?.[0];
  const sigUrgency = (topSignal as any)?.urgency ?? "medium";
  const closeIn = daysToClose(account.close_date);

  return (
    <button
      onClick={onClick}
      data-deal-card
      className={cn(
        "w-full text-left px-3.5 py-2.5 transition-colors border-b border-zinc-100 last:border-0",
        isSelected ? "bg-zinc-50" : "hover:bg-zinc-50/60"
      )}
    >
      {/* Name + urgency dot */}
      <div className="flex items-center justify-between gap-2">
        <p className="text-[13px] font-medium text-zinc-900 truncate" title={account.name}>
          {cleanDealName(account.name)}
        </p>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {account.pending_drafts > 0 && (
            <span className="text-[11px] text-zinc-400 tabular-nums">
              {account.pending_drafts}d
            </span>
          )}
          <span className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0", URGENCY_DOT[level])} />
        </div>
      </div>

      {/* Signal + meta row */}
      <div className="flex items-center gap-2 mt-0.5">
        {topSignal ? (
          <p className="text-[12px] text-zinc-400 truncate flex-1">
            {signalLabel((topSignal as any).type)}
            {(topSignal as any).detail && ` · ${(topSignal as any).detail}`}
          </p>
        ) : (
          <p className="text-[12px] text-zinc-400 flex-1">{account.stage}</p>
        )}
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {account.deal_amount && (
            <span className="text-[11px] text-zinc-400 tabular-nums">{formatCompactCurrency(account.deal_amount)}</span>
          )}
          {closeIn !== null && closeIn < 0 && (
            <span className="text-[11px] text-red-400">{-closeIn}d late</span>
          )}
          {queueRank ? (
            <span className="text-[11px] text-zinc-400">#{queueRank}</span>
          ) : (
            <span className="text-[11px] text-zinc-400">{Math.round(urgency * 100)}%</span>
          )}
        </div>
      </div>
    </button>
  );
}

// ── Inline draft card (right panel) ──────────────────────────────────────────

function DraftCard({
  draft,
  accountId,
  onReviewed,
  enableKeys = false,
}: {
  draft: Draft;
  accountId: string;
  onReviewed: () => void;
  enableKeys?: boolean;
}) {
  const qc = useQueryClient();
  const [declining, setDeclining] = useState(false);
  const [declineCategory, setDeclineCategory] = useState("");
  const [declineNotes, setDeclineNotes] = useState("");

  const reviewMutation = useMutation({
    mutationFn: ({ verdict, category, notes }: { verdict: "approved" | "declined"; category?: string; notes?: string }) =>
      draftsApi.review(draft.id, { action: verdict, training_category: category, reviewer_notes: notes }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["drafts", accountId] });
      qc.invalidateQueries({ queryKey: ["drafts", "pending", "count"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      toast.success(vars.verdict === "approved" ? "Draft approved." : "Draft declined.");
      onReviewed();
    },
    onError: () => toast.error("Could not update draft."),
  });

  // E = approve, D = decline — only the queue's top draft listens
  useEffect(() => {
    if (!enableKeys) return;
    const handler = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || (e.target as HTMLElement)?.isContentEditable) return;
      if (reviewMutation.isPending) return;
      if ((e.key === "e" || e.key === "E") && !declining) {
        e.preventDefault();
        reviewMutation.mutate({ verdict: "approved" });
      }
      if (e.key === "d" || e.key === "D") {
        e.preventDefault();
        setDeclining(true);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enableKeys, declining, reviewMutation.isPending]);

  const typeLabel = draftTypeLabel(draft.type ?? "email");

  return (
    <div className="bg-white rounded-md border border-zinc-200 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-100">
        <div className="flex items-center gap-2">
          <span className="text-[12px] font-medium text-zinc-700">{typeLabel}</span>
          {draft.subject_line && (
            <span className="text-[12px] text-zinc-400 truncate max-w-[200px]">{draft.subject_line}</span>
          )}
        </div>
        <Link
          href={`/account/${accountId}?tab=act`}
          className="text-[11px] text-zinc-400 hover:text-zinc-700 flex items-center gap-0.5 transition-colors"
        >
          War Room <ExternalLink className="w-3 h-3" />
        </Link>
      </div>

      {/* Full draft body — never clamp what the rep is approving */}
      <div className="px-4 py-3">
        <MarkdownContent content={draft.content ?? ""} />
      </div>

      {/* Actions */}
      <div className="px-4 py-3 border-t border-zinc-100 flex items-center gap-2">
        {!declining ? (
          <>
            <button
              onClick={() => reviewMutation.mutate({ verdict: "approved" })}
              disabled={reviewMutation.isPending}
              className="flex items-center gap-1.5 text-xs font-medium px-3.5 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            >
              <CheckCircle className="w-3.5 h-3.5" />
              Approve
            </button>
            <button
              onClick={() => setDeclining(true)}
              className="text-xs font-medium px-3.5 py-2 border border-zinc-200 text-zinc-600 rounded-md hover:bg-zinc-50 transition-colors"
            >
              Decline
            </button>
          </>
        ) : (
          <div className="flex-1 space-y-2">
            <div className="flex flex-wrap gap-1.5">
              {DECLINE_CATEGORIES.map(cat => (
                <button
                  key={cat.value}
                  onClick={() => setDeclineCategory(cat.value)}
                  className={cn(
                    "text-xs px-2.5 py-1 rounded border transition-colors",
                    declineCategory === cat.value
                      ? "bg-zinc-800 text-white border-zinc-800"
                      : "border-zinc-200 text-zinc-500 hover:border-zinc-400"
                  )}
                >
                  {cat.label}
                </button>
              ))}
            </div>
            <textarea
              value={declineNotes}
              onChange={e => setDeclineNotes(e.target.value)}
              placeholder="Notes (optional)"
              rows={2}
              className="w-full text-xs border border-zinc-200 rounded-md px-2.5 py-2 resize-none focus:outline-none focus:border-zinc-400"
            />
            <div className="flex items-center gap-2">
              <button
                onClick={() => reviewMutation.mutate({ verdict: "declined", category: declineCategory || undefined, notes: declineNotes || undefined })}
                disabled={reviewMutation.isPending}
                className="text-xs font-medium px-3 py-1.5 bg-zinc-800 text-white rounded-md hover:bg-zinc-900 disabled:opacity-50 transition-colors"
              >
                Confirm Decline
              </button>
              <button
                onClick={() => { setDeclining(false); setDeclineCategory(""); setDeclineNotes(""); }}
                className="text-xs text-zinc-400 hover:text-zinc-600"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── War Room hero (shown when no drafts — primary right-panel experience) ─────

function WarRoomHero({ account }: { account: AccountListItem }) {
  const id = account.id;
  const warRoomHref = `/account/${id}?center=intel`;

  const { data: stateData, isLoading } = useQuery({
    queryKey: ["account", id, "state", "inbox-war-room"],
    queryFn: () => accountsApi.getState(id),
    staleTime: 5 * 60 * 1000,
  });

  const state = (stateData?.data ?? {}) as Record<string, unknown>;
  const pov = (state.pov ?? {}) as Record<string, unknown>;
  const meddpicc = (pov.meddpicc ?? {}) as Record<string, unknown>;
  const narrative = (
    account.deal_narrative
    ?? (pov.deal_narrative as string | undefined)
    ?? (pov.forecast_rationale as string | undefined)
  );
  const topRisk = account.top_risk_summary ?? (pov.top_risk_summary as string | undefined);
  const overall = typeof meddpicc.overall_score === "number" ? meddpicc.overall_score : null;
  const gapRisk = meddpicc.gap_risk as string | undefined;
  const details = (meddpicc.detail ?? {}) as Record<string, string>;
  const forecast = account.pov_forecast_cat ?? (pov.forecast_category as string | undefined);
  const hasMeddpicc = overall != null || MEDDPICC_KEYS.some(k => typeof meddpicc[k] === "number");

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl mx-auto space-y-5">

          {/* Prompt banner */}
          <div className="rounded-2xl bg-gradient-to-br from-indigo-600 to-indigo-700 text-white px-6 py-5 shadow-md">
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1.5">
                  <Zap className="w-4 h-4 text-indigo-200 flex-shrink-0" />
                  <p className="text-[11px] font-bold uppercase tracking-widest text-indigo-200">
                    No drafts pending
                  </p>
                </div>
                <h3 className="text-lg font-semibold leading-snug">
                  Open the War Room for {cleanDealName(account.name)}
                </h3>
                <p className="text-sm text-indigo-100 mt-1.5 leading-relaxed max-w-xl">
                  Review MEDDPICC scores, deal story, meeting intel, and AI-recommended next moves — all in one place.
                </p>
              </div>
              <div className="flex flex-col sm:flex-row gap-2 flex-shrink-0">
                <Link
                  href={warRoomHref}
                  className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl bg-white text-indigo-700 text-sm font-semibold hover:bg-indigo-50 transition-colors shadow-sm"
                >
                  Open War Room
                  <ArrowUpRight className="w-4 h-4" />
                </Link>
                <Link
                  href="/deals"
                  className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-indigo-400/60 text-indigo-100 text-sm font-medium hover:bg-indigo-500/40 transition-colors"
                >
                  <BookOpen className="w-3.5 h-3.5" />
                  Deal Book
                </Link>
              </div>
            </div>
          </div>

          {isLoading ? (
            <div className="space-y-4">
              <Skeleton className="h-28 rounded-2xl" />
              <Skeleton className="h-48 rounded-2xl" />
            </div>
          ) : (
            <>
              {/* Deal story */}
              {narrative && (
                <div className="bg-white rounded-2xl border border-zinc-200 p-5 shadow-sm">
                  <div className="flex items-center gap-2 mb-3">
                    <Sparkles className="w-4 h-4 text-indigo-500" />
                    <p className="text-sm font-semibold text-zinc-900">AI Deal Story</p>
                  </div>
                  <p className="text-[15px] text-zinc-700 leading-relaxed">{narrative}</p>
                </div>
              )}

              {/* Top risk */}
              {topRisk && (
                <div className="flex items-start gap-3 rounded-2xl border border-red-200 bg-red-50 px-5 py-4">
                  <AlertTriangle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
                  <p className="text-sm text-red-800 leading-relaxed">{topRisk}</p>
                </div>
              )}

              {/* MEDDPICC preview */}
              {hasMeddpicc && (
                <div className="bg-white rounded-2xl border border-zinc-200 p-5 shadow-sm">
                  <div className="flex items-center gap-2 mb-4 flex-wrap">
                    <BarChart3 className="w-4 h-4 text-indigo-500" />
                    <p className="text-sm font-semibold text-zinc-900">MEDDPICC Qualification</p>
                    {overall != null && (
                      <span className={cn(
                        "text-sm font-bold tabular-nums ml-1",
                        overall < 0.3 ? "text-red-600" : overall < 0.6 ? "text-amber-600" : "text-emerald-600"
                      )}>
                        {formatPct(overall)}
                      </span>
                    )}
                    {gapRisk && (
                      <span className={cn(
                        "text-[11px] font-semibold px-2 py-0.5 rounded-full border ml-auto",
                        gapRisk === "critical" ? "bg-red-100 text-red-700 border-red-200" :
                        gapRisk === "high" ? "bg-orange-100 text-orange-700 border-orange-200" :
                        "bg-amber-100 text-amber-700 border-amber-200"
                      )}>
                        {gapRisk} gap risk
                      </span>
                    )}
                    {forecast && (
                      <span className={cn(
                        "text-[11px] font-semibold px-2 py-0.5 rounded-full border",
                        FORECAST_STYLES[forecast] ?? FORECAST_STYLES.Pipeline
                      )}>
                        {forecast}
                      </span>
                    )}
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
                    {MEDDPICC_KEYS.map(k => {
                      const raw = meddpicc[k];
                      const score = typeof raw === "number" ? raw : 0;
                      const pct = Math.round(score * 100);
                      const detail = details[k];
                      const isGap = score < 0.5;
                      return (
                        <div key={k} className="min-w-0">
                          <div className="flex items-center justify-between gap-2 mb-1">
                            <span className={cn(
                              "text-xs truncate",
                              isGap ? "text-red-700 font-semibold" : "text-zinc-500"
                            )}>
                              {MEDDPICC_SHORT[k]}
                            </span>
                            <span className={cn(
                              "text-xs font-bold tabular-nums flex-shrink-0",
                              score < 0.3 ? "text-red-600" : score < 0.6 ? "text-amber-600" : "text-emerald-600"
                            )}>
                              {pct}%
                            </span>
                          </div>
                          <div className="h-2 bg-zinc-100 rounded-full overflow-hidden">
                            <div
                              className={cn("h-full rounded-full transition-all", meddpiccBarColor(score))}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          {detail && isGap && (
                            <p className="text-[11px] text-zinc-500 mt-1 leading-snug line-clamp-2">{detail}</p>
                          )}
                        </div>
                      );
                    })}
                  </div>
                  <Link
                    href={warRoomHref}
                    className="mt-4 inline-flex items-center gap-1 text-xs font-semibold text-indigo-600 hover:text-indigo-700"
                  >
                    Full scorecard &amp; meeting intel in War Room
                    <ArrowUpRight className="w-3.5 h-3.5" />
                  </Link>
                </div>
              )}

              {!narrative && !hasMeddpicc && !topRisk && (
                <div className="bg-white rounded-2xl border border-dashed border-zinc-200 px-6 py-10 text-center">
                  <BarChart3 className="w-8 h-8 text-zinc-300 mx-auto mb-3" />
                  <p className="text-sm font-medium text-zinc-600">Agent hasn&apos;t analysed this deal yet</p>
                  <p className="text-xs text-zinc-400 mt-1 mb-4">Run agents from the top bar, then open the War Room for the full picture.</p>
                  <Link
                    href={warRoomHref}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-zinc-900 text-white text-sm font-medium hover:bg-zinc-800 transition-colors"
                  >
                    Go to War Room
                    <ArrowUpRight className="w-4 h-4" />
                  </Link>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Deal context panel (right panel when deal selected) ───────────────────────

function DealContextPanel({ account }: { account: AccountListItem }) {
  const qc = useQueryClient();
  const id = account.id;
  const urgency = account.urgency_score ?? 0;
  const level = urgencyLevel(urgency);

  // Pending drafts for this account
  const { data: draftsData, isLoading: draftsLoading } = useQuery({
    queryKey: ["drafts", id, "pending"],
    queryFn: () => draftsApi.list({ account_id: id, status: "pending", limit: 5 }),
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000,
  });
  const drafts: Draft[] = useMemo(() => {
    const seen = new Set<string>();
    return (draftsData?.data ?? []).filter(d => { if (seen.has(d.id)) return false; seen.add(d.id); return true; });
  }, [draftsData]);

  // Timeline actions for this account
  const { data: timelineData, isLoading: actionsLoading } = useQuery({
    queryKey: ["timeline", id, "actions"],
    queryFn: () => timelineApi.getForAccount(id),
    staleTime: 2 * 60 * 1000,
  });
  const overdueActions: TimelineAction[] = timelineData?.data?.overdue ?? [];
  const todayActions: TimelineAction[] = timelineData?.data?.upcoming?.filter((a: TimelineAction) => a.status === "today") ?? [];
  const urgentActions = [...overdueActions, ...todayActions].slice(0, 4);

  // Mark action done
  const patchMutation = useMutation({
    mutationFn: ({ actionId, action }: { actionId: string; action: "complete" | "skip" }) =>
      timelineApi.patch(actionId, { action }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["timeline", id] });
      toast.success("Action updated.");
    },
  });

  // Signals from account list item
  const signals = account.signals_summary ?? [];

  const closeDate = account.close_date
    ? new Date(account.close_date).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
    : null;

  const warRoomFocus = !draftsLoading && drafts.length === 0;

  return (
    <div className="h-full flex flex-col bg-zinc-50 min-h-0">
      {/* Deal header — compact when War Room is the main view */}
      <div className={cn(
        "bg-white border-b border-zinc-100 flex-shrink-0",
        warRoomFocus ? "px-6 py-3" : "px-6 py-4"
      )}>
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <h2 className={cn(
              "font-semibold text-zinc-900 truncate",
              warRoomFocus ? "text-base" : "text-[15px]"
            )} title={account.name}>
              {cleanDealName(account.name)}
            </h2>
            <div className="flex items-center gap-2.5 mt-1 flex-wrap">
              <span className="text-[12px] text-zinc-400">{account.stage}</span>
              {account.deal_amount ? (
                <span className="text-[12px] text-zinc-600">{formatCompactCurrency(account.deal_amount)}</span>
              ) : null}
              {closeDate && (
                <span className="text-[12px] text-zinc-400 flex items-center gap-1">
                  <Clock className="w-3 h-3" /> {closeDate}
                </span>
              )}
              {account.pov_forecast_cat && (
                <span className={cn(
                  "text-[10px] font-semibold px-1.5 py-0.5 rounded-full border",
                  FORECAST_STYLES[account.pov_forecast_cat] ?? FORECAST_STYLES.Pipeline
                )}>
                  {account.pov_forecast_cat}
                </span>
              )}
              <span className="text-[12px] text-zinc-400 flex items-center gap-1">
                <span className={cn("w-1.5 h-1.5 rounded-full", URGENCY_DOT[level])} />
                {Math.round(urgency * 100)}% urgency
              </span>
            </div>
          </div>
          {!warRoomFocus && (
            <Link
              href={`/account/${id}?center=intel`}
              className="flex-shrink-0 flex items-center gap-1 text-xs font-medium text-zinc-500 hover:text-zinc-900 border border-zinc-200 hover:border-zinc-300 rounded-md px-3 py-1.5 transition-colors bg-white"
            >
              War Room <ArrowUpRight className="w-3.5 h-3.5" />
            </Link>
          )}
        </div>
      </div>

      {warRoomFocus ? (
        <WarRoomHero account={account} />
      ) : (
        <div className="flex-1 overflow-y-auto p-5 space-y-5 min-h-0">
          {/* What to do */}
          {(actionsLoading || urgentActions.length > 0) && (
            <div>
              <p className="page-section">What to do</p>
              {actionsLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-10 rounded-xl" />
                  <Skeleton className="h-10 rounded-xl" />
                </div>
              ) : (
                <div className="bg-white rounded-lg border border-zinc-200 divide-y divide-zinc-100">
                  {urgentActions.map(action => (
                    <div key={action.id} className="flex items-center gap-3 px-4 py-3">
                      <div className="flex-shrink-0 w-12 text-right">
                        {action.status === "overdue" ? (
                          <span className="text-[11px] text-red-400">Overdue</span>
                        ) : (
                          <span className="text-[11px] text-zinc-400">Today</span>
                        )}
                      </div>
                      <p className="flex-1 text-[13px] text-zinc-700 truncate">{action.title}</p>
                      <div className="flex items-center gap-1.5 flex-shrink-0">
                        <button
                          onClick={() => patchMutation.mutate({ actionId: action.id, action: "complete" })}
                          title="Mark done"
                          className="p-1.5 rounded hover:bg-zinc-100 text-zinc-300 hover:text-zinc-600 transition-colors"
                        >
                          <CheckCircle className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Pending drafts */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <p className="page-section !mb-0">Pending drafts</p>
              <span className="text-[11px] text-zinc-400">{drafts.length} waiting</span>
            </div>
            {draftsLoading ? (
              <div className="space-y-3">
                <Skeleton className="h-40 rounded-xl" />
              </div>
            ) : (
              <div className="space-y-3">
                {drafts.map((draft, i) => (
                  <DraftCard
                    key={draft.id}
                    draft={draft}
                    accountId={id}
                    onReviewed={() => {}}
                    enableKeys={i === 0}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Signals */}
          {signals.length > 0 && (
            <div>
              <p className="page-section">Top signals</p>
              <div className="bg-white rounded-lg border border-zinc-200 divide-y divide-zinc-100">
                {signals.slice(0, 5).map((signal, i) => {
                  const sigUrgency = (signal as any).urgency ?? "medium";
                  const dotColor = sigUrgency === "critical" ? "bg-red-500" : sigUrgency === "high" ? "bg-orange-400" : "bg-amber-300";
                  return (
                    <div key={i} className="flex items-start gap-3 px-4 py-3">
                      <span className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0 mt-1.5", dotColor)} />
                      <div className="flex-1 min-w-0">
                        <p className="text-[12px] font-medium text-zinc-700">{signalLabel((signal as any).type)}</p>
                        {(signal as any).detail && (
                          <p className="text-[12px] text-zinc-500 mt-0.5 line-clamp-2">{(signal as any).detail}</p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Empty right panel state ───────────────────────────────────────────────────

function EmptyPanel({ pendingCount }: { pendingCount: number }) {
  return (
    <div className="h-full flex items-center justify-center bg-zinc-50 px-6">
      <div className="text-center max-w-md">
        <div className="w-12 h-12 bg-indigo-100 rounded-2xl mx-auto mb-4 flex items-center justify-center">
          <Zap className="w-5 h-5 text-indigo-600" />
        </div>
        <p className="text-base font-semibold text-zinc-800">Select a deal</p>
        <p className="text-sm text-zinc-500 mt-2 leading-relaxed">
          {pendingCount > 0
            ? `${pendingCount} draft${pendingCount !== 1 ? "s" : ""} waiting for review — pick a deal from the queue.`
            : "No drafts pending. Select any deal to preview its War Room — MEDDPICC, deal story, and next moves."}
        </p>
      </div>
    </div>
  );
}

// ── Inner page ────────────────────────────────────────────────────────────────

type QuickFilter = "all" | "drafts" | "urgent";

function InboxInner() {
  const searchParams = useSearchParams();
  const query = searchParams.get("q");

  const [selectedAccount, setSelectedAccount] = useState<AccountListItem | null>(null);
  const [quickFilter, setQuickFilter] = useState<QuickFilter>("all");
  const [showRest, setShowRest] = useState(false);
  // Shared engine — Today defaults to dollar-weighted priority ranking
  const [filters, setFilters] = useState<DealFilterState>(() => loadFilters("today", { sort: "priority" }));
  const updateFilters = (next: DealFilterState) => { setFilters(next); saveFilters("today", next); };

  // Account list — sorted by urgency desc, paginated
  const { data, isLoading } = useQuery({
    queryKey: ["accounts", "inbox"],
    queryFn: () => accountsApi.list({
      sort_by: "urgency_score",
      sort_dir: "desc",
      limit: 100,
    }),
    refetchInterval: 5 * 60 * 1000,
    staleTime: 2 * 60 * 1000,
  });

  // Pending drafts count (for badge + empty state)
  const { data: draftsCountData } = useQuery({
    queryKey: ["drafts", "pending", "count"],
    queryFn: () => draftsApi.list({ status: "pending", limit: 1 }),
    refetchInterval: 60 * 1000,
    staleTime: 60 * 1000,
  });
  const pendingCount = draftsCountData?.pagination?.total ?? 0;

  const allAccounts: AccountListItem[] = data?.data ?? [];

  // Semantic search mode
  const { data: searchData, isLoading: searchLoading } = useQuery({
    queryKey: ["accounts", "search", query],
    queryFn: () => accountsApi.search({ query: query!, limit: 20 }),
    enabled: !!query,
  });

  // Today is an action queue — closed deals never belong in it.
  const CLOSED_STAGES = new Set(["won", "closed lost", "closed-lost", "partners"]);
  const openAccounts = allAccounts.filter(
    a => !CLOSED_STAGES.has((a.stage ?? "").trim().toLowerCase())
  );

  // Quick filter tabs (queue modes) compose with the shared engine
  const quickFiltered = openAccounts.filter(a => {
    if (quickFilter === "drafts") return (a.pending_drafts ?? 0) > 0;
    if (quickFilter === "urgent") return (a.urgency_score ?? 0) >= 0.7;
    return true;
  });

  // Shared filter/sort/rank engine — search, stage, category, health, sort
  const ranked = useMemo(
    () => filterAndSortDeals(quickFiltered, filters),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data, quickFilter, filters]
  );

  // Finite daily queue: a rep can finish 7 things; 100 is not a to-do list.
  // The queue view only applies in the default state — any search, filter, or
  // non-priority sort switches to a flat results list.
  const QUEUE_SIZE = 7;
  const isQueueView = quickFilter === "all" && !hasActiveFilters(filters) && filters.sort === "priority";
  const todayQueue = isQueueView ? ranked.slice(0, QUEUE_SIZE) : ranked;
  const restOfPipeline = isQueueView ? ranked.slice(QUEUE_SIZE) : [];
  const visibleList = showRest ? [...todayQueue, ...restOfPipeline] : todayQueue;

  const draftsCount  = openAccounts.filter(a => (a.pending_drafts ?? 0) > 0).length;
  const urgentCount  = openAccounts.filter(a => (a.urgency_score ?? 0) >= 0.7).length;

  // Auto-select the queue's first item — the prime real estate should never
  // show "Select a deal" when the agent already knows what matters most.
  useEffect(() => {
    if (!visibleList.length) return;
    if (!selectedAccount || !visibleList.some(a => a.id === selectedAccount.id)) {
      setSelectedAccount(visibleList[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleList.length, visibleList[0]?.id]);

  // J/K keyboard triage — move down/up the queue (E/D live on the draft card)
  const moveSelection = useCallback((delta: number) => {
    setSelectedAccount(prev => {
      if (!visibleList.length) return prev;
      const idx = prev ? visibleList.findIndex(a => a.id === prev.id) : -1;
      const next = Math.min(Math.max(idx + delta, 0), visibleList.length - 1);
      return visibleList[next];
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleList]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || (e.target as HTMLElement)?.isContentEditable) return;
      if (e.key === "j" || e.key === "J") { e.preventDefault(); moveSelection(1); }
      if (e.key === "k" || e.key === "K") { e.preventDefault(); moveSelection(-1); }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [moveSelection]);

  if (query) {
    return (
      <SearchResults
        query={query}
        results={searchData?.data ?? []}
        isLoading={searchLoading}
        onSelect={(id) => {
          const found = allAccounts.find(a => a.id === id);
          if (found) setSelectedAccount(found);
        }}
      />
    );
  }

  const warRoomFocus =
    !!selectedAccount &&
    (selectedAccount.pending_drafts === 0 || pendingCount === 0);

  return (
    <div className="flex h-full min-h-0">

      {/* ── Left panel — narrower when War Room preview owns the right side */}
      <div className={cn(
        "flex-shrink-0 border-r border-zinc-100 bg-white flex flex-col",
        warRoomFocus ? "w-64" : "w-80"
      )}>

        {/* Search + filters + sort (shared engine) */}
        <div className="px-3 pt-3 pb-2 border-b border-zinc-100 flex-shrink-0">
          <DealFilterBar
            accounts={openAccounts}
            state={filters}
            onChange={updateFilters}
            sortOptions={["priority", "urgency", "amount", "close", "health"]}
          />

          {/* Quick filters */}
          <div className="flex items-center gap-1.5 mt-2">
            {(["all", "drafts", "urgent"] as QuickFilter[]).map(f => {
              const labels = {
                all:    `All (${openAccounts.length})`,
                drafts: `Drafts${draftsCount > 0 ? ` · ${draftsCount}` : ""}`,
                urgent: `Urgent${urgentCount > 0 ? ` · ${urgentCount}` : ""}`,
              };
              return (
                <button
                  key={f}
                  onClick={() => setQuickFilter(f)}
                  className={cn(
                    "flex-1 text-[11px] font-medium px-2 py-1.5 rounded-md transition-colors",
                    quickFilter === f
                      ? "bg-zinc-900 text-white"
                      : "text-zinc-500 hover:bg-zinc-100"
                  )}
                >
                  {labels[f]}
                </button>
              );
            })}
          </div>
        </div>

        {/* Deal list */}
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="pt-2">
              {[1, 2, 3, 4, 5].map(i => (
                <Skeleton key={i} className="h-12 w-full border-b border-zinc-100 rounded-none" />
              ))}
            </div>
          ) : ranked.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center px-4">
              <AlertTriangle className="w-6 h-6 text-zinc-300 mb-3" />
              <p className="text-[13px] font-medium text-zinc-500">No deals found</p>
              <p className="text-[12px] text-zinc-400 mt-1">
                {hasActiveFilters(filters) ? "Try different filters or clear them" : "Connect HubSpot to sync deals"}
              </p>
            </div>
          ) : (
            <>
              {/* Today's queue — finite, dollar-weighted */}
              <div className="flex items-center gap-2 px-3.5 pt-3 pb-1.5">
                <span className="text-[10px] font-medium text-zinc-400">
                  {isQueueView ? `Today · ${todayQueue.length}` : `Results · ${todayQueue.length}`}
                </span>
              </div>
              <div>
                {todayQueue.map((account, i) => (
                  <DealCard
                    key={account.id}
                    account={account}
                    isSelected={selectedAccount?.id === account.id}
                    onClick={() => setSelectedAccount(account)}
                    queueRank={isQueueView ? i + 1 : undefined}
                  />
                ))}
              </div>

              {/* Everything else — collapsed by default; finishing the queue is the job */}
              {isQueueView && restOfPipeline.length > 0 && (
                <div>
                  <button
                    onClick={() => setShowRest(v => !v)}
                    className="w-full flex items-center justify-center gap-1.5 text-[11px] font-medium text-zinc-400 hover:text-zinc-700 py-2.5 border-t border-zinc-100 hover:bg-zinc-50 transition-colors"
                  >
                    {showRest ? "Hide" : "Show"} rest of pipeline ({restOfPipeline.length})
                    <ChevronDown className={cn("w-3 h-3 transition-transform", showRest && "rotate-180")} />
                  </button>
                  {showRest && (
                    <div>
                      {restOfPipeline.map(account => (
                        <DealCard
                          key={account.id}
                          account={account}
                          isSelected={selectedAccount?.id === account.id}
                          onClick={() => setSelectedAccount(account)}
                        />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* Keyboard hints */}
        <div className="flex-shrink-0 border-t border-zinc-100 px-4 py-2 flex items-center gap-3 text-[10px] text-zinc-400">
          <span><kbd className="font-sans border border-zinc-200 rounded px-1">J</kbd>/<kbd className="font-sans border border-zinc-200 rounded px-1">K</kbd> navigate</span>
          <span><kbd className="font-sans border border-zinc-200 rounded px-1">E</kbd> approve</span>
          <span><kbd className="font-sans border border-zinc-200 rounded px-1">D</kbd> decline</span>
        </div>
      </div>

      {/* ── Right panel ────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-hidden">
        {selectedAccount ? (
          <DealContextPanel account={selectedAccount} />
        ) : (
          <EmptyPanel pendingCount={pendingCount} />
        )}
      </div>
    </div>
  );
}

// ── Page export ────────────────────────────────────────────────────────────────

export default function InboxPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center h-full">
        <div className="w-6 h-6 border-2 border-zinc-300 border-t-zinc-700 rounded-full animate-spin" />
      </div>
    }>
      <InboxInner />
    </Suspense>
  );
}
