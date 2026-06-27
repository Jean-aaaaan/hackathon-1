"use client";

import React, { Suspense, useState, useMemo } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  accountsApi, draftsApi, signalsApi,
  type AccountListItem, type Draft, type Signal, type Transcript,
} from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Search, ArrowUpRight, Mail, MessageSquare, Calendar, Clock,
  ChevronDown, ChevronUp, AlertTriangle, CheckCircle, XCircle,
  TrendingDown, TrendingUp, Minus, Users, Activity, BarChart2,
  FileText, Zap, ExternalLink, Download,
} from "lucide-react";
import { cn, signalLabel, urgencyLevel, draftTypeLabel, formatCompactCurrency, cleanDealName } from "@/lib/utils";
import { stripMarkdown } from "@/components/markdown-content";
import { formatDistanceToNow } from "date-fns";
import { toast } from "sonner";
import { DealFilterBar } from "@/components/deal-filter-bar";
import { type DealFilterState, filterAndSortDeals, loadFilters, saveFilters, hasActiveFilters } from "@/lib/deal-filters";

// ── Helpers ───────────────────────────────────────────────────────────────────

const FORECAST_STYLES: Record<string, string> = {
  "Commit":     "forecast-commit",
  "Best Case":  "forecast-bestcase",
  "Pipeline":   "forecast-pipeline",
  "Omit":       "forecast-omit",
};

const MEDDPICC_LABELS: Record<string, string> = {
  metrics:          "M — Metrics",
  economic_buyer:   "E — Economic Buyer",
  decision_criteria:"D — Decision Criteria",
  decision_process: "D — Decision Process",
  implicate_pain:   "I — Implicate Pain",
  champion:         "C — Champion",
  competition:      "C — Competition",
  paper_process:    "P — Paper Process",
};

function fmtPct(v: number | null | undefined) {
  if (v == null) return "–";
  return `${Math.round(v * 100)}%`;
}

function fmtAmount(v: number | null | undefined) {
  if (!v) return "–";
  return formatCompactCurrency(v);
}

function fmtDate(s: string | number | null | undefined) {
  if (!s) return "–";
  // Fireflies dates are epoch milliseconds; everything else is ISO strings
  return new Date(s).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "2-digit" });
}

function fmtRelative(s: string | null | undefined) {
  if (!s) return null;
  const ms = Date.now() - new Date(s).getTime();
  const days = Math.floor(ms / 86400000);
  if (days === 0) return "today";
  if (days === 1) return "1 day ago";
  return `${days}d ago`;
}

function healthColor(score: number | null | undefined) {
  if (score == null) return "bg-zinc-300";
  if (score >= 0.7) return "bg-zinc-800";
  if (score >= 0.4) return "bg-zinc-500";
  return "bg-zinc-300";
}

function meddpiccColor(score: number) {
  if (score >= 0.6) return "bg-zinc-800";
  if (score >= 0.3) return "bg-zinc-500";
  return "bg-zinc-300";
}

function momentumIcon(momentum: string | undefined) {
  if (momentum === "improving") return <TrendingUp className="w-3.5 h-3.5 text-emerald-500" />;
  if (momentum === "declining") return <TrendingDown className="w-3.5 h-3.5 text-red-500" />;
  return <Minus className="w-3.5 h-3.5 text-zinc-400" />;
}

// Extract stakeholders mentioned in signal details
// Sentence-leading words the name regex can swallow ("Only Derick Sim (…)").
const NAME_ARTIFACT_PREFIX = /^(Only|The|Both|Either|All|New|Unknown|Possibly|Likely|Maybe)\s+/;

function extractStakeholders(signals: Signal[], narrative: string): { name: string; role: string; status: string }[] {
  const map = new Map<string, { name: string; role: string; status: string }>();
  const regex = /([A-Z][a-z]+(?: [A-Z][a-z]+)+)\s*\(([^)]{5,60})\)/g;
  const sources = [narrative, ...signals.map(s => s.detail)];
  for (const text of sources) {
    let m: RegExpExecArray | null;
    regex.lastIndex = 0;
    while ((m = regex.exec(text)) !== null) {
      const name = m[1].replace(NAME_ARTIFACT_PREFIX, "");
      const role = m[2];
      if (name.split(" ").length < 2) continue;
      const key = name.toLowerCase();
      if (map.has(key)) continue;
      const isDark = text.toLowerCase().includes("dark") || text.toLowerCase().includes("non-responsive") || text.toLowerCase().includes("departed");
      map.set(key, { name, role, status: isDark ? "dark" : "active" });
    }
  }
  return Array.from(map.values()).slice(0, 8);
}

// ── Left panel: deal row ───────────────────────────────────────────────────────

