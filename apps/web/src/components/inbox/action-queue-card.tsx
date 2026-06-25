"use client";

import { type TimelineAction } from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatDistanceToNow, parseISO } from "date-fns";
import {
  Mail, Phone, Users, Target, TrendingUp,
  AlertTriangle, Clock, Calendar,
} from "lucide-react";

export const ACTION_ICONS: Record<string, React.FC<{ className?: string }>> = {
  email:             ({ className }) => <Mail className={className} />,
  call_prep:         ({ className }) => <Phone className={className} />,
  meeting_prep:      ({ className }) => <Calendar className={className} />,
  stakeholder_intro: ({ className }) => <Users className={className} />,
  proposal_follow:   ({ className }) => <Target className={className} />,
  close_push:        ({ className }) => <TrendingUp className={className} />,
  champion_checkin:  ({ className }) => <Mail className={className} />,
  escalation:        ({ className }) => <AlertTriangle className={className} />,
  rep_created:       ({ className }) => <Target className={className} />,
};

export const STATUS_BORDER: Record<string, string> = {
  overdue: "border-l-4 border-l-red-400",
  today:   "border-l-4 border-l-brand-500",
  upcoming:"border-l-4 border-l-zinc-200",
};

export function dueDateLabel(due: string, status: string): string {
  try {
    const d = parseISO(due);
    if (status === "overdue") {
      return `${formatDistanceToNow(d)} overdue`;
    }
    const dist = formatDistanceToNow(d, { addSuffix: true });
    return dist === "in less than a minute" ? "Today" : dist;
  } catch {
    return due;
  }
}

interface Props {
  action: TimelineAction;
  isSelected: boolean;
  onSelect: (action: TimelineAction) => void;
}

export function ActionQueueCard({ action, isSelected, onSelect }: Props) {
  const ActionIcon = ACTION_ICONS[action.action_type] ?? Mail;
  const isUrgent = action.status === "overdue" || action.status === "today";

  return (
    <button
      onClick={() => onSelect(action)}
      className={cn(
        "w-full text-left rounded-xl border overflow-hidden transition-all",
        STATUS_BORDER[action.status],
        isSelected
          ? "bg-brand-50 border-brand-200 shadow-sm"
          : "bg-white border-zinc-200 hover:border-zinc-300 hover:shadow-sm"
      )}
    >
      <div className="px-3.5 py-3 flex items-start gap-3">
        {/* Type icon */}
        <div className={cn(
          "w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5",
          isUrgent ? "bg-brand-50" : "bg-zinc-50"
        )}>
          <ActionIcon className={cn(
            "w-3.5 h-3.5",
            action.status === "overdue" ? "text-red-500" :
            action.status === "today"   ? "text-brand-600" : "text-zinc-400"
          )} />
        </div>

        <div className="flex-1 min-w-0">
          {/* Account + due badge */}
          <div className="flex items-center gap-1.5 flex-wrap mb-1">
            {action.account_name && (
              <span className="text-xs font-semibold text-zinc-700 truncate max-w-[140px]">
                {action.account_name}
              </span>
            )}
            {action.account_stage && (
              <span className="text-[10px] text-zinc-400 bg-zinc-100 px-1.5 py-0.5 rounded-full">
                {action.account_stage}
              </span>
            )}
            <span className={cn(
              "text-[10px] font-medium px-1.5 py-0.5 rounded-full ml-auto flex-shrink-0",
              action.status === "overdue" ? "bg-red-50 text-red-700 border border-red-200" :
              action.status === "today"   ? "bg-brand-50 text-brand-700 border border-brand-200" :
              "bg-zinc-50 text-zinc-500 border border-zinc-200"
            )}>
              {dueDateLabel(action.due_date, action.status)}
            </span>
          </div>

          {/* Title - 2 lines max */}
          <p className={cn(
            "text-sm font-medium leading-snug line-clamp-2",
            isSelected ? "text-brand-900" : "text-zinc-900"
          )}>
            {action.title}
          </p>

          {/* Reasoning preview - 1 line */}
          {action.reasoning && (
            <p className="text-xs text-zinc-400 mt-0.5 line-clamp-1 leading-snug">
              {action.reasoning}
            </p>
          )}
        </div>
      </div>
    </button>
  );
}
