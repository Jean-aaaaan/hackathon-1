"use client";

/**
 * SmartFieldsPanel - AI-suggested CRM field updates.
 *
 * Shows pending suggestions from the SmartFieldsAgent.
 * Each suggestion shows: field label, current vs suggested value,
 * reason, source, confidence bar, MEDDPICC link, and Dismiss action.
 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { accountsApi, type SmartFieldSuggestion } from "@/lib/api";
// Note: Apply-to-CRM removed; suggestions are read-only intelligence for the rep
import { cn } from "@/lib/utils";
import {
  XCircle,
  AlertTriangle,
  Zap,
  ChevronRight,
  Database,
} from "lucide-react";

// ── Helpers ───────────────────────────────────────────────────────────────────

const IMPACT_STYLE: Record<string, string> = {
  high:   "bg-red-50 text-red-700 border-red-100",
  medium: "bg-orange-50 text-orange-700 border-orange-100",
  low:    "bg-zinc-50 text-zinc-600 border-zinc-200",
};

const IMPACT_DOT: Record<string, string> = {
  high:   "bg-red-500",
  medium: "bg-orange-400",
  low:    "bg-zinc-400",
};

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.8 ? "bg-green-500" : value >= 0.65 ? "bg-yellow-400" : "bg-zinc-300";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-zinc-100 rounded-full overflow-hidden">
        <div className={cn("h-full rounded-full", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-zinc-500 w-8 text-right">{pct}%</span>
    </div>
  );
}

// ── Single suggestion card ────────────────────────────────────────────────────

const DATE_FIELDS = new Set(["closedate", "notes_next_activity_date"]);

function SuggestionCard({
  suggestion,
  accountId,
  onDismissed,
}: {
  suggestion: SmartFieldSuggestion;
  accountId: string;
  onDismissed: (fieldName: string) => void;
}) {
  const [dismissing, setDismissing] = useState(false);
  const queryClient = useQueryClient();

  // A date suggestion pointing into the past was generated before that date
  // arrived — "schedule for tomorrow" shown a week later is worse than nothing
  const isDateField = DATE_FIELDS.has(suggestion.field_name);
  const suggestedDate = isDateField ? new Date(suggestion.suggested_value) : null;
  const isStale =
    suggestedDate != null &&
    !isNaN(suggestedDate.getTime()) &&
    suggestedDate.getTime() < Date.now() - 86_400_000;

  const dismissMutation = useMutation({
    mutationFn: () =>
      accountsApi.dismissSmartField(accountId, {
        field_name: suggestion.field_name,
        suggested_value: suggestion.suggested_value,
      }),
    onMutate: () => setDismissing(true),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["smart-fields", accountId] });
      onDismissed(suggestion.field_name);
    },
    onSettled: () => setDismissing(false),
  });

  return (
    <div className="bg-white border border-zinc-200 rounded-xl overflow-hidden">
      {/* Header row */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-zinc-100">
        <div className={cn("w-2 h-2 rounded-full flex-shrink-0", IMPACT_DOT[suggestion.impact] ?? "bg-zinc-400")} />
        <span className="text-sm font-semibold text-zinc-900 flex-1">{suggestion.field_label}</span>
        {suggestion.meddpicc_component && (
          <span className="text-xs bg-zinc-100 text-zinc-700 border border-zinc-200 px-2 py-0.5 rounded-full">
            {suggestion.meddpicc_component}
          </span>
        )}
        {isStale && (
          <span className="text-xs px-2 py-0.5 rounded-full border bg-amber-50 text-amber-700 border-amber-200 font-medium">
            stale — re-run agent
          </span>
        )}
        <span className={cn("text-xs px-2 py-0.5 rounded-full border capitalize font-medium", IMPACT_STYLE[suggestion.impact] ?? IMPACT_STYLE.low)}>
          {suggestion.impact} impact
        </span>
      </div>

      {/* Value comparison */}
      <div className="px-4 py-3">
        <div className="flex items-center gap-3 text-sm mb-3">
          <div className="flex-1">
            <div className="text-xs text-zinc-400 mb-0.5">Current in HubSpot</div>
            <div className="font-mono text-zinc-500 text-xs bg-zinc-50 px-2 py-1 rounded border border-zinc-100">
              {suggestion.current_value || <span className="italic text-zinc-400">Empty</span>}
            </div>
          </div>
          <ChevronRight className="w-4 h-4 text-zinc-300 flex-shrink-0 mt-4" />
          <div className="flex-1">
            <div className="text-xs text-zinc-400 mb-0.5">AI Suggests</div>
            <div className={cn(
              "font-mono text-xs px-2 py-1 rounded border font-semibold",
              isStale
                ? "text-zinc-400 bg-zinc-50 border-zinc-200 line-through"
                : "text-brand-700 bg-brand-50 border-brand-100"
            )}>
              {isDateField && suggestedDate && !isNaN(suggestedDate.getTime())
                ? suggestedDate.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
                : suggestion.suggested_value}
            </div>
          </div>
        </div>

        {/* Reason */}
        <p className="text-sm text-zinc-700 leading-relaxed mb-2">{suggestion.reason}</p>

        {/* Source + confidence */}
        <div className="mb-3">
          <div className="text-xs text-zinc-400 mb-1">Source: {suggestion.source}</div>
          <ConfidenceBar value={suggestion.confidence} />
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => dismissMutation.mutate()}
            disabled={dismissing}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors",
              "bg-white border border-zinc-200 text-zinc-600 hover:bg-zinc-50 disabled:opacity-50 disabled:cursor-not-allowed"
            )}
          >
            <XCircle className="w-3.5 h-3.5" />
            {dismissing ? "Dismissing..." : "Dismiss"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

export function SmartFieldsPanel({
  accountId,
  suggestions,
  isLoading,
}: {
  accountId: string;
  suggestions: SmartFieldSuggestion[];
  isLoading: boolean;
}) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  const visible = suggestions.filter((s) => !dismissed.has(s.field_name));

  if (isLoading) {
    return (
      <div className="space-y-3 max-w-2xl">
        {[1, 2].map((i) => (
          <div key={i} className="h-36 bg-zinc-100 rounded-xl animate-pulse" />
        ))}
      </div>
    );
  }

  if (visible.length === 0) {
    return (
      <div className="text-center py-12 max-w-2xl">
        <div className="w-10 h-10 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-3">
          <Database className="w-5 h-5 text-green-600" />
        </div>
        <p className="text-sm font-medium text-zinc-700">CRM looks accurate</p>
        <p className="text-xs text-zinc-400 mt-1">
          No field updates needed. Run the agent after new activity to re-check.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3 max-w-2xl">
      {/* Header */}
      <div className="flex items-center gap-2 mb-1">
        <Zap className="w-4 h-4 text-brand-600" />
        <p className="text-sm font-semibold text-zinc-800">
          {visible.length} field{visible.length !== 1 ? "s" : ""} out of sync with AI intelligence
        </p>
      </div>

      {/* Suggestions sorted by impact */}
      {[...visible]
        .sort((a, b) => {
          const order = { high: 0, medium: 1, low: 2 };
          return (order[a.impact] ?? 2) - (order[b.impact] ?? 2);
        })
        .map((s) => (
          <SuggestionCard
            key={s.field_name}
            suggestion={s}
            accountId={accountId}
            onDismissed={(f) => setDismissed((prev) => new Set([...prev, f]))}
          />
        ))}

      {/* Footer note */}
      <div className="flex items-start gap-2 p-3 bg-amber-50 border border-amber-100 rounded-lg">
        <AlertTriangle className="w-3.5 h-3.5 text-amber-600 mt-0.5 flex-shrink-0" />
        <p className="text-xs text-amber-700">
          These are AI suggestions — copy them into your CRM manually. Dismissed suggestions won&apos;t appear again
          until the next agent run detects the same issue.
        </p>
      </div>
    </div>
  );
}
