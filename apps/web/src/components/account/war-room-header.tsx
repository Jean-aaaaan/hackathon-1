"use client";

import Link from "next/link";
import {
  ArrowLeft, Zap, ChevronDown, ExternalLink, RefreshCw, FileText,
  MessagesSquare, BarChart3, Clock,
} from "lucide-react";
import { DOC_TYPE_LABELS, type DocType } from "@/lib/api";
import { cn, urgencyLevel } from "@/lib/utils";

export type WarRoomCenter = "act" | "intel" | "history";

function fmtCurrency(n: number | null) {
  if (!n) return "-";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n);
}

function HealthBadge({ score }: { score: number }) {
  const level = urgencyLevel(score);
  const styles = {
    critical: "bg-red-50 text-red-700 border-red-200 ring-red-100",
    high:     "bg-orange-50 text-orange-700 border-orange-200 ring-orange-100",
    medium:   "bg-amber-50 text-amber-700 border-amber-200 ring-amber-100",
    low:      "bg-emerald-50 text-emerald-700 border-emerald-200 ring-emerald-100",
  };
  const dots = {
    critical: "bg-red-500", high: "bg-orange-400",
    medium: "bg-amber-400", low: "bg-emerald-500",
  };
  const labels = { critical: "Critical", high: "High Risk", medium: "At Risk", low: "Healthy" };
  return (
    <span className={cn(
      "inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border ring-2",
      styles[level]
    )}>
      <span className={cn("w-1.5 h-1.5 rounded-full animate-pulse", dots[level])} />
      {labels[level]}
    </span>
  );
}

export interface WarRoomHeaderProps {
  accountName: string;
  accountStage?: string | null;
  dealAmount?: number | null;
  urgencyScore: number | null;
  momentum?: string | null;
  aiCloseDate?: string | null;
  crmCloseDate?: string | null;
  generateToast?: string | null;
  generateOpen: boolean;
  generatingDoc: boolean;
  agentRunning: boolean;
  briefFetching: boolean;
  sharePending: boolean;
  shareCopied: boolean;
  onChatOpen: () => void;
  onGenerateToggle: () => void;
  onGenerateDoc: (type: DocType) => void;
  onRunAgent: () => void;
  onGenerateClose: () => void;
  onFetchBrief: () => void;
  onShare: () => void;
  onRefresh: () => void;
}

