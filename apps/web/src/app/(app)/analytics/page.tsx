"use client";

/**
 * Analytics - DAR trend, LLM cost, signal distribution, rep performance.
 * All charts are pure SVG - zero external chart library dependency.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { analyticsApi, type DarTrendPoint, type CostTrendPoint, type DraftTypePerf, type ForecastAccuracyRow, type SignalTypeData, type TrainingFeedbackRow, type ExecutionRateWeek, type ExecutionRateData, type PipelineMovement, type PipelineMovementData, type AgentRoiData, type ReplyRateData, type DealVelocityData, type DealVelocityDeal } from "@/lib/api";
import { cn, signalLabel, draftTypeLabel } from "@/lib/utils";
import { TrendingUp, TrendingDown, Minus, DollarSign, Zap, Target, Users, BarChart3 } from "lucide-react";

// ── Sparkline / mini-chart helpers (pure SVG) ─────────────────────────────────

interface LineChartProps {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  fill?: string;
  labels?: string[];
  target?: number;
  className?: string;
}

function LineChart({ data, width = 640, height = 120, color = "#18181B", fill, target, labels, className }: LineChartProps) {
  if (!data.length) return null;

  const min = Math.min(...data, 0);
  const max = Math.max(...data, 1);
  const range = max - min || 1;
  const padX = 0;
  const padY = 8;
  const chartW = width - padX * 2;
  const chartH = height - padY * 2;

  const toX = (i: number) => padX + (i / (data.length - 1 || 1)) * chartW;
  const toY = (v: number) => padY + chartH - ((v - min) / range) * chartH;

  const pathD = data.map((v, i) => `${i === 0 ? "M" : "L"} ${toX(i)} ${toY(v)}`).join(" ");
  const fillD = `${pathD} L ${toX(data.length - 1)} ${padY + chartH} L ${toX(0)} ${padY + chartH} Z`;

  const targetY = target !== undefined ? toY(target) : null;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className={cn("w-full", className)} preserveAspectRatio="none">
      {fill && <path d={fillD} fill={fill} opacity={0.15} />}
      {targetY !== null && (
        <line x1={0} y1={targetY} x2={width} y2={targetY}
          stroke="#f59e0b" strokeWidth={1.5} strokeDasharray="4 3" opacity={0.8} />
      )}
      <path d={pathD} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      {data.map((v, i) => (
        <circle key={i} cx={toX(i)} cy={toY(v)} r={3} fill={color} />
      ))}
      {labels && labels.map((l, i) => {
        const x = toX(i);
        const every = Math.max(1, Math.floor(data.length / 7));
        if (i % every !== 0 && i !== data.length - 1) return null;
        return (
          <text key={i} x={x} y={height - 2} textAnchor="middle"
            className="text-[9px]" fill="#9ca3af" fontSize={9}>
            {l}
          </text>
        );
      })}
    </svg>
  );
}

function BarChart({ data, color = "#18181B", height = 80 }: {
  data: { label: string; value: number; value2?: number }[];
  color?: string;
  height?: number;
}) {
  const max = Math.max(...data.map(d => Math.max(d.value, d.value2 ?? 0)), 1);
  const barW = Math.max(8, Math.floor(320 / data.length) - 4);

  return (
    <div className="flex items-end gap-1" style={{ height }}>
      {data.map((d, i) => (
        <div key={i} className="flex flex-col items-center gap-0.5 flex-1 min-w-0">
          <div className="flex items-end gap-0.5 flex-1 w-full justify-center">
            <div
              className="rounded-sm transition-all"
              style={{
                height: `${(d.value / max) * (height - 16)}px`,
                backgroundColor: color,
                width: barW,
                minHeight: 2,
              }}
            />
            {d.value2 !== undefined && (
              <div
                className="rounded-sm transition-all"
                style={{
                  height: `${(d.value2 / max) * (height - 16)}px`,
                  backgroundColor: "#a1a1aa",
                  width: barW,
                  minHeight: 2,
                }}
              />
            )}
          </div>
          <span className="text-[9px] text-zinc-400 truncate w-full text-center">{d.label}</span>
        </div>
      ))}
    </div>
  );
}

// ── KPI card ──────────────────────────────────────────────────────────────────

function KpiCard({
  label, value, sub, trend, icon: Icon, highlight,
}: {
  label: string;
  value: string;
  sub?: string;
  trend?: "up" | "down" | "flat";
  icon: React.FC<{ className?: string }>;
  highlight?: "good" | "warn" | "bad";
}) {
  const TrendIcon = trend === "up" ? TrendingUp : trend === "down" ? TrendingDown : Minus;
  const trendColor = trend === "up" ? "text-emerald-500" : trend === "down" ? "text-red-500" : "text-zinc-400";

  return (
    <div
      data-testid="kpi-card"
      className={cn(
        "card p-5",
        highlight === "good" ? "border-l-[3px] border-l-emerald-400" :
        highlight === "warn" ? "border-l-[3px] border-l-amber-400" :
        highlight === "bad"  ? "border-l-[3px] border-l-red-400"   :
        ""
      )}
    >
      <div className="flex items-start justify-between mb-3">
        <div className="w-8 h-8 rounded-xl bg-zinc-50 flex items-center justify-center">
          <Icon className="w-4 h-4 text-zinc-500" />
        </div>
        {trend && <TrendIcon className={cn("w-4 h-4", trendColor)} />}
      </div>
      <div className="text-4xl font-bold text-zinc-900 tabular-nums tracking-tight leading-none mb-1.5">{value}</div>
      <div className="text-xs text-zinc-400 uppercase tracking-wider font-medium">{label}</div>
      {sub && <div className="text-xs text-zinc-400 mt-0.5">{sub}</div>}
    </div>
  );
}

// ── Animated DAR Ring ─────────────────────────────────────────────────────────

function DarRing({ pct, size = 120 }: { pct: number; size?: number }) {
  const r = (size - 16) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ * (1 - pct / 100);
  const cx = size / 2;

  const color = pct >= 60 ? "#10B981" : pct >= 45 ? "#F59E0B" : "#EF4444";

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <circle cx={cx} cy={cx} r={r} fill="none" stroke="#F4F4F5" strokeWidth={12} />
      <circle
        cx={cx} cy={cx} r={r}
        fill="none" stroke={color} strokeWidth={12}
        strokeLinecap="round"
        strokeDasharray={circ}
        strokeDashoffset={offset}
        transform={`rotate(-90 ${cx} ${cx})`}
        style={{ transition: "stroke-dashoffset 1.2s ease-out, stroke 0.3s" }}
      />
      <text x={cx} y={cx + 1} textAnchor="middle" dominantBaseline="middle"
        fontSize={size / 5} fontWeight="700" fill="#18181B" fontFamily="Inter, sans-serif">
        {pct}%
      </text>
    </svg>
  );
}

// ── DAR Trend chart panel ─────────────────────────────────────────────────────

function DarTrendPanel({ days, setDays }: { days: number; setDays: (d: number) => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ["analytics", "dar-trend", days],
    queryFn: () => analyticsApi.darTrend(days),
    staleTime: 5 * 60 * 1000,
  });

  const points: DarTrendPoint[] = data?.data ?? [];
  const darValues = points.map(p => p.dar_pct);
  const labels = points.map(p => {
    const d = new Date(p.date);
    return `${d.getMonth() + 1}/${d.getDate()}`;
  });

  const avg = darValues.length ? Math.round(darValues.reduce((a, b) => a + b, 0) / darValues.length) : 0;
  const last = darValues[darValues.length - 1] ?? 0;

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-zinc-900">Draft Acceptance Rate</h3>
          <p className="text-xs text-zinc-400 mt-0.5">Target: 60% · Amber line = target</p>
        </div>
        <div className="flex items-center gap-1.5 bg-zinc-50 rounded-lg p-1">
          {[30, 60, 90].map(d => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={cn(
                "text-xs font-medium px-3 py-1 rounded-md transition-colors",
                days === d ? "bg-white text-zinc-900 shadow-sm" : "text-zinc-500 hover:text-zinc-700"
              )}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-6 mb-4">
        <div>
          <div className="text-3xl font-bold text-zinc-900 tabular-nums tracking-tight">{last}%</div>
          <div className="text-xs text-zinc-400">Last day</div>
        </div>
        <div>
          <div className="text-3xl font-bold text-zinc-700 tabular-nums tracking-tight">{avg}%</div>
          <div className="text-xs text-zinc-400">{days}d avg</div>
        </div>
        <div className={cn(
          "text-sm font-medium px-2.5 py-1 rounded-full",
          last >= 60 ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-700"
        )}>
          {last >= 60 ? "On target" : `${60 - last}pp below target`}
        </div>
      </div>

      {isLoading ? (
        <div className="h-32 flex items-center justify-center text-sm text-zinc-400">Loading...</div>
      ) : (
        <LineChart
          data={darValues}
          labels={labels}
          target={60}
          color="#18181B"
          fill="#18181B"
          height={140}
        />
      )}

      {/* Per-day bar breakdown */}
      {points.length > 0 && (
        <div className="mt-4 pt-4 border-t border-zinc-100">
          <p className="text-xs text-zinc-400 mb-2">Generated vs Approved (per day)</p>
          <BarChart
            data={points.slice(-14).map(p => ({
              label: `${new Date(p.date).getMonth() + 1}/${new Date(p.date).getDate()}`,
              value: p.generated,
              value2: p.approved,
            }))}
            color="#18181B"
            height={72}
          />
          <div className="flex items-center gap-3 mt-2">
            <div className="flex items-center gap-1.5">
              <div className="w-2.5 h-2.5 rounded-sm bg-zinc-500" />
              <span className="text-xs text-zinc-400">Generated</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-2.5 h-2.5 rounded-sm bg-zinc-400" />
              <span className="text-xs text-zinc-400">Approved</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Cost Trend panel ──────────────────────────────────────────────────────────

function CostTrendPanel({ days }: { days: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ["analytics", "cost-trend", days],
    queryFn: () => analyticsApi.costTrend(days),
    staleTime: 5 * 60 * 1000,
  });

  const points: CostTrendPoint[] = data?.data ?? [];
  const costs = points.map(p => p.cost_usd);
  const labels = points.map(p => {
    const d = new Date(p.date);
    return `${d.getMonth() + 1}/${d.getDate()}`;
  });

  const totalCost = costs.reduce((a, b) => a + b, 0);
  const totalRuns = points.reduce((a, p) => a + p.runs, 0);
  const avgPerRun = totalRuns ? totalCost / totalRuns : 0;

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-zinc-900">LLM Cost</h3>
          <p className="text-xs text-zinc-400 mt-0.5">Daily spend · Haiku + Sonnet combined</p>
        </div>
      </div>

      <div className="flex items-center gap-6 mb-4">
        <div>
          <div className="text-3xl font-bold text-zinc-900 tabular-nums tracking-tight">${totalCost.toFixed(2)}</div>
          <div className="text-xs text-zinc-400">{days}d total</div>
        </div>
        <div>
          <div className="text-3xl font-bold text-zinc-700 tabular-nums tracking-tight">${avgPerRun.toFixed(2)}</div>
          <div className="text-xs text-zinc-400">per run</div>
        </div>
        <div>
          <div className="text-3xl font-bold text-zinc-700 tabular-nums tracking-tight">{totalRuns}</div>
          <div className="text-xs text-zinc-400">total runs</div>
        </div>
      </div>

      {isLoading ? (
        <div className="h-32 flex items-center justify-center text-sm text-zinc-400">Loading...</div>
      ) : (
        <LineChart
          data={costs}
          labels={labels}
          color="#10b981"
          fill="#10b981"
          height={120}
        />
      )}

      {/* Nightly vs manual breakdown */}
      {points.length > 0 && (
        <div className="mt-4 pt-4 border-t border-zinc-100">
          <p className="text-xs text-zinc-400 mb-2">Nightly vs Manual runs (last 14 days)</p>
          <BarChart
            data={points.slice(-14).map(p => ({
              label: `${new Date(p.date).getMonth() + 1}/${new Date(p.date).getDate()}`,
              value: p.nightly_runs,
              value2: p.manual_runs,
            }))}
            color="#10b981"
            height={60}
          />
          <div className="flex items-center gap-3 mt-2">
            <div className="flex items-center gap-1.5">
              <div className="w-2.5 h-2.5 rounded-sm bg-emerald-500" />
              <span className="text-xs text-zinc-400">Nightly</span>
            </div>
            <div className="flex items-center gap-1.5">
              <div className="w-2.5 h-2.5 rounded-sm bg-emerald-300" />
              <span className="text-xs text-zinc-400">Manual</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Signal distribution ───────────────────────────────────────────────────────

function SignalDistributionPanel() {
  const { data } = useQuery({
    queryKey: ["analytics", "signal-types"],
    queryFn: analyticsApi.signalTypes,
    staleTime: 5 * 60 * 1000,
  });

  const types: SignalTypeData[] = data?.data ?? [];
  const total = types.reduce((a, t) => a + t.total, 0);

  const URGENCY_COLORS: Record<string, string> = {
    critical: "bg-red-400",
    high:     "bg-orange-400",
    medium:   "bg-yellow-400",
    low:      "bg-green-400",
  };

  return (
    <div className="card p-5">
      <div className="mb-4">
        <h3 className="text-sm font-semibold text-zinc-900">Signal Distribution</h3>
        <p className="text-xs text-zinc-400 mt-0.5">Last 30 days · {total} total signals</p>
      </div>

      {types.length === 0 ? (
        <div className="text-center py-6 text-sm text-zinc-400">No signal data yet</div>
      ) : (
        <div className="space-y-3">
          {types.sort((a, b) => b.total - a.total).map(t => {
            const pct = total ? Math.round((t.total / total) * 100) : 0;
            return (
              <div key={t.type}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm text-zinc-700">{signalLabel(t.type)}</span>
                  <span className="text-xs text-zinc-500">{t.total} ({pct}%)</span>
                </div>
                <div className="flex h-2 rounded-full overflow-hidden gap-0.5">
                  {(["critical", "high", "medium", "low"] as const).map(u => {
                    const cnt = t.by_urgency[u] ?? 0;
                    const w = t.total ? (cnt / t.total) * 100 : 0;
                    if (w === 0) return null;
                    return (
                      <div key={u} className={cn("h-full rounded-sm", URGENCY_COLORS[u])} style={{ width: `${w}%` }} />
                    );
                  })}
                </div>
              </div>
            );
          })}

          {/* Legend */}
          <div className="flex items-center gap-3 pt-2">
            {["critical", "high", "medium", "low"].map(u => (
              <div key={u} className="flex items-center gap-1.5">
                <div className={cn("w-2 h-2 rounded-sm", URGENCY_COLORS[u])} />
                <span className="text-xs text-zinc-400 capitalize">{u}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Rep performance table ─────────────────────────────────────────────────────

function RepPerformancePanel() {
  const { data, isLoading } = useQuery({
    queryKey: ["analytics", "rep-performance"],
    queryFn: analyticsApi.repPerformance,
    staleTime: 5 * 60 * 1000,
  });

  const reps = data?.data ?? [];

  return (
    <div className="card p-5">
      <div className="mb-4">
        <h3 className="text-sm font-semibold text-zinc-900">Rep Performance</h3>
        <p className="text-xs text-zinc-400 mt-0.5">DAR ranked · managers only</p>
      </div>

      {isLoading ? (
        <div className="text-center py-6 text-sm text-zinc-400">Loading...</div>
      ) : reps.length === 0 ? (
        <div className="text-center py-6 text-sm text-zinc-400">No rep data yet</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-100">
                <th className="text-left text-xs font-medium text-zinc-400 pb-2">Rep</th>
                <th className="text-right text-xs font-medium text-zinc-400 pb-2">DAR</th>
                <th className="text-right text-xs font-medium text-zinc-400 pb-2">Approved</th>
                <th className="text-right text-xs font-medium text-zinc-400 pb-2">Declined</th>
                <th className="text-right text-xs font-medium text-zinc-400 pb-2">Pending</th>
                <th className="text-right text-xs font-medium text-zinc-400 pb-2">Accounts</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-50">
              {reps.map((r, i) => (
                <tr key={r.rep_id} className="hover:bg-zinc-50">
                  <td className="py-2.5">
                    <div className="flex items-center gap-2">
                      <div className="w-6 h-6 rounded-full bg-zinc-100 flex items-center justify-center">
                        <span className="text-xs font-bold text-zinc-500">{i + 1}</span>
                      </div>
                      <span
                        className="text-zinc-700 font-medium text-xs truncate max-w-32"
                        title={r.rep_id}
                      >
                        {r.rep_name
                          ?? (r.rep_email
                            ? r.rep_email.split("@")[0]
                            : `Rep #${String(r.rep_id).slice(-6)}`)}
                      </span>
                    </div>
                  </td>
                  <td className="py-2.5 text-right">
                    <span className={cn(
                      "font-semibold text-sm",
                      r.dar_pct >= 60 ? "text-green-600" : r.dar_pct >= 40 ? "text-amber-600" : "text-red-600"
                    )}>
                      {r.dar_pct}%
                    </span>
                  </td>
                  <td className="py-2.5 text-right text-zinc-600">{r.approved}</td>
                  <td className="py-2.5 text-right text-zinc-600">{r.declined}</td>
                  <td className="py-2.5 text-right text-zinc-500">{r.pending}</td>
                  <td className="py-2.5 text-right text-zinc-500">{r.accounts_with_drafts}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Draft Performance panel (F1-F2) ──────────────────────────────────────────

function DraftPerformancePanel() {
  const { data: perfData } = useQuery({
    queryKey: ["analytics", "draft-performance"],
    queryFn: analyticsApi.draftPerformance,
    staleTime: 5 * 60 * 1000,
  });
  const { data: feedbackData } = useQuery({
    queryKey: ["analytics", "training-feedback"],
    queryFn: analyticsApi.trainingFeedback,
    staleTime: 5 * 60 * 1000,
  });

  const perfRows: DraftTypePerf[] = perfData?.data ?? [];
  const feedbackRows: TrainingFeedbackRow[] = feedbackData?.data ?? [];
  const maxDar = Math.max(...perfRows.map(r => r.dar_pct), 1);

  return (
    <div className="card p-5">
      <h3 className="text-sm font-semibold text-zinc-900 mb-4">Draft Performance by Type</h3>
      {perfRows.length === 0 ? (
        <p className="text-sm text-zinc-400 text-center py-6">No draft history yet</p>
      ) : (
        <div className="space-y-2">
          {perfRows.map(row => (
            <div key={row.type} className="flex items-center gap-3">
              <div className="w-40 text-xs text-zinc-600 truncate flex-shrink-0" title={draftTypeLabel(row.type)}>
                {draftTypeLabel(row.type)}
              </div>
              <div className="flex-1 h-2 bg-zinc-100 rounded-full overflow-hidden">
                <div
                  className={cn("h-full rounded-full", row.dar_pct >= 60 ? "bg-green-400" : row.dar_pct >= 40 ? "bg-yellow-400" : "bg-red-400")}
                  style={{ width: `${(row.dar_pct / maxDar) * 100}%` }}
                />
              </div>
              <div className="w-12 text-right text-xs font-semibold text-zinc-700">{row.dar_pct}%</div>
              <div className="w-16 text-right text-xs text-zinc-400">{row.approved}/{row.total}</div>
            </div>
          ))}
        </div>
      )}
      {feedbackRows.length > 0 && (
        <div className="mt-5 pt-4 border-t border-zinc-100">
          <h4 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-3">Decline Reasons</h4>
          <div className="flex flex-wrap gap-2">
            {feedbackRows.map(row => (
              <div key={row.training_category} className="flex items-center gap-1.5 bg-red-50 border border-red-100 px-2.5 py-1 rounded-full">
                <span className="text-xs font-medium text-red-700">{row.training_category.replace(/_/g, " ")}</span>
                <span className="text-xs text-red-500 font-bold">{row.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Forecast Accuracy panel (F3) ──────────────────────────────────────────────

function ForecastAccuracyPanel() {
  const { data } = useQuery({
    queryKey: ["analytics", "forecast-accuracy"],
    queryFn: analyticsApi.forecastAccuracy,
    staleTime: 10 * 60 * 1000,
  });
  const rows: ForecastAccuracyRow[] = data?.data ?? [];
  const catColor: Record<string, string> = {
    Commit:      "text-green-700 bg-green-50 border-green-200",
    "Best Case": "text-blue-700 bg-blue-50 border-blue-200",
    Pipeline:    "text-zinc-600 bg-zinc-50 border-zinc-200",
    Omit:        "text-red-600 bg-red-50 border-red-200",
  };

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-zinc-900">AI Forecast Track Record</h3>
        <span className="text-xs text-zinc-400">Last 90 days</span>
      </div>
      {rows.length === 0 ? (
        <p className="text-sm text-zinc-400 text-center py-6">Accuracy data accumulates over 2+ weeks of agent runs</p>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          {rows.map(row => (
            <div key={row.category} className={cn("border rounded-xl p-3", catColor[row.category] ?? catColor.Pipeline)}>
              <div className="text-xs font-semibold mb-1">{row.category}</div>
              <div className="text-xl font-bold">{row.accuracy_pct}%</div>
              <div className="text-xs mt-1 opacity-70">{row.correct}/{row.total} correct</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Execution Rate panel (Sprint 7-10) ───────────────────────────────────────

function ExecutionRatePanel() {
  const { data } = useQuery({
    queryKey: ["analytics", "execution-rate"],
    queryFn: analyticsApi.executionRate,
    staleTime: 5 * 60 * 1000,
  });
  const rate: ExecutionRateData | undefined = data?.data;
  const weeks: ExecutionRateWeek[] = rate?.weeks ?? [];

  const maxTotal = Math.max(...weeks.map(w => w.total_generated), 1);

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-sm font-semibold text-zinc-900">Action Execution Rate</h3>
        {rate && (
          <span className={cn(
            "text-xs font-bold px-2 py-0.5 rounded-full",
            rate.overall_rate_pct >= 60 ? "bg-emerald-100 text-emerald-700" :
            rate.overall_rate_pct >= 40 ? "bg-amber-100 text-amber-700" :
            "bg-red-100 text-red-600"
          )}>
            {rate.overall_rate_pct}% overall
          </span>
        )}
      </div>
      <p className="text-xs text-zinc-400 mb-4">
        Agent-generated actions completed by reps · last 5 weeks
      </p>
      {weeks.length === 0 ? (
        <p className="text-sm text-zinc-400 text-center py-6">Execution data appears after the first week of timeline actions</p>
      ) : (
        <div className="space-y-3">
          {weeks.map(w => (
            <div key={w.week_start ?? w.week_label} className="space-y-1">
              <div className="flex items-center justify-between text-xs text-zinc-500">
                <span className="w-12 flex-shrink-0">{w.week_label}</span>
                <div className="flex-1 mx-3 relative h-5">
                  {/* total bar */}
                  <div className="absolute inset-y-0 left-0 rounded-full bg-zinc-100" style={{ width: `${(w.total_generated / maxTotal) * 100}%` }} />
                  {/* completed bar */}
                  <div
                    className={cn(
                      "absolute inset-y-0 left-0 rounded-full",
                      w.rate_pct >= 60 ? "bg-emerald-400" :
                      w.rate_pct >= 40 ? "bg-amber-400" : "bg-red-400"
                    )}
                    style={{ width: `${((w.completed / maxTotal)) * 100}%` }}
                  />
                </div>
                <span className="w-14 text-right font-medium">
                  {w.completed}/{w.total_generated} · {w.rate_pct}%
                </span>
              </div>
            </div>
          ))}
          {rate && (
            <div className="flex gap-4 pt-2 border-t border-zinc-100 text-xs text-zinc-400">
              <span>{rate.total_generated} generated</span>
              <span>{rate.total_completed} completed</span>
              <span className="ml-auto">Target: {rate.target_pct}%</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Pipeline Movement panel (Sprint 7-10) ────────────────────────────────────

function PipelineMovementPanel() {
  const { data } = useQuery({
    queryKey: ["analytics", "pipeline-movement"],
    queryFn: () => analyticsApi.pipelineMovement(30),
    staleTime: 5 * 60 * 1000,
  });
  const d: PipelineMovementData | undefined = data?.data;
  const movements: PipelineMovement[] = d?.movements ?? [];

  const fmt = (v: number) =>
    new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 0 }).format(v);

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-sm font-semibold text-zinc-900">Pipeline Movement</h3>
        <span className="text-xs text-zinc-400">Last 30 days</span>
      </div>
      {d && (
        <div className="flex gap-4 mb-4">
          <div className="text-xs">
            <span className="font-bold text-emerald-600">+{d.advanced_count}</span>
            <span className="text-zinc-400 ml-1">advanced · {fmt(d.advanced_value)}</span>
          </div>
          <div className="text-xs">
            <span className="font-bold text-red-500">-{d.regressed_count}</span>
            <span className="text-zinc-400 ml-1">regressed · {fmt(d.regressed_value)}</span>
          </div>
        </div>
      )}
      {movements.length === 0 ? (
        <p className="text-sm text-zinc-400 text-center py-6">Stage changes appear as HubSpot syncs over time</p>
      ) : (
        <div className="divide-y divide-zinc-50 max-h-64 overflow-y-auto">
          {movements.map((m, i) => (
            <div key={i} className="flex items-center gap-3 py-2">
              <span className={cn(
                "text-xs font-bold w-5 text-center flex-shrink-0",
                m.direction === "advanced" ? "text-emerald-500" :
                m.direction === "regressed" ? "text-red-500" : "text-zinc-400"
              )}>
                {m.direction === "advanced" ? "↑" : m.direction === "regressed" ? "↓" : "→"}
              </span>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-zinc-800 truncate">{m.account_name}</p>
                <p className="text-[10px] text-zinc-400 truncate">{m.from_stage} → {m.to_stage}</p>
              </div>
              {m.deal_amount ? (
                <span className="text-xs text-zinc-500 flex-shrink-0">{fmt(m.deal_amount)}</span>
              ) : null}
              {m.changed_at && (
                <span className="text-[10px] text-zinc-400 flex-shrink-0">
                  {new Date(m.changed_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Agent ROI panel (Sprint 7-10) ────────────────────────────────────────────

function AgentRoiPanel() {
  const { data } = useQuery({
    queryKey: ["analytics", "agent-roi"],
    queryFn: analyticsApi.agentRoi,
    staleTime: 10 * 60 * 1000,
  });
  const roi: AgentRoiData | undefined = data?.data;

  const fmt = (v: number | null) =>
    v == null ? "-" :
    new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(v);

  const tiles = roi ? [
    { label: "LLM cost (30d)",        value: `$${roi.cost_30d_usd.toFixed(2)}`,         color: "text-zinc-800" },
    { label: "Agent runs (30d)",       value: roi.run_count_30d.toString(),              color: "text-zinc-800" },
    { label: "Deals advanced (30d)",   value: roi.deals_advanced_30d.toString(),         color: "text-emerald-700" },
    { label: "Cost / deal advanced",   value: fmt(roi.cost_per_deal_advanced_usd),       color: "text-zinc-700" },
    { label: "Deals won (90d)",        value: roi.deals_won_90d.toString(),              color: "text-emerald-700" },
    { label: "Cost / deal closed",     value: fmt(roi.cost_per_deal_won_usd),            color: "text-zinc-700" },
  ] : [];

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-zinc-900">Agent ROI</h3>
        <span className="text-xs text-zinc-400">Cost efficiency</span>
      </div>
      {!roi ? (
        <p className="text-sm text-zinc-400 text-center py-6">ROI data accumulates after 30+ days of active use</p>
      ) : (
        <div className="grid grid-cols-3 gap-3">
          {tiles.map(t => (
            <div key={t.label} className="bg-zinc-50 rounded-xl p-3">
              <p className="text-[10px] text-zinc-400 mb-1 leading-tight">{t.label}</p>
              <p className={cn("text-lg font-bold tabular", t.color)}>{t.value}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Reply Rate panel (#13) ────────────────────────────────────────────────────

function ReplyRatePanel() {
  const { data } = useQuery({
    queryKey: ["analytics", "reply-rate"],
    queryFn: () => analyticsApi.replyRate(30),
    staleTime: 10 * 60 * 1000,
  });
  const d: ReplyRateData | undefined = data?.data;

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-sm font-semibold text-zinc-900">Reply Rate</h3>
        {d && (
          <span className={cn(
            "text-xs font-bold px-2 py-0.5 rounded-full",
            d.reply_rate_pct >= d.target_pct ? "bg-emerald-100 text-emerald-700" :
            d.reply_rate_pct >= d.target_pct * 0.66 ? "bg-amber-100 text-amber-700" :
            "bg-red-100 text-red-600"
          )}>
            {d.reply_rate_pct}%
          </span>
        )}
      </div>
      <p className="text-xs text-zinc-400 mb-4">Approved emails that got a reply · target {d?.target_pct ?? 30}%</p>
      {!d || d.emails_sent === 0 ? (
        <p className="text-sm text-zinc-400 text-center py-6">Reply data appears after Vantage-drafted emails are sent and HubSpot records replies</p>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-3">
            {[
              { label: "Emails sent", value: d.emails_sent },
              { label: "Accounts replied", value: d.accounts_replied },
              { label: "Contacted", value: d.accounts_contacted },
            ].map(t => (
              <div key={t.label} className="bg-zinc-50 rounded-xl p-3">
                <p className="text-[10px] text-zinc-400 mb-1">{t.label}</p>
                <p className="text-lg font-bold text-zinc-800 tabular">{t.value}</p>
              </div>
            ))}
          </div>
          <div className="h-2 bg-zinc-100 rounded-full overflow-hidden">
            <div
              className={cn("h-full rounded-full transition-all",
                d.reply_rate_pct >= d.target_pct ? "bg-emerald-400" :
                d.reply_rate_pct >= d.target_pct * 0.66 ? "bg-amber-400" : "bg-red-400"
              )}
              style={{ width: `${Math.min(d.reply_rate_pct, 100)}%` }}
            />
          </div>
          <div className="flex justify-between text-[10px] text-zinc-400">
            <span>0%</span>
            <span className="text-zinc-600 font-medium">Target {d.target_pct}%</span>
            <span>100%</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Deal Velocity panel (#14) ─────────────────────────────────────────────────

function DealVelocityPanel() {
  const { data } = useQuery({
    queryKey: ["analytics", "deal-velocity"],
    queryFn: analyticsApi.dealVelocity,
    staleTime: 10 * 60 * 1000,
  });
  const d: DealVelocityData | undefined = data?.data;
  const stalled = (d?.deals ?? []).filter(deal => deal.stalled).slice(0, 8);
  const ok = (d?.deals ?? []).filter(deal => !deal.stalled).slice(0, 5);

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-sm font-semibold text-zinc-900">Deal Velocity</h3>
        {d && d.stalled_count > 0 && (
          <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-red-100 text-red-700">
            {d.stalled_count} stalled
          </span>
        )}
      </div>
      <p className="text-xs text-zinc-400 mb-4">Days in current stage vs. historical average</p>
      {!d || d.deals.length === 0 ? (
        <p className="text-sm text-zinc-400 text-center py-6">Velocity data builds up as deals move through stages</p>
      ) : (
        <div className="space-y-2 max-h-72 overflow-y-auto">
          {stalled.length > 0 && (
            <>
              <p className="text-[10px] font-semibold text-red-500 uppercase tracking-wider">Stalled</p>
              {stalled.map(deal => <VelocityRow key={deal.account_id} deal={deal} />)}
            </>
          )}
          {ok.length > 0 && (
            <>
              <p className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider mt-3">On track</p>
              {ok.map(deal => <VelocityRow key={deal.account_id} deal={deal} />)}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function VelocityRow({ deal }: { deal: DealVelocityDeal }) {
  const hasAvg = deal.avg_days_for_stage > 0;
  return (
    <div className="flex items-center gap-3 py-2 border-b border-zinc-50 last:border-0">
      <div className="flex-1 min-w-0">
        <a href={`/account/${deal.account_id}`} className="text-xs font-medium text-zinc-800 hover:text-zinc-700 truncate block transition-colors">
          {deal.name}
        </a>
        <p className="text-[10px] text-zinc-400 truncate">{deal.stage}</p>
      </div>
      <div className="text-right flex-shrink-0">
        <p className={cn("text-xs font-bold tabular", deal.stalled ? "text-red-600" : "text-zinc-700")}>
          {deal.days_in_stage}d
        </p>
        {hasAvg && (
          <p className="text-[10px] text-zinc-400">avg {deal.avg_days_for_stage}d</p>
        )}
      </div>
      {deal.stalled && deal.days_over_avg != null && (
        <span className="text-[10px] font-medium text-red-600 bg-red-50 px-1.5 py-0.5 rounded-full flex-shrink-0">
          +{deal.days_over_avg}d
        </span>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const [days, setDays] = useState(30);

  const { data: overviewData, isLoading: overviewLoading } = useQuery({
    queryKey: ["analytics", "overview"],
    queryFn: analyticsApi.overview,
    staleTime: 2 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
  });

  const overview = overviewData?.data;

  const darTrend = overview?.drafts.dar_vs_target !== undefined
    ? overview.drafts.dar_vs_target > 0 ? "up" : overview.drafts.dar_vs_target < 0 ? "down" : "flat"
    : undefined;

  const darPct   = overview?.drafts.dar_pct ?? 0;
  const darColor = darPct >= 60 ? "text-emerald-600" : darPct >= 45 ? "text-amber-600" : "text-red-600";

  return (
    <div className="page-scroll p-6 space-y-4">

      {/* ── Bento grid - top row ──────────────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-4">

        {/* Hero: DAR ring */}
        <div className="intel-card p-6 flex items-center gap-6 col-span-1">
          <DarRing pct={darPct} size={100} />
          <div>
            <p className="section-header mb-1">Draft Acceptance · all time</p>
            <p className={cn("text-3xl font-bold tabular", darColor)}>{darPct}%</p>
            {overview && (
              <p className="text-xs text-zinc-500 mt-1">
                Target 60% · {overview.drafts.dar_vs_target >= 0 ? "+" : ""}{overview.drafts.dar_vs_target}pp
              </p>
            )}
            <p className={cn("text-xs font-medium mt-1.5", darTrend === "up" ? "text-emerald-600" : darTrend === "down" ? "text-red-500" : "text-zinc-400")}>
              {darTrend === "up" ? "↑ Improving" : darTrend === "down" ? "↓ Declining" : "→ Stable"}
            </p>
          </div>
        </div>

        {/* Secondary KPIs - 2 cards stacked */}
        <div className="col-span-2 grid grid-cols-3 gap-4">
          <KpiCard
            label="Account Coverage"
            value={overviewLoading ? "-" : `${Math.round((overview?.accounts.coverage_pct ?? 0) * 100)}%`}
            sub={overview ? `${overview.accounts.covered} of ${overview.accounts.total} accounts` : undefined}
            icon={Users}
            highlight={
              !overview ? undefined :
              (overview.accounts.coverage_pct ?? 0) >= 0.8 ? "good" :
              (overview.accounts.coverage_pct ?? 0) >= 0.5 ? "warn" : "bad"
            }
          />
          <KpiCard
            label="LLM Spend (30d)"
            value={overviewLoading ? "-" : `$${(overview?.cost_30d_usd ?? 0).toFixed(2)}`}
            sub={overview ? `${overview.drafts.total} drafts generated` : undefined}
            icon={DollarSign}
          />
          <KpiCard
            label="Pipeline Covered"
            value={overviewLoading ? "-" : (
              overview?.accounts.total_pipeline
                ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 }).format(overview.accounts.total_pipeline)
                : "$0"
            )}
            sub={overview ? `Avg urgency ${Math.round((overview.accounts.avg_urgency ?? 0) * 100)}%` : undefined}
            icon={Zap}
          />
        </div>
      </div>

      {/* DAR trend + Cost trend */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <DarTrendPanel days={days} setDays={setDays} />
        <CostTrendPanel days={days} />
      </div>

      {/* Signal distribution + Rep performance */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SignalDistributionPanel />
        <RepPerformancePanel />
      </div>

      {/* Draft performance + forecast accuracy */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <DraftPerformancePanel />
        <ForecastAccuracyPanel />
      </div>

      {/* Execution rate + Pipeline movement */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ExecutionRatePanel />
        <PipelineMovementPanel />
      </div>

      {/* Reply rate + Deal velocity */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ReplyRatePanel />
        <DealVelocityPanel />
      </div>

      {/* Agent ROI */}
      <AgentRoiPanel />

      {/* Pending drafts notice */}
      {overview && overview.drafts.pending > 0 && (
        <div className="card border-l-[3px] border-l-zinc-600 p-4 flex items-center gap-3">
          <BarChart3 className="w-5 h-5 text-zinc-500 flex-shrink-0" />
          <div>
            <p className="text-sm font-medium text-zinc-800">
              {overview.drafts.pending} draft{overview.drafts.pending > 1 ? "s" : ""} awaiting review
            </p>
            <p className="text-xs text-zinc-500 mt-0.5">
              Reviewing pending drafts improves DAR and trains the agent for future runs.
            </p>
          </div>
          <a href="/inbox" className="ml-auto text-sm font-medium text-zinc-700 hover:text-zinc-800 flex-shrink-0">
            Review now →
          </a>
        </div>
      )}
    </div>
  );
}
