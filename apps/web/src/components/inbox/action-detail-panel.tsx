"use client";

import Link from "next/link";
import { useState, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { timelineApi, streamChat, type TimelineAction } from "@/lib/api";
import { cn } from "@/lib/utils";
import { MarkdownContent } from "@/components/markdown-content";
import { formatDistanceToNow } from "date-fns";
import {
  CheckCircle, SkipForward, ExternalLink, ArrowUpRight,
  MessageSquare, Phone, Calendar, TrendingUp, Send, ChevronDown,
} from "lucide-react";
import { ACTION_ICONS, dueDateLabel } from "./action-queue-card";

const MEDDPICC_LABELS: Record<string, string> = {
  metrics:           "M - Metrics",
  economic_buyer:    "EB - Economic Buyer",
  decision_criteria: "DC - Decision Criteria",
  decision_process:  "DP - Decision Process",
  implicate_pain:    "IP - Implicate Pain",
  champion:          "Ch - Champion",
  competition:       "Co - Competition",
  paper_process:     "PP - Paper Process",
};

const SOURCE_LABELS: Record<string, string> = {
  fireflies_action_item: "Action item from call",
  agent_gap_fill:        "Agent run",
  calendar_match:        "Calendar match",
  hubspot_stage_change:  "Stage change trigger",
  signal_trigger:        "Agent run",
  rep_created:           "Added manually",
};

const ACTION_TYPE_LABEL: Record<string, string> = {
  email:             "Send email",
  call_prep:         "Prepare for call",
  meeting_prep:      "Meeting prep",
  stakeholder_intro: "Stakeholder intro",
  proposal_follow:   "Proposal follow-up",
  close_push:        "Close push",
  champion_checkin:  "Champion check-in",
  escalation:        "Escalate",
  rep_created:       "Custom action",
};

type Outcome = "sent_email" | "had_call" | "got_response" | "meeting_booked" | "not_relevant";

const OUTCOME_OPTIONS: { value: Outcome; label: string; icon: React.FC<{ className?: string }> }[] = [
  { value: "sent_email",     label: "Sent email",     icon: ({ className }) => <MessageSquare className={className} /> },
  { value: "had_call",       label: "Had a call",     icon: ({ className }) => <Phone className={className} /> },
  { value: "got_response",   label: "Got response",   icon: ({ className }) => <CheckCircle className={className} /> },
  { value: "meeting_booked", label: "Booked meeting", icon: ({ className }) => <Calendar className={className} /> },
  { value: "not_relevant",   label: "Not relevant",   icon: ({ className }) => <SkipForward className={className} /> },
];

interface Props {
  action: TimelineAction;
  onComplete: () => void;
}

export function ActionDetailPanel({ action, onComplete }: Props) {
  const qc = useQueryClient();
  const ActionIcon = ACTION_ICONS[action.action_type] ?? ACTION_ICONS.email;
  const [step, setStep] = useState<"detail" | "outcome">("detail");
  const [selectedOutcome, setSelectedOutcome] = useState<Outcome | null>(null);
  const [outcomeNotes, setOutcomeNotes] = useState("");

  // Inline Ask Agent state (#22)
  const [askOpen, setAskOpen] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState<{ role: "user" | "assistant"; content: string }[]>([]);
  const [chatStreaming, setChatStreaming] = useState(false);
  const [streamBuffer, setStreamBuffer] = useState("");
  const chatInputRef = useRef<HTMLInputElement>(null);

  const sendChat = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatInput.trim() || chatStreaming) return;
    const q = chatInput.trim();
    const seedQ = `I'm looking at this action on ${action.account_name}: "${action.title}". ${q}`;
    setChatInput("");
    setChatMessages(prev => [...prev, { role: "user", content: q }]);
    setChatStreaming(true);
    setStreamBuffer("");
    let full = "";
    try {
      const stream = streamChat({ account_id: action.account_id, message: seedQ });
      for await (const chunk of stream) {
        full += chunk;
        setStreamBuffer(full);
      }
      setChatMessages(prev => [...prev, { role: "assistant", content: full }]);
    } catch {
      setChatMessages(prev => [...prev, { role: "assistant", content: "Sorry, could not reach the agent." }]);
    } finally {
      setChatStreaming(false);
      setStreamBuffer("");
    }
  };

  const completeMutation = useMutation({
    mutationFn: (vars: { outcome?: Outcome; notes?: string }) =>
      timelineApi.patch(action.id, { action: "complete", outcome: vars.outcome, notes: vars.notes }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["action-queue"] });
      qc.invalidateQueries({ queryKey: ["action-plan", action.account_id] });
      onComplete();
    },
  });

  const skipMutation = useMutation({
    mutationFn: () => timelineApi.patch(action.id, { action: "skip" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["action-queue"] });
      onComplete();
    },
  });

  const content = action.prepared_content as {
    type?: string;
    content?: string;
    subject_line?: string;
    target_contact?: string;
    talking_points?: string[];
  } | null;

  const isUrgent = action.status === "overdue" || action.status === "today";

  if (step === "outcome") {
    return (
      <div className="h-full flex flex-col bg-white">
        <div className="px-6 py-5 border-b border-zinc-100">
          <div className="flex items-center gap-2 mb-1">
            <div className="w-6 h-6 rounded-full bg-green-100 flex items-center justify-center">
              <CheckCircle className="w-3.5 h-3.5 text-green-600" />
            </div>
            <span className="text-sm font-semibold text-zinc-900">What happened?</span>
          </div>
          <p className="text-xs text-zinc-500 ml-8">Takes 5 seconds. Helps the agent plan your next move.</p>
        </div>

        <div className="flex-1 px-6 py-5 space-y-3">
          <div className="grid grid-cols-1 gap-2">
            {OUTCOME_OPTIONS.map(opt => {
              const Icon = opt.icon;
              return (
                <button
                  key={opt.value}
                  onClick={() => setSelectedOutcome(prev => prev === opt.value ? null : opt.value)}
                  className={cn(
                    "flex items-center gap-3 px-4 py-3 rounded-xl border text-left transition-all",
                    selectedOutcome === opt.value
                      ? "bg-brand-50 border-brand-300 text-brand-700"
                      : "bg-white border-zinc-200 text-zinc-700 hover:border-zinc-300"
                  )}
                >
                  <Icon className="w-4 h-4 flex-shrink-0" />
                  <span className="text-sm font-medium">{opt.label}</span>
                  {selectedOutcome === opt.value && (
                    <CheckCircle className="w-4 h-4 text-brand-600 ml-auto flex-shrink-0" />
                  )}
                </button>
              );
            })}
          </div>

          <div>
            <textarea
              value={outcomeNotes}
              onChange={e => setOutcomeNotes(e.target.value)}
              placeholder="Notes (optional) - e.g. 'Ahmad confirmed budget approved, will reply next week'"
              rows={3}
              className="w-full text-sm border border-zinc-200 rounded-xl px-4 py-3 resize-none focus:outline-none focus:border-brand-400 placeholder-zinc-400"
            />
          </div>
        </div>

        <div className="px-6 py-4 border-t border-zinc-100 flex gap-2">
          <button
            onClick={() => completeMutation.mutate({ outcome: selectedOutcome ?? undefined, notes: outcomeNotes.trim() || undefined })}
            disabled={completeMutation.isPending}
            className="flex-1 flex items-center justify-center gap-1.5 text-sm font-medium py-2.5 bg-green-600 text-white rounded-xl hover:bg-green-700 disabled:opacity-40 transition-colors"
          >
            <CheckCircle className="w-4 h-4" />
            {completeMutation.isPending ? "Logging..." : "Log & Complete"}
          </button>
          <button
            onClick={() => completeMutation.mutate({})}
            disabled={completeMutation.isPending}
            className="px-4 py-2.5 text-sm text-zinc-400 hover:text-zinc-600 transition-colors"
          >
            Skip log
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Header */}
      <div className={cn(
        "px-6 py-5 border-b border-zinc-100",
        action.status === "overdue" ? "border-l-4 border-l-red-400" :
        action.status === "today"   ? "border-l-4 border-l-brand-500" : ""
      )}>
        <div className="flex items-center gap-2 mb-3">
          <div className={cn(
            "w-8 h-8 rounded-xl flex items-center justify-center",
            isUrgent ? "bg-brand-50" : "bg-zinc-50"
          )}>
            <ActionIcon className={cn(
              "w-4 h-4",
              action.status === "overdue" ? "text-red-500" :
              action.status === "today"   ? "text-brand-600" : "text-zinc-400"
            )} />
          </div>
          <span className="text-xs font-semibold text-zinc-500 uppercase tracking-wide">
            {ACTION_TYPE_LABEL[action.action_type] ?? action.action_type.replace(/_/g, " ")}
          </span>
          <span className={cn(
            "ml-auto text-xs font-medium px-2 py-0.5 rounded-full border",
            action.status === "overdue" ? "bg-red-50 text-red-700 border-red-200" :
            action.status === "today"   ? "bg-brand-50 text-brand-700 border-brand-200" :
            "bg-zinc-50 text-zinc-500 border-zinc-200"
          )}>
            {dueDateLabel(action.due_date, action.status)}
          </span>
        </div>
        <div className="flex items-center gap-2 mb-2">
          <Link
            href={`/account/${action.account_id}`}
            className="text-sm font-bold text-zinc-900 hover:text-brand-600 transition-colors flex items-center gap-1"
          >
            {action.account_name}
            <ArrowUpRight className="w-3.5 h-3.5 opacity-40" />
          </Link>
          {action.account_stage && (
            <span className="text-xs text-zinc-400 bg-zinc-100 px-2 py-0.5 rounded-full">
              {action.account_stage}
            </span>
          )}
        </div>
        <h2 className="text-base font-semibold text-zinc-900 leading-snug">{action.title}</h2>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
        {action.reasoning && (
          <div>
            <p className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider mb-2">Why now</p>
            <p className="text-sm text-zinc-700 leading-relaxed whitespace-pre-line">{action.reasoning}</p>
          </div>
        )}
        {content?.type === "draft" && content.content && (
          <div>
            <p className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider mb-2">Prepared draft</p>
            <div className="bg-zinc-50 border border-zinc-200 rounded-xl p-4">
              {content.subject_line && (
                <p className="text-xs font-semibold text-zinc-500 mb-2">Subject: {content.subject_line}</p>
              )}
              {content.target_contact && (
                <p className="text-xs text-zinc-400 mb-2">To: {content.target_contact}</p>
              )}
              <MarkdownContent content={content.content ?? ""} />
            </div>
          </div>
        )}
        {Array.isArray(content?.talking_points) && content.talking_points.length > 0 && (
          <div>
            <p className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider mb-2">Talking points</p>
            <ul className="space-y-1.5">
              {content.talking_points.map((pt, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-zinc-700">
                  <span className="text-zinc-300 flex-shrink-0 mt-0.5">·</span>{pt}
                </li>
              ))}
            </ul>
          </div>
        )}
        <div className="grid grid-cols-2 gap-3">
          {action.meddpicc_component && (
            <div className="bg-zinc-50 rounded-xl p-3">
              <p className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider mb-1">Addresses</p>
              <p className="text-xs font-medium text-zinc-700">
                {MEDDPICC_LABELS[action.meddpicc_component] ?? action.meddpicc_component.replace(/_/g, " ")}
              </p>
            </div>
          )}
          {action.source && (
            <div className="bg-zinc-50 rounded-xl p-3">
              <p className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider mb-1">Created by</p>
              <p className="text-xs font-medium text-zinc-700">
                {SOURCE_LABELS[action.source] ?? action.source.replace(/_/g, " ")}
              </p>
            </div>
          )}
          {action.created_at && (
            <div className="bg-zinc-50 rounded-xl p-3">
              <p className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider mb-1">Added</p>
              <p className="text-xs font-medium text-zinc-700">
                {formatDistanceToNow(new Date(action.created_at), { addSuffix: true })}
              </p>
            </div>
          )}
          {action.skip_count > 0 && (
            <div className="bg-amber-50 rounded-xl p-3">
              <p className="text-[10px] font-semibold text-amber-500 uppercase tracking-wider mb-1">Skipped</p>
              <p className="text-xs font-medium text-amber-700">{action.skip_count}x - agent keeps surfacing this</p>
            </div>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="px-6 py-4 border-t border-zinc-100 flex items-center gap-2">
        {action.draft_id ? (
          <Link
            href={`/account/${action.account_id}?tab=drafts`}
            className="flex items-center gap-1.5 text-sm font-medium px-4 py-2 bg-brand-600 text-white rounded-xl hover:bg-brand-700 transition-colors"
          >
            <CheckCircle className="w-4 h-4" />
            Review Draft
          </Link>
        ) : (
          <button
            onClick={() => setStep("outcome")}
            className="flex items-center gap-1.5 text-sm font-medium px-4 py-2 bg-green-600 text-white rounded-xl hover:bg-green-700 transition-colors"
          >
            <CheckCircle className="w-4 h-4" />
            Mark Done
          </button>
        )}
        <button
          onClick={() => skipMutation.mutate()}
          disabled={skipMutation.isPending}
          className="flex items-center gap-1.5 text-sm font-medium px-4 py-2 bg-white border border-zinc-200 text-zinc-600 rounded-xl hover:bg-zinc-50 transition-colors"
        >
          <SkipForward className="w-4 h-4" />
          Defer 2d
        </button>
        <button
          onClick={() => setAskOpen(o => !o)}
          className={cn(
            "flex items-center gap-1.5 text-sm font-medium px-3 py-2 border rounded-xl transition-colors",
            askOpen
              ? "border-brand-300 text-brand-700 bg-brand-50"
              : "border-zinc-200 text-zinc-500 hover:text-brand-600 hover:border-brand-200"
          )}
        >
          <MessageSquare className="w-4 h-4" />
          Ask Agent
          <ChevronDown className={cn("w-3 h-3 transition-transform", askOpen && "rotate-180")} />
        </button>
        <Link
          href={`/account/${action.account_id}`}
          className="ml-auto flex items-center gap-1.5 text-sm font-medium text-zinc-400 hover:text-zinc-600 transition-colors"
        >
          <ExternalLink className="w-4 h-4" />
          War Room
        </Link>
      </div>

      {/* Inline Ask Agent chat (#22) */}
      {askOpen && (
        <div className="border-t border-zinc-100 p-4 space-y-3">
          <div className="max-h-48 overflow-y-auto space-y-2">
            {chatMessages.map((m, i) => (
              <div key={i} className={cn("text-xs rounded-xl px-3 py-2 max-w-[90%]",
                m.role === "user"
                  ? "bg-brand-600 text-white ml-auto"
                  : "bg-zinc-100 text-zinc-800"
              )}>
                {m.content}
              </div>
            ))}
            {chatStreaming && (
              <div className="bg-zinc-100 text-zinc-800 text-xs rounded-xl px-3 py-2 max-w-[90%]">
                {streamBuffer || <span className="animate-pulse">Thinking...</span>}
              </div>
            )}
          </div>
          <form onSubmit={sendChat} className="flex gap-2">
            <input
              ref={chatInputRef}
              value={chatInput}
              onChange={e => setChatInput(e.target.value)}
              placeholder={`Ask about: ${action.title.slice(0, 40)}...`}
              disabled={chatStreaming}
              className="flex-1 text-xs border border-zinc-200 rounded-xl px-3 py-2 focus:outline-none focus:border-brand-400 disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={!chatInput.trim() || chatStreaming}
              className="p-2 bg-brand-600 text-white rounded-xl hover:bg-brand-700 disabled:opacity-40 transition-colors"
            >
              <Send className="w-3.5 h-3.5" />
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
