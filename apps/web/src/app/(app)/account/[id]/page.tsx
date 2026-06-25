"use client";

import React, { use, useState, useEffect, useRef, useCallback } from "react";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  accountsApi, agentApi, analyticsApi, draftsApi, signalsApi,
  workspaceApi, timelineApi, documentsApi, streamChat, devAuthHeaders,
  DOC_TYPE_LABELS,
  type ActivitySummary, type TimelineEvent, type Signal, type Draft,
  type NextAction, type AccountNote, type SmartFieldSuggestion,
  type Transcript,
  type TimelineAction, type GeneratedDocument, type DocType,
} from "@/lib/api";
import { SmartFieldsPanel } from "@/components/account/smart-fields-panel";
import { MarkdownContent } from "@/components/markdown-content";
import { cn, signalLabel, formatDate, draftTypeLabel, urgencyLevel } from "@/lib/utils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { formatDistanceToNow, format } from "date-fns";
import {
  ArrowLeft, Zap, AlertTriangle, Clock, TrendingUp, TrendingDown, Minus,
  CheckCircle, XCircle, Send, MessageSquare, BarChart3, Activity,
  ChevronDown, ChevronUp, ExternalLink, RefreshCw, User, Bot,
  StickyNote, Sparkles, Shield, Target, HelpCircle, GraduationCap,
  CalendarDays, FileText, Download, X, MessagesSquare, Phone,
} from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: Array<{ text: string; source: string }>;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const URGENCY_BAR: Record<string, string> = {
  critical: "bg-red-500", high: "bg-orange-400",
  medium: "bg-yellow-400", low: "bg-green-400",
};

const EVENT_TYPE_STYLE: Record<string, { label: string; color: string; dot: string }> = {
  signal:         { label: "Signal",     color: "text-orange-600", dot: "bg-orange-400" },
  interaction:    { label: "Interaction",color: "text-blue-600",   dot: "bg-blue-400"   },
  draft_created:  { label: "Draft",      color: "text-purple-600", dot: "bg-purple-400" },
  draft_reviewed: { label: "Reviewed",   color: "text-green-600",  dot: "bg-green-400"  },
  crm_change:     { label: "CRM Update", color: "text-gray-600",   dot: "bg-gray-400"   },
};

const MEDDPICC_LABELS: Record<string, string> = {
  metrics: "Metrics", economic_buyer: "Economic Buyer",
  decision_criteria: "Decision Criteria", decision_process: "Decision Process",
  implicate_pain: "Implicate Pain", champion: "Champion",
  competition: "Competition", paper_process: "Paper Process",
};

const RISK_LABELS: Record<string, string> = {
  champion: "Champion", economic: "Economic Buyer",
  timeline: "Timeline", competition: "Competition", stakeholder: "Stakeholder",
};

const DECLINE_CATEGORIES = [
  { value: "wrong_tone",    label: "Wrong tone" },
  { value: "wrong_timing",  label: "Wrong timing" },
  { value: "already_sent",  label: "Already sent" },
  { value: "wrong_content", label: "Wrong content" },
  { value: "not_relevant",  label: "Not relevant" },
  { value: "other",         label: "Other" },
];

// ── Helpers ───────────────────────────────────────────────────────────────────


function fmtCurrency(n: number | null) {
  if (!n) return "-";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n);
}

function fmtPct(n: number | null | undefined) {
  if (n == null) return "—";
  return `${Math.round(n * 100)}%`;
}

// ── Health badge ──────────────────────────────────────────────────────────────

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

// ── Deal story ────────────────────────────────────────────────────────────────

function DealStory({ text }: { text: string }) {
  const [expanded, setExpanded] = React.useState(false);
  const LIMIT = 180;
  const isLong = text.length > LIMIT;
  return (
    <div>
      <p className="text-sm text-gray-700 leading-relaxed">
        {isLong && !expanded ? text.slice(0, LIMIT).trimEnd() + "…" : text}
      </p>
      {isLong && (
        <button onClick={() => setExpanded(v => !v)}
          className="text-xs text-brand-600 hover:text-brand-700 mt-1 font-medium">
          {expanded ? "Show less" : "Read more"}
        </button>
      )}
    </div>
  );
}

// ── Signal row ────────────────────────────────────────────────────────────────

function SignalRow({ signal, onAck }: { signal: Signal; onAck: (id: string) => void }) {
  const [expanded, setExpanded] = React.useState(false);
  const typeLabel = signalLabel(signal.type);
  const urgency = signal.urgency ?? urgencyLevel(signal.urgency_score);
  const dotColor = { critical: "bg-red-500", high: "bg-orange-400", medium: "bg-yellow-400", low: "bg-gray-300" }[urgency] ?? "bg-gray-300";

  return (
    <div className="group" onClick={() => setExpanded(v => !v)}>
      <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-gray-100 cursor-pointer transition-colors">
        <span className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0 mt-px", dotColor)} />
        <span className="text-xs text-gray-700 flex-1 truncate" title={typeLabel}>{typeLabel}</span>
        <span className="text-[10px] text-gray-400 whitespace-nowrap">
          {signal.created_at ? formatDistanceToNow(new Date(signal.created_at), { addSuffix: true }) : ""}
        </span>
        {!signal.acknowledged && (
          <button onClick={e => { e.stopPropagation(); onAck(signal.id); }}
            className="opacity-0 group-hover:opacity-60 hover:!opacity-100 transition-opacity flex-shrink-0">
            <CheckCircle className="w-3 h-3 text-gray-500" />
          </button>
        )}
      </div>
      {expanded && signal.detail && (
        <p className="text-xs text-gray-500 leading-relaxed px-5 pb-1.5">{signal.detail}</p>
      )}
    </div>
  );
}

/**
 * One row per signal TYPE with a ×N chip — repeated nightly runs re-raise the
 * same signal, and a wall of identical "Champion Dark" rows buries real variety.
 */
function SignalTypeGroupRow({ signals, onAck }: { signals: Signal[]; onAck: (id: string) => void }) {
  const [expanded, setExpanded] = React.useState(false);
  const sorted = [...signals].sort((a, b) =>
    (b.created_at ?? "").localeCompare(a.created_at ?? "")
  );
  const latest = sorted[0];
  const typeLabel = signalLabel(latest.type);
  const worst = sorted.reduce((acc, s) => {
    const u = s.urgency ?? urgencyLevel(s.urgency_score);
    const rank = { critical: 3, high: 2, medium: 1, low: 0 }[u] ?? 0;
    return rank > acc.rank ? { rank, u } : acc;
  }, { rank: -1, u: "low" });
  const dotColor = { critical: "bg-red-500", high: "bg-orange-400", medium: "bg-yellow-400", low: "bg-gray-300" }[worst.u] ?? "bg-gray-300";

  return (
    <div>
      <div
        onClick={() => setExpanded(v => !v)}
        className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-gray-100 cursor-pointer transition-colors"
      >
        <span className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0 mt-px", dotColor)} />
        <span className="text-xs text-gray-700 truncate" title={typeLabel}>{typeLabel}</span>
        <span className="text-[10px] font-semibold text-gray-500 bg-gray-100 rounded-full px-1.5 py-px flex-shrink-0">
          ×{sorted.length}
        </span>
        <span className="text-[10px] text-gray-400 whitespace-nowrap ml-auto">
          {latest.created_at ? formatDistanceToNow(new Date(latest.created_at), { addSuffix: true }) : ""}
        </span>
        {expanded ? <ChevronUp className="w-3 h-3 text-gray-400 flex-shrink-0" /> : <ChevronDown className="w-3 h-3 text-gray-400 flex-shrink-0" />}
      </div>
      {expanded && (
        <div className="ml-2 border-l border-gray-100 pl-1">
          {sorted.map(s => <SignalRow key={s.id} signal={s} onAck={onAck} />)}
        </div>
      )}
    </div>
  );
}

// ── Signal group ──────────────────────────────────────────────────────────────

function SignalGroup({ label, dotColor, count, signals, defaultExpanded, onAck }: {
  label: string; dotColor: string; count: number;
  signals: Signal[]; defaultExpanded: boolean;
  onAck: (id: string) => void;
}) {
  const [open, setOpen] = useState(defaultExpanded);
  if (count === 0) return null;
  return (
    <div>
      <button onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-2 py-1.5 text-left">
        <span className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0", dotColor)} />
        <span className="text-xs font-medium text-gray-600 flex-1">{label}</span>
        <span className="text-xs tabular-nums text-gray-400 font-medium">{count}</span>
        {open ? <ChevronUp className="w-3 h-3 text-gray-400" /> : <ChevronDown className="w-3 h-3 text-gray-400" />}
      </button>
      {open && (
        <div className="ml-3 space-y-0.5">
          {(() => {
            // Collapse identical signal types into one row with a ×N chip,
            // preserving first-seen order of types.
            const byType = new Map<string, Signal[]>();
            for (const s of signals) {
              const list = byType.get(s.type) ?? [];
              list.push(s);
              byType.set(s.type, list);
            }
            return [...byType.entries()].map(([type, group]) =>
              group.length === 1
                ? <SignalRow key={group[0].id} signal={group[0]} onAck={onAck} />
                : <SignalTypeGroupRow key={type} signals={group} onAck={onAck} />
            );
          })()}
        </div>
      )}
    </div>
  );
}

// ── Transcript card (History tab) ─────────────────────────────────────────────

const OWNER_CHIP: Record<string, string> = {
  us:      "bg-indigo-50 text-indigo-700 border-indigo-200",
  buyer:   "bg-emerald-50 text-emerald-700 border-emerald-200",
  unknown: "bg-gray-50 text-gray-500 border-gray-200",
};

