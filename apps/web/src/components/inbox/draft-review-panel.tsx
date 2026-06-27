"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { accountsApi, draftsApi } from "@/lib/api";
import { AuditPanel } from "@/components/audit/audit-panel";
import React, { useState } from "react";
import { toast } from "sonner";
import {
  CheckCircle, XCircle, Edit3, ChevronDown, ChevronUp,
  AlertTriangle, Clock, ExternalLink, RefreshCw, Zap, TrendingUp,
  TrendingDown, FileText, Target, Shield
} from "lucide-react";
import { cn, formatCompactCurrency, draftTypeLabel } from "@/lib/utils";
import { MarkdownContent } from "@/components/markdown-content";
import { formatDistanceToNow } from "date-fns";

interface Props {
  accountId: string;
  accountName?: string;
  lastAgentRunAt?: string | null;
}

type Tab = "drafts" | "pov" | "actions";
type DraftStatus = "pending" | "approved" | "declined";

export function DraftReviewPanel({ accountId, accountName, lastAgentRunAt }: Props) {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<Tab>("drafts");
  const [draftStatus, setDraftStatus] = useState<DraftStatus>("pending");
  const [expandedDraftId, setExpandedDraftId] = useState<string | null>(null);
  const [editingDraftId, setEditingDraftId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [auditTarget, setAuditTarget] = useState<{ fact: string; source: string } | null>(null);
  const [declineReason, setDeclineReason] = useState<string>("");
  const [decliningDraftId, setDecliningDraftId] = useState<string | null>(null);

  // Account POV
  const { data: povData } = useQuery({
    queryKey: ["account-pov", accountId],
    queryFn: () => accountsApi.getPov(accountId),
  });

  // Next actions
  const { data: actionsData } = useQuery({
    queryKey: ["account-actions", accountId],
    queryFn: () => accountsApi.getNextActions(accountId),
  });

  // Drafts for this account (status-aware)
  const { data: draftsData, isLoading: draftsLoading } = useQuery({
    queryKey: ["drafts", draftStatus, accountId],
    queryFn: () => draftsApi.list({ account_id: accountId, status: draftStatus }),
  });

  // Run agents for this account
  const runAgentsMutation = useMutation({
    mutationFn: () => accountsApi.batchRefresh([accountId]),
    onSuccess: () => {
      toast.success("Agent queued - check back in a few minutes");
    },
    onError: () => toast.error("Failed to queue agent run"),
  });

  // Draft review mutation
  const reviewMutation = useMutation({
    mutationFn: ({ id, action, notes, modified, category }: {
      id: string; action: string; notes?: string; modified?: string; category?: string;
    }) =>
      draftsApi.review(id, {
        action,
        reviewer_notes: notes,
        modified_content: modified,
        training_category: category,
      }),
    onSuccess: (_, vars) => {
      queryClient.invalidateQueries({ queryKey: ["drafts"] });
      const msg = vars.action === "approved" ? "Draft approved" :
                  vars.action === "approved_modified" ? "Approved with edits" :
                  "Declined - feedback saved";
      toast.success(msg);
      setDecliningDraftId(null);
      setEditingDraftId(null);
    },
    onError: () => toast.error("Action failed. Try again."),
  });

  const pov = povData?.data;
  const actions = actionsData?.data?.next_actions ?? [];
  const drafts = draftsData?.data ?? [];
  const urgency = pov?.urgency_score ?? 0;
  const health = pov?.health_score ?? 0;
  const stage = pov?.crm_stage;
  const amount = pov?.crm_amount;
  const hasDivergence = pov?.delta?.ai_vs_crm && pov.delta.ai_vs_crm !== "AI agrees with CRM";

  const lastRun = lastAgentRunAt
    ? formatDistanceToNow(new Date(lastAgentRunAt), { addSuffix: true })
    : "never";

  const urgencyColor =
    urgency >= 0.85 ? "text-red-600 bg-red-50 border-red-200" :
    urgency >= 0.7  ? "text-orange-600 bg-orange-50 border-orange-200" :
    urgency >= 0.5  ? "text-yellow-700 bg-yellow-50 border-yellow-200" :
                      "text-green-700 bg-green-50 border-green-200";

  const healthColor =
    health >= 0.75 ? "bg-green-400" :
    health >= 0.5  ? "bg-yellow-400" : "bg-red-400";

  return (
    <div data-testid="draft-review-panel" className="h-full flex flex-col bg-zinc-50">

      {/* ── Account header ── */}
      <div className="bg-white border-b border-zinc-200 px-5 py-3 flex-shrink-0 flex items-center justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-zinc-900 truncate">
            {accountName ?? (pov?.pov as Record<string, string>)?.account_name ?? "Account"}
          </h2>
          <div className="flex items-center gap-2 mt-0.5 flex-wrap">
            {stage && <span className="text-xs text-zinc-400">{stage}</span>}
            {amount && (
              <>
                <span className="text-zinc-200">·</span>
                <span className="text-xs text-zinc-400">
                  {formatCompactCurrency(amount)}
                </span>
              </>
            )}
            {hasDivergence && (
              <>
                <span className="text-zinc-200">·</span>
                <span className="text-xs text-amber-600 font-medium">{pov!.delta.ai_vs_crm}</span>
              </>
            )}
          </div>
        </div>
        <a
          href={`/account/${accountId}`}
          className="flex-shrink-0 text-xs font-medium text-zinc-500 hover:text-zinc-900 border border-zinc-200 hover:border-zinc-300 rounded-md px-3 py-1.5 transition-colors whitespace-nowrap bg-white"
        >
          Open War Room
        </a>
      </div>

      {/* ── Tabs ────────────────────────────────────────────────────────────── */}
      <div className="bg-white border-b border-zinc-200 px-5 flex-shrink-0">
        <div className="flex gap-0">
          {([
            { id: "drafts",  label: "Drafts",   icon: FileText,   badge: draftStatus === "pending" && drafts.length > 0 ? drafts.length : null },
            { id: "pov",     label: "AI Analysis", icon: TrendingUp, badge: null as number | null },
            { id: "actions", label: "Actions",  icon: Target,     badge: actions.length > 0 ? actions.length : null },
          ] as { id: Tab; label: string; icon: React.ElementType; badge: number | null }[]).map(({ id, label, icon: Icon, badge }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={cn(
                "flex items-center gap-1.5 px-4 py-3 text-xs font-medium border-b-2 transition-colors",
                activeTab === id
                  ? "border-zinc-900 text-zinc-900"
                  : "border-transparent text-zinc-500 hover:text-zinc-700 hover:border-zinc-300"
              )}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
              {badge !== undefined && badge !== null && (
                <span className={cn(
                  "text-xs font-semibold px-1.5 py-0.5 rounded-full",
                  activeTab === id ? "bg-zinc-200 text-zinc-700" : "bg-zinc-100 text-zinc-600"
                )}>
                  {badge}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* ── Tab content ─────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto">

        {/* ── DRAFTS TAB ──────────────────────────────────────────────────── */}
        {activeTab === "drafts" && (
          <div className="p-5">
            {/* Status sub-tabs */}
            <div className="flex mb-4 border-b border-zinc-200 -mx-5 px-5">
              {(["pending", "approved", "declined"] as DraftStatus[]).map((s) => (
                <button
                  key={s}
                  onClick={() => { setDraftStatus(s); setExpandedDraftId(null); setEditingDraftId(null); setDecliningDraftId(null); }}
                  className={cn(
                    "mr-5 pb-2.5 text-xs font-medium transition-colors capitalize border-b-2 -mb-px",
                    draftStatus === s
                      ? "border-zinc-900 text-zinc-900"
                      : "border-transparent text-zinc-400 hover:text-zinc-600"
                  )}
                >
                  {s}
                </button>
              ))}
            </div>
            {draftsLoading ? (
              <div className="space-y-3">
                {[1, 2].map(i => (
                  <div key={i} className="h-36 bg-white border border-zinc-200 rounded-xl animate-pulse" />
                ))}
              </div>
            ) : drafts.length === 0 ? (
              <div className="bg-white border border-zinc-200 rounded-lg p-8 text-center">
                <div className="w-10 h-10 bg-zinc-100 rounded-full mx-auto mb-3 flex items-center justify-center">
                  <FileText className="w-5 h-5 text-zinc-400" />
                </div>
                {draftStatus === "pending" ? (
                  <>
                    <p className="text-sm font-medium text-zinc-700">No pending drafts</p>
                    <p className="text-xs text-zinc-400 mt-1 mb-5">
                      Last agent run: {lastRun}. Click Run Agents in the top bar to generate drafts and meeting briefs.
                    </p>
                    <button
                      onClick={() => runAgentsMutation.mutate()}
                      disabled={runAgentsMutation.isPending}
                      className="inline-flex items-center gap-2 text-xs font-medium bg-zinc-900 text-white px-4 py-2 rounded-md hover:bg-zinc-800 transition-colors disabled:opacity-50"
                    >
                      <RefreshCw className={cn("w-3.5 h-3.5", runAgentsMutation.isPending && "animate-spin")} />
                      {runAgentsMutation.isPending ? "Queuing..." : "Run Agents Now"}
                    </button>
                  </>
                ) : (
                  <p className="text-sm font-medium text-zinc-700">No {draftStatus} drafts</p>
                )}
              </div>
            ) : (
              <div className="space-y-4">
                {drafts.map((draft) => (
                  <DraftCard
                    key={draft.id}
                    draft={draft}
                    draftStatus={draftStatus}
                    isExpanded={expandedDraftId === draft.id}
                    isEditing={editingDraftId === draft.id}
                    isDeclining={decliningDraftId === draft.id}
                    editContent={editContent}
                    declineReason={declineReason}
                    reviewPending={reviewMutation.isPending}
                    onToggleExpand={() => setExpandedDraftId(expandedDraftId === draft.id ? null : draft.id)}
                    onStartEdit={() => { setEditContent(draft.content); setEditingDraftId(draft.id); }}
                    onCancelEdit={() => setEditingDraftId(null)}
                    onEditChange={setEditContent}
                    onApprove={() => reviewMutation.mutate({ id: draft.id, action: "approved" })}
                    onApproveModified={() => reviewMutation.mutate({ id: draft.id, action: "approved_modified", modified: editContent })}
                    onStartDecline={() => setDecliningDraftId(draft.id)}
                    onCancelDecline={() => setDecliningDraftId(null)}
                    onDeclineReasonChange={setDeclineReason}
                    onConfirmDecline={() => reviewMutation.mutate({ id: draft.id, action: "declined", category: declineReason || undefined })}
                    onViewAudit={() => setAuditTarget({ fact: "sources_cited", source: "Drafter Agent" })}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── AI POV TAB ──────────────────────────────────────────────────── */}
        {activeTab === "pov" && (
          <div className="p-5 space-y-4">
            {!pov ? (
              <NoPovState lastRun={lastRun} onRunAgents={() => runAgentsMutation.mutate()} running={runAgentsMutation.isPending} />
            ) : (
              <>
                {/* Forecast */}
                {(pov.pov as Record<string, unknown>)?.forecast_category && (
                  <InfoCard title="Forecast">
                    <div className="flex items-center gap-3">
                      <ForecastPill cat={String((pov.pov as Record<string, unknown>).forecast_category)} />
                      {!!(pov.pov as Record<string, unknown>)?.forecast_confidence && (
                        <span className="text-xs text-zinc-500">
                          {Math.round(Number((pov.pov as Record<string, unknown>).forecast_confidence) * 100)}% confidence
                        </span>
                      )}
                    </div>
                    {!!(pov.pov as Record<string, unknown>)?.forecast_rationale && (
                      <p className="text-sm text-zinc-700 mt-2 leading-relaxed">
                        {String((pov.pov as Record<string, unknown>).forecast_rationale)}
                      </p>
                    )}
                  </InfoCard>
                )}

                {/* MEDDPICC scorecard */}
                {(() => {
                  const meddpicc = (pov.pov as Record<string, unknown>)?.meddpicc as Record<string, unknown> | undefined;
                  if (!meddpicc) return null;
                  const components: [string, string][] = [
                    ["M", "Metrics"], ["E", "Econ. Buyer"], ["D", "Decision Criteria"],
                    ["D", "Decision Process"], ["I", "Implicate Pain"], ["C", "Champion"],
                    ["C", "Competition"], ["P", "Paper Process"],
                  ];
                  const keys = ["metrics","economic_buyer","decision_criteria","decision_process","implicate_pain","champion","competition","paper_process"];
                  const overall = Number(meddpicc.overall_score ?? 0);
                  const gaps = (meddpicc.gaps as string[]) ?? [];
                  return (
                    <InfoCard title="MEDDPICC Qualification">
                      {/* Overall bar */}
                      <div className="flex items-center gap-3 mb-3">
                        <div className="flex-1 h-2 bg-zinc-100 rounded-full overflow-hidden">
                          <div
                            className={cn("h-full rounded-full transition-all",
                              overall >= 0.7 ? "bg-green-400" : overall >= 0.4 ? "bg-yellow-400" : "bg-red-400"
                            )}
                            style={{ width: `${Math.round(overall * 100)}%` }}
                          />
                        </div>
                        <span className={cn("text-xs font-bold tabular-nums",
                          overall >= 0.7 ? "text-green-700" : overall >= 0.4 ? "text-amber-700" : "text-red-700"
                        )}>
                          {Math.round(overall * 100)}%
                        </span>
                      </div>
                      {/* Component grid */}
                      <div className="grid grid-cols-4 gap-1.5 mb-3">
                        {components.map(([letter, label], i) => {
                          const score = Number(meddpicc[keys[i]] ?? 0);
                          const color = score >= 0.7 ? "bg-green-400" : score >= 0.4 ? "bg-yellow-400" : "bg-red-400";
                          return (
                            <div key={i} className="text-center">
                              <div className="relative h-1 bg-zinc-100 rounded-full overflow-hidden mb-0.5">
                                <div className={cn("h-full rounded-full", color)} style={{ width: `${Math.round(score * 100)}%` }} />
                              </div>
                              <p className="text-[9px] text-zinc-500 truncate leading-none">{label}</p>
                            </div>
                          );
                        })}
                      </div>
                      {/* Gaps */}
                      {gaps.length > 0 && (
                        <div className="space-y-1">
                          {gaps.slice(0, 3).map((gap, i) => (
                            <div key={i} className="flex items-start gap-1.5">
                              <AlertTriangle className="w-3 h-3 text-amber-400 mt-0.5 flex-shrink-0" />
                              <p className="text-xs text-zinc-600">{gap}</p>
                            </div>
                          ))}
                        </div>
                      )}
                    </InfoCard>
                  );
                })()}

                {/* Risk Vectors */}
                {(() => {
                  const rv = (pov.pov as Record<string, unknown>)?.risk_vectors as Record<string, string> | undefined;
                  const momentum = String((pov.pov as Record<string, unknown>)?.deal_momentum ?? "");
                  const threeWhys = (pov.pov as Record<string, unknown>)?.three_whys as Record<string, Record<string, unknown>> | undefined;
                  if (!rv && !momentum && !threeWhys) return null;
                  const riskColor: Record<string, string> = {
                    critical: "text-red-600 bg-red-50 border-red-200",
                    high:     "text-orange-600 bg-orange-50 border-orange-200",
                    medium:   "text-yellow-700 bg-yellow-50 border-yellow-200",
                    low:      "text-green-600 bg-green-50 border-green-200",
                  };
                  const momentumColor: Record<string, string> = {
                    accelerating: "text-green-700", neutral: "text-zinc-600",
                    stalling: "text-amber-700", declining: "text-red-700",
                  };
                  return (
                    <InfoCard title="Risk Vectors & Momentum">
                      {rv && (
                        <div className="flex flex-wrap gap-1.5 mb-3">
                          {Object.entries(rv).map(([key, level]) => (
                            <span key={key} className={cn("text-xs px-2 py-0.5 rounded-full border font-medium capitalize",
                              riskColor[level] ?? riskColor.medium
                            )}>
                              {key}: {level}
                            </span>
                          ))}
                        </div>
                      )}
                      {momentum && (
                        <div className="flex items-center gap-2 mb-3">
                          <span className="text-xs text-zinc-500">Momentum:</span>
                          <span className={cn("text-xs font-semibold capitalize", momentumColor[momentum] ?? "text-zinc-700")}>
                            {momentum}
                          </span>
                        </div>
                      )}
                      {threeWhys && (
                        <div className="space-y-1.5">
                          {[["why_change", "Why Change"], ["why_now", "Why Now"], ["why_us", "Why Us"]].map(([key, label]) => {
                            const w = threeWhys[key];
                            if (!w) return null;
                            const present = Boolean(w.present);
                            return (
                              <div key={key} className="flex items-start gap-2">
                                <div className={cn("w-3 h-3 rounded-full mt-0.5 flex-shrink-0",
                                  present ? "bg-green-400" : "bg-red-400"
                                )} />
                                <div>
                                  <span className="text-xs font-medium text-zinc-700">{label}: </span>
                                  <span className="text-xs text-zinc-500">{String(w.evidence ?? (present ? "Confirmed" : "Not established"))}</span>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </InfoCard>
                  );
                })()}

                {/* Risks */}
                {Array.isArray((pov.pov as Record<string, unknown>)?.risks) && ((pov.pov as Record<string, unknown>).risks as unknown[]).length > 0 && (
                  <InfoCard title="Risks">
                    <ul className="space-y-2">
                      {((pov.pov as Record<string, unknown>).risks as Array<string | Record<string, string>>)
                        .slice(0, 5)
                        .map((risk, i) => (
                          <li key={i} className="flex items-start gap-2 text-sm text-zinc-700">
                            <TrendingDown className="w-3.5 h-3.5 text-red-400 mt-0.5 flex-shrink-0" />
                            {typeof risk === "string" ? risk : String(risk?.description ?? JSON.stringify(risk))}
                          </li>
                        ))}
                    </ul>
                  </InfoCard>
                )}

                {/* Key intel */}
                {Array.isArray((pov.pov as Record<string, unknown>)?.key_intel) && ((pov.pov as Record<string, unknown>).key_intel as unknown[]).length > 0 && (
                  <InfoCard title="Key Intelligence">
                    <ul className="space-y-2">
                      {((pov.pov as Record<string, unknown>).key_intel as unknown[])
                        .slice(0, 5)
                        .map((item, i) => (
                          <li key={i} className="flex items-start gap-2 text-sm text-zinc-700">
                            <Zap className="w-3.5 h-3.5 text-zinc-500 mt-0.5 flex-shrink-0" />
                            {String(item)}
                          </li>
                        ))}
                    </ul>
                  </InfoCard>
                )}

                {/* Grounding */}
                {pov.grounding_confidence != null && (
                  <InfoCard title="Grounding">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 w-24 bg-zinc-100 rounded-full overflow-hidden">
                          <div
                            className={cn("h-full rounded-full",
                              pov.grounding_confidence >= 0.8 ? "bg-green-400" :
                              pov.grounding_confidence >= 0.6 ? "bg-yellow-400" : "bg-red-400"
                            )}
                            style={{ width: `${pov.grounding_confidence * 100}%` }}
                          />
                        </div>
                        <span className={cn(
                          "text-xs font-medium",
                          pov.grounding_confidence >= 0.8 ? "text-green-700" :
                          pov.grounding_confidence >= 0.6 ? "text-yellow-700" : "text-red-700"
                        )}>
                          {Math.round(pov.grounding_confidence * 100)}% confident
                        </span>
                      </div>
                      <button
                        onClick={() => setAuditTarget({ fact: "grounding_summary", source: "Grounding Agent" })}
                        className="text-xs text-zinc-600 hover:underline flex items-center gap-1"
                      >
                        View Audit <ExternalLink className="w-3 h-3" />
                      </button>
                    </div>
                    {pov.grounding_summary && (
                      <p className="text-xs text-zinc-500 mt-2 leading-relaxed">{pov.grounding_summary}</p>
                    )}
                  </InfoCard>
                )}

                {/* Gold data snapshot */}
                {pov.gold_data && Object.keys(pov.gold_data).length > 0 && (
                  <InfoCard title="Gold Data Layer">
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                      {Object.entries(pov.gold_data).slice(0, 8).map(([key, value]) => (
                        <div key={key}>
                          <p className="text-xs text-zinc-400">{key.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}</p>
                          <p className="text-xs font-medium text-zinc-700 truncate">{String(value ?? "-")}</p>
                        </div>
                      ))}
                    </div>
                  </InfoCard>
                )}
              </>
            )}
          </div>
        )}

        {/* ── ACTIONS TAB ─────────────────────────────────────────────────── */}
        {activeTab === "actions" && (
          <div className="p-5 space-y-3">
            {actions.length === 0 ? (
              <NoPovState lastRun={lastRun} onRunAgents={() => runAgentsMutation.mutate()} running={runAgentsMutation.isPending} />
            ) : (
              actions.map((action, i) => (
                <div
                  key={i}
                  className={cn(
                    "bg-white border rounded-xl p-4",
                    i === 0 ? "border-zinc-200" : "border-zinc-200"
                  )}
                >
                  <div className="flex items-start gap-3">
                    <div className={cn(
                      "w-6 h-6 rounded-lg flex-shrink-0 flex items-center justify-center text-xs font-bold",
                      i === 0 ? "bg-zinc-200 text-zinc-700" : "bg-zinc-100 text-zinc-500"
                    )}>
                      {i + 1}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-zinc-800">{action.action}</p>
                      <p className="text-xs text-zinc-500 mt-1 leading-relaxed">{action.reason ?? action.rationale}</p>
                      <div className="flex items-center gap-2 mt-2 flex-wrap">
                        {action.target_contact && (
                          <span className="text-xs text-zinc-400">@ {action.target_contact}</span>
                        )}
                        {action.meddpicc_component && (
                          <span className="text-xs font-medium text-zinc-600 bg-zinc-100 px-2 py-0.5 rounded-full">
                            {action.meddpicc_component}
                          </span>
                        )}
                        {action.framework_rationale && (
                          <span className="text-xs text-zinc-400 italic">
                            {action.framework_rationale}
                          </span>
                        )}
                        {action.draft_recommended && (
                          <span className="text-xs font-medium text-zinc-600 bg-zinc-100 px-2 py-0.5 rounded-full">
                            {action.draft_type ? draftTypeLabel(action.draft_type) : "Draft"} ready
                          </span>
                        )}
                      </div>
                    </div>
                    <div className={cn(
                      "flex-shrink-0 text-xs font-semibold px-2 py-1 rounded-lg",
                      action.urgency_score >= 0.85 ? "bg-red-50 text-red-600" :
                      action.urgency_score >= 0.7  ? "bg-orange-50 text-orange-600" : "bg-zinc-100 text-zinc-500"
                    )}>
                      {Math.round(action.urgency_score * 100)}%
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      {/* Audit Panel (slide-in overlay) */}
      {auditTarget && (
        <AuditPanel
          accountId={accountId}
          factKey={auditTarget.fact}
          onClose={() => setAuditTarget(null)}
        />
      )}
    </div>
  );
}


// ── Sub-components ────────────────────────────────────────────────────────────

const DECLINE_CATEGORIES = [
  { value: "wrong_tone",    label: "Wrong tone" },
  { value: "wrong_timing",  label: "Wrong timing" },
  { value: "already_sent",  label: "Already sent" },
  { value: "wrong_content", label: "Wrong content" },
  { value: "not_relevant",  label: "Not relevant" },
  { value: "hallucination", label: "Unsupported fact" },
  { value: "other",         label: "Other" },
];

function ConfidenceBadge({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  const cls =
    pct >= 85 ? "bg-green-50 text-green-700 border-green-200" :
    pct >= 65 ? "bg-yellow-50 text-yellow-700 border-yellow-200" :
                "bg-red-50 text-red-600 border-red-200";
  const label =
    pct >= 85 ? "High confidence" :
    pct >= 65 ? "Review carefully" :
                "Needs verification";
  return (
    <span className={cn("text-xs px-2 py-0.5 rounded-full border font-medium", cls)} title={`Confidence: ${pct}%`}>
      {pct}% {label}
    </span>
  );
}

function DraftCard({
  draft, draftStatus, isExpanded, isEditing, isDeclining,
  editContent, declineReason,
  reviewPending,
  onToggleExpand, onStartEdit, onCancelEdit, onEditChange,
  onApprove, onApproveModified, onStartDecline, onCancelDecline,
  onDeclineReasonChange, onConfirmDecline, onViewAudit,
}: {
  draft: Parameters<typeof draftsApi.list>[0] extends { account_id?: string } ? ReturnType<typeof Array.prototype.find> : any;
  draftStatus: DraftStatus;
  isExpanded: boolean;
  isEditing: boolean;
  isDeclining: boolean;
  editContent: string;
  declineReason: string;
  reviewPending: boolean;
  onToggleExpand: () => void;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onEditChange: (v: string) => void;
  onApprove: () => void;
  onApproveModified: () => void;
  onStartDecline: () => void;
  onCancelDecline: () => void;
  onDeclineReasonChange: (v: string) => void;
  onConfirmDecline: () => void;
  onViewAudit: () => void;
}) {
  const [showSources, setShowSources] = React.useState(false);
  const sources: Array<{ fact: string; source: string; confidence?: number }> = draft.sources_cited ?? [];

  // Always show first 3 lines as preview
  const preview = draft.content?.split("\n").filter(Boolean).slice(0, 3).join("\n") ?? "";
  const hasMore = (draft.content?.split("\n").filter(Boolean).length ?? 0) > 3;

  return (
    <div className="bg-white border border-zinc-200 rounded-lg overflow-hidden">
      {/* Header row */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-100">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-medium bg-zinc-100 text-zinc-600 px-2 py-0.5 rounded-full">
            {draftTypeLabel(draft.type ?? "")}
          </span>
          {draft.play_triggered && (
            <span
              className="text-xs font-medium bg-zinc-100 text-zinc-600 px-2 py-0.5 rounded-full"
              title={draft.play_reason ?? undefined}
            >
              ▶ {draft.play_name ?? "Play"}
            </span>
          )}
          {draft.confidence != null && (
            <ConfidenceBadge confidence={draft.confidence} />
          )}
          <span className="text-xs text-zinc-400">
            {draft.created_at
              ? formatDistanceToNow(new Date(draft.created_at), { addSuffix: true })
              : "just now"}
          </span>
        </div>
        <button
          onClick={onViewAudit}
          className="text-xs text-zinc-400 hover:text-zinc-600 flex items-center gap-1"
        >
          Audit <ExternalLink className="w-3 h-3" />
        </button>
      </div>

      {/* Preview - always visible */}
      <div className="px-4 pt-3 pb-2">
        {isEditing ? (
          <textarea
            value={editContent}
            onChange={e => onEditChange(e.target.value)}
            className="w-full text-sm text-zinc-800 font-mono resize-none focus:outline-none focus:ring-1 focus:ring-zinc-300 rounded p-2 border border-zinc-200"
            rows={12}
            autoFocus
          />
        ) : (
          <>
            <MarkdownContent content={isExpanded ? draft.content : preview} />
            {hasMore && !isExpanded && (
              <p className="text-xs text-zinc-400 mt-1 italic">
                Draft continues...
              </p>
            )}
          </>
        )}
        {hasMore && !isEditing && (
          <button
            onClick={onToggleExpand}
            className="flex items-center gap-1 text-xs text-zinc-600 hover:text-brand-700 mt-2"
          >
            {isExpanded ? <><ChevronUp className="w-3 h-3" /> Show less</> : <><ChevronDown className="w-3 h-3" /> Read full draft</>}
          </button>
        )}
      </div>

      {/* Source citations accordion (B1) */}
      {sources.length > 0 && (
        <div className="border-t border-zinc-100">
          <button
            onClick={() => setShowSources(s => !s)}
            className="w-full flex items-center justify-between px-4 py-2.5 text-xs text-zinc-500 hover:text-zinc-700 hover:bg-zinc-50 transition-colors"
          >
            <span className="flex items-center gap-1.5">
              <Shield className="w-3.5 h-3.5 text-zinc-400" />
              Sources used ({sources.length})
            </span>
            {showSources ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
          {showSources && (
            <div className="px-4 pb-3 space-y-2">
              {sources.map((s, i) => (
                <div key={i} className="flex items-start gap-2 text-xs">
                  <div className="w-1.5 h-1.5 rounded-full bg-zinc-400 mt-1.5 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <span className="text-zinc-700">{s.fact}</span>
                    <span className="text-zinc-400 ml-2">
                      {s.source}
                      {s.confidence != null ? ` (${Math.round(s.confidence * 100)}%)` : ""}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Decline feedback form */}
      {isDeclining && (
        <div className="px-4 pb-3 pt-2 border-t border-zinc-100 bg-red-50">
          <p className="text-xs font-medium text-red-700 mb-2">Why decline?</p>
          <div className="grid grid-cols-2 gap-2 mb-3">
            {DECLINE_CATEGORIES.map(({ value, label }) => (
              <button
                key={value}
                onClick={() => onDeclineReasonChange(value)}
                className={cn(
                  "text-xs px-2 py-1.5 rounded-lg border transition-colors text-left",
                  declineReason === value
                    ? "border-red-400 bg-red-100 text-red-700 font-medium"
                    : "border-zinc-200 bg-white text-zinc-600 hover:border-red-300"
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <button
              onClick={onConfirmDecline}
              disabled={reviewPending}
              className="flex-1 text-xs font-medium bg-red-500 text-white px-3 py-2 rounded-lg hover:bg-red-600 transition-colors disabled:opacity-50"
            >
              Confirm decline
            </button>
            <button
              onClick={onCancelDecline}
              className="text-xs text-zinc-500 px-3 py-2 hover:text-zinc-700"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Action buttons */}
      {!isDeclining && (
        <div className="flex items-center gap-2 px-4 py-3 border-t border-zinc-100 bg-zinc-50">
          {isEditing ? (
            <>
              <button
                onClick={onApproveModified}
                disabled={reviewPending}
                className="flex items-center gap-1.5 text-xs font-medium bg-blue-600 text-white px-3 py-2 rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
              >
                <CheckCircle className="w-3.5 h-3.5" />
                Save & Approve
              </button>
              <button
                onClick={onCancelEdit}
                className="text-xs text-zinc-500 px-3 py-2 hover:text-zinc-700"
              >
                Cancel
              </button>
            </>
          ) : draftStatus === "pending" ? (
            <>
              <button
                onClick={onApprove}
                disabled={reviewPending}
                className="flex items-center gap-1.5 text-xs font-medium bg-green-600 text-white px-3 py-2 rounded-lg hover:bg-green-700 transition-colors disabled:opacity-50"
              >
                <CheckCircle className="w-3.5 h-3.5" />
                Approve
              </button>
              <button
                onClick={onStartEdit}
                className="flex items-center gap-1.5 text-xs font-medium border border-zinc-200 bg-white text-zinc-600 px-3 py-2 rounded-lg hover:bg-zinc-50 transition-colors"
              >
                <Edit3 className="w-3.5 h-3.5" />
                Edit
              </button>
              <button
                onClick={onStartDecline}
                className="flex items-center gap-1.5 text-xs font-medium text-red-500 px-3 py-2 rounded-lg hover:bg-red-50 transition-colors ml-auto"
              >
                <XCircle className="w-3.5 h-3.5" />
                Decline
              </button>
            </>
          ) : draftStatus === "approved" ? (
            <>
              <span className="flex items-center gap-1.5 text-xs text-green-700 font-medium">
                <CheckCircle className="w-3.5 h-3.5" />
                Approved
              </span>
              <button
                onClick={onStartEdit}
                className="flex items-center gap-1.5 text-xs font-medium border border-zinc-200 bg-white text-zinc-600 px-3 py-2 rounded-lg hover:bg-zinc-50 transition-colors ml-auto"
              >
                <Edit3 className="w-3.5 h-3.5" />
                Edit & Re-approve
              </button>
              <button
                onClick={onStartDecline}
                disabled={reviewPending}
                className="flex items-center gap-1.5 text-xs font-medium text-red-500 px-3 py-2 rounded-lg hover:bg-red-50 transition-colors"
              >
                <XCircle className="w-3.5 h-3.5" />
                Decline instead
              </button>
            </>
          ) : (
            /* declined */
            <>
              <span className="flex items-center gap-1.5 text-xs text-red-600 font-medium">
                <XCircle className="w-3.5 h-3.5" />
                Declined
              </span>
              <button
                onClick={onApprove}
                disabled={reviewPending}
                className="flex items-center gap-1.5 text-xs font-medium bg-green-600 text-white px-3 py-2 rounded-lg hover:bg-green-700 transition-colors disabled:opacity-50 ml-auto"
              >
                <CheckCircle className="w-3.5 h-3.5" />
                Approve instead
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}


function InfoCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white border border-zinc-200 rounded-lg p-4">
      <h4 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-3">{title}</h4>
      {children}
    </div>
  );
}


function ForecastPill({ cat }: { cat: string }) {
  const style: Record<string, string> = {
    "Commit":    "bg-green-100 text-green-700",
    "Best Case": "bg-blue-100 text-blue-700",
    "Pipeline":  "bg-zinc-100 text-zinc-600",
    "Omit":      "bg-red-100 text-red-700",
  };
  return (
    <span className={cn("text-xs font-medium px-2.5 py-1 rounded-full", style[cat] ?? "bg-zinc-100 text-zinc-600")}>
      {cat}
    </span>
  );
}


function NoPovState({ lastRun, onRunAgents, running }: { lastRun: string; onRunAgents: () => void; running: boolean }) {
  return (
    <div className="bg-white border border-zinc-200 rounded-lg p-8 text-center">
      <div className="w-10 h-10 bg-zinc-100 rounded-full mx-auto mb-3 flex items-center justify-center">
        <Zap className="w-5 h-5 text-zinc-400" />
      </div>
      <p className="text-sm font-medium text-zinc-700">No data yet</p>
      <p className="text-xs text-zinc-400 mt-1 mb-5">
        Last agent run: {lastRun}. Click Run Agents in the top bar to populate AI Analysis.
      </p>
      <button
        onClick={onRunAgents}
        disabled={running}
        className="inline-flex items-center gap-2 text-xs font-medium bg-zinc-900 text-white px-4 py-2 rounded-md hover:bg-zinc-800 transition-colors disabled:opacity-50"
      >
        <RefreshCw className={cn("w-3.5 h-3.5", running && "animate-spin")} />
        {running ? "Queuing..." : "Run Agents Now"}
      </button>
    </div>
  );
}


// MarkdownContent moved to components/markdown-content.tsx — shared by every
// surface that renders draft content (inbox detail, war room, deal book).