export function WarRoomHeader({
  accountName,
  accountStage,
  dealAmount,
  urgencyScore,
  momentum,
  aiCloseDate,
  crmCloseDate,
  generateToast,
  generateOpen,
  generatingDoc,
  agentRunning,
  briefFetching,
  sharePending,
  shareCopied,
  onChatOpen,
  onGenerateToggle,
  onGenerateDoc,
  onRunAgent,
  onGenerateClose,
  onFetchBrief,
  onShare,
  onRefresh,
}: WarRoomHeaderProps) {
  const momentumStyle = momentum === "accelerating" ? "text-emerald-600" : momentum === "declining" ? "text-red-500" : "text-amber-500";
  const momentumIcon = momentum === "accelerating" ? "↗" : momentum === "declining" ? "↓" : "↘";

  return (
    <div className="bg-white border-b border-zinc-200 px-5 py-3.5 flex items-center gap-4">
      <Link href="/inbox" className="text-zinc-400 hover:text-zinc-600 transition-colors flex-shrink-0">
        <ArrowLeft className="w-4 h-4" />
      </Link>

      <div className="flex items-center gap-3 min-w-0">
        <h1 className="text-base font-semibold text-zinc-900 truncate">{accountName}</h1>
        {accountStage && (
          <span className="text-xs font-medium text-zinc-500 bg-zinc-100 px-2 py-0.5 rounded-full flex-shrink-0">
            {accountStage}
          </span>
        )}
        {dealAmount && (
          <span className="text-sm font-semibold text-zinc-700 flex-shrink-0">{fmtCurrency(dealAmount)}</span>
        )}
      </div>

      <div className="flex items-center gap-2 flex-shrink-0">
        {urgencyScore !== null && <HealthBadge score={urgencyScore} />}
        {momentum && (
          <span className={cn("text-xs font-medium", momentumStyle)}>
            {momentumIcon} {momentum}
          </span>
        )}
        {aiCloseDate && crmCloseDate && aiCloseDate !== crmCloseDate && (
          <span className="text-xs text-zinc-400">
            AI close: <span className="font-medium text-zinc-700">
              {new Date(aiCloseDate).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
            </span>
            {" · "}CRM: {new Date(crmCloseDate).toLocaleDateString("en-US", { month: "short", year: "numeric" })}
          </span>
        )}
      </div>

      {generateToast && (
        <span className="text-xs font-medium text-zinc-700 bg-zinc-100 border border-zinc-200 px-3 py-1 rounded-full">
          {generateToast}
        </span>
      )}

      <div className="ml-auto flex items-center gap-2 flex-shrink-0">
        <button onClick={onChatOpen} className="btn-secondary flex items-center gap-1.5 text-xs">
          <MessagesSquare className="w-3 h-3" />
          Chat
        </button>

        <div className="relative">
          <button onClick={onGenerateToggle} className="btn-accent flex items-center gap-1.5 text-xs">
            <FileText className="w-3 h-3" />
            {generatingDoc ? "Generating…" : "Generate"}
            <ChevronDown className="w-3 h-3 opacity-80" />
          </button>
          {generateOpen && (
            <div className="absolute right-0 top-full mt-1.5 bg-white border border-zinc-200 rounded-xl shadow-lg z-30 min-w-[200px] py-1.5 overflow-hidden">
              {(Object.entries(DOC_TYPE_LABELS) as [DocType, string][]).map(([type, label]) => (
                <button key={type} onClick={() => onGenerateDoc(type)}
                  className="w-full text-left px-4 py-2 text-sm text-zinc-700 hover:bg-zinc-50 transition-colors">
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>

        <button onClick={onRunAgent} disabled={agentRunning}
          className={cn(
            "flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-md transition-colors disabled:opacity-50",
            agentRunning ? "bg-zinc-100 text-zinc-700 border border-zinc-200" : "btn-accent"
          )}>
          <Zap className="w-3 h-3" />
          {agentRunning ? "Running…" : "Run Agent"}
        </button>

        <div className="relative">
          <button onClick={onGenerateClose}
            className="flex items-center gap-1 text-zinc-400 hover:text-zinc-600 transition-colors px-1.5 py-1.5 rounded-lg hover:bg-zinc-100">
            <ChevronDown className="w-4 h-4" />
          </button>
        </div>

        <button onClick={onFetchBrief} disabled={briefFetching}
          className="btn-secondary flex items-center gap-1.5 text-xs px-2.5 disabled:opacity-50"
          title="Meeting Brief">
          <FileText className="w-3.5 h-3.5" />
        </button>

        <button onClick={onShare} disabled={sharePending}
          title={shareCopied ? "Copied!" : "Copy share link"}
          className="text-zinc-400 hover:text-zinc-600 transition-colors p-1 disabled:opacity-50">
          <ExternalLink className="w-4 h-4" />
        </button>

        <button onClick={onRefresh} title="Refresh"
          className="text-zinc-400 hover:text-zinc-600 transition-colors p-1">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

export interface WarRoomTabNavProps {
  activeCenter: WarRoomCenter;
  onCenterChange: (c: WarRoomCenter) => void;
  actBadgeCount: number;
}

const TABS = [
  { id: "act" as const,     label: "Act",          icon: Zap },
  { id: "intel" as const,   label: "Intelligence", icon: BarChart3 },
  { id: "history" as const, label: "History",      icon: Clock },
];

export function WarRoomTabNav({ activeCenter, onCenterChange, actBadgeCount }: WarRoomTabNavProps) {
  return (
    <div className="bg-white border-b border-zinc-200 px-6 flex items-center gap-1">
      {TABS.map(tab => {
        const Icon = tab.icon;
        const isActive = activeCenter === tab.id;
        const badge = tab.id === "act" ? actBadgeCount : 0;
        return (
          <button key={tab.id} onClick={() => onCenterChange(tab.id)}
            className={cn(
              "flex items-center gap-1.5 px-3 py-3.5 text-sm font-medium border-b-2 transition-colors relative",
              isActive ? "border-zinc-900 text-zinc-900" : "border-transparent text-zinc-500 hover:text-zinc-700"
            )}>
            <Icon className="w-3.5 h-3.5" />
            {tab.label}
            {badge > 0 && (
              <span className="inline-flex items-center justify-center min-w-[16px] h-4 text-[10px] font-bold bg-zinc-900 text-white rounded-full px-1">
                {badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
