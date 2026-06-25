"use client";

/**
 * Watchtower - Portfolio health command centre.
 * Upgraded Sprint 2: signal clustering, forecast treemap, radar overlay, War Room links.
 */

import Link from "next/link";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { accountsApi, analyticsApi, agentApi, forecastApi, signalsApi, type AccountListItem, type AiVsCrmDelta, type CompetitorEntry, type ForecastRollup, type PipelineReview, type PipelineReviewDeal, type Signal, type StalledDeal, type WatcherDeltaData } from "@/lib/api";
import { cn, signalLabel, cleanDealName, formatDate } from "@/lib/utils";
import { formatDistanceToNow } from "date-fns";
import { AlertTriangle, TrendingDown, TrendingUp, Activity, CheckCircle, ExternalLink, Filter, Zap } from "lucide-react";
import { toast } from "sonner";

// ── Radar chart (pure SVG, 5 axes) ───────────────────────────────────────────

function RadarChart({
  values,
  labels,
  size = 160,
}: {
  values: number[];   // 0-1 for each axis
  labels: string[];
  size?: number;
}) {
  const cx = size / 2;
  const cy = size / 2;
  const r = size * 0.38;
  const n = values.length;

  const angleOf = (i: number) => (Math.PI * 2 * i) / n - Math.PI / 2;
  const px = (val: number, i: number) => cx + r * val * Math.cos(angleOf(i));
  const py = (val: number, i: number) => cy + r * val * Math.sin(angleOf(i));

  // Grid rings (3 rings at 33/66/100%)
  const rings = [0.33, 0.66, 1.0];

  const polygon = (val: number) =>
    Array.from({ length: n }, (_, i) => `${px(val, i)},${py(val, i)}`).join(" ");

  const dataPath = values.map((v, i) => `${px(v, i)},${py(v, i)}`).join(" ");

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      {/* Grid rings */}
      {rings.map((f, ri) => (
        <polygon key={ri} points={polygon(f)} fill="none" stroke="#e5e7eb" strokeWidth={1} />
      ))}
      {/* Axis lines */}
      {Array.from({ length: n }, (_, i) => (
        <line key={i} x1={cx} y1={cy} x2={px(1, i)} y2={py(1, i)} stroke="#e5e7eb" strokeWidth={1} />
      ))}
      {/* Data polygon */}
      <polygon points={dataPath} fill="#6366f1" fillOpacity={0.15} stroke="#6366f1" strokeWidth={2} strokeLinejoin="round" />
      {/* Data points */}
      {values.map((v, i) => (
        <circle key={i} cx={px(v, i)} cy={py(v, i)} r={3} fill="#6366f1" />
      ))}
      {/* Labels */}
      {labels.map((l, i) => {
        const a = angleOf(i);
        const lx = cx + (r + 18) * Math.cos(a);
        const ly = cy + (r + 18) * Math.sin(a);
        return (
          <text
            key={i}
            x={lx}
            y={ly}
            textAnchor="middle"
            dominantBaseline="central"
            fontSize={8}
            fill="#6b7280"
          >
            {l}
          </text>
        );
      })}
    </svg>
  );
}

// ── Signal cluster badge ──────────────────────────────────────────────────────

function SignalCluster({ type, signals, amountAtRisk, onSelect, isSelected }: {
  type: string;
  signals: Signal[];
  amountAtRisk: number;
  onSelect: (type: string) => void;
  isSelected: boolean;
}) {
  const criticalCount = signals.filter(s => s.urgency_score >= 0.85).length;
  const criticalShare = signals.length > 0 ? criticalCount / signals.length : 0;

  // 7-day trend from signal timestamps — is this cluster growing or cooling?
  const now = Date.now();
  const within = (s: Signal, fromDays: number, toDays: number) => {
    if (!s.created_at) return false;
    const age = (now - new Date(s.created_at).getTime()) / 86_400_000;
    return age >= fromDays && age < toDays;
  };
  const thisWeek = signals.filter(s => within(s, 0, 7)).length;
  const prevWeek = signals.filter(s => within(s, 7, 14)).length;
  const trend = thisWeek - prevWeek;

  // Red is reserved for clusters that are mostly critical — a cluster of
  // medium-urgency signals is amber/neutral, not an alarm
  const severityBar =
    criticalShare >= 0.75 ? "bg-red-400" :
    criticalShare >= 0.4 ? "bg-amber-400" : "bg-zinc-300";

  return (
    <button
      onClick={() => onSelect(type)}
      className={cn(
        "w-full block text-left rounded-2xl border p-4 transition-all duration-150",
        isSelected
          ? "bg-indigo-50 border-indigo-300 shadow-sm"
          : "bg-white border-zinc-200 hover:border-indigo-200 hover:shadow-sm"
      )}
    >
      <div className="flex items-start justify-between mb-2.5">
        <span className={cn(
          "text-sm font-semibold capitalize leading-snug",
          isSelected ? "text-indigo-900" : "text-zinc-800"
        )}>
          {signalLabel(type)}
        </span>
        <span className={cn(
          "text-xl font-bold tabular leading-none ml-2 flex-shrink-0",
          isSelected ? "text-indigo-700" : "text-zinc-900"
        )}>
          {signals.length}
        </span>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        {amountAtRisk > 0 && (
          <span className="text-xs font-semibold text-zinc-700 tabular">
            ${amountAtRisk >= 1_000_000 ? `${(amountAtRisk / 1_000_000).toFixed(1)}M` : `${Math.round(amountAtRisk / 1000)}K`} at risk
          </span>
        )}
        {trend !== 0 && (
          <span className={cn(
            "flex items-center gap-0.5 text-[11px] font-medium",
            trend > 0 ? "text-red-600" : "text-emerald-600"
          )}>
            {trend > 0 ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
            {trend > 0 ? `+${trend}` : trend} this week
          </span>
        )}
        {criticalCount > 0 && trend === 0 && amountAtRisk === 0 && (
          <span className="flex items-center gap-1 text-xs text-red-600">
            <span className="dot dot-critical" />
            {criticalCount} critical
          </span>
        )}
      </div>
      <div className="mt-3 h-1 bg-zinc-100 rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full", severityBar)}
          style={{ width: `${Math.round(Math.max(criticalShare, 0.06) * 100)}%` }}
        />
      </div>
    </button>
  );
}

