"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { forecastApi, type ForecastAccount, type AiVsCrmDelta, type WeekDelta } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ChevronDown, ChevronRight, TrendingUp, AlertTriangle, Check, RefreshCw, ArrowRight } from "lucide-react";

// ── Constants ─────────────────────────────────────────────────────────────────

const CATEGORIES = ["Commit", "Best Case", "Pipeline", "Omit"] as const;
type Category = typeof CATEGORIES[number];

const CAT_STYLES: Record<Category, { bg: string; text: string; border: string; ring: string; dot: string }> = {
  Commit:     { bg: "bg-emerald-50",  text: "text-emerald-700",  border: "border-emerald-200", ring: "ring-emerald-500", dot: "bg-emerald-500" },
  "Best Case":{ bg: "bg-blue-50",     text: "text-blue-700",     border: "border-blue-200",    ring: "ring-blue-400",   dot: "bg-blue-500" },
  Pipeline:   { bg: "bg-zinc-50",     text: "text-zinc-600",     border: "border-zinc-200",    ring: "ring-zinc-400",   dot: "bg-zinc-400" },
  Omit:       { bg: "bg-red-50",      text: "text-red-600",      border: "border-red-200",     ring: "ring-red-400",    dot: "bg-red-400" },
};

const fmt = (v: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 }).format(v);