function DealRow({ account, isSelected, onClick }: {
  account: AccountListItem;
  isSelected: boolean;
  onClick: () => void;
}) {
  const pov = account.pov_forecast_cat;
  const swept = account.last_agent_run_at
    ? formatDistanceToNow(new Date(account.last_agent_run_at), { addSuffix: true }).replace(/^about /, "")
    : null;
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full text-left px-3 py-2.5 border-b border-zinc-100 transition-colors flex items-center gap-3",
        isSelected ? "bg-zinc-50 border-l-2 border-l-zinc-800" : "hover:bg-zinc-50 border-l-2 border-l-transparent"
      )}
    >
      <span className={cn("w-2 h-2 rounded-full flex-shrink-0", healthColor(account.health_score))} />
      <div className="flex-1 min-w-0">
        <p className="text-[13px] font-medium text-zinc-900 truncate" title={account.name}>{cleanDealName(account.name)}</p>
        <div className="flex items-center gap-1.5 mt-0.5">
          <span className="text-[10px] text-zinc-400">{account.stage ?? "–"}</span>
          {account.deal_amount ? (
            <span className="text-[10px] text-zinc-400">· {fmtAmount(account.deal_amount)}</span>
          ) : null}
          <span className="text-[10px] text-zinc-400 truncate">
            · {swept ? `swept ${swept}` : "not swept yet"}
          </span>
        </div>
      </div>
      {account.urgency_score != null && (
        <span className={cn(
          "text-[10px] font-semibold px-1.5 py-0.5 rounded flex-shrink-0",
          urgencyLevel(account.urgency_score) === "critical" ? "text-red-600 bg-red-50" :
          urgencyLevel(account.urgency_score) === "high"     ? "text-amber-600 bg-amber-50" :
          urgencyLevel(account.urgency_score) === "medium"   ? "text-zinc-500 bg-zinc-100" :
          "text-zinc-400 bg-zinc-50"
        )}>
          {Math.round(account.urgency_score * 100)}%
        </span>
      )}
      {pov && (
        <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full border font-medium flex-shrink-0", FORECAST_STYLES[pov] ?? FORECAST_STYLES["Pipeline"])}>
          {pov}
        </span>
      )}
    </button>
  );
}

// ── MEDDPICC bar ──────────────────────────────────────────────────────────────