// ── Account row with radar + links ────────────────────────────────────────────

function AccountRow({ account }: { account: AccountListItem }) {
  const health = account.health_score ?? 0;
  const urgency = account.urgency_score ?? 0;
  const pct = Math.round(health * 100);
  const healthColor = health >= 0.7 ? "bg-green-400" : health >= 0.4 ? "bg-yellow-400" : "bg-red-400";

  // Radar: Health, Momentum (inverse urgency), Coverage, Confidence, Activity
  const radarValues = [
    health,
    Math.max(0, 1 - urgency),                     // Momentum (low urgency = healthy)
    account.last_agent_run_at ? 0.85 : 0.2,        // Coverage
    account.pov_confidence ?? 0.5,                 // Confidence
    Math.min(1, account.signals_summary.length / 5), // Activity
  ];

  return (
    <tr className="hover:bg-zinc-50 transition-colors group">
      <td className="px-5 py-3">
        <Link href={`/account/${account.id}`} className="group-hover:text-indigo-600 transition-colors">
          <p className="font-medium text-zinc-900 group-hover:text-indigo-700">{account.name}</p>
          <p className="text-xs text-zinc-400">
            {account.deal_amount
              ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(account.deal_amount)
              : null}
          </p>
        </Link>
      </td>
      <td className="px-3 py-3 text-xs text-zinc-600">
        {(() => {
          const isRaw = account.stage ? /^\d{6,}$/.test(account.stage) : false;
          return (!account.stage || isRaw) ? <span className="text-zinc-300">Open</span> : account.stage;
        })()}
      </td>
      <td className="px-3 py-3">
        {account.pov_forecast_cat ? (
          <span className={cn(
            "text-xs px-2 py-0.5 rounded-full font-medium",
            account.pov_forecast_cat === "Commit" ? "forecast-commit" :
            account.pov_forecast_cat === "Best Case" ? "forecast-bestcase" :
            account.pov_forecast_cat === "Pipeline" ? "forecast-pipeline" : "forecast-omit"
          )}>
            {account.pov_forecast_cat}
          </span>
        ) : <span className="text-zinc-300 text-xs">-</span>}
      </td>
      <td className="px-3 py-3">
        <div className="flex items-center gap-2">
          <div className="w-16 h-1.5 bg-zinc-100 rounded-full overflow-hidden">
            <div className={cn("h-full rounded-full", healthColor)} style={{ width: `${pct}%` }} />
          </div>
          <span className="text-xs text-zinc-600 w-8">{pct}%</span>
        </div>
      </td>
      <td className="px-3 py-3 text-right">
        <span className={cn(
          "text-xs font-medium",
          urgency >= 0.85 ? "text-red-600" :
          urgency >= 0.7  ? "text-orange-500" :
          urgency >= 0.5  ? "text-yellow-600" : "text-zinc-400"
        )}>
          {Math.round(urgency * 100)}%
        </span>
      </td>
      <td className="px-3 py-3">
        <RadarChart values={radarValues} labels={["Health", "Mom.", "Cov.", "Conf.", "Act."]} size={60} />
      </td>
      <td className="px-5 py-3">
        <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <Link
            href={`/account/${account.id}`}
            className="text-xs font-medium text-indigo-600 hover:text-indigo-700 flex items-center gap-1"
          >
            <ExternalLink className="w-3 h-3" />
            War Room
          </Link>
        </div>
      </td>
    </tr>
  );
}

// ── Kanban board view ─────────────────────────────────────────────────────────

const STAGE_ORDER = [
  "Qualification",
  "Demo",
  "Discovery",
  "Proposal",
  "Negotiation",
  "Closed Won",
  "Closed Lost",
];

function urgencyDotClass(score: number | null) {
  if (!score) return "dot-low";
  if (score >= 0.85) return "dot-critical";
  if (score >= 0.7)  return "dot-high";
  if (score >= 0.5)  return "dot-medium";
  return "dot-low";
}