const fmtFull = (v: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(v);

// ── Override modal ────────────────────────────────────────────────────────────

function OverrideModal({
  account,
  current,
  onClose,
}: {
  account: ForecastAccount & { _category: string };
  current: Category;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<Category>(current);
  const [reason, setReason] = useState("");

  const mutation = useMutation({
    mutationFn: () => forecastApi.override(account.id, selected, reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["forecast", "rollup"] });
      onClose();
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
        <h3 className="text-sm font-semibold text-zinc-900 mb-1">Override Forecast Category</h3>
        <p className="text-xs text-zinc-400 mb-4">{account.name}</p>

        <div className="grid grid-cols-2 gap-2 mb-4">
          {CATEGORIES.map(cat => {
            const s = CAT_STYLES[cat];
            return (
              <button
                key={cat}
                onClick={() => setSelected(cat)}
                className={cn(
                  "px-3 py-2 rounded-xl text-xs font-medium border-2 transition-all",
                  selected === cat
                    ? `${s.bg} ${s.text} border-current ring-2 ${s.ring}`
                    : "bg-white text-zinc-500 border-zinc-200 hover:border-zinc-300"
                )}
              >
                <span className={cn("inline-block w-1.5 h-1.5 rounded-full mr-1.5 -mt-0.5", s.dot)} />
                {cat}
              </button>
            );
          })}
        </div>

        <div className="mb-4">
          <label className="text-xs font-medium text-zinc-700 block mb-1">Reason (optional)</label>
          <textarea
            value={reason}
            onChange={e => setReason(e.target.value)}
            placeholder="e.g. Verbal commit from champion, contract in legal review"
            rows={3}
            className="w-full text-xs border border-zinc-200 rounded-xl px-3 py-2 resize-none focus:outline-none focus:border-indigo-300"
          />
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
            className="flex-1 py-2 bg-indigo-600 text-white text-xs font-medium rounded-xl hover:bg-indigo-700 disabled:opacity-40 transition-colors"
          >
            {mutation.isPending ? "Saving..." : "Save Override"}
          </button>
          <button onClick={onClose} className="px-4 py-2 text-xs text-zinc-400 hover:text-zinc-600">
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Category section ──────────────────────────────────────────────────────────

function CategorySection({
  category,
  data,
  onOverride,
}: {
  category: string;
  data: { count: number; total_amount: number; accounts: ForecastAccount[] };
  onOverride: (acc: ForecastAccount & { _category: string }) => void;
}) {
  const [open, setOpen] = useState(category === "Commit" || category === "Best Case");
  const s = CAT_STYLES[category as Category] ?? CAT_STYLES.Pipeline;

  return (
    <div className={cn("rounded-2xl border overflow-hidden", s.border)}>
      {/* Header */}
      <button
        onClick={() => setOpen(o => !o)}
        className={cn("w-full flex items-center gap-3 px-5 py-4", s.bg)}
      >
        <span className={cn("w-2.5 h-2.5 rounded-full flex-shrink-0", s.dot)} />
        <span className={cn("text-sm font-semibold flex-1 text-left", s.text)}>{category}</span>
        <span className={cn("text-xs font-medium mr-3", s.text)}>{data.count} deals</span>
        <span className={cn("text-base font-bold tabular", s.text)}>{fmt(data.total_amount)}</span>
        {open
          ? <ChevronDown className={cn("w-4 h-4 flex-shrink-0", s.text)} />
          : <ChevronRight className={cn("w-4 h-4 flex-shrink-0", s.text)} />}
      </button>

      {/* Deal rows */}
      {open && data.accounts.length > 0 && (
        <div className="divide-y divide-zinc-100">
          {data.accounts
            .sort((a, b) => b.amount - a.amount)
            .map(acc => (
              <div key={acc.id} className="flex items-center gap-4 px-5 py-3 bg-white hover:bg-zinc-50 transition-colors">
                <div className="flex-1 min-w-0">
                  <a href={`/account/${acc.id}`} className="text-xs font-medium text-zinc-800 hover:text-indigo-600 truncate block transition-colors">
                    {acc.name}
                  </a>
                  <div className="flex items-center gap-2 mt-0.5">
                    <div className="flex-1 max-w-[80px] h-1 bg-zinc-100 rounded-full overflow-hidden">
                      <div
                        className={cn("h-full rounded-full", s.dot)}
                        style={{ width: `${Math.round(acc.confidence * 100)}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-zinc-400">{Math.round(acc.confidence * 100)}% conf</span>
                    {acc.overridden && (
                      <span className="text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded-full font-medium">overridden</span>
                    )}
                  </div>
                </div>
                <span className="text-xs font-semibold text-zinc-700 tabular w-20 text-right flex-shrink-0">
                  {fmtFull(acc.amount)}
                </span>
                <button
                  onClick={() => onOverride({ ...acc, _category: category })}
                  className="text-[10px] text-zinc-300 hover:text-indigo-600 transition-colors flex-shrink-0 border border-zinc-200 hover:border-indigo-300 rounded-lg px-2 py-1"
                >
                  Override
                </button>
              </div>
            ))}
        </div>
      )}
      {open && data.accounts.length === 0 && (
        <p className="text-xs text-zinc-400 text-center py-4 bg-white">No deals in this category</p>
      )}
    </div>
  );
}

// ── AI vs CRM Deltas table ────────────────────────────────────────────────────

function DeltaTable({ rows }: { rows: AiVsCrmDelta[] }) {
  const [show, setShow] = useState(false);
  if (rows.length === 0) return null;

  return (
    <div className="bg-white rounded-2xl border border-zinc-200 overflow-hidden">
      <button
        onClick={() => setShow(s => !s)}
        className="w-full flex items-center gap-3 px-5 py-4 hover:bg-zinc-50 transition-colors"
      >
        <AlertTriangle className="w-4 h-4 text-amber-500 flex-shrink-0" />
        <span className="text-sm font-semibold text-zinc-800 flex-1 text-left">
          AI vs CRM Disagreements
        </span>
        <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-medium mr-2">
          {rows.length}
        </span>
        {show ? <ChevronDown className="w-4 h-4 text-zinc-400" /> : <ChevronRight className="w-4 h-4 text-zinc-400" />}
      </button>

      {show && (
        <div className="border-t border-zinc-100 divide-y divide-zinc-50 max-h-80 overflow-y-auto">
          <div className="grid grid-cols-[1fr_100px_100px_100px_auto] gap-3 px-5 py-2 bg-zinc-50 text-[10px] font-semibold text-zinc-400 uppercase tracking-wide">
            <span>Deal</span>
            <span>Amount</span>
            <span>AI says</span>
            <span>CRM says</span>
            <span></span>
          </div>
          {rows.map(row => {
            const aiS = CAT_STYLES[row.ai_category as Category] ?? CAT_STYLES.Pipeline;
            const crmS = CAT_STYLES[row.crm_category as Category] ?? CAT_STYLES.Pipeline;
            return (
              <div key={row.account_id} className="grid grid-cols-[1fr_100px_100px_100px_auto] gap-3 px-5 py-2.5 items-center">
                <a href={`/account/${row.account_id}`} className="text-xs font-medium text-zinc-800 hover:text-indigo-600 truncate transition-colors">
                  {row.name}
                </a>
                <span className="text-xs text-zinc-500 tabular">{fmt(row.amount)}</span>
                <span className={cn("text-[10px] px-2 py-0.5 rounded-full font-medium w-fit", aiS.bg, aiS.text)}>
                  {row.ai_category}
                </span>
                <span className={cn("text-[10px] px-2 py-0.5 rounded-full font-medium w-fit", crmS.bg, crmS.text)}>
                  {row.crm_category}
                </span>
                {row.overridden && (
                  <span title="Rep has overridden"><Check className="w-3 h-3 text-emerald-500 flex-shrink-0" /></span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Week-over-week movement ───────────────────────────────────────────────────

function WeekMovement({ rows }: { rows: WeekDelta[] }) {
  if (rows.length === 0) return null;
  const order = ["Omit", "Pipeline", "Best Case", "Commit"];
  return (
    <div className="bg-white rounded-2xl border border-zinc-200 overflow-hidden">
      <div className="flex items-center gap-3 px-5 py-4 border-b border-zinc-100">
        <TrendingUp className="w-4 h-4 text-indigo-500 flex-shrink-0" />
        <span className="text-sm font-semibold text-zinc-800 flex-1">Moved this week</span>
        <span className="text-xs bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded-full font-medium">{rows.length}</span>
      </div>
      <div className="divide-y divide-zinc-50 max-h-80 overflow-y-auto">
        {rows.map(row => {
          const upgraded = order.indexOf(row.to_category) > order.indexOf(row.from_category);
          const fromS = CAT_STYLES[row.from_category as Category] ?? CAT_STYLES.Pipeline;
          const toS = CAT_STYLES[row.to_category as Category] ?? CAT_STYLES.Pipeline;
          return (
            <div key={row.account_id} className="px-5 py-3">
              <div className="flex items-center gap-3">
                <a href={`/account/${row.account_id}`} className="text-xs font-medium text-zinc-800 hover:text-indigo-600 truncate transition-colors flex-1 min-w-0">
                  {row.name}
                </a>
                <span className="text-xs text-zinc-500 tabular flex-shrink-0">{fmt(row.amount)}</span>
                <span className={cn("text-[10px] px-2 py-0.5 rounded-full font-medium flex-shrink-0", fromS.bg, fromS.text)}>
                  {row.from_category}
                </span>
                <ArrowRight className={cn("w-3 h-3 flex-shrink-0", upgraded ? "text-emerald-500" : "text-red-400")} />
                <span className={cn("text-[10px] px-2 py-0.5 rounded-full font-medium flex-shrink-0", toS.bg, toS.text)}>
                  {row.to_category}
                </span>
              </div>
              {row.reason && (
                <p className="text-[11px] text-zinc-400 mt-1 line-clamp-2">{row.reason}</p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ForecastPage() {
  const [overrideTarget, setOverrideTarget] = useState<(ForecastAccount & { _category: string }) | null>(null);
  const [repFilter, setRepFilter] = useState<string | null>(null);

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["forecast", "rollup", repFilter],
    queryFn: () => forecastApi.rollup(repFilter ?? undefined),
    staleTime: 2 * 60 * 1000,
  });
  const rollup = data?.data;

  const coveragePct = rollup
    ? Math.round((rollup.accounts_analyzed / Math.max(rollup.accounts_total, 1)) * 100)
    : 0;

  return (
    <div className="p-6 space-y-4 max-w-5xl mx-auto">

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-900 flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-indigo-500" />
            AI Forecast
          </h1>
          <p className="text-xs text-zinc-400 mt-0.5">
            Agent-generated pipeline categories · {coveragePct}% of deals analysed
          </p>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-1.5 text-xs text-zinc-400 hover:text-zinc-700 transition-colors"
        >
          <RefreshCw className={cn("w-3.5 h-3.5", isFetching && "animate-spin")} />
          Refresh
        </button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-64 text-zinc-400 text-sm">Loading forecast...</div>
      ) : rollup ? (
        <>
          {/* ── Rep filter ───────────────────────────────────────────────── */}
          {(rollup.reps ?? []).length > 1 && (
            <div className="flex items-center gap-1.5 flex-wrap">
              <button
                onClick={() => setRepFilter(null)}
                className={cn(
                  "text-xs font-medium px-3 py-1.5 rounded-full border transition-colors",
                  !repFilter ? "bg-indigo-600 text-white border-indigo-600" : "text-zinc-500 border-zinc-200 hover:border-zinc-300"
                )}
              >
                Whole team
              </button>
              {(rollup.reps ?? []).map(r => (
                <button
                  key={r.id}
                  onClick={() => setRepFilter(repFilter === r.id ? null : r.id)}
                  className={cn(
                    "text-xs font-medium px-3 py-1.5 rounded-full border transition-colors",
                    repFilter === r.id ? "bg-indigo-600 text-white border-indigo-600" : "text-zinc-500 border-zinc-200 hover:border-zinc-300"
                  )}
                >
                  {r.name} · {fmt(r.total_amount)}
                </button>
              ))}
            </div>
          )}

          {/* ── Summary bar ──────────────────────────────────────────────── */}
          <div className="grid grid-cols-4 gap-3">
            {CATEGORIES.map(cat => {
              const d = rollup.categories[cat] ?? { count: 0, total_amount: 0, accounts: [] };
              const s = CAT_STYLES[cat];
              const pct = rollup.total_pipeline > 0
                ? Math.round((d.total_amount / rollup.total_pipeline) * 100)
                : 0;
              return (
                <div key={cat} className={cn("rounded-2xl border p-4", s.bg, s.border)}>
                  <div className="flex items-center gap-1.5 mb-2">
                    <span className={cn("w-2 h-2 rounded-full", s.dot)} />
                    <span className={cn("text-xs font-semibold", s.text)}>{cat}</span>
                  </div>
                  <p className={cn("text-xl font-bold tabular", s.text)}>{fmt(d.total_amount)}</p>
                  <p className="text-[10px] text-zinc-400 mt-0.5">{d.count} {d.count === 1 ? "deal" : "deals"} · {pct}% of pipe</p>
                </div>
              );
            })}
          </div>

          {/* Coverage + override stats */}
          <div className="flex items-center gap-6 text-xs text-zinc-400 px-1">
            <span>Total pipeline: <span className="font-semibold text-zinc-700">{fmt(rollup.total_pipeline)}</span></span>
            <span>{rollup.accounts_analyzed} of {rollup.accounts_total} deals analysed by agent</span>
            {rollup.overridden_count > 0 && (
              <span className="text-amber-600">{rollup.overridden_count} rep override{rollup.overridden_count !== 1 ? "s" : ""}</span>
            )}
          </div>

          {/* ── Category sections ────────────────────────────────────────── */}
          <div className="space-y-3">
            {CATEGORIES.map(cat => {
              const d = rollup.categories[cat];
              if (!d) return null;
              return (
                <CategorySection
                  key={cat}
                  category={cat}
                  data={d}
                  onOverride={setOverrideTarget}
                />
              );
            })}
          </div>

          {/* ── Week-over-week movement ──────────────────────────────────── */}
          <WeekMovement rows={rollup.week_deltas ?? []} />

          {/* ── AI vs CRM deltas ─────────────────────────────────────────── */}
          <DeltaTable rows={rollup.ai_vs_crm_deltas} />
        </>
      ) : (
        <div className="flex flex-col items-center justify-center h-64 text-center">
          <TrendingUp className="w-10 h-10 text-zinc-200 mb-3" />
          <p className="text-sm font-medium text-zinc-500">No forecast data yet</p>
          <p className="text-xs text-zinc-400 mt-1">Run agents on at least one account to generate AI forecast categories.</p>
        </div>
      )}

      {/* ── Override modal ────────────────────────────────────────────────── */}
      {overrideTarget && (
        <OverrideModal
          account={overrideTarget}
          current={(overrideTarget._category as Category) ?? "Pipeline"}
          onClose={() => setOverrideTarget(null)}
        />
      )}
    </div>
  );
}