function MEDDPICCBar({ label, score, gap }: { label: string; score: number; gap?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mb-2">
      <div className="flex items-center gap-2 cursor-pointer group" onClick={() => gap && setOpen(o => !o)}>
        <span className="text-[11px] font-medium text-zinc-600 w-40 flex-shrink-0">{label}</span>
        <div className="flex-1 bg-zinc-100 rounded-full h-1.5 overflow-hidden">
          <div
            className={cn("h-1.5 rounded-full transition-all", meddpiccColor(score))}
            style={{ width: `${Math.round(score * 100)}%` }}
          />
        </div>
        <span className={cn("text-[11px] font-semibold tabular-nums w-8 text-right flex-shrink-0", score < 0.3 ? "text-zinc-400" : score < 0.6 ? "text-zinc-600" : "text-zinc-900")}>
          {Math.round(score * 100)}%
        </span>
        {gap && (
          <span className="text-zinc-300 group-hover:text-zinc-500 transition-colors flex-shrink-0">
            {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </span>
        )}
      </div>
      {open && gap && (
        <div className="mt-1.5 ml-40 pl-2 border-l-2 border-red-200">
          <p className="text-[11px] text-zinc-600 leading-relaxed">{gap}</p>
        </div>
      )}
    </div>
  );
}

// ── Why card ──────────────────────────────────────────────────────────────────

function WhyCard({ title, present, evidence }: { title: string; present: boolean; evidence: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div
      className={cn(
        "rounded-xl border p-3.5 cursor-pointer transition-colors",
        present ? "border-emerald-200 bg-emerald-50" : "border-red-100 bg-red-50"
      )}
      onClick={() => setOpen(o => !o)}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {present
            ? <CheckCircle className="w-4 h-4 text-emerald-500 flex-shrink-0" />
            : <XCircle className="w-4 h-4 text-red-400 flex-shrink-0" />}
          <span className={cn("text-xs font-semibold", present ? "text-emerald-700" : "text-red-700")}>{title}</span>
        </div>
        <span className={cn("text-[10px] font-bold px-2 py-0.5 rounded-full", present ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-600")}>
          {present ? "Present" : "Missing"}
        </span>
      </div>
      {open && (
        <p className="mt-2 text-[11px] text-zinc-600 leading-relaxed border-t border-current border-opacity-20 pt-2">
          {evidence}
        </p>
      )}
    </div>
  );
}

// ── Deal Dossier (right panel) ─────────────────────────────────────────────────

function DealDossier({ account }: { account: AccountListItem }) {
  const id = account.id;

  // Full state (POV, MEDDPICC, signals, memory)
  const { data: stateData, isLoading: stateLoading } = useQuery({
    queryKey: ["state", id],
    queryFn: () => accountsApi.getState(id),
    staleTime: 5 * 60 * 1000,
  });
  const state = (stateData?.data ?? {}) as Record<string, unknown>;
  const pov = (state.pov ?? {}) as Record<string, unknown>;
  const meddpicc = (pov.meddpicc ?? {}) as Record<string, unknown>;
  const threeWhys = (pov.three_whys ?? {}) as Record<string, { present: boolean; evidence: string }>;
  const riskVectors = (pov.risk_vectors ?? {}) as Record<string, string>;
  const signalThemes = (pov.signal_themes ?? []) as Array<{ theme: string; summary: string; severity: string; signal_count: number }>;
  const episodic = ((state.memory as Record<string, unknown>)?.episodic ?? []) as Array<Record<string, unknown>>;
  const stateSignals = (state.signals ?? []) as Array<{ type: string; urgency: string; detail: string; detected_at?: string; meddpicc_component?: string }>;

  const dealNarrative = (pov.deal_narrative as string) ?? "";
  const forecastCategory = (pov.forecast_category as string) ?? account.pov_forecast_cat ?? null;
  const winProbability = (pov.win_probability as number) ?? null;
  const healthScore = pov.health_score as number ?? account.health_score;
  const momentum = pov.deal_momentum as string | undefined;
  const daysSince = pov.days_since_meaningful_activity as number | undefined;
  const meddpiccOverall = (meddpicc.overall_score as number) ?? null;

  // Drafts / emails
  const { data: draftsAllData, isLoading: draftsLoading } = useQuery({
    queryKey: ["drafts", id, "all"],
    queryFn: () => draftsApi.list({ account_id: id, limit: 100 }),
    staleTime: 5 * 60 * 1000,
  });
  const allDrafts: Draft[] = draftsAllData?.data ?? [];
  const approvedDrafts = allDrafts.filter(d => d.status === "approved");
  const pendingDrafts = allDrafts.filter(d => d.status === "pending");
  const declinedDrafts = allDrafts.filter(d => d.status === "declined");

  // Transcripts / meetings
  const { data: transcriptsData, isLoading: meetingsLoading } = useQuery({
    queryKey: ["transcripts", id],
    queryFn: () => accountsApi.getTranscripts(id),
    staleTime: 10 * 60 * 1000,
  });
  const meetings: Transcript[] = transcriptsData?.data ?? [];

  // All signals (for full timeline)
  const { data: signalsData } = useQuery({
    queryKey: ["signals", id, "all"],
    queryFn: () => signalsApi.list({ account_id: id, limit: 50 }),
    staleTime: 5 * 60 * 1000,
  });
  const fullSignals: Signal[] = signalsData?.data ?? [];

  // Stakeholders: prefer the curated ASO list (validated + deduped by the
  // agent pipeline); regex extraction from narrative text is the fallback only.
  const stakeholders = useMemo(() => {
    const aso = (state.stakeholders ?? []) as Array<Record<string, unknown>>;
    const curated = aso
      .filter(s => typeof s.name === "string" && (s.name as string).trim())
      .map(s => ({
        name: s.name as string,
        role: (s.title as string) || (s.role as string) || "",
        status:
          s.engagement_level === "dark" || s.engagement_level === "departed"
            ? "dark"
            : "active",
      }));
    return curated.length > 0
      ? curated.slice(0, 8)
      : extractStakeholders(fullSignals, dealNarrative);
  }, [state, fullSignals, dealNarrative]);

  // Close date
  const closeDate = account.close_date
    ? new Date(account.close_date).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })
    : null;

  const lastRun = account.last_agent_run_at;

  if (stateLoading) {
    return (
      <div className="p-6 space-y-4">
        <Skeleton className="h-24 rounded-2xl" />
        <Skeleton className="h-32 rounded-2xl" />
        <Skeleton className="h-48 rounded-2xl" />
        <Skeleton className="h-48 rounded-2xl" />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto bg-zinc-50">

      {/* ── Sticky Header ──────────────────────────────────────────── */}
      <div className="bg-white border-b border-zinc-200 px-6 py-4 sticky top-0 z-10">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-lg font-bold text-zinc-900">{account.name}</h2>
              {forecastCategory && (
                <span className={cn("text-xs px-2 py-0.5 rounded-full border font-semibold", FORECAST_STYLES[forecastCategory] ?? FORECAST_STYLES["Pipeline"])}>
                  {forecastCategory}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 mt-1.5 flex-wrap text-sm text-zinc-500">
              <span className="bg-zinc-100 rounded-full px-2.5 py-0.5 text-xs font-medium text-zinc-600">{account.stage ?? "–"}</span>
              {account.deal_amount && <span className="font-semibold text-zinc-700">{fmtAmount(account.deal_amount)}</span>}
              {closeDate && <span className="flex items-center gap-1 text-xs"><Clock className="w-3 h-3" /> Close {closeDate}</span>}
            </div>
            {account.signals_summary[0] && (
              <p className="text-xs text-zinc-500 mt-1">
                Triggered by:{" "}
                <span className="font-medium text-zinc-700">{signalLabel(account.signals_summary[0].type)}</span>
              </p>
            )}
          </div>
          <Link
            href={`/account/${id}`}
            className="flex-shrink-0 flex items-center gap-1 text-xs font-semibold text-zinc-700 hover:text-zinc-700 bg-zinc-50 hover:bg-zinc-100 rounded-lg px-3 py-2 transition-colors whitespace-nowrap"
          >
            War Room <ArrowUpRight className="w-3.5 h-3.5" />
          </Link>
        </div>

        {/* Vitals bar */}
        <div className="flex items-center gap-4 mt-3 pt-3 border-t border-zinc-100">
          <VitalStat
            icon={<Activity className="w-3.5 h-3.5" />}
            label="Health"
            value={fmtPct(healthScore)}
            color={healthScore != null && healthScore < 0.3 ? "text-red-600" : healthScore != null && healthScore < 0.6 ? "text-amber-600" : "text-emerald-600"}
          />
          <VitalStat
            icon={<BarChart2 className="w-3.5 h-3.5" />}
            label="MEDDPICC"
            value={fmtPct(meddpiccOverall)}
            color={meddpiccOverall != null && meddpiccOverall < 0.3 ? "text-red-600" : meddpiccOverall != null && meddpiccOverall < 0.6 ? "text-amber-600" : "text-emerald-600"}
          />
          <VitalStat
            icon={<Mail className="w-3.5 h-3.5" />}
            label="Emails sent"
            value={String(
              (state.activity_summary as Record<string, number> | undefined)
                ?.total_emails_sent ?? "–"
            )}
          />
          <VitalStat
            icon={<Calendar className="w-3.5 h-3.5" />}
            label="Meetings"
            value={String(
              (state.activity_summary as Record<string, number> | undefined)
                ?.total_meetings ?? meetings.length
            )}
          />
          <VitalStat
            icon={momentumIcon(momentum)}
            label="Momentum"
            value={momentum ? momentum.charAt(0).toUpperCase() + momentum.slice(1) : "–"}
            color={momentum === "improving" ? "text-emerald-600" : momentum === "declining" ? "text-red-600" : "text-zinc-600"}
          />
          {winProbability != null && (
            <VitalStat
              icon={<TrendingUp className="w-3.5 h-3.5" />}
              label="Win prob"
              value={fmtPct(winProbability)}
              color={winProbability < 0.3 ? "text-red-600" : winProbability < 0.6 ? "text-amber-600" : "text-emerald-600"}
            />
          )}
          {daysSince != null && (
            <VitalStat
              icon={<Clock className="w-3.5 h-3.5" />}
              label="Days silent"
              value={String(daysSince)}
              color={daysSince > 30 ? "text-red-600" : daysSince > 14 ? "text-amber-600" : "text-zinc-700"}
            />
          )}
        </div>
      </div>

      <div className="p-5 space-y-5">

        {/* ── AI Narrative ─────────────────────────────────────────── */}
        {dealNarrative && (
          <Section title="AI Deal Story" icon={<Zap className="w-3.5 h-3.5 text-zinc-500" />}>
            <div className="bg-zinc-50 border border-zinc-200 rounded-xl px-4 py-3">
              <p className="text-sm text-zinc-900 leading-relaxed">{dealNarrative}</p>
            </div>
          </Section>
        )}

        {/* ── Top risk summary ─────────────────────────────────────── */}
        {(pov.top_risk_summary as string | undefined) && (
          <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
            <p className="text-sm text-red-800 leading-relaxed">{pov.top_risk_summary as string}</p>
          </div>
        )}

        {/* ── People ───────────────────────────────────────────────── */}
        <Section title="People & Contacts" icon={<Users className="w-3.5 h-3.5 text-zinc-500" />} count={stakeholders.length}>
          {stakeholders.length === 0 ? (
            <p className="text-sm text-zinc-400 text-center py-4">No contacts extracted yet. Run agents on this account to populate.</p>
          ) : (
            <div className="grid grid-cols-1 gap-2">
              {stakeholders.map(s => (
                <div key={s.name} className={cn(
                  "flex items-center gap-3 bg-white border rounded-xl px-3.5 py-2.5",
                  s.status === "dark" ? "border-red-200 bg-red-50" : "border-zinc-200"
                )}>
                  <div className={cn(
                    "w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 text-[11px] font-bold",
                    s.status === "dark" ? "bg-red-100 text-red-700" : "bg-zinc-100 text-zinc-700"
                  )}>
                    {s.name.split(" ").map(w => w[0]).join("").slice(0, 2)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-zinc-900">{s.name}</p>
                    <p className="text-[11px] text-zinc-500 truncate">{s.role}</p>
                  </div>
                  <span className={cn(
                    "text-[10px] font-bold px-2 py-0.5 rounded-full flex-shrink-0",
                    s.status === "dark" ? "bg-red-100 text-red-700" : "bg-emerald-100 text-emerald-700"
                  )}>
                    {s.status === "dark" ? "Dark" : "Active"}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Section>

        {/* ── Communication ────────────────────────────────────────── */}
        <Section title="Communication" icon={<Mail className="w-3.5 h-3.5 text-zinc-500" />}>
          <div className="grid grid-cols-3 gap-2 mb-3">
            <CommStat label="Sent / Approved" value={approvedDrafts.length} color="text-zinc-700" bg="bg-zinc-50 border-zinc-200" />
            <CommStat label="Pending review" value={pendingDrafts.length} color="text-orange-700" bg="bg-orange-50 border-orange-100" />
            <CommStat label="Declined" value={declinedDrafts.length} color="text-zinc-600" bg="bg-zinc-50 border-zinc-100" />
          </div>
          {approvedDrafts.length > 0 && (
            <div className="space-y-2">
              <p className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wider">Recent sent</p>
              {approvedDrafts.slice(0, 3).map(d => (
                <div key={d.id} className="bg-white border border-zinc-200 rounded-xl px-3.5 py-2.5">
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="text-xs font-semibold text-zinc-700">
                      {draftTypeLabel(d.type ?? "email")}
                    </span>
                    <span className="text-[10px] text-zinc-400">{fmtDate(d.reviewed_at ?? d.created_at)}</span>
                  </div>
                  {d.subject_line && <p className="text-[11px] text-zinc-500 mb-1">{d.subject_line}</p>}
                  <p className="text-[11px] text-zinc-600 line-clamp-2 leading-relaxed">{stripMarkdown(d.content ?? "")}</p>
                </div>
              ))}
            </div>
          )}
          {draftsLoading && <Skeleton className="h-20 rounded-xl" />}
        </Section>

        {/* ── Meetings ─────────────────────────────────────────────── */}
        <Section title="Meeting Log" icon={<Calendar className="w-3.5 h-3.5 text-zinc-500" />} count={meetings.length}>
          {meetingsLoading ? (
            <Skeleton className="h-32 rounded-xl" />
          ) : meetings.length === 0 ? (
            <div className="bg-white border border-zinc-200 rounded-xl px-4 py-5 text-center">
              <p className="text-sm text-zinc-400">No meeting transcripts yet.</p>
              <p className="text-xs text-zinc-300 mt-1">Connect Fireflies.ai or upload a transcript to see meeting intelligence.</p>
            </div>
          ) : (
            <div className="space-y-2">
              {meetings.map((m, i) => (
                <MeetingCard key={m.id ?? i} transcript={m} />
              ))}
            </div>
          )}
        </Section>

        {/* ── MEDDPICC Scorecard ───────────────────────────────────── */}
        <Section title="MEDDPICC Scorecard" icon={<BarChart2 className="w-3.5 h-3.5 text-zinc-500" />}>
          <div className="bg-white border border-zinc-200 rounded-xl px-4 py-4">
            {/* Overall */}
            <div className="flex items-center justify-between mb-4 pb-3 border-b border-zinc-100">
              <span className="text-sm font-semibold text-zinc-700">Overall qualification</span>
              <div className="flex items-center gap-3">
                <div className="w-32 bg-zinc-100 rounded-full h-2 overflow-hidden">
                  <div
                    className={cn("h-2 rounded-full", meddpiccColor(meddpiccOverall ?? 0))}
                    style={{ width: `${Math.round((meddpiccOverall ?? 0) * 100)}%` }}
                  />
                </div>
                <span className={cn("text-sm font-bold tabular-nums", (meddpiccOverall ?? 0) < 0.3 ? "text-red-600" : (meddpiccOverall ?? 0) < 0.6 ? "text-amber-600" : "text-emerald-600")}>
                  {fmtPct(meddpiccOverall)}
                </span>
              </div>
            </div>
            {/* Per-component */}
            {Object.entries(MEDDPICC_LABELS).map(([key, label]) => {
              const score = (meddpicc[key] as number) ?? 0;
              const gaps = meddpicc.gaps as string[] | undefined;
              const gap = gaps?.find(g => g.toLowerCase().startsWith(label.split("—")[1]?.trim().split(" ")[0].toLowerCase() ?? ""));
              return (
                <MEDDPICCBar key={key} label={label} score={score} gap={gap} />
              );
            })}
          </div>
        </Section>

        {/* ── 3 Whys ───────────────────────────────────────────────── */}
        <Section title="The 3 Whys" icon={<MessageSquare className="w-3.5 h-3.5 text-zinc-500" />}>
          <div className="space-y-2">
            {[
              { key: "why_change", title: "Why Change?" },
              { key: "why_now",    title: "Why Now?" },
              { key: "why_us",     title: "Why Us?" },
            ].map(({ key, title }) => {
              const why = threeWhys[key];
              if (!why) return null;
              return <WhyCard key={key} title={title} present={why.present} evidence={why.evidence} />;
            })}
          </div>
        </Section>

        {/* ── Risk Vectors ─────────────────────────────────────────── */}
        {Object.keys(riskVectors).length > 0 && (
          <Section title="Risk Vectors" icon={<AlertTriangle className="w-3.5 h-3.5 text-zinc-500" />}>
            <div className="flex flex-wrap gap-2">
              {Object.entries(riskVectors).map(([k, v]) => (
                <div key={k} className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold border",
                  v === "critical" ? "bg-red-50 text-red-700 border-red-200" :
                  v === "high" ? "bg-orange-50 text-orange-700 border-orange-200" :
                  v === "medium" ? "bg-amber-50 text-amber-700 border-amber-200" :
                  "bg-green-50 text-green-700 border-green-200"
                )}>
                  <span className={cn("w-1.5 h-1.5 rounded-full", v === "critical" ? "bg-red-500" : v === "high" ? "bg-orange-400" : v === "medium" ? "bg-amber-400" : "bg-green-400")} />
                  {k.charAt(0).toUpperCase() + k.slice(1)}: {v}
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* ── Signal Themes ────────────────────────────────────────── */}
        {signalThemes.length > 0 && (
          <Section title="Signal Clusters" icon={<Zap className="w-3.5 h-3.5 text-zinc-500" />} count={signalThemes.length}>
            <div className="space-y-2">
              {signalThemes.map((t, i) => (
                <div key={i} className={cn(
                  "bg-white border rounded-xl px-4 py-3",
                  t.severity === "critical" ? "border-red-200" : t.severity === "high" ? "border-orange-200" : "border-zinc-200"
                )}>
                  <div className="flex items-center justify-between mb-1.5">
                    <p className="text-sm font-semibold text-zinc-800">{t.theme}</p>
                    <span className={cn("text-[10px] font-bold px-2 py-0.5 rounded-full",
                      t.severity === "critical" ? "bg-red-100 text-red-700" : t.severity === "high" ? "bg-orange-100 text-orange-700" : "bg-amber-100 text-amber-700"
                    )}>
                      {t.signal_count} signals
                    </span>
                  </div>
                  <p className="text-xs text-zinc-600 leading-relaxed">{t.summary}</p>
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* ── Full Signal Feed ─────────────────────────────────────── */}
        {stateSignals.length > 0 && (
          <Section title="All Signals" icon={<Activity className="w-3.5 h-3.5 text-zinc-500" />} count={stateSignals.length}>
            <div className="bg-white border border-zinc-200 rounded-xl divide-y divide-zinc-100 overflow-hidden">
              {stateSignals.map((sig, i) => {
                const dotColor = sig.urgency === "critical" ? "bg-red-500" : sig.urgency === "high" ? "bg-zinc-700" : sig.urgency === "medium" ? "bg-zinc-400" : "bg-zinc-300";
                return (
                  <div key={i} className="flex items-start gap-3 px-4 py-3">
                    <span className={cn("w-2 h-2 rounded-full flex-shrink-0 mt-1.5", dotColor)} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-semibold text-zinc-700">{signalLabel(sig.type)}</p>
                        {sig.detected_at && (
                          <span className="text-[10px] text-zinc-400 flex-shrink-0">{fmtRelative(sig.detected_at)}</span>
                        )}
                      </div>
                      <p className="text-xs text-zinc-500 mt-0.5 leading-relaxed line-clamp-2">{sig.detail}</p>
                      {sig.meddpicc_component && (
                        <span className="mt-1 inline-block text-[10px] text-zinc-700 bg-zinc-50 px-1.5 py-0.5 rounded font-medium">
                          {sig.meddpicc_component}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </Section>
        )}

        {/* ── Agent Run History ────────────────────────────────────── */}
        {episodic.length > 0 && (
          <Section title="Agent Run History" icon={<Clock className="w-3.5 h-3.5 text-zinc-500" />} count={episodic.length}>
            <div className="space-y-2">
              {[...episodic].reverse().slice(0, 5).map((run, i) => (
                <div key={i} className="bg-white border border-zinc-200 rounded-xl px-4 py-3">
                  <div className="flex items-center justify-between gap-2 mb-1.5">
                    <span className="text-xs font-semibold text-zinc-700">{run.date as string}</span>
                    <div className="flex items-center gap-2">
                      {(run.meddpicc_score as number) != null && (
                        <span className="text-[10px] text-zinc-700 bg-zinc-50 px-1.5 py-0.5 rounded font-medium">
                          MEDDPICC {fmtPct(run.meddpicc_score as number)}
                        </span>
                      )}
                      {(run.health_score as number) != null && (
                        <span className={cn("text-[10px] px-1.5 py-0.5 rounded font-medium",
                          (run.health_score as number) < 0.3 ? "bg-red-100 text-red-700" : "bg-emerald-100 text-emerald-700"
                        )}>
                          Health {fmtPct(run.health_score as number)}
                        </span>
                      )}
                      {(run.signals_detected as number) > 0 && (
                        <span className="text-[10px] text-zinc-500">{run.signals_detected as number} signals</span>
                      )}
                    </div>
                  </div>
                  <p className="text-xs text-zinc-600 leading-relaxed line-clamp-3">{run.key_changes as string}</p>
                </div>
              ))}
            </div>
          </Section>
        )}

        {/* Spacer */}
        <div className="h-8" />
      </div>
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function VitalStat({ icon, label, value, color }: { icon: React.ReactNode; label: string; value: string; color?: string }) {
  return (
    <div className="flex flex-col items-center gap-0.5 min-w-0">
      <div className={cn("flex items-center gap-1 text-zinc-400", color)}>{icon}</div>
      <span className={cn("text-sm font-bold tabular-nums", color ?? "text-zinc-800")}>{value}</span>
      <span className="text-[10px] text-zinc-400 leading-none whitespace-nowrap">{label}</span>
    </div>
  );
}

function Section({ title, icon, count, children }: { title: string; icon: React.ReactNode; count?: number; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        {icon}
        <span className="text-[11px] font-semibold text-zinc-500 uppercase tracking-wider">{title}</span>
        {count != null && count > 0 && (
          <span className="text-[10px] text-zinc-700 bg-zinc-50 px-1.5 py-0.5 rounded-full font-semibold">{count}</span>
        )}
      </div>
      {children}
    </div>
  );
}

function CommStat({ label, value, color, bg }: { label: string; value: number; color: string; bg: string }) {
  return (
    <div className={cn("rounded-xl border px-3 py-2.5 text-center", bg)}>
      <p className={cn("text-2xl font-bold tabular-nums", color)}>{value}</p>
      <p className="text-[10px] text-zinc-500 mt-0.5 leading-tight">{label}</p>
    </div>
  );
}

function MeetingCard({ transcript }: { transcript: Transcript }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="bg-white border border-zinc-200 rounded-xl overflow-hidden">
      <button
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-zinc-50 transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <Calendar className="w-4 h-4 text-zinc-400 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-zinc-800 truncate">{transcript.title ?? "Meeting"}</p>
          <div className="flex items-center gap-2 mt-0.5">
            {transcript.date && <span className="text-[11px] text-zinc-400">{fmtDate(transcript.date)}</span>}
            {transcript.duration_minutes && <span className="text-[11px] text-zinc-400">· {transcript.duration_minutes}min</span>}
            {transcript.participants.length > 0 && (
              <span className="text-[11px] text-zinc-400">· {transcript.participants.length} attendees</span>
            )}
          </div>
        </div>
        {open ? <ChevronUp className="w-4 h-4 text-zinc-400 flex-shrink-0" /> : <ChevronDown className="w-4 h-4 text-zinc-400 flex-shrink-0" />}
      </button>

      {open && (
        <div className="px-4 pb-4 border-t border-zinc-100 pt-3 space-y-3">
          {transcript.participants.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider mb-1.5">Attendees</p>
              <div className="flex flex-wrap gap-1.5">
                {transcript.participants.map(p => (
                  <span key={p} className="text-[11px] bg-zinc-100 text-zinc-700 px-2 py-0.5 rounded-full font-medium">{p}</span>
                ))}
              </div>
            </div>
          )}
          {transcript.summary && (
            <div>
              <p className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider mb-1.5">Summary</p>
              <p className="text-xs text-zinc-700 leading-relaxed">{transcript.summary}</p>
            </div>
          )}
          {(transcript.commitments?.length || transcript.action_items.length) > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider mb-1.5">Action items</p>
              <ul className="space-y-1">
                {(transcript.commitments?.length
                  ? transcript.commitments
                  : transcript.action_items.map(a => ({ text: a, owner: "unknown" as const, owner_name: null }))
                ).map((c, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-zinc-700">
                    <span className={cn(
                      "text-[9px] font-semibold px-1.5 py-0.5 rounded-full border flex-shrink-0 mt-0.5",
                      c.owner === "us" ? "bg-zinc-50 text-zinc-700 border-zinc-200" :
                      c.owner === "buyer" ? "bg-emerald-50 text-emerald-700 border-emerald-200" :
                      "bg-zinc-50 text-zinc-500 border-zinc-200"
                    )}>
                      {c.owner === "us" ? "Us" : c.owner === "buyer" ? "Buyer" : "—"}
                    </span>
                    {c.text}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {Object.keys(transcript.speaker_stats).length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider mb-1.5">Talk time</p>
              <div className="space-y-1">
                {Object.entries(transcript.speaker_stats).slice(0, 5).map(([speaker, stats]) => (
                  <div key={speaker} className="flex items-center gap-2">
                    <span className="text-[11px] text-zinc-600 w-32 truncate">{speaker}</span>
                    <div className="flex-1 bg-zinc-100 rounded-full h-1 overflow-hidden">
                      <div
                        className="h-1 bg-zinc-700 rounded-full"
                        style={{ width: `${stats.talk_time_pct ?? 0}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-zinc-400 w-8 text-right">{stats.talk_time_pct ?? 0}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyDossier() {
  return (
    <div className="h-full flex items-center justify-center bg-zinc-50">
      <div className="text-center max-w-xs px-6">
        <div className="w-14 h-14 bg-white border border-zinc-200 rounded-2xl mx-auto mb-4 flex items-center justify-center shadow-sm">
          <FileText className="w-6 h-6 text-zinc-400" />
        </div>
        <p className="text-sm font-semibold text-zinc-800">Select a deal</p>
        <p className="text-xs text-zinc-400 mt-2 leading-relaxed">
          Contacts, emails, meetings, MEDDPICC scorecard, and AI analysis in one place.
        </p>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

function DealsInner() {
  const [selectedAccount, setSelectedAccount] = useState<AccountListItem | null>(null);
  const [filters, setFilters] = useState<DealFilterState>(() => loadFilters("dealbook"));
  const [highIntentOnly, setHighIntentOnly] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["accounts", "deals"],
    queryFn: () => accountsApi.list({ limit: 100, sort_by: "urgency_score", sort_dir: "desc" }),
    staleTime: 5 * 60 * 1000,
    refetchInterval: 10 * 60 * 1000,
  });

  const allAccounts: AccountListItem[] = data?.data ?? [];

  const sorted = useMemo(
    () => filterAndSortDeals(allAccounts, filters),
    [allAccounts, filters]
  );

  const displayed = highIntentOnly
    ? sorted.filter(a => (a.urgency_score ?? 0) >= 0.7)
    : sorted;

  const exportCSV = () => {
    const headers = ["Name", "Stage", "Amount", "Close Date", "Health %", "Intent %", "Forecast", "Last Swept", "Top Signal"];
    const rows = sorted.map(a => [
      cleanDealName(a.name),
      a.stage ?? "",
      a.deal_amount != null ? String(a.deal_amount) : "",
      a.close_date ?? "",
      a.health_score != null ? String(Math.round(a.health_score * 100)) : "",
      a.urgency_score != null ? String(Math.round(a.urgency_score * 100)) : "",
      a.pov_forecast_cat ?? "",
      a.last_agent_run_at ?? "",
      a.signals_summary[0]?.type ? signalLabel(a.signals_summary[0].type) : "",
    ]);
    const csv = [headers, ...rows]
      .map(r => r.map(c => `"${c.replace(/"/g, '""')}"`).join(","))
      .join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "deals.csv";
    link.click();
    URL.revokeObjectURL(url);
  };

  const updateFilters = (next: DealFilterState) => {
    setFilters(next);
    saveFilters("dealbook", next);
  };

  return (
    <div className="flex h-full">

      {/* ── Left panel ─────────────────────────────────────────────── */}
      <div className="w-72 flex-shrink-0 border-r border-zinc-100 bg-white flex flex-col">

        {/* Search + filters + sort (shared engine) */}
        <div className="px-3 pt-3 pb-2 border-b border-zinc-100">
          <DealFilterBar
            accounts={allAccounts}
            state={filters}
            onChange={updateFilters}
            sortOptions={["urgency", "amount", "close", "health", "swept", "name"]}
          />
        </div>

        {/* Count + controls */}
        <div className="px-3 py-1.5 border-b border-zinc-100 flex items-center justify-between gap-2">
          <p className="text-[10px] text-zinc-400">
            {displayed.length} of {allAccounts.length} deals{hasActiveFilters(filters) || highIntentOnly ? " · filtered" : ""}
          </p>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setHighIntentOnly(o => !o)}
              className={cn(
                "text-[10px] font-semibold px-2 py-0.5 rounded-full border transition-colors",
                highIntentOnly
                  ? "bg-zinc-900 text-white border-zinc-900"
                  : "text-zinc-600 border-zinc-200 hover:border-zinc-400"
              )}
            >
              ≥70%
            </button>
            <button
              onClick={exportCSV}
              className="text-zinc-400 hover:text-zinc-700 transition-colors"
              title="Download CSV"
            >
              <Download className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Deal list */}
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="space-y-0">
              {[1,2,3,4,5,6,7,8].map(i => <Skeleton key={i} className="h-14 rounded-none border-b border-zinc-100" />)}
            </div>
          ) : displayed.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center px-4">
              <AlertTriangle className="w-8 h-8 text-zinc-200 mb-3" />
              <p className="text-sm font-medium text-zinc-600">No deals found</p>
            </div>
          ) : (
            displayed.map(account => (
              <DealRow
                key={account.id}
                account={account}
                isSelected={selectedAccount?.id === account.id}
                onClick={() => setSelectedAccount(account)}
              />
            ))
          )}
        </div>
      </div>

      {/* ── Right panel ────────────────────────────────────────────── */}
      <div className="flex-1 overflow-hidden">
        {selectedAccount ? (
          <DealDossier account={selectedAccount} />
        ) : (
          <EmptyDossier />
        )}
      </div>
    </div>
  );
}

export default function DealsPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center h-full">
        <div className="w-6 h-6 border-2 border-zinc-900 border-t-transparent rounded-full animate-spin" />
      </div>
    }>
      <DealsInner />
    </Suspense>
  );
}
