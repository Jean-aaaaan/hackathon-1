"use client";

import { Suspense } from "react";
import { useQuery } from "@tanstack/react-query";
import { analyticsApi, forecastApi, signalsApi, accountsApi, type AccountListItem, type CompetitorEntry, type StalledDeal, type SignalTypeData } from "@/lib/api";
import { cn, signalLabel, formatCompactCurrency } from "@/lib/utils";
import { TrendingUp, AlertTriangle, Zap, Shield, Users } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtMoney(v: number) {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${Math.round(v / 1000)}K`;
  return `$${v}`;
}

function fmtPct(v: number) {
  return `${Math.round(v * 100)}%`;
}

// ── KPI card ──────────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, icon: Icon, accent }: {
  label: string;
  value: string;
  sub?: string;
  icon: React.ElementType;
  accent?: string;
}) {
  return (
    <div className="card p-6">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs text-zinc-400 font-medium uppercase tracking-wider">{label}</p>
        <Icon className={cn("w-4 h-4", accent ?? "text-zinc-400")} />
      </div>
      <p className="text-4xl font-bold text-zinc-900 tabular-nums tracking-tight leading-none">{value}</p>
      {sub && <p className="text-xs text-zinc-400 mt-2">{sub}</p>}
    </div>
  );
}

// ── Signal urgency bar ────────────────────────────────────────────────────────

function SignalUrgencyBar({ data }: { data: SignalTypeData }) {
  const total = data.total || 1;
  const critical = data.by_urgency?.critical ?? 0;
  const high     = data.by_urgency?.high     ?? 0;
  const medium   = data.by_urgency?.medium   ?? 0;

  const critPct = Math.round((critical / total) * 100);
  const highPct = Math.round((high     / total) * 100);
  const medPct  = Math.round((medium   / total) * 100);

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <p className="text-sm font-medium text-zinc-900">{signalLabel(data.type)}</p>
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-500 tabular-nums">{data.total} signals</span>
          {critical > 0 && (
            <span className="text-[10px] font-semibold text-red-600 bg-red-50 px-1.5 py-0.5 rounded-full">
              {critical} critical
            </span>
          )}
        </div>
      </div>
      <div className="h-1.5 bg-zinc-100 rounded-full overflow-hidden flex">
        {critPct > 0 && <div className="h-full bg-red-400" style={{ width: `${critPct}%` }} />}
        {highPct > 0 && <div className="h-full bg-orange-400" style={{ width: `${highPct}%` }} />}
        {medPct  > 0 && <div className="h-full bg-amber-400" style={{ width: `${medPct}%` }} />}
        <div className="h-full bg-emerald-300 flex-1" />
      </div>
      <div className="flex items-center gap-3 mt-1">
        {critPct > 0 && <span className="text-[10px] text-red-500">{critPct}% critical</span>}
        {highPct > 0 && <span className="text-[10px] text-orange-500">{highPct}% high</span>}
        {medPct  > 0 && <span className="text-[10px] text-amber-500">{medPct}% medium</span>}
      </div>
    </div>
  );
}

// ── Main page content ─────────────────────────────────────────────────────────

function IntelligenceInner() {
  const { data: forecastData } = useQuery({
    queryKey: ["forecast", "rollup"],
    queryFn: () => forecastApi.rollup(),
    staleTime: 5 * 60 * 1000,
  });
  const forecast = forecastData?.data;

  const { data: stalledData } = useQuery({
    queryKey: ["analytics", "stalled-intel"],
    queryFn: () => analyticsApi.stalledDeals(20),
    staleTime: 5 * 60 * 1000,
  });
  const stalled = stalledData?.data;

  const { data: competitiveData, isLoading: compLoading } = useQuery({
    queryKey: ["analytics", "competitive"],
    queryFn: analyticsApi.competitiveLeaderboard,
    staleTime: 10 * 60 * 1000,
  });
  const competitors: CompetitorEntry[] = competitiveData?.data?.competitors ?? [];

  const { data: signalTypesData, isLoading: sigLoading } = useQuery({
    queryKey: ["analytics", "signal-types"],
    queryFn: analyticsApi.signalTypes,
    staleTime: 10 * 60 * 1000,
  });
  const signalTypes: SignalTypeData[] = (signalTypesData?.data ?? [])
    .sort((a: SignalTypeData, b: SignalTypeData) => b.total - a.total);

  const { data: darData } = useQuery({
    queryKey: ["analytics", "dar-trend", 30],
    queryFn: () => analyticsApi.darTrend(30),
    staleTime: 5 * 60 * 1000,
  });
  const darPoints = darData?.data ?? [];
  const latestDar = darPoints.length > 0 ? darPoints[darPoints.length - 1]?.dar_pct ?? 0 : 0;

  const { data: accountsData } = useQuery({
    queryKey: ["accounts", "intel"],
    queryFn: () => accountsApi.list({ limit: 100, sort_by: "health_score", sort_dir: "asc" }),
    staleTime: 5 * 60 * 1000,
  });
  const accounts: AccountListItem[] = accountsData?.data ?? [];
  const atRiskCount = accounts.filter(a => (a.health_score ?? 1) < 0.4).length;

  // Timeline bins — bucket accounts by close_date proximity
  const nowMs = Date.now();
  const timelineBins = [
    { label: "Immediate", desc: "≤30 days",    color: "bg-red-400"    },
    { label: "Near-term", desc: "31–90 days",  color: "bg-amber-400"  },
    { label: "Mid-term",  desc: "91–180 days", color: "bg-zinc-500" },
    { label: "Long-term", desc: ">180 days",   color: "bg-zinc-300"   },
    { label: "No Date",   desc: "Not set",     color: "bg-zinc-200"   },
  ].map((bin, i) => ({
    ...bin,
    deals: accounts.filter(a => {
      if (!a.close_date) return i === 4;
      const days = (new Date(a.close_date).getTime() - nowMs) / 86400000;
      if (i === 0) return days <= 30;
      if (i === 1) return days > 30 && days <= 90;
      if (i === 2) return days > 90 && days <= 180;
      if (i === 3) return days > 180;
      return false;
    }),
  }));
  const timelineMax = Math.max(1, ...timelineBins.map(b => b.deals.length));

  // Risk vectors across portfolio — derive top themes from signal type breakdown
  const topRiskSignals = signalTypes.filter(s => {
    const critical = s.by_urgency?.critical ?? 0;
    const high     = s.by_urgency?.high     ?? 0;
    return (critical + high) / (s.total || 1) > 0.4 && s.total >= 2;
  }).slice(0, 5);

  return (
    <div className="px-6 py-6 max-w-[1400px] mx-auto space-y-8">

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div>
        <h1 className="text-xl font-semibold text-zinc-900 tracking-tight">Intelligence</h1>
        <p className="text-sm text-zinc-400 mt-0.5">Cross-portfolio AI patterns · Updated nightly</p>
      </div>

      {/* ── Portfolio Pulse KPIs ─────────────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          label="Total Pipeline"
          value={forecast?.total_pipeline
            ? fmtMoney(forecast.total_pipeline)
            : "–"}
          sub={`${forecast?.accounts_total ?? accounts.length} accounts`}
          icon={TrendingUp}
          accent="text-emerald-500"
        />
        <KpiCard
          label="At-Risk Revenue"
          value={stalled?.total_at_risk ? fmtMoney(stalled.total_at_risk) : "–"}
          sub={`${stalled?.count ?? 0} stalled deals`}
          icon={AlertTriangle}
          accent="text-red-500"
        />
        <KpiCard
          label="Draft Acceptance"
          value={latestDar ? `${latestDar}%` : "–"}
          sub="Last 30 days · Target 60%"
          icon={Zap}
          accent={latestDar >= 60 ? "text-emerald-500" : "text-amber-500"}
        />
        <KpiCard
          label="Active Competitions"
          value={String(competitiveData?.data?.total_competitive_deals ?? "–")}
          sub={`${competitors.length} unique competitor${competitors.length !== 1 ? "s" : ""}`}
          icon={Shield}
          accent="text-zinc-500"
        />
      </div>

      {/* ── Pipeline by Close Date ──────────────────────────────────────── */}
      {accounts.length > 0 && (
        <div className="card p-6">
          <div className="mb-5">
            <h2 className="text-sm font-semibold text-zinc-900">Pipeline by Close Date</h2>
            <p className="text-xs text-zinc-400 mt-0.5">Close date distribution across {accounts.length} accounts</p>
          </div>
          <div className="space-y-3">
            {timelineBins.map(bin => {
              const total = bin.deals.reduce((s, a) => s + (a.deal_amount ?? 0), 0);
              const pct = Math.round((bin.deals.length / timelineMax) * 100);
              return (
                <div key={bin.label} className="flex items-center gap-4">
                  <div className="w-20 flex-shrink-0 text-right">
                    <p className="text-xs font-medium text-zinc-700">{bin.label}</p>
                    <p className="text-[10px] text-zinc-400">{bin.desc}</p>
                  </div>
                  <div className="flex-1 bg-zinc-100 rounded-full h-5 overflow-hidden">
                    <div
                      className={cn("h-full rounded-full transition-all", bin.color)}
                      style={{ width: `${Math.max(pct, bin.deals.length > 0 ? 4 : 0)}%` }}
                    />
                  </div>
                  <div className="w-28 flex-shrink-0">
                    <span className="text-xs font-semibold text-zinc-700 tabular-nums">
                      {bin.deals.length} deal{bin.deals.length !== 1 ? "s" : ""}
                    </span>
                    {total > 0 && (
                      <span className="text-[10px] text-zinc-400 ml-1.5">{formatCompactCurrency(total)}</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* ── Competitor Framing ───────────────────────────────────────────── */}
        <div className="card overflow-hidden">
          <div className="px-6 py-4 border-b border-zinc-100">
            <h2 className="text-sm font-semibold text-zinc-900">Competitor Framing</h2>
            <p className="text-xs text-zinc-400 mt-0.5">Competitors appearing across active deals · last 90 days</p>
          </div>
          <div className="p-6">
            {compLoading ? (
              <div className="space-y-2">
                {[1,2,3].map(i => <Skeleton key={i} className="h-12 rounded-lg" />)}
              </div>
            ) : competitors.length === 0 ? (
              <div className="text-center py-8">
                <Shield className="w-8 h-8 text-zinc-200 mx-auto mb-2" />
                <p className="text-sm text-zinc-400">No competitors detected yet.</p>
                <p className="text-xs text-zinc-300 mt-1">Run agents on your accounts to surface competitive intel.</p>
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                {competitors.map((c: CompetitorEntry) => (
                  <div
                    key={c.competitor}
                    className="flex items-center gap-2 px-3.5 py-2.5 bg-white border border-zinc-200 rounded-xl hover:border-zinc-300 transition-colors"
                  >
                    <div>
                      <p className="text-sm font-semibold text-zinc-900">{c.competitor}</p>
                      <p className="text-[11px] text-zinc-400">
                        ×{c.deal_count} deal{c.deal_count !== 1 ? "s" : ""}
                        {c.total_amount_at_risk > 0 && (
                          <span className="text-red-500 ml-1">· {fmtMoney(c.total_amount_at_risk)} at risk</span>
                        )}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ── Risk Signals (Unsaid Objections) ─────────────────────────────── */}
        <div className="card overflow-hidden">
          <div className="px-6 py-4 border-b border-zinc-100">
            <h2 className="text-sm font-semibold text-zinc-900">Risk Signals Across Portfolio</h2>
            <p className="text-xs text-zinc-400 mt-0.5">Signal types with highest critical · high concentration</p>
          </div>
          <div className="p-6">
            {sigLoading ? (
              <div className="space-y-4">
                {[1,2,3].map(i => <Skeleton key={i} className="h-10 rounded" />)}
              </div>
            ) : topRiskSignals.length === 0 ? (
              <div className="text-center py-8">
                <Zap className="w-8 h-8 text-zinc-200 mx-auto mb-2" />
                <p className="text-sm text-zinc-400">No concentrated risk signals yet.</p>
              </div>
            ) : (
              <div className="space-y-5">
                {topRiskSignals.map((s: SignalTypeData) => (
                  <SignalUrgencyBar key={s.type} data={s} />
                ))}
              </div>
            )}

            {/* Intel callout */}
            {topRiskSignals.length > 0 && (
              <div className="mt-5 intel-callout">
                <p className="text-[11px] font-semibold text-amber-800 uppercase tracking-wider mb-1">Unsaid patterns</p>
                <p className="text-xs text-amber-700 leading-relaxed">
                  {topRiskSignals[0]
                    ? `"${signalLabel(topRiskSignals[0].type)}" is your most concentrated risk. ${Math.round(((topRiskSignals[0].by_urgency?.critical ?? 0) + (topRiskSignals[0].by_urgency?.high ?? 0)) / (topRiskSignals[0].total || 1) * 100)}% of these signals are critical or high urgency.`
                    : "Review your top signal clusters for emerging patterns."}
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Signal Theme Clusters ─────────────────────────────────────────── */}
      <div className="card overflow-hidden">
        <div className="px-6 py-4 border-b border-zinc-100 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-zinc-900">All Signal Themes</h2>
            <p className="text-xs text-zinc-400 mt-0.5">Every signal type detected across your pipeline</p>
          </div>
          <span className="text-xs text-zinc-400">{signalTypes.length} types</span>
        </div>
        {sigLoading ? (
          <div className="p-6 space-y-4">
            {[1,2,3,4,5].map(i => <Skeleton key={i} className="h-10 rounded" />)}
          </div>
        ) : signalTypes.length === 0 ? (
          <div className="p-8 text-center text-sm text-zinc-400">
            No signal data yet. Run agents on your accounts to start tracking signals.
          </div>
        ) : (
          <div className="divide-y divide-zinc-50">
            {signalTypes.map((s: SignalTypeData, i: number) => {
              const critShare = ((s.by_urgency?.critical ?? 0) / (s.total || 1));
              const barColor =
                critShare >= 0.6 ? "bg-red-400" :
                critShare >= 0.3 ? "bg-orange-400" :
                critShare >= 0.1 ? "bg-amber-400" : "bg-emerald-300";
              return (
                <div key={s.type} className="flex items-center gap-4 px-6 py-3 hover:bg-zinc-50 transition-colors">
                  <span className="text-xs text-zinc-400 tabular-nums w-5 flex-shrink-0 text-right">{i + 1}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-zinc-900">{signalLabel(s.type)}</p>
                  </div>
                  <div className="flex items-center gap-3 flex-shrink-0">
                    {Object.entries(s.by_urgency ?? {}).map(([level, count]) => count > 0 ? (
                      <span key={level} className={cn(
                        "text-[10px] font-semibold px-1.5 py-0.5 rounded-full",
                        level === "critical" ? "bg-red-100 text-red-700" :
                        level === "high"     ? "bg-orange-100 text-orange-700" :
                        level === "medium"   ? "bg-amber-100 text-amber-700" :
                        "bg-emerald-100 text-emerald-700"
                      )}>
                        {count} {level}
                      </span>
                    ) : null)}
                    <div className="w-20 h-1.5 bg-zinc-100 rounded-full overflow-hidden flex-shrink-0">
                      <div className={cn("h-full rounded-full", barColor)} style={{ width: `${Math.min(100, critShare * 100 + 15)}%` }} />
                    </div>
                    <span className="text-xs font-semibold text-zinc-700 tabular-nums w-8 text-right">{s.total}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Stalled Deals ────────────────────────────────────────────────── */}
      {(stalled?.count ?? 0) > 0 && (
        <div className="card overflow-hidden">
          <div className="px-6 py-4 border-b border-zinc-100 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-zinc-900">Stalled Deals Needing Attention</h2>
              <p className="text-xs text-zinc-400 mt-0.5">Declining or stalling momentum · sorted by deal size</p>
            </div>
            <div className="text-right">
              <p className="text-xs text-zinc-400">Total at risk</p>
              <p className="text-sm font-bold text-red-600">{fmtMoney(stalled?.total_at_risk ?? 0)}</p>
            </div>
          </div>
          <div className="divide-y divide-zinc-50">
            {(stalled?.deals ?? []).map((deal: StalledDeal) => (
              <a
                key={deal.id}
                href={`/account/${deal.id}`}
                className="flex items-center gap-3 px-6 py-3.5 hover:bg-zinc-50 transition-colors group"
              >
                <span className={cn(
                  "w-1.5 h-1.5 rounded-full flex-shrink-0",
                  deal.momentum === "declining" ? "bg-red-500" : "bg-amber-400"
                )} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-zinc-900 truncate">{deal.name}</p>
                  <p className="text-xs text-zinc-400">
                    {deal.stage ?? "Unknown"} ·{" "}
                    {deal.days_stuck != null ? `${deal.days_stuck}d since buyer activity` : "buyer activity unknown"}
                  </p>
                </div>
                {deal.deal_amount && (
                  <span className="text-sm font-semibold text-zinc-700 flex-shrink-0 tabular-nums">
                    {fmtMoney(deal.deal_amount)}
                  </span>
                )}
                <span className={cn(
                  "text-xs font-medium flex-shrink-0 px-2 py-0.5 rounded-full",
                  deal.momentum === "declining"
                    ? "bg-red-50 text-red-700"
                    : "bg-amber-50 text-amber-700"
                )}>
                  {deal.momentum === "declining" ? "Declining" : "Stalling"}
                </span>
                <span className="text-xs text-zinc-500 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                  Open →
                </span>
              </a>
            ))}
          </div>
        </div>
      )}

      <div className="h-6" />
    </div>
  );
}

export default function IntelligencePage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center h-full py-24">
        <div className="w-6 h-6 border-2 border-zinc-900 border-t-transparent rounded-full animate-spin" />
      </div>
    }>
      <IntelligenceInner />
    </Suspense>
  );
}