function KanbanBoard({ accounts }: { accounts: AccountListItem[] }) {
  const isRawId = (s: string | null) => s ? /^\d{6,}$/.test(s) : false;

  // Group accounts by stage, normalise raw stage IDs to "Unknown"
  const grouped = accounts.reduce<Record<string, AccountListItem[]>>((acc, a) => {
    const stage = !a.stage || isRawId(a.stage) ? "Unknown" : a.stage;
    acc[stage] = acc[stage] ?? [];
    acc[stage].push(a);
    return acc;
  }, {});

  // Order columns: known stages first (in order), then unknown, then anything else
  const stages = [
    ...STAGE_ORDER.filter(s => grouped[s]?.length > 0),
    ...Object.keys(grouped).filter(s => !STAGE_ORDER.includes(s) && s !== "Unknown" && grouped[s]?.length > 0),
    ...(grouped["Unknown"]?.length > 0 ? ["Unknown"] : []),
  ];

  const fmtAmount = (n: number | null) =>
    n ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 }).format(n) : null;

  return (
    <div className="flex gap-3 overflow-x-auto pb-4 px-6 pt-2" style={{ scrollbarWidth: "none" }}>
      {stages.map(stage => {
        const cards = grouped[stage] ?? [];
        const totalAmt = cards.reduce((s, a) => s + (a.deal_amount ?? 0), 0);
        return (
          <div key={stage} className="min-w-[220px] flex-shrink-0 bg-zinc-50 rounded-2xl p-3 border border-zinc-100">
            <div className="flex items-center justify-between mb-3">
              <p className="text-xs font-semibold text-zinc-600 truncate" title={stage}>{stage}</p>
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] text-zinc-400">{cards.length}</span>
                {totalAmt > 0 && (
                  <span className="text-[10px] font-medium text-zinc-500 bg-white border border-zinc-200 rounded px-1.5 py-0.5">
                    {fmtAmount(totalAmt)}
                  </span>
                )}
              </div>
            </div>
            <div className="space-y-2">
              {cards.map(a => (
                <Link
                  key={a.id}
                  href={`/account/${a.id}`}
                  className="block bg-white rounded-xl border border-zinc-200 p-3 hover:border-zinc-300 hover:shadow-sm transition-all"
                >
                  <div className="flex items-start gap-2 mb-1.5">
                    <span className={cn("dot mt-0.5 flex-shrink-0", urgencyDotClass(a.urgency_score))} />
                    <p className="text-[13px] font-medium text-zinc-900 leading-snug line-clamp-2" title={a.name}>
                      {cleanDealName(a.name)}
                    </p>
                  </div>
                  {(a.deal_amount || a.close_date) && (
                    <div className="flex items-center gap-2 ml-[18px]">
                      {a.deal_amount && (
                        <span className="text-xs text-zinc-500 tabular">{fmtAmount(a.deal_amount)}</span>
                      )}
                      {a.close_date && (
                        <span className="text-xs text-zinc-400" title={`Close date: ${formatDate(a.close_date)}`}>
                          {formatDate(a.close_date)}
                        </span>
                      )}
                    </div>
                  )}
                  {a.pending_drafts > 0 && (
                    <div className="flex justify-end mt-1.5">
                      <span
                        className="text-[10px] font-bold bg-indigo-600 text-white px-1.5 py-0.5 rounded-full leading-none"
                        title={`${a.pending_drafts} draft${a.pending_drafts === 1 ? "" : "s"} awaiting review`}
                      >
                        {a.pending_drafts}
                      </span>
                    </div>
                  )}
                </Link>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function WatchtowerPage() {
  const queryClient = useQueryClient();
  const [signalFilter, setSignalFilter] = useState<string>("all");
  const [selectedCluster, setSelectedCluster] = useState<string | null>(null);
  const [view, setView] = useState<"pipeline" | "board" | "forecast" | "delta">("pipeline");
  const [actingOnCluster, setActingOnCluster] = useState<string | null>(null);
  const qc = useQueryClient();

  const { data: accountsData } = useQuery({
    queryKey: ["accounts", "all"],
    queryFn: () => accountsApi.list({ limit: 100, sort_by: "health_score", sort_dir: "asc" }),
    staleTime: 2 * 60 * 1000,
  });

  const { data: signalsData, dataUpdatedAt } = useQuery({
    queryKey: ["signals", "high"],
    queryFn: () => signalsApi.list({ min_urgency: 0.7, limit: 100 }),
    refetchInterval: 2 * 60 * 1000,
  });

  const { data: stalledData } = useQuery({
    queryKey: ["analytics", "stalled"],
    queryFn: () => analyticsApi.stalledDeals(10),
    staleTime: 5 * 60 * 1000,
  });

  const { data: competitiveData } = useQuery({
    queryKey: ["analytics", "competitive"],
    queryFn: analyticsApi.competitiveLeaderboard,
    staleTime: 10 * 60 * 1000,
  });

  const { data: forecastData, isLoading: forecastLoading } = useQuery({
    queryKey: ["forecast", "rollup"],
    queryFn: () => forecastApi.rollup(),
    // Always fetch: the Pipeline KPI row uses the server-side rollup totals so
    // they match the Forecast page (the client-side sum only sees one page).
    staleTime: 5 * 60 * 1000,
  });
  const forecast = forecastData?.data;

  const { data: deltaData } = useQuery({
    queryKey: ["analytics", "watchtower-delta"],
    queryFn: analyticsApi.watcherDelta,
    staleTime: 5 * 60 * 1000,
    enabled: view === "delta",
  });

  const { data: reviewData } = useQuery({
    queryKey: ["analytics", "pipeline-review"],
    queryFn: analyticsApi.pipelineReview,
    staleTime: 10 * 60 * 1000,
    enabled: view === "delta",
  });
  const delta: WatcherDeltaData | undefined = deltaData?.data;

  const ackMutation = useMutation({
    mutationFn: signalsApi.acknowledge,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["signals"] }),
  });

  const handleActOnCluster = async (clusterType: string) => {
    setActingOnCluster(clusterType);
    try {
      await agentApi.refreshUrgent();
      toast.success(`Queued urgent re-analysis for ${signalLabel(clusterType)} accounts.`);
      qc.invalidateQueries({ queryKey: ["action-queue"] });
    } catch {
      toast.error("Could not queue re-analysis.");
    }
    setActingOnCluster(null);
  };

  const accounts = accountsData?.data ?? [];
  const allSignals = signalsData?.data ?? [];

  // Stats
  const atRisk = accounts.filter(a => (a.health_score ?? 1) < 0.4).length;
  const avgHealth = accounts.length > 0
    ? accounts.reduce((sum, a) => sum + (a.health_score ?? 0.5), 0) / accounts.length
    : 0;
  const commitCount = accounts.filter(a => a.pov_forecast_cat === "Commit").length;
  // Server-side rollup is the source of truth — the paginated accounts list
  // only sees the first page and undercounts the portfolio.
  const totalPipeline = forecast?.total_pipeline
    ?? accounts.reduce((sum, a) => sum + (a.deal_amount ?? 0), 0);
  const totalAccounts = forecast?.accounts_total ?? accounts.length;

  // Signal clustering by type
  const signalsByType = allSignals.reduce<Record<string, Signal[]>>((acc, s) => {
    acc[s.type] = acc[s.type] ?? [];
    acc[s.type].push(s);
    return acc;
  }, {});

  // $ at risk per cluster — sum of unique account amounts (from the loaded page
  // of accounts; deals we can't resolve are excluded rather than guessed)
  const amountById = new Map(accounts.map(a => [a.id, a.deal_amount ?? 0]));
  const clusterAmount = (sigs: Signal[]) => {
    const seen = new Set<string>();
    let total = 0;
    for (const s of sigs) {
      const accId = s.account?.id;
      if (accId && !seen.has(accId)) {
        seen.add(accId);
        total += amountById.get(accId) ?? 0;
      }
    }
    return total;
  };

  // Filter displayed signals
  const displaySignals = selectedCluster
    ? allSignals.filter(s => s.type === selectedCluster)
    : signalFilter === "all"
    ? allSignals
    : allSignals.filter(s => s.urgency === signalFilter);

  // Sort accounts: at-risk first, then by urgency
  const sortedAccounts = [...accounts].sort((a, b) => {
    const aRisk = (a.health_score ?? 0.5) < 0.4 ? 0 : 1;
    const bRisk = (b.health_score ?? 0.5) < 0.4 ? 0 : 1;
    if (aRisk !== bRisk) return aRisk - bRisk;
    return (b.urgency_score ?? 0) - (a.urgency_score ?? 0);
  });

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-zinc-900">Watchtower</h1>
          <p className="text-sm text-zinc-500 mt-0.5">Portfolio health · Signal clusters · Forecast roll-up</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="tab-bar">
            {(["pipeline", "board", "forecast", "delta"] as const).map(v => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={cn("tab-pill capitalize", view === v && "tab-pill-active")}
              >
                {v === "delta" ? "This Week" : v}
              </button>
            ))}
          </div>
          {dataUpdatedAt > 0 && (
            <p className="text-xs text-zinc-400">
              Updated {formatDistanceToNow(new Date(dataUpdatedAt), { addSuffix: true })}
            </p>
          )}
        </div>
      </div>

      {view === "pipeline" && (
        <>
          {/* KPI row */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="card px-5 py-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-zinc-400 font-medium uppercase tracking-wider">Total Pipeline</span>
                <TrendingUp className="w-4 h-4 text-green-500" />
              </div>
              <p className="text-4xl font-bold text-zinc-900 tabular-nums tracking-tight leading-none">
                ${(totalPipeline / 1_000_000).toFixed(1)}M
              </p>
              <p className="text-xs text-zinc-400 mt-2">{totalAccounts} accounts</p>
            </div>

            <div className="card px-5 py-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-zinc-400 font-medium uppercase tracking-wider">Commit</span>
                <Activity className="w-4 h-4 text-blue-500" />
              </div>
              <p className="text-4xl font-bold text-zinc-900 tabular-nums tracking-tight leading-none">{commitCount}</p>
              <p className="text-xs text-zinc-400 mt-2">AI forecast · Commit category</p>
            </div>

            <div className={cn(
              "card px-5 py-4",
              atRisk > 0 ? "card-urgent border-l-red-400" : ""
            )}>
              <div className="flex items-center justify-between mb-2">
                <span className={cn("text-xs font-medium uppercase tracking-wider", atRisk > 0 ? "text-red-600" : "text-zinc-400")}>At Risk</span>
                <AlertTriangle className={cn("w-4 h-4", atRisk > 0 ? "text-red-500" : "text-zinc-400")} />
              </div>
              <p className={cn("text-4xl font-bold tabular-nums tracking-tight leading-none", atRisk > 0 ? "text-red-700" : "text-zinc-900")}>{atRisk}</p>
              <p className={cn("text-xs mt-2", atRisk > 0 ? "text-red-500" : "text-zinc-400")}>Health below 40%</p>
            </div>

            <div className="card px-5 py-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-zinc-400 font-medium uppercase tracking-wider">Avg Health</span>
                <TrendingDown className="w-4 h-4 text-zinc-400" />
              </div>
              <p className={cn(
                "text-4xl font-bold tabular-nums tracking-tight leading-none",
                avgHealth >= 0.7 ? "text-green-700" :
                avgHealth >= 0.4 ? "text-amber-700" :
                "text-red-700"
              )}>
                {Math.round(avgHealth * 100)}%
              </p>
              <p className="text-xs text-zinc-400 mt-2">Portfolio average</p>
            </div>
          </div>

          {/* Signal clusters */}
          {Object.keys(signalsByType).length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-zinc-900">Signal Clusters <span className="text-zinc-400 font-normal ml-1">(last 30 days)</span></h2>
                {selectedCluster && (
                  <button
                    onClick={() => setSelectedCluster(null)}
                    className="text-xs text-indigo-600 hover:text-indigo-700 font-medium"
                  >
                    Clear filter ×
                  </button>
                )}
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                {Object.entries(signalsByType)
                  .sort(([, a], [, b]) => b.length - a.length)
                  .map(([type, sigs]) => (
                    <SignalCluster
                      key={type}
                      type={type}
                      signals={sigs}
                      amountAtRisk={clusterAmount(sigs)}
                      isSelected={selectedCluster === type}
                      onSelect={(t) => setSelectedCluster(prev => prev === t ? null : t)}
                    />
                  ))}
              </div>

              {/* Inline deal list - expands when a cluster is selected */}
              {selectedCluster && (() => {
                const clusterSignals = signalsByType[selectedCluster] ?? [];
                // Deduplicate by account ID
                const seen = new Set<string>();
                const uniqueSignals = clusterSignals.filter(s => {
                  const id = s.account?.id;
                  if (!id || seen.has(id)) return false;
                  seen.add(id);
                  return true;
                });
                return (
                  <div className="mt-3 card overflow-hidden animate-fade-up">
                    <div className="px-4 py-3 border-b border-zinc-100 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="dot dot-critical" />
                        <p className="text-sm font-semibold text-zinc-900">
                          {signalLabel(selectedCluster)}
                        </p>
                        <span className="badge-neutral">{uniqueSignals.length} deals</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => handleActOnCluster(selectedCluster)}
                          disabled={actingOnCluster === selectedCluster}
                          className="flex items-center gap-1 text-xs font-medium px-2.5 py-1 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-40 transition-colors"
                        >
                          <Zap className="w-3 h-3" />
                          {actingOnCluster === selectedCluster ? "Queuing..." : "Act on this"}
                        </button>
                        <button
                          onClick={() => setSelectedCluster(null)}
                          className="text-zinc-400 hover:text-zinc-600 text-xs"
                        >
                          ✕
                        </button>
                      </div>
                    </div>
                    <div className="divide-y divide-zinc-50 max-h-72 overflow-y-auto">
                      {uniqueSignals.map(s => (
                        <Link
                          key={s.account?.id ?? s.id}
                          href={`/account/${s.account?.id}`}
                          className="flex items-center gap-3 px-4 py-3 hover:bg-zinc-50 transition-colors group"
                        >
                          <span className={cn(
                            "dot flex-shrink-0",
                            s.urgency_score >= 0.85 ? "dot-critical" :
                            s.urgency_score >= 0.7  ? "dot-high" : "dot-medium"
                          )} />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-zinc-900 truncate">{s.account?.name}</p>
                            <p className="text-xs text-zinc-400 truncate">{s.detail}</p>
                          </div>
                          <span className="text-xs text-indigo-600 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                            Open →
                          </span>
                        </Link>
                      ))}
                    </div>
                  </div>
                );
              })()}
            </div>
          )}

          {/* Stalled Deals panel (E1) */}
          {(stalledData?.data?.count ?? 0) > 0 && (
            <div className="card overflow-hidden">
              <div className="px-5 py-4 border-b border-zinc-100 flex items-center justify-between">
                <div>
                  <h2 className="text-sm font-semibold text-zinc-900">Stalled Deals</h2>
                  <p className="text-xs text-zinc-400 mt-0.5">Declining or stalling momentum · Sorted by deal size</p>
                </div>
                <div className="text-right">
                  <p className="text-xs text-zinc-400">At risk</p>
                  <p className="text-sm font-bold text-red-600">
                    ${((stalledData?.data?.total_at_risk ?? 0) / 1_000_000).toFixed(1)}M
                  </p>
                </div>
              </div>
              <div className="divide-y divide-gray-50">
                {(stalledData?.data?.deals ?? []).map((deal: StalledDeal) => (
                  <div key={deal.id} className="flex items-center justify-between px-5 py-3 hover:bg-zinc-50 group">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium text-zinc-900 truncate">{deal.name}</p>
                        <span className={cn(
                          "text-xs font-medium flex-shrink-0 flex items-center gap-1",
                          deal.momentum === "declining" ? "text-red-600" : "text-amber-700"
                        )}>
                          <span className={cn("dot", deal.momentum === "declining" ? "dot-critical" : "dot-high")} />
                          {deal.momentum === "declining" ? "Declining" : "Stalling"}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 mt-0.5 text-xs text-zinc-400">
                        <span>{deal.stage ?? "Unknown stage"}</span>
                        <span>·</span>
                        <span>{deal.days_stuck != null ? `${deal.days_stuck}d since buyer activity` : "buyer activity unknown"}</span>
                        {deal.deal_amount && (
                          <>
                            <span>·</span>
                            <span className="font-medium text-zinc-600">
                              {new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(deal.deal_amount)}
                            </span>
                          </>
                        )}
                      </div>
                    </div>
                    <Link
                      href={`/account/${deal.id}`}
                      className="ml-3 text-xs font-medium text-indigo-600 hover:text-indigo-700 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
                    >
                      <ExternalLink className="w-3 h-3" />
                      War Room
                    </Link>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Competitor leaderboard (E2) */}
          {(competitiveData?.data?.competitors ?? []).length > 0 && (
            <div className="card overflow-hidden">
              <div className="px-5 py-4 border-b border-zinc-100">
                <h2 className="text-sm font-semibold text-zinc-900">Active Competitions</h2>
                <p className="text-xs text-zinc-400 mt-0.5">Competitors detected in active deals (last 90 days)</p>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-0 divide-x divide-gray-100">
                {(competitiveData?.data?.competitors ?? []).slice(0, 5).map((c: CompetitorEntry) => (
                  <div key={c.competitor} className="px-5 py-4">
                    <p className="text-sm font-semibold text-zinc-900 truncate">{c.competitor}</p>
                    <p className="text-xs text-zinc-400 mt-0.5">{c.deal_count} deal{c.deal_count !== 1 ? "s" : ""}</p>
                    <p className="text-xs font-medium text-red-600 mt-1">
                      {new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 }).format(c.total_amount_at_risk)} at risk
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Main body - health grid + signal feed */}
          <div className="grid grid-cols-3 gap-6">
            {/* Health grid */}
            <div className="col-span-2 bg-white border border-zinc-200 rounded-xl">
              <div className="px-5 py-4 border-b border-zinc-100">
                <h2 className="text-sm font-semibold text-zinc-900">Portfolio Health Grid</h2>
                <p className="text-xs text-zinc-400 mt-0.5">Hover any row for War Room link · Radar = 5-dimensional health</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-zinc-500 border-b border-zinc-100">
                      <th className="text-left px-5 py-2.5 font-medium">Account</th>
                      <th className="text-left px-3 py-2.5 font-medium">Stage</th>
                      <th className="text-left px-3 py-2.5 font-medium">AI Forecast</th>
                      <th className="text-left px-3 py-2.5 font-medium">Health</th>
                      <th className="text-right px-3 py-2.5 font-medium">Urgency</th>
                      <th className="text-left px-3 py-2.5 font-medium">Radar</th>
                      <th className="px-5 py-2.5" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {sortedAccounts.slice(0, 25).map((account) => (
                      <AccountRow key={account.id} account={account} />
                    ))}
                    {sortedAccounts.length === 0 && (
                      <tr>
                        <td colSpan={7} className="px-5 py-12 text-center text-sm text-zinc-400">
                          No accounts yet. Run a HubSpot sync or add accounts manually.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Signal feed */}
            <div className="card flex flex-col">
              <div className="px-5 py-4 border-b border-zinc-100">
                <div className="flex items-center justify-between mb-2">
                  <h2 className="text-sm font-semibold text-zinc-900">Risk Feed</h2>
                  <span className="text-xs text-zinc-400">{displaySignals.length} signals</span>
                </div>

                {/* Filter strip */}
                <div className="flex items-center gap-1">
                  <Filter className="w-3 h-3 text-zinc-400" />
                  {["all", "critical", "high"].map(f => (
                    <button
                      key={f}
                      onClick={() => { setSignalFilter(f); setSelectedCluster(null); }}
                      className={cn(
                        "text-xs px-2 py-0.5 rounded-full transition-colors capitalize",
                        signalFilter === f && !selectedCluster
                          ? "bg-indigo-100 text-indigo-700 font-medium"
                          : "text-zinc-400 hover:text-zinc-600"
                      )}
                    >
                      {f}
                    </button>
                  ))}
                  {selectedCluster && (
                    <span className="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full font-medium capitalize ml-1">
                      {signalLabel(selectedCluster)}
                    </span>
                  )}
                </div>
              </div>

              <div className="flex-1 overflow-y-auto divide-y divide-gray-50">
                {displaySignals.length === 0 ? (
                  <div className="p-6 text-center text-zinc-400 text-sm">
                    {allSignals.length === 0 ? "No high-urgency signals" : "No signals match filter"}
                  </div>
                ) : displaySignals.slice(0, 50).map((signal) => (
                  <div key={signal.id} className="px-5 py-3 hover:bg-zinc-50 transition-colors group">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5 mb-0.5">
                          <div className={cn(
                            "w-2 h-2 rounded-full flex-shrink-0",
                            signal.urgency_score >= 0.85 ? "bg-red-500" :
                            signal.urgency_score >= 0.7  ? "bg-orange-400" : "bg-yellow-400"
                          )} />
                          <Link
                            href={`/account/${signal.account?.id}`}
                            className="text-xs font-semibold text-zinc-900 hover:text-indigo-600 transition-colors truncate"
                          >
                            {signal.account?.name}
                          </Link>
                        </div>
                        <p className="text-xs text-zinc-500 leading-relaxed line-clamp-2">{signal.detail}</p>
                        <div className="flex items-center gap-2 mt-1">
                          <span className="text-xs text-zinc-300">{signalLabel(signal.type)}</span>
                          <span className="text-xs text-zinc-300">·</span>
                          <span className="text-xs text-zinc-300">
                            {signal.created_at ? formatDistanceToNow(new Date(signal.created_at), { addSuffix: true }) : ""}
                          </span>
                        </div>
                      </div>
                      {!signal.acknowledged && (
                        <button
                          onClick={() => ackMutation.mutate(signal.id)}
                          className="text-gray-200 hover:text-green-500 transition-colors flex-shrink-0 opacity-0 group-hover:opacity-100"
                          title="Acknowledge"
                        >
                          <CheckCircle className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}

      {view === "board" && (
        <KanbanBoard accounts={sortedAccounts} />
      )}

      {view === "forecast" && (
        <div className="p-6 space-y-6">
          {forecastLoading ? (
            <div className="flex items-center justify-center py-16">
              <div className="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : forecast ? (
            <>
              {/* Category cards */}
              <div>
                <h2 className="text-sm font-semibold text-zinc-900 mb-3">AI Forecast Breakdown</h2>
                <div className="grid grid-cols-4 gap-3">
                  {(["Commit", "Best Case", "Pipeline", "Omit"] as const).map(cat => {
                    const d = forecast.categories[cat];
                    const amount = d?.total_amount ?? 0;
                    const count = d?.count ?? 0;
                    return (
                      <div key={cat} className="card p-4">
                        <span className={cn(
                          "text-xs font-medium px-2 py-0.5 rounded-full",
                          cat === "Commit" ? "forecast-commit" :
                          cat === "Best Case" ? "forecast-bestcase" :
                          cat === "Pipeline" ? "forecast-pipeline" : "forecast-omit"
                        )}>
                          {cat}
                        </span>
                        <p className="text-2xl font-bold text-zinc-900 tabular-nums tracking-tight mt-2">
                          {amount > 0
                            ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0, notation: "compact" }).format(amount)
                            : "-"}
                        </p>
                        <p className="text-xs text-zinc-400 mt-0.5">{count} deal{count !== 1 ? "s" : ""}</p>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* AI vs CRM delta table */}
              {forecast.ai_vs_crm_deltas.length > 0 && (
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <h2 className="text-sm font-semibold text-zinc-900">AI vs CRM Disagreements</h2>
                    <span className="text-xs text-zinc-400">{forecast.ai_vs_crm_deltas.length} deals</span>
                  </div>
                  <div className="card overflow-hidden">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-zinc-100 bg-zinc-50">
                          <th className="text-left px-4 py-2.5 font-medium text-zinc-500">Account</th>
                          <th className="text-left px-4 py-2.5 font-medium text-zinc-500">Amount</th>
                          <th className="text-left px-4 py-2.5 font-medium text-zinc-500">AI Forecast</th>
                          <th className="text-left px-4 py-2.5 font-medium text-zinc-500">CRM Forecast</th>
                          <th className="text-right px-4 py-2.5 font-medium text-zinc-500">AI Confidence</th>
                        </tr>
                      </thead>
                      <tbody>
                        {forecast.ai_vs_crm_deltas.map((delta: AiVsCrmDelta) => (
                          <tr key={delta.account_id} className="border-b border-gray-50 last:border-0 hover:bg-zinc-50 transition-colors">
                            <td className="px-4 py-3">
                              <a href={`/account/${delta.account_id}`} className="font-medium text-zinc-900 hover:text-indigo-600 transition-colors">
                                {delta.name}
                              </a>
                              {delta.overridden && (
                                <span className="ml-1.5 text-xs text-zinc-400">(overridden)</span>
                              )}
                            </td>
                            <td className="px-4 py-3 text-zinc-600">
                              {delta.amount > 0
                                ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(delta.amount)
                                : "-"}
                            </td>
                            <td className="px-4 py-3">
                              <span className={cn(
                                "text-xs font-medium px-2 py-0.5 rounded-full",
                                delta.ai_category === "Commit" ? "forecast-commit" :
                                delta.ai_category === "Best Case" ? "forecast-bestcase" :
                                delta.ai_category === "Pipeline" ? "forecast-pipeline" : "forecast-omit"
                              )}>
                                {delta.ai_category}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-zinc-600">{delta.crm_category}</td>
                            <td className="px-4 py-3 text-right text-zinc-500">{Math.round(delta.ai_confidence * 100)}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              <p className="text-xs text-zinc-400">
                {forecast.accounts_analyzed} of {forecast.accounts_total} accounts analyzed.
                {forecast.overridden_count > 0 && ` ${forecast.overridden_count} rep override${forecast.overridden_count !== 1 ? "s" : ""} active.`}
              </p>
            </>
          ) : (
            <div className="text-center py-16 text-sm text-zinc-400">
              No forecast data. Run the agent on your accounts to populate forecasts.
            </div>
          )}
        </div>
      )}

      {/* ── Delta / This Week view (#20) ─────────────────────────────────────── */}
      {view === "delta" && (
        <div className="space-y-4">
          {!delta ? (
            <div className="text-center py-16 text-sm text-zinc-400">Loading weekly delta...</div>
          ) : (
            <>
              {/* Summary tiles */}
              <div className="grid grid-cols-3 gap-4">
                {[
                  {
                    label: "Signals this week",
                    value: delta.signals.this_week,
                    sub: `${delta.signals.last_week} last week`,
                    delta: delta.signals.delta,
                    critical: delta.signals.critical_this_week > 0 ? `${delta.signals.critical_this_week} critical` : null,
                  },
                  {
                    label: "Stage moves",
                    value: delta.stage_moves.this_week,
                    sub: `${delta.stage_moves.last_week} last week`,
                    delta: delta.stage_moves.delta,
                    critical: null,
                  },
                ].map(tile => (
                  <div key={tile.label} className="card p-4">
                    <p className="text-xs text-zinc-400 mb-1">{tile.label}</p>
                    <p className="text-4xl font-bold text-zinc-900 tabular-nums tracking-tight leading-none">{tile.value}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <p className="text-xs text-zinc-400">{tile.sub}</p>
                      {tile.delta !== 0 && (
                        <span className={cn("text-xs font-medium", tile.delta > 0 ? "text-red-600" : "text-emerald-600")}>
                          {tile.delta > 0 ? `+${tile.delta}` : tile.delta}
                        </span>
                      )}
                      {tile.critical && <span className="text-xs text-red-600 font-medium">{tile.critical}</span>}
                    </div>
                  </div>
                ))}
                <div className="card p-4">
                  <p className="text-xs text-zinc-400 mb-1">Needs attention now</p>
                  <p className="text-4xl font-bold text-zinc-900 tabular-nums tracking-tight leading-none">{delta.top_urgent_accounts.length}</p>
                  <p className="text-xs text-zinc-400 mt-1">High urgency accounts</p>
                </div>
              </div>

              {/* Top urgent accounts */}
              {delta.top_urgent_accounts.length > 0 && (
                <div className="card overflow-hidden">
                  <div className="px-5 py-4 border-b border-zinc-100">
                    <h3 className="text-sm font-semibold text-zinc-900">Accounts Needing Attention</h3>
                  </div>
                  <div className="divide-y divide-zinc-50">
                    {delta.top_urgent_accounts.map(acc => (
                      <a
                        key={acc.account_id}
                        href={`/account/${acc.account_id}`}
                        className="flex items-center gap-3 px-5 py-3 hover:bg-zinc-50 transition-colors group"
                      >
                        <span className={cn(
                          "dot flex-shrink-0",
                          acc.urgency_score >= 0.85 ? "dot-critical" :
                          acc.urgency_score >= 0.7 ? "dot-high" : "dot-medium"
                        )} />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-zinc-900 truncate">{acc.name}</p>
                          <p className="text-xs text-zinc-400">{acc.stage}</p>
                        </div>
                        <div className="text-right flex-shrink-0">
                          <p className="text-xs font-medium text-zinc-700">{Math.round(acc.urgency_score * 100)}% urgency</p>
                          <p className="text-xs text-zinc-400">{Math.round(acc.health_score * 100)}% health</p>
                        </div>
                        <ExternalLink className="w-3.5 h-3.5 text-zinc-300 group-hover:text-indigo-500 transition-colors flex-shrink-0" />
                      </a>
                    ))}
                  </div>
                </div>
              )}

              {/* Weekly AI Pipeline Review */}
              {reviewData?.data && <PipelineReviewPanel review={reviewData.data} />}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Weekly Pipeline Review ────────────────────────────────────────────────────

function PipelineReviewPanel({ review }: { review: PipelineReview }) {
  const fmtK = (v: number) =>
    v >= 1_000_000 ? `$${(v / 1_000_000).toFixed(1)}M` : `$${Math.round(v / 1000)}K`;

  const sections: { key: keyof Pick<PipelineReview, "moved" | "stalled" | "slipped" | "meddpicc_gaps" | "no_next_step">; title: string; detail: (d: PipelineReviewDeal) => string }[] = [
    {
      key: "moved",
      title: "Moved this week",
      detail: d => `${d.from_category} → ${d.to_category}${d.reason ? ` — ${d.reason}` : ""}`,
    },
    {
      key: "stalled",
      title: "Stalled",
      detail: d => `${d.momentum}${d.days_since_buyer_activity != null ? ` · ${d.days_since_buyer_activity}d since buyer activity` : ""}`,
    },
    {
      key: "slipped",
      title: "Slipped close dates",
      detail: d => `was ${d.close_date} · ${d.days_overdue}d overdue`,
    },
    {
      key: "meddpicc_gaps",
      title: "Late-stage qualification gaps",
      detail: d => `MEDDPICC ${Math.round((d.overall_score ?? 0) * 100)}%${d.gaps?.length ? ` — ${d.gaps.join("; ")}` : ""}`,
    },
    {
      key: "no_next_step",
      title: "No next step recorded",
      detail: d => d.stage ?? "",
    },
  ];

  return (
    <div className="card overflow-hidden">
      <div className="px-5 py-4 border-b border-zinc-100 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-zinc-900">Weekly Pipeline Review</h3>
          <p className="text-xs text-zinc-400 mt-0.5">Week of {review.week_of} · generated from nightly agent data</p>
        </div>
      </div>
      <div className="divide-y divide-zinc-100">
        {sections.map(({ key, title, detail }) => {
          const section = review[key];
          if (!section || section.count === 0) return null;
          return (
            <div key={key} className="px-5 py-4">
              <div className="flex items-center gap-2 mb-2">
                <h4 className="text-xs font-semibold text-zinc-700 uppercase tracking-wide">{title}</h4>
                <span className="text-[11px] text-zinc-400">
                  {section.count} deal{section.count !== 1 ? "s" : ""} · {fmtK(section.total_amount)}
                </span>
              </div>
              <div className="space-y-1.5">
                {section.deals.slice(0, 5).map(d => (
                  <a
                    key={d.account_id}
                    href={`/account/${d.account_id}`}
                    className="flex items-baseline gap-2 group"
                  >
                    <span className="text-xs font-medium text-zinc-800 group-hover:text-indigo-600 transition-colors flex-shrink-0">
                      {cleanDealName(d.name)}
                    </span>
                    <span className="text-[11px] text-zinc-400 tabular flex-shrink-0">{fmtK(d.amount)}</span>
                    <span className="text-[11px] text-zinc-400 truncate">{detail(d)}</span>
                  </a>
                ))}
                {section.count > 5 && (
                  <p className="text-[11px] text-zinc-300">+{section.count - 5} more</p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
