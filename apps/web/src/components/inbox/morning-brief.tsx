"use client";

/**
 * Morning Brief - Top-of-inbox daily intelligence summary.
 * Shows: top 3 urgent accounts, pending drafts count, one-action prompt.
 * Dismisses when the user selects an account or clicks X.
 * Dismissed state persists per-day via localStorage.
 */

import Link from "next/link";
import { useEffect, useState } from "react";
import { type AccountListItem } from "@/lib/api";
import { cn, urgencyLevel } from "@/lib/utils";
import { X, Zap, MessageSquare, ArrowRight } from "lucide-react";

const DISMISS_KEY = "morning_brief_dismissed_date";

interface Props {
  accounts: AccountListItem[];
  pendingDrafts: number;
  onDismiss: () => void;
  onSelectAccount: (id: string) => void;
}

const URGENCY_COLOR: Record<string, string> = {
  critical: "bg-red-500",
  high:     "bg-orange-400",
  medium:   "bg-yellow-400",
  low:      "bg-green-400",
};

export function MorningBrief({ accounts, pendingDrafts, onDismiss, onSelectAccount }: Props) {
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    const today = new Date().toISOString().slice(0, 10);
    const stored = typeof window !== "undefined" ? localStorage.getItem(DISMISS_KEY) : null;
    if (stored === today) setDismissed(true);
  }, []);

  const handleDismiss = () => {
    const today = new Date().toISOString().slice(0, 10);
    if (typeof window !== "undefined") localStorage.setItem(DISMISS_KEY, today);
    setDismissed(true);
    onDismiss();
  };

  if (accounts.length === 0 || dismissed) return null;

  // Pick the single most urgent account for the "one action" prompt
  const topAccount = accounts[0];
  const topPreview = topAccount.deal_narrative ?? topAccount.signals_summary[0]?.detail ?? null;

  const now = new Date();
  const hour = now.getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";

  return (
    <div data-testid="morning-brief" className="bg-white border-b border-zinc-100 border-l-4 border-l-zinc-800 px-5 py-4">
      <div className="flex items-start gap-4">
        {/* Icon */}
        <div className="w-9 h-9 bg-zinc-900 rounded-xl flex items-center justify-center flex-shrink-0">
          <Zap className="w-5 h-5 text-white" />
        </div>

        <div className="flex-1 min-w-0">
          {/* Headline */}
          <div className="flex items-center gap-2 mb-1">
            <p className="text-sm font-semibold text-zinc-900">{greeting}. Here&apos;s what needs your attention today.</p>
            {pendingDrafts > 0 && (
              <span className="text-xs bg-orange-100 text-orange-700 border border-orange-200 px-2 py-0.5 rounded-full font-medium">
                {pendingDrafts} draft{pendingDrafts > 1 ? "s" : ""} to review
              </span>
            )}
          </div>

          {/* Top action */}
          <p className="text-sm text-zinc-600 mb-3">
            <span className="font-medium text-zinc-800">{topAccount.name}</span> is your highest priority today
            {topPreview && `: ${topPreview.charAt(0).toLowerCase() + topPreview.slice(1)}`}.
          </p>

          {/* Account pills */}
          <div className="flex flex-wrap gap-2">
            {accounts.map((a, i) => {
              const level = urgencyLevel(a.urgency_score ?? 0);
              return (
                <button
                  key={a.id}
                  onClick={() => onSelectAccount(a.id)}
                  className={cn(
                    "flex items-center gap-2 bg-white border rounded-xl px-3 py-2 text-left hover:shadow-sm transition-all",
                    i === 0 ? "border-brand-200 shadow-sm" : "border-zinc-200"
                  )}
                >
                  <div className="flex items-center gap-1.5">
                    <div className={cn("w-2 h-2 rounded-full flex-shrink-0", URGENCY_COLOR[level])} />
                    <span className="text-sm font-medium text-zinc-900">{a.name}</span>
                  </div>
                  {a.pending_drafts > 0 && (
                    <span className="text-xs bg-orange-100 text-orange-600 px-1.5 py-0.5 rounded-full">
                      {a.pending_drafts}
                    </span>
                  )}
                  <ArrowRight className="w-3.5 h-3.5 text-zinc-300 ml-1" />
                </button>
              );
            })}

            {/* Quick Ask Agent for top account */}
            <Link
              href={`/assistant?account_id=${topAccount.id}&seed=true`}
              className="flex items-center gap-1.5 bg-brand-600 text-white rounded-xl px-3 py-2 text-sm font-medium hover:bg-brand-700 transition-colors"
            >
              <MessageSquare className="w-3.5 h-3.5" />
              Ask Agent about {topAccount.name.split(" ")[0]}
            </Link>
          </div>
        </div>

        {/* Dismiss */}
        <button
          onClick={handleDismiss}
          className="text-zinc-400 hover:text-zinc-600 transition-colors flex-shrink-0 mt-0.5"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
