"use client";

import Link from "next/link";
import { type AccountListItem } from "@/lib/api";
import { cn, urgencyLevel as canonicalUrgencyLevel } from "@/lib/utils";
import { formatDistanceToNow, format, parseISO } from "date-fns";
import { MessageSquare, ExternalLink, Calendar } from "lucide-react";

interface Props {
  account: AccountListItem;
  isSelected: boolean;
  onClick: () => void;
}

const URGENCY_COLOR: Record<string, string> = {
  critical: "bg-red-500",
  high:     "bg-orange-400",
  medium:   "bg-yellow-400",
  low:      "bg-green-400",
};

const URGENCY_TEXT: Record<string, string> = {
  critical: "text-red-600",
  high:     "text-orange-600",
  medium:   "text-yellow-600",
  low:      "text-green-600",
};

const HEALTH_COLOR: Record<string, string> = {
  good:    "bg-green-400",
  fair:    "bg-yellow-400",
  poor:    "bg-red-400",
};

const FORECAST_STYLE: Record<string, string> = {
  "Commit":    "forecast-commit",
  "Best Case": "forecast-bestcase",
  "Pipeline":  "forecast-pipeline",
  "Omit":      "forecast-omit",
};

function formatCloseDate(dateStr: string | null): string | null {
  if (!dateStr) return null;
  try {
    const d = parseISO(dateStr);
    return format(d, "MMM d, yyyy");
  } catch {
    return null;
  }
}