function TranscriptCard({ transcript: t }: { transcript: Transcript }) {
  const [open, setOpen] = useState(false);
  const speakers = Object.entries(t.speaker_stats ?? {})
    .sort(([, a], [, b]) => (b.talk_time_pct ?? 0) - (a.talk_time_pct ?? 0))
    .slice(0, 5);

  return (
    <div className="bg-white rounded-2xl border border-gray-200 p-4">
      <button onClick={() => setOpen(o => !o)} className="w-full text-left">
        <div className="flex items-start gap-2">
          <Phone className="w-3.5 h-3.5 text-brand-600 mt-0.5 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-gray-800 truncate">{t.title}</p>
            <p className="text-xs text-gray-400">
              {t.date ? format(new Date(t.date), "MMM d, yyyy") : ""}
              {t.duration_minutes ? ` · ${t.duration_minutes}min` : ""}
              {t.attendees?.length ? ` · ${t.attendees.length} attendees` : ""}
              {t.talk_ratio_rep != null ? ` · rep talked ${Math.round(t.talk_ratio_rep * 100)}%` : ""}
            </p>
          </div>
          {open ? <ChevronUp className="w-3.5 h-3.5 text-gray-400 flex-shrink-0 mt-1" /> : <ChevronDown className="w-3.5 h-3.5 text-gray-400 flex-shrink-0 mt-1" />}
        </div>
        {!open && t.summary && (
          <p className="text-xs text-gray-500 leading-relaxed pl-5 mt-1 line-clamp-2">{t.summary}</p>
        )}
      </button>

      {open && (
        <div className="pl-5 mt-2 space-y-3">
          {t.summary && <p className="text-xs text-gray-600 leading-relaxed">{t.summary}</p>}

          {/* Talk-time bars */}
          {speakers.length > 0 && (
            <div>
              <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1.5">Talk time</p>
              <div className="space-y-1">
                {speakers.map(([name, s]) => (
                  <div key={name} className="flex items-center gap-2">
                    <span className="text-[11px] text-gray-600 w-28 truncate flex-shrink-0">{name}</span>
                    <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                      <div className="h-full bg-brand-400 rounded-full" style={{ width: `${Math.min(100, s.talk_time_pct ?? 0)}%` }} />
                    </div>
                    <span className="text-[10px] text-gray-400 w-9 text-right flex-shrink-0">{Math.round(s.talk_time_pct ?? 0)}%</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Action items with owner chips */}
          {(t.commitments?.length ? t.commitments : (t.action_items ?? []).map(a => ({ text: a, owner: "unknown" as const, owner_name: null }))).length > 0 && (
            <div>
              <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1.5">Action items</p>
              <div className="space-y-1">
                {(t.commitments?.length ? t.commitments : (t.action_items ?? []).map(a => ({ text: a, owner: "unknown" as const, owner_name: null }))).map((c, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <span className={cn("text-[9px] font-semibold px-1.5 py-0.5 rounded-full border flex-shrink-0 mt-0.5", OWNER_CHIP[c.owner] ?? OWNER_CHIP.unknown)}>
                      {c.owner === "us" ? "Us" : c.owner === "buyer" ? "Buyer" : "—"}
                    </span>
                    <p className="text-xs text-gray-600 leading-snug">{c.text}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Buyer questions */}
          {(t.buyer_questions ?? []).length > 0 && (
            <div>
              <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1.5">Buyer questions</p>
              {(t.buyer_questions ?? []).map((q, i) => (
                <p key={i} className="text-xs text-gray-600 leading-snug mb-0.5">
                  <span className="font-semibold">{q.speaker}:</span> “{q.text}”
                </p>
              ))}
            </div>
          )}

          {t.transcript_url && (
            <a
              href={t.transcript_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700"
            >
              Open in Fireflies <ExternalLink className="w-3 h-3" />
            </a>
          )}
        </div>
      )}
    </div>
  );
}

// ── Timeline row ──────────────────────────────────────────────────────────────

function TimelineRow({ event }: { event: TimelineEvent }) {
  const style = EVENT_TYPE_STYLE[event.event_type] ?? { label: event.event_type, color: "text-gray-500", dot: "bg-gray-300" };
  const ts = event.occurred_at ? format(new Date(event.occurred_at), "MMM d, h:mm a") : "";
  return (
    <div className="flex items-start gap-3 py-2.5">
      <div className="flex flex-col items-center">
        <div className={cn("w-2 h-2 rounded-full mt-1 flex-shrink-0", style.dot)} />
        <div className="w-px flex-1 bg-gray-100 mt-1" />
      </div>
      <div className="flex-1 min-w-0 pb-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={cn("text-xs font-semibold uppercase tracking-wide", style.color)}>{style.label}</span>
          {event.subtype && <span className="text-xs text-gray-500">{event.subtype}</span>}
          <span className="text-xs text-gray-400 ml-auto">{ts}</span>
        </div>
        {event.description && (
          <p className="text-sm text-gray-700 mt-0.5 line-clamp-2">{event.description}</p>
        )}
      </div>
    </div>
  );
}

// ── Timeline action card ──────────────────────────────────────────────────────

const ACTION_TYPE_ICON: Record<string, React.FC<{ className?: string }>> = {
  email:             ({ className }) => <MessageSquare className={className} />,
  call_prep:         ({ className }) => <Activity className={className} />,
  meeting_prep:      ({ className }) => <Clock className={className} />,
  champion_checkin:  ({ className }) => <MessageSquare className={className} />,
  stakeholder_intro: ({ className }) => <User className={className} />,
  close_push:        ({ className }) => <TrendingUp className={className} />,
  escalation:        ({ className }) => <AlertTriangle className={className} />,
  proposal_follow:   ({ className }) => <Target className={className} />,
};

function TimelineActionCard({
  action, onPatch,
}: {
  action: TimelineAction;
  onPatch: (args: { actionId: string; body: Parameters<typeof timelineApi.patch>[1] }) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const Icon = ACTION_TYPE_ICON[action.action_type] ?? Zap;
  const content = action.prepared_content as { type?: string; content?: string; subject_line?: string } | null;
  const isUrgent = action.status === "overdue" || action.status === "today";

  return (
    <div className={cn(
      "bg-white rounded-xl border overflow-hidden transition-all",
      action.status === "overdue" ? "border-l-4 border-l-red-400 border-gray-200" :
      action.status === "today" ? "border-l-4 border-l-brand-500 border-gray-200" :
      "border-gray-200"
    )}>
      <button onClick={() => setExpanded(v => !v)}
        className="w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-gray-50 transition-colors">
        <div className={cn("w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5",
          isUrgent ? "bg-brand-50" : "bg-gray-50")}>
          <Icon className={cn("w-3.5 h-3.5", isUrgent ? "text-brand-600" : "text-gray-400")} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            {action.status === "overdue" && (
              <span className="text-[10px] font-bold text-red-600 bg-red-50 px-1.5 py-0.5 rounded-full">Overdue</span>
            )}
            {action.status === "today" && (
              <span className="text-[10px] font-bold text-brand-700 bg-brand-50 px-1.5 py-0.5 rounded-full">Today</span>
            )}
            <span className="text-[10px] text-gray-400 ml-auto">{formatDate(action.due_date)}</span>
          </div>
          <p className="text-sm font-medium text-gray-900">{action.title}</p>
          {action.reasoning && !expanded && (
            <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{action.reasoning}</p>
          )}
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-gray-300 flex-shrink-0 mt-1" /> : <ChevronDown className="w-4 h-4 text-gray-300 flex-shrink-0 mt-1" />}
      </button>

      {expanded && (
        <div className="border-t border-gray-100 bg-gray-50 px-4 py-3 space-y-3">
          {action.reasoning && <p className="text-xs text-gray-600 leading-relaxed">{action.reasoning}</p>}
          {content?.type === "draft" && content.content && (
            <div className="bg-white border border-gray-200 rounded-lg p-3">
              {content.subject_line && <p className="text-xs font-semibold text-gray-500 mb-1.5">Subject: {content.subject_line}</p>}
              <div className="text-xs line-clamp-5"><MarkdownContent content={content.content} /></div>
            </div>
          )}
          <div className="flex items-center gap-2">
            <button onClick={() => onPatch({ actionId: action.id, body: { action: "complete" } })}
              className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors">
              <CheckCircle className="w-3.5 h-3.5" /> Done
            </button>
            <button onClick={() => onPatch({ actionId: action.id, body: { action: "skip" } })}
              className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 bg-white border border-gray-200 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors">
              Defer
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Draft card ────────────────────────────────────────────────────────────────

function DraftCard({ draft, onApprove, onDecline, outlookConnected }: {
  draft: Draft;
  onApprove: (id: string) => void;
  onDecline: (id: string, category: string, notes?: string) => void;
  outlookConnected?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [declining, setDeclining] = useState(false);
  const [declineCategory, setDeclineCategory] = useState("");
  const [declineNotes, setDeclineNotes] = useState("");
  const [feedbackSaved, setFeedbackSaved] = useState(false);
  const [sendingOpen, setSendingOpen] = useState(false);
  const [sendTo, setSendTo] = useState((draft as any).target_contact_email ?? "");
  const [sendSubject, setSendSubject] = useState((draft as any).subject_line ?? `Re: ${(draft as any).target_contact ?? "Follow-up"}`);
  const [sending, setSending] = useState(false);
  const [sentConfirm, setSentConfirm] = useState(false);

  const statusColors: Record<string, string> = {
    pending: "bg-amber-100 text-amber-700",
    approved: "bg-green-100 text-green-700",
    approved_modified: "bg-teal-100 text-teal-700",
    declined: "bg-red-100 text-red-600",
  };

  const handleDeclineSubmit = () => {
    if (!declineCategory) return;
    onDecline(draft.id, declineCategory, declineNotes.trim() || undefined);
    setFeedbackSaved(true);
    setDeclining(false);
  };

  const handleSendViaOutlook = async () => {
    if (!sendTo.trim() || sending) return;
    setSending(true);
    try {
      await draftsApi.sendViaOutlook(draft.id, { to: sendTo.trim(), subject: sendSubject });
      setSentConfirm(true);
      setSendingOpen(false);
    } catch (e: any) {
      alert((e as Error)?.message ?? "Outlook not connected. Go to Settings.");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <button onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors text-left">
        <span className={cn("text-xs font-medium px-2 py-0.5 rounded-full flex-shrink-0",
          statusColors[draft.status] ?? "bg-gray-100 text-gray-600")}>
          {draft.status.replace("_", " ")}
        </span>
        <span className="text-sm font-medium text-gray-800 flex-1">{draftTypeLabel(draft.type)}</span>
        {(draft as any).target_contact && (
          <span className="text-xs text-gray-400 truncate max-w-[100px]">{(draft as any).target_contact}</span>
        )}
        {draft.created_at && (
          <span className="text-xs text-gray-400">{formatDistanceToNow(new Date(draft.created_at), { addSuffix: true })}</span>
        )}
        {expanded ? <ChevronUp className="w-4 h-4 text-gray-300" /> : <ChevronDown className="w-4 h-4 text-gray-300" />}
      </button>

      {expanded && (
        <div className="border-t border-gray-100 px-4 py-3 bg-gray-50 space-y-3">
          {(draft as any).subject_line && (
            <p className="text-xs font-semibold text-gray-500">Subject: {(draft as any).subject_line}</p>
          )}
          <div>
            <MarkdownContent content={draft.content ?? ""} />
          </div>

          {draft.status === "pending" && !declining && !feedbackSaved && !sentConfirm && (
            <div className="flex items-center gap-2 flex-wrap">
              {outlookConnected && ["email_followup", "champion_reengagement", "executive_alignment", "expansion_pitch"].includes(draft.type) ? (
                <button onClick={() => setSendingOpen(true)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-brand-600 text-white text-xs font-medium rounded-lg hover:bg-brand-700 transition-colors">
                  <Send className="w-3.5 h-3.5" /> Save to Outlook Drafts
                </button>
              ) : (
                <button onClick={() => onApprove(draft.id)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 text-white text-xs font-medium rounded-lg hover:bg-green-700 transition-colors">
                  <CheckCircle className="w-3.5 h-3.5" /> Approve
                </button>
              )}
              <button onClick={() => setDeclining(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-gray-200 text-gray-600 text-xs font-medium rounded-lg hover:bg-gray-50 transition-colors">
                <XCircle className="w-3.5 h-3.5" /> Decline
              </button>
            </div>
          )}

          {sendingOpen && (
            <div className="border border-brand-200 rounded-lg bg-brand-50 p-3 space-y-2">
              <p className="text-xs font-semibold text-brand-800">Save to Outlook Drafts</p>
              <p className="text-xs text-brand-600/70">You review and send from Outlook.</p>
              <input type="email" value={sendTo} onChange={e => setSendTo(e.target.value)}
                placeholder="To: recipient@company.com"
                className="w-full text-xs border border-brand-200 rounded px-2.5 py-1.5 bg-white focus:outline-none focus:border-brand-400" />
              <input type="text" value={sendSubject} onChange={e => setSendSubject(e.target.value)}
                placeholder="Subject"
                className="w-full text-xs border border-brand-200 rounded px-2.5 py-1.5 bg-white focus:outline-none focus:border-brand-400" />
              <div className="flex gap-2">
                <button onClick={handleSendViaOutlook} disabled={!sendTo.trim() || sending}
                  className="px-3 py-1.5 bg-brand-600 text-white text-xs font-medium rounded-lg hover:bg-brand-700 disabled:opacity-40 transition-colors">
                  {sending ? "Saving..." : "Save to Drafts"}
                </button>
                <button onClick={() => setSendingOpen(false)} className="text-xs text-gray-500">Cancel</button>
              </div>
            </div>
          )}

          {sentConfirm && (
            <div className="flex items-center gap-1.5 text-xs text-brand-700 bg-brand-50 border border-brand-200 rounded-lg px-3 py-2">
              <CheckCircle className="w-3.5 h-3.5" /> Saved to Outlook Drafts
            </div>
          )}

          {declining && (
            <div className="border border-red-200 rounded-lg bg-red-50 p-3 space-y-2">
              <p className="text-xs font-semibold text-red-700">Why decline?</p>
              <div className="flex flex-wrap gap-1.5">
                {DECLINE_CATEGORIES.map(cat => (
                  <button key={cat.value}
                    onClick={() => setDeclineCategory(cat.value)}
                    className={cn("text-xs px-2.5 py-1 rounded-full border transition-colors",
                      declineCategory === cat.value
                        ? "bg-red-600 text-white border-red-600"
                        : "bg-white text-gray-600 border-gray-200 hover:border-red-300")}>
                    {cat.label}
                  </button>
                ))}
              </div>
              <input type="text" value={declineNotes} onChange={e => setDeclineNotes(e.target.value)}
                placeholder="Optional notes"
                className="w-full text-xs border border-red-200 rounded px-2.5 py-1.5 bg-white focus:outline-none" />
              <div className="flex gap-2">
                <button onClick={handleDeclineSubmit} disabled={!declineCategory}
                  className="px-3 py-1.5 bg-red-600 text-white text-xs font-medium rounded-lg disabled:opacity-40">
                  Submit
                </button>
                <button onClick={() => { setDeclining(false); setDeclineCategory(""); }}
                  className="text-xs text-gray-500">Cancel</button>
              </div>
            </div>
          )}

          {feedbackSaved && (
            <div className="flex items-center gap-1.5 text-xs text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2">
              <CheckCircle className="w-3.5 h-3.5" /> Feedback saved
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Chat panel (slide-over) ───────────────────────────────────────────────────

function ChatPanel({ accountId, accountName, contextSeed, onClose }: {
  accountId: string;
  accountName: string;
  contextSeed?: string;
  onClose: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [threadId, setThreadId] = useState<string | undefined>();
  const [streaming, setStreaming] = useState(false);
  // Ref, not state: Strict Mode double-fires this effect before a state
  // update re-renders, which posted the seed question twice
  const seededRef = useRef(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (seededRef.current) return;
    seededRef.current = true;
    const seed = contextSeed ?? `I'm in the Deal Room for ${accountName}. What's the single most important thing to do today to advance this deal?`;
    handleSend(seed, true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

  const handleSend = useCallback(async (text: string, isAuto = false) => {
    const msg = text.trim();
    if (!msg || streaming) return;
    setMessages(prev => [...prev, { role: "user", content: msg }]);
    if (!isAuto) setInput("");
    setStreaming(true);
    let assistantText = "";
    const citations: ChatMessage["citations"] = [];
    let newThreadId = threadId;
    setMessages(prev => [...prev, { role: "assistant", content: "" }]);
    try {
      for await (const event of streamChat({ message: msg, account_id: accountId, thread_id: newThreadId, use_perplexity: false })) {
        if (event.type === "thread") { newThreadId = event.thread_id; setThreadId(newThreadId); }
        else if (event.type === "text") {
          assistantText += event.delta ?? event.content ?? "";
          setMessages(prev => [...prev.slice(0, -1), { role: "assistant", content: assistantText, citations }]);
        } else if (event.type === "citations" && Array.isArray(event.citations)) {
          citations.push(...event.citations);
          setMessages(prev => [...prev.slice(0, -1), { role: "assistant", content: assistantText, citations: [...citations] }]);
        }
      }
    } catch {
      setMessages(prev => [...prev.slice(0, -1), { role: "assistant", content: "Could not reach the agent. Please try again." }]);
    }
    setStreaming(false);
  }, [accountId, threadId, streaming]);

  return (
    <>
      {/* Overlay */}
      <div className="fixed inset-0 bg-black/20 z-40" onClick={onClose} />
      {/* Panel */}
      <div className="fixed right-0 top-0 bottom-0 w-[420px] bg-white shadow-2xl z-50 flex flex-col border-l border-gray-200">
        {/* Header */}
        <div className="px-5 py-4 border-b border-gray-100 flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-brand-100 flex items-center justify-center">
            <Bot className="w-4 h-4 text-brand-600" />
          </div>
          <div>
            <p className="text-sm font-semibold text-gray-900">AI Agent</p>
            <p className="text-xs text-gray-400">{accountName}</p>
          </div>
          {streaming && <span className="text-xs text-brand-600 ml-auto animate-pulse">Thinking…</span>}
          <button onClick={onClose} className="ml-auto text-gray-400 hover:text-gray-600 transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {messages.map((msg, i) => (
            <div key={i} className={cn("flex gap-2.5", msg.role === "user" ? "justify-end" : "justify-start")}>
              {msg.role === "assistant" && (
                <div className="w-6 h-6 rounded-full bg-brand-100 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Bot className="w-3 h-3 text-brand-600" />
                </div>
              )}
              <div className={cn(
                "max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed",
                msg.role === "user" ? "bg-brand-600 text-white rounded-tr-sm" : "bg-gray-100 text-gray-800 rounded-tl-sm"
              )}>
                {msg.role === "user" ? msg.content : msg.content ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
                    h1: ({ children }) => <h1 className="text-sm font-bold mt-2 mb-1 first:mt-0">{children}</h1>,
                    h2: ({ children }) => <h2 className="text-sm font-bold mt-2 mb-1 first:mt-0">{children}</h2>,
                    p: ({ children }) => <p className="mb-1.5 last:mb-0 text-xs">{children}</p>,
                    ul: ({ children }) => <ul className="mb-1.5 pl-3.5 space-y-0.5 list-disc text-xs">{children}</ul>,
                    ol: ({ children }) => <ol className="mb-1.5 pl-3.5 space-y-0.5 list-decimal text-xs">{children}</ol>,
                    li: ({ children }) => <li>{children}</li>,
                    strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                    code: ({ children, className }) => className ? (
                      <pre className="bg-white/50 rounded px-2 py-1 my-1 text-xs font-mono overflow-x-auto"><code>{children}</code></pre>
                    ) : <code className="bg-white/70 rounded px-1 text-xs font-mono">{children}</code>,
                  }}>{msg.content}</ReactMarkdown>
                ) : (streaming && i === messages.length - 1 ? (
                  <span className="inline-flex gap-0.5">
                    {[0, 150, 300].map(d => <span key={d} className="w-1 h-1 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: `${d}ms` }} />)}
                  </span>
                ) : null)}
                {msg.citations && msg.citations.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2 pt-2 border-t border-gray-200">
                    {msg.citations.map((c, ci) => (
                      <span key={ci} title={c.text || undefined} className="text-xs bg-white border border-gray-200 text-gray-500 px-1.5 py-0.5 rounded cursor-help">{c.source}</span>
                    ))}
                  </div>
                )}
              </div>
              {msg.role === "user" && (
                <div className="w-6 h-6 rounded-full bg-gray-200 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <User className="w-3 h-3 text-gray-600" />
                </div>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Quick prompts */}
        {messages.length <= 2 && !streaming && (
          <div className="px-5 pb-2 flex flex-wrap gap-1.5">
            {["What's blocking this deal?", "Draft a follow-up", "Key stakeholders?"].map(p => (
              <button key={p} onClick={() => handleSend(p)}
                className="text-xs text-brand-600 border border-brand-200 px-2.5 py-1 rounded-full hover:bg-brand-50 transition-colors">
                {p}
              </button>
            ))}
          </div>
        )}

        {/* Input */}
        <div className="px-5 pb-5 pt-2 border-t border-gray-100">
          <div className="flex items-end gap-2 bg-gray-50 rounded-xl border border-gray-200 px-3 py-2.5 focus-within:border-brand-300 transition-colors">
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(input); } }}
              placeholder="Ask about this deal…"
              className="flex-1 text-sm bg-transparent resize-none focus:outline-none max-h-28"
              rows={1}
            />
            <button onClick={() => handleSend(input)} disabled={!input.trim() || streaming}
              className="w-8 h-8 bg-brand-600 rounded-lg flex items-center justify-center hover:bg-brand-700 disabled:opacity-40 transition-colors flex-shrink-0">
              <Send className="w-3.5 h-3.5 text-white" />
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function WarRoomPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const router = useRouter();

  // Tab state
  const rawCenter = searchParams.get("center");
  const activeCenter: "act" | "intel" | "history" =
    (["act", "intel", "history"] as const).find(c => c === rawCenter) ?? "act";
  const setActiveCenter = (c: "act" | "intel" | "history") => {
    const p = new URLSearchParams(searchParams.toString());
    p.set("center", c);
    router.replace(`/account/${id}?${p.toString()}`, { scroll: false });
  };

  // UI state
  const [chatOpen, setChatOpen] = useState(false);
  const [generateOpen, setGenerateOpen] = useState(false);
  const [generatingDoc, setGeneratingDoc] = useState<DocType | null>(null);
  const [generateToast, setGenerateToast] = useState<string | null>(null);
  const [briefOpen, setBriefOpen] = useState(false);
  const [briefFetching, setBriefFetching] = useState(false);
  const [briefData, setBriefData] = useState<null | {
    brief: string;
    top_signals: Array<{ type: string; urgency: string; detail: string }>;
    next_actions: Array<{ action: string; reason: string; urgency_score: number }>;
    stakeholders: Array<{ name: string; title?: string; role?: string; sentiment?: string }>;
  }>(null);
  const [povOverrideOpen, setPovOverrideOpen] = useState(false);
  const [overrideCategory, setOverrideCategory] = useState("");
  const [overrideReason, setOverrideReason] = useState("");
  const [winLossOpen, setWinLossOpen] = useState(false);
  const [winLossOutcome, setWinLossOutcome] = useState<"won" | "lost" | null>(null);
  const [winLossReason, setWinLossReason] = useState("");
  const [winLossCompetitor, setWinLossCompetitor] = useState("");
  const [winLossNotes, setWinLossNotes] = useState("");
  const [noteInput, setNoteInput] = useState("");
  const [savingNote, setSavingNote] = useState(false);
  const [nsEditing, setNsEditing] = useState(false);
  const [nsText, setNsText] = useState("");
  const [nsDate, setNsDate] = useState("");
  const [nsSaving, setNsSaving] = useState(false);
  const [shareCopied, setShareCopied] = useState(false);
  const [calendarSyncing, setCalendarSyncing] = useState(false);
  const [calendarSynced, setCalendarSynced] = useState<{ meetings_found: number; matched: number } | null>(null);
  const [agentRunning, setAgentRunning] = useState(false);

  // SSE real-time updates
  // EventSource cannot set Authorization headers or send cookies cross-origin.
  // We fetch a short-lived stream token using the session cookie (credentials:"include"),
  // then pass it as ?t= in the EventSource URL. No JS cookie access needed.
  useEffect(() => {
    const base = process.env.NEXT_PUBLIC_API_URL || "";
    let es: EventSource | null = null;

    const connect = async () => {
      try {
        // Fetch the stream token via the normal authenticated fetch (cookie-based;
        // dev-bypass header in local dev)
        const res = await fetch(`${base}/v1/accounts/${id}/stream-token`, {
          credentials: "include",
          headers: devAuthHeaders(),
        });
        if (!res.ok) return; // auth failed — stream is best-effort
        const { data } = await res.json();
        es = new EventSource(`${base}/v1/accounts/${id}/stream?t=${encodeURIComponent(data.token)}`);
        es.onmessage = (e) => {
          try {
            const payload = JSON.parse(e.data);
            if (payload.type === "agent_run_complete") {
              queryClient.invalidateQueries({ queryKey: ["account", id] });
              queryClient.invalidateQueries({ queryKey: ["signals", id] });
              queryClient.invalidateQueries({ queryKey: ["drafts", id] });
            }
          } catch {}
        };
      } catch {
        // Stream is best-effort — failure is silent
      }
    };

    connect();
    return () => es?.close();
  }, [id, queryClient]);

  // Data fetching
  const { data: stateData, isLoading: stateLoading } = useQuery({
    queryKey: ["account", id, "state"],
    queryFn: () => accountsApi.getState(id),
    staleTime: 2 * 60 * 1000,
  });
  const { data: povData } = useQuery({
    queryKey: ["account", id, "pov"],
    queryFn: () => accountsApi.getPov(id),
    staleTime: 2 * 60 * 1000,
  });
  const { data: actionsData } = useQuery({
    queryKey: ["account", id, "next-actions"],
    queryFn: () => accountsApi.getNextActions(id),
    staleTime: 2 * 60 * 1000,
  });
  const { data: signalsData } = useQuery({
    queryKey: ["signals", id],
    queryFn: () => signalsApi.list({ account_id: id, limit: 30 }),
    staleTime: 60 * 1000,
    refetchInterval: 2 * 60 * 1000,
  });
  const { data: draftsData } = useQuery({
    queryKey: ["drafts", id],
    queryFn: () => draftsApi.list({ account_id: id, limit: 20 }),
    staleTime: 60 * 1000,
  });
  const { data: timelineData } = useQuery({
    queryKey: ["timeline", id],
    queryFn: () => analyticsApi.accountTimeline(id, 50),
    staleTime: 2 * 60 * 1000,
    enabled: activeCenter === "history",
  });
  const { data: notesData, refetch: refetchNotes } = useQuery({
    queryKey: ["notes", id],
    queryFn: () => accountsApi.getNotes(id),
    staleTime: 2 * 60 * 1000,
    enabled: activeCenter === "history",
  });
  // Powers History transcripts + the Intelligence Conversation card + the
  // left-rail "Last call" line — always fetch, not just on the History tab
  const { data: transcriptsData } = useQuery({
    queryKey: ["transcripts", id],
    queryFn: () => accountsApi.getTranscripts(id),
    staleTime: 5 * 60 * 1000,
  });
  const { data: smartFieldsData, isLoading: smartFieldsLoading } = useQuery({
    queryKey: ["smart-fields", id],
    queryFn: () => accountsApi.getSmartFields(id),
    staleTime: 5 * 60 * 1000,
    enabled: activeCenter === "intel",
  });
  const { data: workspaceData } = useQuery({
    queryKey: ["workspace"],
    queryFn: workspaceApi.get,
    staleTime: 5 * 60 * 1000,
  });
  const { data: actionPlanData, isLoading: actionPlanLoading } = useQuery({
    queryKey: ["action-plan", id],
    queryFn: () => timelineApi.getForAccount(id),
    staleTime: 60 * 1000,
    refetchInterval: 3 * 60 * 1000,
  });
  const { data: documentsData, refetch: refetchDocuments } = useQuery({
    queryKey: ["documents", id],
    queryFn: () => documentsApi.list(id),
    staleTime: 10 * 1000,
    refetchInterval: (query) => {
      const docs = query.state.data?.data ?? [];
      return docs.some((d: GeneratedDocument) => d.status === "generating") ? 3000 : false;
    },
  });

  // Derived data
  const state = stateData?.data as Record<string, unknown> | undefined;
  const pov = povData?.data;
  const signals = signalsData?.data ?? [];
  const drafts = draftsData?.data ?? [];
  const timeline = timelineData?.data ?? [];
  const notes = notesData?.data ?? [];
  const smartFieldSuggestions: SmartFieldSuggestion[] = smartFieldsData?.data?.suggestions ?? [];
  const activitySummary = state?.activity_summary as ActivitySummary | undefined;
  const outlookConnected = workspaceData?.data?.integrations?.outlook?.connected ?? false;

  const accountName = (state?.name as string) ?? "Account";
  const accountStage = state?.stage as string | undefined;
  const dealAmount = state?.deal_amount as number | null ?? null;

  const urgencyScore = (pov?.urgency_score ?? (state?.urgency_score as number | undefined)) ?? null;
  const healthScore = (pov?.health_score ?? (state?.health_score as number | undefined)) ?? null;
  const level = urgencyLevel(urgencyScore ?? 0);

  const povObj = pov?.pov as Record<string, unknown> | undefined;
  const momentum = povObj?.deal_momentum as string | undefined;
  const narrative = (povObj?.deal_narrative ?? povObj?.forecast_rationale ?? povObj?.summary) as string | undefined;
  const nextStepData = state?.next_step as { text?: string; due_date?: string; source?: string } | undefined;

  const forecastCat = povObj?.forecast_category as string | undefined;
  const crmCloseDate = pov?.crm_close_date ?? state?.close_date as string | undefined;
  const aiCloseDate = pov?.pov_close_date as string | undefined;

  const meddpiccData = (pov?.pov as any)?.meddpicc ?? {};
  const riskVectors = (pov?.pov as any)?.risk_vectors ?? {};
  const threeWhys = (pov?.pov as any)?.three_whys ?? {};
  const groundingConf = (pov?.grounding_confidence as number | undefined) ?? null;
  const povRisks: string[] = ((pov?.pov as any)?.risks ?? []).filter((r: unknown) => typeof r === "string" && r.trim());

  const pendingDrafts = drafts.filter(d => d.status === "pending");
  const overduePlanActions = actionPlanData?.data?.overdue ?? [];
  const upcomingPlanActions = actionPlanData?.data?.upcoming ?? [];
  const completedPlanActions = actionPlanData?.data?.history ?? [];
  const topAction = overduePlanActions[0] ?? upcomingPlanActions[0];

  // Signal groups
  const criticalSignals = signals.filter(s => (s.urgency ?? urgencyLevel(s.urgency_score)) === "critical" || (s.urgency ?? urgencyLevel(s.urgency_score)) === "high");
  const warningSignals  = signals.filter(s => (s.urgency ?? urgencyLevel(s.urgency_score)) === "medium");
  const activitySignals = signals.filter(s => (s.urgency ?? urgencyLevel(s.urgency_score)) === "low");

  // Mutations
  const patchActionMutation = useMutation({
    mutationFn: ({ actionId, body }: { actionId: string; body: Parameters<typeof timelineApi.patch>[1] }) =>
      timelineApi.patch(actionId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["action-plan", id] });
      queryClient.invalidateQueries({ queryKey: ["action-queue"] });
    },
  });

  const reviewMutation = useMutation({
    mutationFn: ({ draftId, action, training_category, reviewer_notes }: {
      draftId: string; action: "approved" | "declined";
      training_category?: string; reviewer_notes?: string;
    }) => draftsApi.review(draftId, { action, training_category, reviewer_notes }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["drafts", id] }),
  });

  const ackMutation = useMutation({
    mutationFn: signalsApi.acknowledge,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["signals", id] }),
  });

  const runAgentMutation = useMutation({
    mutationFn: () => accountsApi.batchRefresh([id]),
    onMutate: () => setAgentRunning(true),
    onSettled: () => {
      setTimeout(() => {
        setAgentRunning(false);
        queryClient.invalidateQueries({ queryKey: ["account", id] });
        queryClient.invalidateQueries({ queryKey: ["signals", id] });
        queryClient.invalidateQueries({ queryKey: ["drafts", id] });
      }, 15_000);
    },
  });

  const shareMutation = useMutation({
    mutationFn: () => accountsApi.createShareLink(id),
    onSuccess: (data) => {
      const url = (data as any)?.data?.share_url ?? window.location.href;
      navigator.clipboard.writeText(url).catch(() => {});
      setShareCopied(true);
      setTimeout(() => setShareCopied(false), 2000);
    },
  });

  const nsSetMutation = useMutation({
    mutationFn: () => accountsApi.setNextStep(id, { text: nsText, due_date: nsDate || undefined }),
    onSuccess: () => {
      setNsEditing(false);
      queryClient.invalidateQueries({ queryKey: ["account", id, "state"] });
    },
    onSettled: () => setNsSaving(false),
  });

  const winLossMutation = useMutation({
    mutationFn: () => accountsApi.captureWinLoss(id, {
      outcome: winLossOutcome!, reason: winLossReason,
      competitor: winLossCompetitor || undefined, notes: winLossNotes || undefined,
    }),
    onSuccess: () => {
      setWinLossOpen(false);
      queryClient.invalidateQueries({ queryKey: ["account", id, "state"] });
    },
  });

  const overridePovMutation = useMutation({
    mutationFn: () => accountsApi.overridePov(id, { override_category: overrideCategory, reason: overrideReason }),
    onSuccess: () => {
      setPovOverrideOpen(false);
      queryClient.invalidateQueries({ queryKey: ["account", id, "pov"] });
    },
  });

  const syncCalendarMutation = useMutation({
    mutationFn: () => workspaceApi.syncCalendar(),
    onMutate: () => setCalendarSyncing(true),
    onSuccess: (data) => setCalendarSynced(data.data),
    onSettled: () => setCalendarSyncing(false),
  });

  const handleSaveNote = async () => {
    if (!noteInput.trim() || savingNote) return;
    setSavingNote(true);
    try {
      await accountsApi.logFeedback(id, { interaction_type: "note", notes: noteInput.trim() });
      setNoteInput("");
      refetchNotes();
    } catch {} finally { setSavingNote(false); }
  };

  const fetchBrief = async () => {
    if (briefFetching) return;
    const prebuilt = state?.prebuilt_meeting_brief as any;
    if (prebuilt?.brief) { setBriefData(prebuilt); setBriefOpen(true); return; }
    setBriefFetching(true);
    setBriefOpen(true);
    try {
      const data = await agentApi.getMeetingBrief(id);
      setBriefData(data.data);
    } catch {} finally { setBriefFetching(false); }
  };

  const handleGenerateDoc = async (docType: DocType) => {
    setGenerateOpen(false);
    setGeneratingDoc(docType);
    try {
      await documentsApi.generate(id, docType);
      setGenerateToast(`Generating ${DOC_TYPE_LABELS[docType]}…`);
      setActiveCenter("act");
      refetchDocuments();
    } catch {
      setGenerateToast("Generation failed. Try again.");
    } finally {
      setGeneratingDoc(null);
      setTimeout(() => setGenerateToast(null), 4000);
    }
  };

  const handleDownloadDoc = async (doc: GeneratedDocument) => {
    try {
      const blob = await documentsApi.download(doc.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = doc.file_name; a.click();
      URL.revokeObjectURL(url);
    } catch {}
  };

  // Closed deal auto win/loss prompt
  const closedStages = ["closedwon", "closedlost", "closed won", "closed lost"];
  const isClosed = accountStage && closedStages.some(s => accountStage.toLowerCase().includes(s));
  const winLossAlreadyCaptured = !!(state?.win_loss_captured);
  useEffect(() => {
    if (isClosed && !winLossAlreadyCaptured && !winLossOpen) setWinLossOpen(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isClosed, winLossAlreadyCaptured]);

  const momentumStyle = momentum === "accelerating" ? "text-emerald-600" : momentum === "declining" ? "text-red-500" : "text-amber-500";
  const momentumIcon = momentum === "accelerating" ? "↗" : momentum === "declining" ? "↓" : "↘";

  const contextSeed = (() => {
    if (overduePlanActions.length > 0) return `${accountName} has ${overduePlanActions.length} overdue action(s). What's the best approach to clear them?`;
    if (activitySummary?.days_since_last_inbound && activitySummary.days_since_last_inbound > 14)
      return `${accountName} hasn't replied in ${activitySummary.days_since_last_inbound} days. What's the best re-engagement approach?`;
    return undefined;
  })();

  // ── Render ──────────────────────────────────────────────────────────────────

  if (stateLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-gray-50">

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="bg-white border-b border-gray-200 px-5 py-3.5 flex items-center gap-4">
        {/* Back + account info */}
        <Link href="/inbox" className="text-gray-400 hover:text-gray-600 transition-colors flex-shrink-0">
          <ArrowLeft className="w-4 h-4" />
        </Link>

        <div className="flex items-center gap-3 min-w-0">
          <h1 className="text-base font-semibold text-gray-900 truncate">{accountName}</h1>
          {accountStage && (
            <span className="text-xs font-medium text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full flex-shrink-0">
              {accountStage}
            </span>
          )}
          {dealAmount && (
            <span className="text-sm font-semibold text-gray-700 flex-shrink-0">{fmtCurrency(dealAmount)}</span>
          )}
        </div>

        {/* Status chips */}
        <div className="flex items-center gap-2 flex-shrink-0">
          {urgencyScore !== null && <HealthBadge score={urgencyScore} />}
          {momentum && (
            <span className={cn("text-xs font-medium", momentumStyle)}>
              {momentumIcon} {momentum}
            </span>
          )}
          {aiCloseDate && crmCloseDate && aiCloseDate !== crmCloseDate && (
            <span className="text-xs text-gray-400">
              AI close: <span className="font-medium text-gray-700">
                {new Date(aiCloseDate).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
              </span>
              {" · "}CRM: {new Date(crmCloseDate).toLocaleDateString("en-US", { month: "short", year: "numeric" })}
            </span>
          )}
        </div>

        {/* Generate toast */}
        {generateToast && (
          <span className="text-xs font-medium text-brand-700 bg-brand-50 border border-brand-200 px-3 py-1 rounded-full">
            {generateToast}
          </span>
        )}

        {/* Actions — push to right */}
        <div className="ml-auto flex items-center gap-2 flex-shrink-0">
          <button onClick={() => setChatOpen(true)}
            className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors">
            <MessagesSquare className="w-3 h-3" />
            Chat
          </button>

          {/* Generate dropdown */}
          <div className="relative">
            <button onClick={() => setGenerateOpen(v => !v)}
              className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 transition-colors">
              <FileText className="w-3 h-3" />
              {generatingDoc ? "Generating…" : "Generate"}
              <ChevronDown className="w-3 h-3 opacity-80" />
            </button>
            {generateOpen && (
              <div className="absolute right-0 top-full mt-1.5 bg-white border border-gray-200 rounded-xl shadow-lg z-30 min-w-[200px] py-1.5 overflow-hidden">
                {(Object.entries(DOC_TYPE_LABELS) as [DocType, string][]).map(([type, label]) => (
                  <button key={type} onClick={() => handleGenerateDoc(type)}
                    className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors">
                    {label}
                  </button>
                ))}
              </div>
            )}
          </div>

          <button onClick={() => runAgentMutation.mutate()} disabled={agentRunning}
            className={cn(
              "flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50",
              agentRunning ? "bg-indigo-50 text-indigo-700 border border-indigo-200" : "bg-slate-900 text-white hover:bg-slate-800"
            )}>
            <Zap className="w-3 h-3" />
            {agentRunning ? "Running…" : "Run Agent"}
          </button>

          {/* Overflow: Brief + Share + Refresh */}
          <div className="relative">
            <button onClick={() => setGenerateOpen(false)}
              className="flex items-center gap-1 text-gray-400 hover:text-gray-600 transition-colors px-1.5 py-1.5 rounded-lg hover:bg-gray-100">
              <ChevronDown className="w-4 h-4" />
            </button>
          </div>

          <button onClick={fetchBrief} disabled={briefFetching}
            className="flex items-center gap-1.5 text-xs font-medium px-2.5 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors disabled:opacity-50"
            title="Meeting Brief">
            <Sparkles className="w-3.5 h-3.5" />
          </button>

          <button onClick={() => shareMutation.mutate()} disabled={shareMutation.isPending}
            title={shareCopied ? "Copied!" : "Copy share link"}
            className="text-gray-400 hover:text-gray-600 transition-colors p-1">
            <ExternalLink className="w-4 h-4" />
          </button>

          <button onClick={() => queryClient.invalidateQueries({ queryKey: ["account", id] })}
            title="Refresh"
            className="text-gray-400 hover:text-gray-600 transition-colors p-1">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* ── Body: sidebar + main ───────────────────────────────────────────── */}
      <div className="flex-1 flex overflow-hidden">

        {/* ── Sidebar ─────────────────────────────────────────────────────── */}
        <div className="w-72 flex-shrink-0 bg-white border-r border-gray-200 flex flex-col overflow-y-auto">
          <div className="p-4 space-y-4">

            {/* Do Now card */}
            {topAction && (
              <div className="bg-slate-900 rounded-2xl p-4 text-white">
                <div className="flex items-center gap-1.5 mb-3">
                  <Zap className="w-3 h-3 text-brand-400" />
                  <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Do Now</span>
                  {topAction.status === "overdue" && (
                    <span className="ml-auto text-[10px] font-bold bg-red-500/20 text-red-400 border border-red-500/30 px-1.5 py-0.5 rounded-full">
                      Overdue
                    </span>
                  )}
                </div>
                <p className="text-sm font-semibold leading-snug mb-1.5">{topAction.title}</p>
                {topAction.reasoning && (
                  <p className="text-xs text-slate-400 leading-relaxed line-clamp-2">{topAction.reasoning}</p>
                )}
                <div className="flex gap-2 mt-3">
                  <button
                    onClick={() => patchActionMutation.mutate({ actionId: topAction.id, body: { action: "complete" } })}
                    className="flex-1 text-xs font-medium bg-white/10 hover:bg-white/20 rounded-xl py-1.5 transition-colors">
                    Done
                  </button>
                  <button
                    onClick={() => patchActionMutation.mutate({ actionId: topAction.id, body: { action: "skip" } })}
                    className="flex-1 text-xs font-medium bg-white/5 hover:bg-white/10 rounded-xl py-1.5 transition-colors text-slate-400">
                    Defer
                  </button>
                </div>
              </div>
            )}

            {/* Deal story */}
            {narrative && (
              <div className="space-y-1.5">
                <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Deal Story</p>
                <div className="space-y-1.5">
                  {narrative.split(/(?<=\.)\s+/).filter(Boolean).map((sentence, i) => (
                    <p key={i} className="text-xs text-gray-700 leading-relaxed">{sentence}</p>
                  ))}
                </div>
              </div>
            )}

            {/* Health metrics */}
            <div className="space-y-1">
              <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Health</p>
              <div className="flex items-center gap-2 flex-wrap">
                {(meddpiccData.overall_score ?? healthScore) != null && (
                  <span className={cn("text-xs font-semibold tabular-nums",
                    (meddpiccData.overall_score ?? healthScore) >= 0.6 ? "text-emerald-600" :
                    (meddpiccData.overall_score ?? healthScore) >= 0.3 ? "text-amber-600" : "text-red-600")}>
                    {fmtPct(meddpiccData.overall_score ?? healthScore)} MEDDPICC
                  </span>
                )}
                {urgencyScore != null && (
                  <>
                    <span className="text-gray-200">·</span>
                    <span className={cn("text-xs font-semibold tabular-nums",
                      urgencyScore >= 0.85 ? "text-red-600" : urgencyScore >= 0.6 ? "text-orange-600" : "text-emerald-600")}>
                      {fmtPct(urgencyScore)} urgency
                    </span>
                  </>
                )}
              </div>
            </div>

            {/* Signals */}
            {signals.length > 0 && (
              <div className="space-y-1">
                <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Signals</p>
                <SignalGroup label="Critical" dotColor="bg-red-500" count={criticalSignals.length} signals={criticalSignals} defaultExpanded={criticalSignals.length > 0} onAck={id => ackMutation.mutate(id)} />
                <SignalGroup label="Warning"  dotColor="bg-amber-400" count={warningSignals.length}  signals={warningSignals}  defaultExpanded={false} onAck={id => ackMutation.mutate(id)} />
                <SignalGroup label="Activity" dotColor="bg-gray-300"  count={activitySignals.length} signals={activitySignals} defaultExpanded={false} onAck={id => ackMutation.mutate(id)} />
              </div>
            )}

            {/* Engagement */}
            {activitySummary && (
              <div className="space-y-1">
                <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Engagement</p>
                <div className="space-y-1.5">
                  {activitySummary.last_inbound_reply_date && (
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-400">Last reply</span>
                      <span className={cn("text-xs font-medium",
                        (activitySummary.days_since_last_inbound ?? 0) > 14 ? "text-orange-600" : "text-gray-700")}>
                        {activitySummary.days_since_last_inbound != null
                          ? `${activitySummary.days_since_last_inbound}d ago`
                          : activitySummary.last_inbound_reply_date}
                      </span>
                    </div>
                  )}
                  {activitySummary.email_exchange_count > 0 && (
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-400">Emails</span>
                      <span className="text-xs font-medium text-gray-700">
                        {activitySummary.total_emails_received} in · {activitySummary.total_emails_sent} out
                      </span>
                    </div>
                  )}
                  {activitySummary.total_meetings > 0 && (
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-400">Meetings</span>
                      <span className="text-xs font-medium text-gray-700">
                        {activitySummary.total_meetings}
                        {activitySummary.total_fireflies_transcripts > 0 ? ` (${activitySummary.total_fireflies_transcripts} recorded)` : ""}
                      </span>
                    </div>
                  )}
                  {transcriptsData?.intel?.last_call_date != null && (
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-400">Last call</span>
                      <span className={cn("text-xs font-medium",
                        (transcriptsData.intel.days_since_last_call ?? 0) > 21 ? "text-orange-600" : "text-gray-700")}>
                        {transcriptsData.intel.days_since_last_call != null
                          ? `${transcriptsData.intel.days_since_last_call}d ago`
                          : "—"}
                        {transcriptsData.intel.calls_last_30d > 0 ? ` · ${transcriptsData.intel.calls_last_30d}/30d` : ""}
                      </span>
                    </div>
                  )}
                  {activitySummary.deal_created_at && (
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-400">Created</span>
                      <span className="text-xs font-medium text-gray-700">
                        {new Date(activitySummary.deal_created_at).toLocaleDateString("en-US", { month: "short", year: "numeric" })}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* No data state */}
            {signals.length === 0 && !topAction && !narrative && (
              <div className="py-8 text-center">
                <p className="text-sm text-gray-400">No intelligence yet.</p>
                <button onClick={() => runAgentMutation.mutate()}
                  className="mt-2 text-xs text-brand-600 hover:text-brand-700 font-medium">
                  Run Agent to analyse this deal
                </button>
              </div>
            )}
          </div>
        </div>

        {/* ── Main content ─────────────────────────────────────────────────── */}
        <div className="flex-1 flex flex-col overflow-hidden bg-gray-50">

          {/* Tab strip — 3 tabs */}
          <div className="bg-white border-b border-gray-200 px-6 flex items-center gap-1">
            {([
              { id: "act",     label: "Act",          icon: Zap,      badge: overduePlanActions.length + pendingDrafts.length },
              { id: "intel",   label: "Intelligence",  icon: BarChart3, badge: 0 },
              { id: "history", label: "History",       icon: Clock,    badge: 0 },
            ] as const).map(tab => {
              const Icon = tab.icon;
              const isActive = activeCenter === tab.id;
              return (
                <button key={tab.id} onClick={() => setActiveCenter(tab.id)}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-3.5 text-sm font-medium border-b-2 transition-colors relative",
                    isActive ? "border-indigo-600 text-indigo-700" : "border-transparent text-gray-500 hover:text-gray-700"
                  )}>
                  <Icon className="w-3.5 h-3.5" />
                  {tab.label}
                  {tab.badge > 0 && (
                    <span className="inline-flex items-center justify-center min-w-[16px] h-4 text-[10px] font-bold bg-indigo-600 text-white rounded-full px-1">
                      {tab.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Tab content */}
          <div className="flex-1 overflow-y-auto">
            <div className="max-w-3xl mx-auto px-6 py-6">

              {/* ── ACT ── */}
              {activeCenter === "act" && (
                <div className="space-y-6">

                  {/* Next step */}
                  <div className="bg-white rounded-2xl border border-gray-200 p-5">
                    <div className="flex items-center gap-2 mb-3">
                      <Target className="w-4 h-4 text-brand-600" />
                      <p className="text-sm font-semibold text-gray-800">Next Step</p>
                      {nextStepData?.source && (
                        <span className="text-xs text-gray-400 ml-1">
                          {nextStepData.source === "rep" ? "You set this" : "AI suggested"}
                        </span>
                      )}
                      {nextStepData?.due_date && (
                        <span className="text-xs text-gray-400 ml-auto">Due {formatDate(nextStepData.due_date)}</span>
                      )}
                      <button onClick={() => { setNsEditing(true); setNsText(nextStepData?.text ?? ""); setNsDate(nextStepData?.due_date ?? ""); }}
                        className="text-xs text-gray-400 hover:text-gray-600 transition-colors">
                        Edit
                      </button>
                    </div>
                    {nsEditing ? (
                      <div className="space-y-2">
                        <textarea value={nsText} onChange={e => setNsText(e.target.value)} rows={2}
                          className="w-full text-sm border border-gray-200 rounded-xl px-3.5 py-2.5 focus:outline-none focus:border-brand-400 resize-none" />
                        <div className="flex items-center gap-2">
                          <input type="date" value={nsDate} onChange={e => setNsDate(e.target.value)}
                            className="text-sm border border-gray-200 rounded-xl px-3 py-2 focus:outline-none focus:border-brand-400" />
                          <button onClick={() => { setNsSaving(true); nsSetMutation.mutate(); }}
                            disabled={nsSaving || !nsText.trim()}
                            className="px-4 py-2 bg-brand-600 text-white text-sm font-medium rounded-xl hover:bg-brand-700 disabled:opacity-40 transition-colors">
                            {nsSaving ? "Saving…" : "Save"}
                          </button>
                          <button onClick={() => setNsEditing(false)} className="text-sm text-gray-400 hover:text-gray-600">Cancel</button>
                        </div>
                      </div>
                    ) : nextStepData?.text ? (
                      <p className="text-sm text-gray-700 leading-relaxed">{nextStepData.text}</p>
                    ) : (
                      <button onClick={() => setNsEditing(true)}
                        className="text-sm text-gray-400 hover:text-brand-600 transition-colors">
                        + Set next step
                      </button>
                    )}
                  </div>

                  {/* Win/loss banner */}
                  {isClosed && !winLossAlreadyCaptured && (
                    <div className={cn(
                      "rounded-2xl p-4 border flex items-center gap-3",
                      accountStage?.toLowerCase().includes("won") ? "bg-emerald-50 border-emerald-200" : "bg-red-50 border-red-200"
                    )}>
                      <div className="flex-1">
                        <p className={cn("text-sm font-semibold",
                          accountStage?.toLowerCase().includes("won") ? "text-emerald-800" : "text-red-800")}>
                          {accountStage?.toLowerCase().includes("won") ? "Deal closed. Capture the win." : "Deal lost. Capture the reason."}
                        </p>
                      </div>
                      <button onClick={() => setWinLossOpen(true)}
                        className={cn("text-xs font-medium px-3 py-1.5 rounded-xl transition-colors",
                          accountStage?.toLowerCase().includes("won")
                            ? "bg-emerald-600 text-white hover:bg-emerald-700"
                            : "bg-red-600 text-white hover:bg-red-700")}>
                        Capture Reason
                      </button>
                    </div>
                  )}

                  {/* Action plan */}
                  {actionPlanLoading ? (
                    <div className="flex items-center justify-center py-12">
                      <div className="w-5 h-5 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
                    </div>
                  ) : (
                    <>
                      {overduePlanActions.length > 0 && (
                        <div className="space-y-2">
                          <p className="text-[11px] font-bold text-red-500 uppercase tracking-widest">Overdue</p>
                          {overduePlanActions.map((a: TimelineAction) => (
                            <TimelineActionCard key={a.id} action={a} onPatch={patchActionMutation.mutate} />
                          ))}
                        </div>
                      )}

                      {upcomingPlanActions.length > 0 && (
                        <div className="space-y-2">
                          <p className="text-[11px] font-bold text-gray-400 uppercase tracking-widest">Coming Up</p>
                          {upcomingPlanActions.map((a: TimelineAction) => (
                            <TimelineActionCard key={a.id} action={a} onPatch={patchActionMutation.mutate} />
                          ))}
                        </div>
                      )}

                      {completedPlanActions.length > 0 && (
                        <div className="space-y-1 opacity-60">
                          <p className="text-[11px] font-bold text-gray-400 uppercase tracking-widest">Completed</p>
                          {completedPlanActions.slice(0, 5).map((a: TimelineAction) => (
                            <div key={a.id} className="flex items-center gap-3 px-4 py-2 bg-white rounded-xl border border-gray-100">
                              <CheckCircle className="w-3.5 h-3.5 text-green-500 flex-shrink-0" />
                              <span className="text-sm text-gray-600 line-through">{a.title}</span>
                              <span className="text-xs text-gray-400 ml-auto">{a.completed_at ? format(new Date(a.completed_at), "MMM d") : ""}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )}

                  {/* Drafts to review */}
                  {pendingDrafts.length > 0 && (
                    <div className="space-y-2">
                      <p className="text-[11px] font-bold text-brand-600 uppercase tracking-widest">Drafts to Review</p>
                      {pendingDrafts.map(draft => (
                        <DraftCard
                          key={draft.id}
                          draft={draft}
                          onApprove={(draftId) => reviewMutation.mutate({ draftId, action: "approved" })}
                          onDecline={(draftId, category, notes) => reviewMutation.mutate({ draftId, action: "declined", training_category: category, reviewer_notes: notes })}
                          outlookConnected={outlookConnected}
                        />
                      ))}
                    </div>
                  )}

                  {/* Other drafts */}
                  {drafts.filter(d => d.status !== "pending").length > 0 && (
                    <div className="space-y-2">
                      <p className="text-[11px] font-bold text-gray-400 uppercase tracking-widest">All Drafts</p>
                      {drafts.filter(d => d.status !== "pending").map(draft => (
                        <DraftCard
                          key={draft.id}
                          draft={draft}
                          onApprove={(draftId) => reviewMutation.mutate({ draftId, action: "approved" })}
                          onDecline={(draftId, category, notes) => reviewMutation.mutate({ draftId, action: "declined", training_category: category, reviewer_notes: notes })}
                          outlookConnected={outlookConnected}
                        />
                      ))}
                    </div>
                  )}

                  {overduePlanActions.length === 0 && upcomingPlanActions.length === 0 && pendingDrafts.length === 0 && !actionPlanLoading && (
                    <div className="text-center py-12">
                      <CheckCircle className="w-8 h-8 text-green-400 mx-auto mb-3" />
                      <p className="text-sm text-gray-500">All clear. Run Agent to generate new actions.</p>
                    </div>
                  )}

                  {/* Compact documents section */}
                  {(() => {
                    const docs = documentsData?.data ?? [];
                    const ready = docs.filter((d: GeneratedDocument) => d.status === "ready");
                    const generating = docs.filter((d: GeneratedDocument) => d.status === "generating");
                    if (docs.length === 0) return null;
                    return (
                      <div className="bg-white rounded-2xl border border-gray-200 p-5">
                        <div className="flex items-center justify-between mb-3">
                          <p className="text-sm font-semibold text-gray-800">Documents</p>
                          <button onClick={() => setGenerateOpen(v => !v)} className="text-xs font-medium text-indigo-600 hover:text-indigo-700">
                            Generate new ▾
                          </button>
                        </div>
                        {generating.length > 0 && generating.map((d: GeneratedDocument) => (
                          <div key={d.id} className="flex items-center gap-2 py-2 border-b border-gray-100 last:border-0">
                            <div className="w-3.5 h-3.5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin flex-shrink-0" />
                            <span className="text-xs text-gray-600">{d.title} - generating</span>
                          </div>
                        ))}
                        {ready.map((d: GeneratedDocument) => (
                          <div key={d.id} className="flex items-center gap-3 py-2 border-b border-gray-100 last:border-0">
                            <FileText className="w-3.5 h-3.5 text-indigo-400 flex-shrink-0" />
                            <span className="text-xs text-gray-700 flex-1 truncate">{d.title}</span>
                            <button onClick={() => handleDownloadDoc(d)} className="text-xs font-medium text-indigo-600 hover:text-indigo-700 flex-shrink-0">
                              Download
                            </button>
                          </div>
                        ))}
                      </div>
                    );
                  })()}
                </div>
              )}

              {/* ── INTELLIGENCE ── */}
              {activeCenter === "intel" && (
                <div className="space-y-4">
                  {/* MEDDPICC */}
                  {Object.keys(meddpiccData).length > 0 && (
                    <div className="bg-white rounded-2xl border border-gray-200 p-5">
                      <div className="flex items-center gap-2 mb-4">
                        <BarChart3 className="w-4 h-4 text-brand-600" />
                        <p className="text-sm font-semibold text-gray-800">MEDDPICC Qualification</p>
                        <span className="ml-auto text-sm font-bold text-gray-700">{fmtPct(meddpiccData.overall_score)}</span>
                        {meddpiccData.gap_risk && (
                          <span className={cn("text-xs font-medium px-2 py-0.5 rounded-full",
                            meddpiccData.gap_risk === "critical" ? "bg-red-100 text-red-700" :
                            meddpiccData.gap_risk === "high" ? "bg-orange-100 text-orange-700" :
                            "bg-amber-100 text-amber-700")}>
                            {meddpiccData.gap_risk} risk
                          </span>
                        )}
                      </div>
                      <div className="space-y-2">
                        {["metrics","economic_buyer","decision_criteria","decision_process","implicate_pain","champion","competition","paper_process"].map(k => {
                          const val = (meddpiccData[k] as number) ?? 0;
                          const barColor = val >= 0.6 ? "bg-green-400" : val >= 0.3 ? "bg-amber-400" : "bg-red-400";
                          const isGap = val < 0.5;
                          return (
                            <div key={k} className="flex items-center gap-3">
                              <span className={cn("text-xs w-36 flex-shrink-0", isGap ? "text-red-600 font-semibold" : "text-gray-500")}>
                                {MEDDPICC_LABELS[k]}
                              </span>
                              <div className="flex-1 bg-gray-100 rounded-full h-1.5 overflow-hidden">
                                <div className={cn("h-full rounded-full", barColor)} style={{ width: `${val * 100}%` }} />
                              </div>
                              <span className={cn("text-xs w-8 text-right tabular-nums flex-shrink-0", isGap ? "text-red-500 font-semibold" : "text-gray-400")}>
                                {Math.round(val * 100)}%
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Risk vectors */}
                  {Object.keys(riskVectors).length > 0 && (
                    <div className="bg-white rounded-2xl border border-gray-200 p-5">
                      <div className="flex items-center gap-2 mb-4">
                        <Shield className="w-4 h-4 text-brand-600" />
                        <p className="text-sm font-semibold text-gray-800">Risk Vectors</p>
                      </div>
                      <div className="grid grid-cols-5 gap-2">
                        {["champion","economic","timeline","competition","stakeholder"].map(k => {
                          const level = ((riskVectors[k] ?? "unknown") as string).toLowerCase();
                          const style = level === "critical" ? "bg-red-50 border-red-200 text-red-700" :
                            level === "high" ? "bg-orange-50 border-orange-200 text-orange-700" :
                            level === "medium" ? "bg-amber-50 border-amber-200 text-amber-700" :
                            level === "low" ? "bg-green-50 border-green-200 text-green-700" :
                            "bg-gray-50 border-gray-200 text-gray-500";
                          return (
                            <div key={k} className={cn("flex flex-col items-center gap-1 px-1.5 py-2.5 rounded-xl border text-center", style)}>
                              <span className="text-[10px] font-semibold leading-tight">{RISK_LABELS[k]}</span>
                              <span className="text-[10px] capitalize font-medium opacity-70">{level}</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Conversation Intelligence — from Fireflies call data */}
                  {(() => {
                    const intel = transcriptsData?.intel;
                    const calls = transcriptsData?.data ?? [];
                    if (!intel || !intel.calls_total) {
                      return (
                        <div className="bg-white rounded-2xl border border-gray-200 p-5">
                          <div className="flex items-center gap-2 mb-1">
                            <Phone className="w-4 h-4 text-brand-600" />
                            <p className="text-sm font-semibold text-gray-800">Conversation Intelligence</p>
                          </div>
                          <p className="text-xs text-gray-400">
                            No recorded calls for this deal yet. Calls recorded in Fireflies are matched here automatically.
                          </p>
                        </div>
                      );
                    }
                    const talkPct = intel.avg_talk_ratio_rep != null ? Math.round(intel.avg_talk_ratio_rep * 100) : null;
                    const buyerQs = calls.flatMap(t => (t.buyer_questions ?? []).map(q => ({ ...q, call: t.title })));
                    return (
                      <div className="bg-white rounded-2xl border border-gray-200 p-5 space-y-4">
                        <div className="flex items-center gap-2">
                          <Phone className="w-4 h-4 text-brand-600" />
                          <p className="text-sm font-semibold text-gray-800">Conversation Intelligence</p>
                          <span className="ml-auto text-xs text-gray-400">{intel.calls_total} recorded call{intel.calls_total !== 1 ? "s" : ""}</span>
                        </div>

                        {/* Headline stats */}
                        <div className="grid grid-cols-3 gap-2">
                          <div className="rounded-xl bg-gray-50 border border-gray-100 px-3 py-2.5 text-center">
                            <p className="text-base font-bold text-gray-800">
                              {intel.days_since_last_call != null ? `${intel.days_since_last_call}d` : "—"}
                            </p>
                            <p className="text-[10px] text-gray-400">since last call</p>
                          </div>
                          <div className="rounded-xl bg-gray-50 border border-gray-100 px-3 py-2.5 text-center">
                            <p className="text-base font-bold text-gray-800">{intel.calls_last_30d}</p>
                            <p className="text-[10px] text-gray-400">calls last 30d</p>
                          </div>
                          <div className={cn(
                            "rounded-xl border px-3 py-2.5 text-center",
                            talkPct != null && talkPct > 65 ? "bg-amber-50 border-amber-200" : "bg-gray-50 border-gray-100"
                          )}>
                            <p className={cn("text-base font-bold", talkPct != null && talkPct > 65 ? "text-amber-700" : "text-gray-800")}>
                              {talkPct != null ? `${talkPct}%` : "—"}
                            </p>
                            <p className={cn("text-[10px]", talkPct != null && talkPct > 65 ? "text-amber-600" : "text-gray-400")}>
                              rep talk share{talkPct != null && talkPct > 65 ? " · high" : ""}
                            </p>
                          </div>
                        </div>

                        {/* EB attendance flag */}
                        {intel.eb_identified && !intel.eb_attendance && (
                          <div className="flex items-start gap-2 rounded-xl bg-red-50 border border-red-200 px-3 py-2.5">
                            <AlertTriangle className="w-3.5 h-3.5 text-red-500 flex-shrink-0 mt-0.5" />
                            <p className="text-xs text-red-700">
                              The economic buyer has never attended a recorded call. Decisions are happening in rooms you are not in.
                            </p>
                          </div>
                        )}

                        {/* What the buyer asked */}
                        {buyerQs.length > 0 && (
                          <div>
                            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2">What the buyer asked</p>
                            <div className="space-y-1.5">
                              {buyerQs.slice(0, 5).map((q, i) => (
                                <p key={i} className="text-xs text-gray-600 leading-snug">
                                  <span className="font-semibold text-gray-700">{q.speaker}:</span> “{q.text}”
                                </p>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Open commitments */}
                        {(intel.open_buyer_commitments.length > 0 || intel.open_our_commitments.length > 0) && (
                          <div className="grid grid-cols-2 gap-3">
                            <div>
                              <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1.5">They owe us</p>
                              {intel.open_buyer_commitments.length === 0 ? (
                                <p className="text-xs text-gray-300">Nothing open</p>
                              ) : intel.open_buyer_commitments.slice(0, 4).map((c, i) => (
                                <p key={i} className="text-xs text-gray-600 leading-snug mb-1">
                                  {c.text}
                                  {c.call_date ? <span className="text-gray-400"> · {format(new Date(c.call_date), "MMM d")}</span> : null}
                                </p>
                              ))}
                            </div>
                            <div>
                              <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1.5">We owe them</p>
                              {intel.open_our_commitments.length === 0 ? (
                                <p className="text-xs text-gray-300">Nothing open</p>
                              ) : intel.open_our_commitments.slice(0, 4).map((c, i) => (
                                <p key={i} className="text-xs text-gray-600 leading-snug mb-1">
                                  {c.text}
                                  {c.call_date ? <span className="text-gray-400"> · {format(new Date(c.call_date), "MMM d")}</span> : null}
                                </p>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })()}

                  {/* 3 Whys */}
                  {Object.keys(threeWhys).length > 0 && (
                    <div className="bg-white rounded-2xl border border-gray-200 p-5">
                      <div className="flex items-center gap-2 mb-4">
                        <Target className="w-4 h-4 text-brand-600" />
                        <p className="text-sm font-semibold text-gray-800">3 Whys</p>
                      </div>
                      <div className="space-y-3">
                        {[
                          { key: "why_change", label: "Why Change", hint: "Reason to move from status quo" },
                          { key: "why_now",    label: "Why Now",    hint: "Timing trigger this quarter" },
                          { key: "why_us",     label: "Why Us",     hint: "Clear differentiation vs alternatives" },
                        ].map(({ key, label, hint }) => {
                          const entry = threeWhys[key] as { present?: boolean; evidence?: string } | null;
                          const present = entry?.present ?? false;
                          const evidence = (() => {
                            if (!entry?.evidence) return "";
                            const raw = String(entry.evidence).trim();
                            // Strip @{...evidence=VALUE} artifacts sometimes emitted by the LLM
                            const m = raw.match(/@\{[^}]*?evidence=([^}]*)\}/);
                            return m ? m[1].trim() : raw;
                          })();
                          return (
                            <div key={key} className={cn("rounded-xl p-3.5 border", present ? "bg-green-50 border-green-200" : "bg-red-50/50 border-red-100")}>
                              <div className="flex items-center gap-2 mb-1">
                                {present ? <CheckCircle className="w-3.5 h-3.5 text-green-600 flex-shrink-0" /> : <XCircle className="w-3.5 h-3.5 text-red-400 flex-shrink-0" />}
                                <span className={cn("text-sm font-semibold", present ? "text-green-800" : "text-red-700")}>{label}</span>
                                {!present && <span className="text-xs text-red-400 ml-auto">Missing</span>}
                              </div>
                              {present && evidence ? (
                                <p className="text-xs text-green-700 leading-relaxed pl-5 line-clamp-3">{evidence}</p>
                              ) : !present ? (
                                <p className="text-xs text-red-500/70 pl-5">{hint}</p>
                              ) : null}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Grounding */}
                  {groundingConf != null && (
                    <div className="bg-white rounded-2xl border border-gray-200 p-5">
                      <div className="flex items-center gap-2 mb-2">
                        <Shield className="w-4 h-4 text-brand-600" />
                        <p className="text-sm font-semibold text-gray-800">Data Grounding</p>
                        <span className="ml-auto text-sm font-bold text-gray-700">{fmtPct(groundingConf)}</span>
                      </div>
                      <p className="text-xs text-gray-500">
                        {groundingConf >= 0.7 ? "High confidence. Most claims verified against CRM and call data." :
                         groundingConf >= 0.4 ? "Moderate confidence. Some claims need verification." :
                         "Low confidence. Run agent sweep to improve data quality."}
                      </p>
                    </div>
                  )}

                  {/* Deal analysis — narrative + risks */}
                  {(narrative || povRisks.length > 0) && (
                    <div className="bg-white rounded-2xl border border-gray-200 p-5">
                      <div className="flex items-center gap-2 mb-4">
                        <FileText className="w-4 h-4 text-brand-600" />
                        <p className="text-sm font-semibold text-gray-800">Deal Analysis</p>
                      </div>
                      {narrative && (
                        <div className="mb-4">
                          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2">Narrative</p>
                          <div className="space-y-2">
                            {narrative.split(/(?<=\.)\s+/).filter(Boolean).map((sentence, i) => (
                              <p key={i} className="text-sm text-gray-700 leading-relaxed">{sentence}</p>
                            ))}
                          </div>
                        </div>
                      )}
                      {povRisks.length > 0 && (
                        <div>
                          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2">Key Risks</p>
                          <ul className="space-y-2">
                            {povRisks.map((risk, i) => (
                              <li key={i} className="flex items-start gap-2">
                                <span className="text-red-400 mt-0.5 flex-shrink-0 text-xs">•</span>
                                <p className="text-sm text-gray-700 leading-relaxed">{risk}</p>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}

                  {Object.keys(meddpiccData).length === 0 && (
                    <div className="text-center py-12">
                      <BarChart3 className="w-8 h-8 text-gray-300 mx-auto mb-3" />
                      <p className="text-sm text-gray-400">Run Agent to generate deal intelligence.</p>
                    </div>
                  )}
                </div>
              )}


              {/* ── HISTORY ── */}
              {activeCenter === "history" && (
                <div className="space-y-6">
                  {/* Timeline */}
                  <div className="bg-white rounded-2xl border border-gray-200 p-5">
                    <p className="text-[11px] font-bold text-gray-400 uppercase tracking-widest mb-3">Deal Timeline</p>
                    {timeline.length === 0 ? (
                      <p className="text-sm text-gray-400 py-4 text-center">No events yet</p>
                    ) : timeline.map(e => <TimelineRow key={e.event_id} event={e} />)}
                  </div>

                  {/* Transcripts */}
                  {(transcriptsData?.data ?? []).length > 0 && (
                    <div className="space-y-2">
                      <p className="text-[11px] font-bold text-gray-400 uppercase tracking-widest">Call Transcripts</p>
                      {(transcriptsData!.data ?? []).map((t: Transcript, i: number) => (
                        <TranscriptCard key={t.id ?? i} transcript={t} />
                      ))}
                    </div>
                  )}

                  {/* Notes */}
                  <div className="space-y-3">
                    <p className="text-[11px] font-bold text-gray-400 uppercase tracking-widest">Notes</p>
                    <div className="bg-white rounded-2xl border border-gray-200 p-4 space-y-2">
                      <textarea
                        value={noteInput}
                        onChange={e => setNoteInput(e.target.value)}
                        placeholder="Add a note… (Ctrl+Enter to save)"
                        rows={2}
                        className="w-full text-sm border border-gray-200 rounded-xl px-3.5 py-2.5 focus:outline-none focus:border-brand-400 resize-none"
                        onKeyDown={e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); handleSaveNote(); } }}
                      />
                      <button onClick={handleSaveNote} disabled={!noteInput.trim() || savingNote}
                        className="text-xs font-medium px-3 py-1.5 bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-40 transition-colors">
                        {savingNote ? "Saving…" : "Save note"}
                      </button>
                    </div>
                    {notes.map((n: AccountNote, i: number) => (
                      <div key={n.id ?? i} className="bg-white rounded-2xl border border-gray-200 px-4 py-3">
                        <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">{n.notes}</p>
                        {n.occurred_at && (
                          <p className="text-xs text-gray-400 mt-1">
                            {formatDistanceToNow(new Date(n.occurred_at), { addSuffix: true })}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* ── SMART FIELDS — shown in Intel tab ── */}
              {activeCenter === "intel" && smartFieldSuggestions.length > 0 && (
                <div className="mt-6">
                  <SmartFieldsPanel accountId={id} suggestions={smartFieldSuggestions} isLoading={smartFieldsLoading} />
                </div>
              )}

            </div>
          </div>
        </div>
      </div>

      {/* ── Chat slide-over ───────────────────────────────────────────────── */}
      {chatOpen && (
        <ChatPanel
          accountId={id}
          accountName={accountName}
          contextSeed={contextSeed}
          onClose={() => setChatOpen(false)}
        />
      )}

      {/* ── Meeting Brief modal ───────────────────────────────────────────── */}
      {briefOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full max-h-[80vh] overflow-y-auto">
            <div className="sticky top-0 bg-white px-6 py-4 border-b border-gray-100 flex items-center gap-3">
              <Sparkles className="w-4 h-4 text-brand-600" />
              <h2 className="text-base font-semibold text-gray-900">Meeting Brief</h2>
              <span className="text-xs text-gray-400 ml-1">{accountName}</span>
              <button onClick={() => setBriefOpen(false)} className="ml-auto text-gray-400 hover:text-gray-600">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="px-6 py-5 space-y-5">
              {briefFetching ? (
                <div className="flex items-center justify-center py-12">
                  <div className="w-6 h-6 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
                </div>
              ) : briefData ? (
                <>
                  {briefData.brief && (
                    <div>
                      <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2">Brief</p>
                      <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">{briefData.brief}</p>
                    </div>
                  )}
                  {briefData.stakeholders?.length > 0 && (
                    <div>
                      <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2">Stakeholders</p>
                      <div className="space-y-1.5">
                        {briefData.stakeholders.map((s, i) => (
                          <div key={i} className="flex items-center gap-3 py-1.5">
                            <User className="w-3.5 h-3.5 text-gray-400" />
                            <span className="text-sm font-medium text-gray-800">{s.name}</span>
                            {s.title && <span className="text-xs text-gray-400">{s.title}</span>}
                            {s.role && <span className="text-xs text-brand-600 bg-brand-50 px-1.5 py-0.5 rounded">{s.role}</span>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {briefData.next_actions?.length > 0 && (
                    <div>
                      <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2">Recommended Actions</p>
                      <div className="space-y-1.5">
                        {briefData.next_actions.slice(0, 3).map((a, i) => (
                          <div key={i} className="flex items-start gap-2">
                            <span className="text-xs font-bold text-brand-600 w-4 flex-shrink-0 mt-0.5">{i + 1}.</span>
                            <p className="text-sm text-gray-700">{a.action}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <p className="text-sm text-gray-400 text-center py-8">Brief not available. Run Agent first.</p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── POV Override modal ────────────────────────────────────────────── */}
      {povOverrideOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6">
            <div className="flex items-center gap-2 mb-4">
              <h2 className="text-base font-semibold text-gray-900">Override AI Forecast</h2>
              <button onClick={() => setPovOverrideOpen(false)} className="ml-auto text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
            </div>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2">
                {["Pipeline","Best Case","Commit","Omit"].map(cat => (
                  <button key={cat} onClick={() => setOverrideCategory(cat)}
                    className={cn("py-2 text-sm font-medium rounded-xl border transition-colors",
                      overrideCategory === cat ? "bg-brand-600 text-white border-brand-600" : "border-gray-200 text-gray-700 hover:bg-gray-50")}>
                    {cat}
                  </button>
                ))}
              </div>
              <textarea value={overrideReason} onChange={e => setOverrideReason(e.target.value)}
                placeholder="Reason for override…" rows={3}
                className="w-full text-sm border border-gray-200 rounded-xl px-3.5 py-2.5 focus:outline-none focus:border-brand-400 resize-none" />
              <div className="flex gap-2">
                <button onClick={() => overridePovMutation.mutate()} disabled={!overrideCategory || !overrideReason.trim()}
                  className="flex-1 py-2 bg-brand-600 text-white text-sm font-medium rounded-xl hover:bg-brand-700 disabled:opacity-40 transition-colors">
                  Save Override
                </button>
                <button onClick={() => setPovOverrideOpen(false)} className="px-4 py-2 text-sm text-gray-500 hover:text-gray-700">Cancel</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Win/Loss modal ────────────────────────────────────────────────── */}
      {winLossOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6">
            <div className="flex items-center gap-2 mb-4">
              <h2 className="text-base font-semibold text-gray-900">Capture Deal Outcome</h2>
              <button onClick={() => setWinLossOpen(false)} className="ml-auto text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
            </div>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2">
                <button onClick={() => setWinLossOutcome("won")}
                  className={cn("py-3 text-sm font-semibold rounded-xl border-2 transition-colors",
                    winLossOutcome === "won" ? "bg-emerald-600 text-white border-emerald-600" : "border-gray-200 text-gray-700 hover:border-emerald-300")}>
                  Won
                </button>
                <button onClick={() => setWinLossOutcome("lost")}
                  className={cn("py-3 text-sm font-semibold rounded-xl border-2 transition-colors",
                    winLossOutcome === "lost" ? "bg-red-600 text-white border-red-600" : "border-gray-200 text-gray-700 hover:border-red-300")}>
                  Lost
                </button>
              </div>
              {winLossOutcome && (
                <>
                  <div className="flex flex-wrap gap-1.5">
                    {["price","champion","timing","competition","no_budget","product_gap","no_business_case","other"].map(r => (
                      <button key={r} onClick={() => setWinLossReason(r)}
                        className={cn("text-xs px-2.5 py-1 rounded-full border transition-colors",
                          winLossReason === r ? "bg-brand-600 text-white border-brand-600" : "border-gray-200 text-gray-600 hover:border-brand-300")}>
                        {r.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
                      </button>
                    ))}
                  </div>
                  {winLossReason === "competition" && (
                    <input type="text" value={winLossCompetitor} onChange={e => setWinLossCompetitor(e.target.value)}
                      placeholder="Competitor name"
                      className="w-full text-sm border border-gray-200 rounded-xl px-3.5 py-2.5 focus:outline-none focus:border-brand-400" />
                  )}
                  <textarea value={winLossNotes} onChange={e => setWinLossNotes(e.target.value)}
                    placeholder="Notes (optional)" rows={2}
                    className="w-full text-sm border border-gray-200 rounded-xl px-3.5 py-2.5 focus:outline-none focus:border-brand-400 resize-none" />
                </>
              )}
              <div className="flex gap-2">
                <button onClick={() => winLossMutation.mutate()}
                  disabled={!winLossOutcome || !winLossReason}
                  className="flex-1 py-2 bg-brand-600 text-white text-sm font-medium rounded-xl hover:bg-brand-700 disabled:opacity-40 transition-colors">
                  Save
                </button>
                <button onClick={() => setWinLossOpen(false)} className="px-4 py-2 text-sm text-gray-500">Cancel</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