export function AccountCard({ account, isSelected, onClick }: Props) {
  const urgencyBar = account.urgency_score ?? 0;
  const urgencyPct = Math.round(urgencyBar * 100);
  const urgencyLevel = canonicalUrgencyLevel(urgencyBar);

  const healthBar   = account.health_score ?? null;
  const healthPct   = healthBar !== null ? Math.round(healthBar * 100) : null;
  const healthLevel = healthBar !== null
    ? healthBar >= 0.7 ? "good" : healthBar >= 0.4 ? "fair" : "poor"
    : "fair";

  const lastRun = account.last_agent_run_at
    ? formatDistanceToNow(new Date(account.last_agent_run_at), { addSuffix: true })
    : "Never";

  const dealAmount = account.deal_amount
    ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(account.deal_amount)
    : null;

  const closeDate = formatCloseDate(account.close_date);

  // Guard against raw HubSpot stage IDs (long numeric strings like "1219886089")
  const isRawStageId = account.stage ? /^\d{6,}$/.test(account.stage) : false;
  const stageDisplay = !account.stage || isRawStageId ? null : account.stage;

  return (
    <div
      data-testid="account-card"
      className={cn(
        "w-full text-left transition-colors border-b border-gray-100 last:border-0",
        isSelected ? "bg-brand-50" : "hover:bg-gray-50"
      )}
    >
      {/* Main click area */}
      <button onClick={onClick} className="w-full text-left px-4 pt-3.5 pb-3">

        {/* Top row: name + urgency */}
        <div className="flex items-start justify-between mb-1.5">
          <p className="text-sm font-semibold text-gray-900 truncate pr-3 leading-tight">{account.name}</p>
          <div className="flex-shrink-0 flex items-center gap-1.5">
            <div className={cn("w-2 h-2 rounded-full flex-shrink-0", URGENCY_COLOR[urgencyLevel])} />
            <span className={cn("text-xs font-bold tabular-nums", URGENCY_TEXT[urgencyLevel])}>{urgencyPct}%</span>
          </div>
        </div>

        {/* Row 2: stage · amount · close date */}
        <div className="flex items-center gap-1.5 flex-wrap mb-2.5">
          {stageDisplay && (
            <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full truncate max-w-[120px]">
              {stageDisplay}
            </span>
          )}
          {dealAmount && (
            <span className="text-xs font-medium text-gray-700">{dealAmount}</span>
          )}
          {closeDate && (
            <span className="flex items-center gap-1 text-xs text-gray-400">
              <Calendar className="w-3 h-3" />
              {closeDate}
            </span>
          )}
        </div>

        {/* Dual-bar: urgency (top) + health (bottom) */}
        <div className="space-y-1 mb-2.5">
          {/* Urgency bar */}
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-gray-400 w-11 flex-shrink-0">Urgency</span>
            <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div
                className={cn("h-full rounded-full transition-all", URGENCY_COLOR[urgencyLevel])}
                style={{ width: `${urgencyPct}%` }}
              />
            </div>
          </div>
          {/* Health bar (only shown when available) */}
          {healthPct !== null && (
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-gray-400 w-11 flex-shrink-0">Health</span>
              <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                <div
                  className={cn("h-full rounded-full transition-all", HEALTH_COLOR[healthLevel])}
                  style={{ width: `${healthPct}%` }}
                />
              </div>
            </div>
          )}
        </div>

        {/* AI Forecast + ICP + pending drafts badge */}
        <div className="flex items-center gap-2 min-h-[20px]">
          {account.pov_forecast_cat && (
            <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium flex-shrink-0", FORECAST_STYLE[account.pov_forecast_cat] ?? "forecast-pipeline")}>
              {account.pov_forecast_cat}
            </span>
          )}
          {account.pov_confidence && account.pov_forecast_cat && (
            <span className="text-xs text-gray-400">{Math.round(account.pov_confidence * 100)}% conf.</span>
          )}
          {account.icp_score != null && (
            <span className={cn(
              "text-xs px-1.5 py-0.5 rounded-full font-medium flex-shrink-0",
              account.icp_score >= 0.7 ? "bg-green-100 text-green-700" :
              account.icp_score >= 0.4 ? "bg-yellow-100 text-yellow-700" :
              "bg-gray-100 text-gray-500"
            )}
              title={`ICP fit: ${Math.round(account.icp_score * 100)}%`}
            >
              ICP {Math.round(account.icp_score * 100)}%
            </span>
          )}
          {account.pending_drafts > 0 && (
            <span className="ml-auto text-xs font-semibold bg-orange-100 text-orange-700 px-2 py-0.5 rounded-full flex-shrink-0">
              {account.pending_drafts} draft{account.pending_drafts > 1 ? "s" : ""}
            </span>
          )}
        </div>

        {/* Next step / deal narrative / signal preview */}
        {account.next_step ? (
          <p className="text-xs text-brand-600 truncate mt-1.5 leading-tight font-medium">
            ↪ {account.next_step.text}
          </p>
        ) : account.deal_narrative ? (
          <p className="text-xs text-gray-500 line-clamp-2 mt-1.5 leading-snug">
            {account.deal_narrative}
          </p>
        ) : account.signals_summary[0] ? (
          <p className="text-xs text-gray-400 truncate mt-1.5 leading-tight">
            ↑ {account.signals_summary[0].detail}
          </p>
        ) : null}

        {/* Last agent run */}
        <p className="text-[10px] text-gray-400 mt-1.5">Agent ran {lastRun}</p>
      </button>

      {/* Action strip */}
      <div className="flex items-center gap-1 px-4 pb-3">
        <Link
          href={`/assistant?account_id=${account.id}&seed=true`}
          onClick={(e) => e.stopPropagation()}
          className="flex items-center gap-1.5 text-xs font-medium text-brand-600 hover:text-brand-700 px-2.5 py-1 rounded-md hover:bg-brand-50 transition-colors"
        >
          <MessageSquare className="w-3 h-3" />
          Ask Agent
        </Link>
        <Link
          href={`/account/${account.id}`}
          onClick={(e) => e.stopPropagation()}
          className="flex items-center gap-1.5 text-xs font-medium text-gray-500 hover:text-gray-700 px-2.5 py-1 rounded-md hover:bg-gray-100 transition-colors"
        >
          <ExternalLink className="w-3 h-3" />
          War Room
        </Link>
      </div>
    </div>
  );
}
