"use client";

import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { accountsApi, type SharedBriefData } from "@/lib/api";
import { cn, signalLabel, urgencyLevel } from "@/lib/utils";
import { TrendingUp, TrendingDown, Minus, AlertTriangle, CheckCircle, Users } from "lucide-react";
import { Providers } from "@/components/providers";

const URGENCY_COLOR: Record<string, string> = {
  critical: "text-red-600 bg-red-50 border-red-200",
  high:     "text-orange-600 bg-orange-50 border-orange-200",
  medium:   "text-yellow-700 bg-yellow-50 border-yellow-200",
  low:      "text-green-600 bg-green-50 border-green-200",
};

const FORECAST_STYLE: Record<string, string> = {
  "Commit":    "bg-green-100 text-green-700",
  "Best Case": "bg-blue-100 text-blue-700",
  "Pipeline":  "bg-gray-100 text-gray-600",
  "Omit":      "bg-red-100 text-red-700",
};

function SharedBriefPage({ token }: { token: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["shared-brief", token],
    queryFn: () => accountsApi.getSharedBrief(token),
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="w-6 h-6 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (isError || !data?.data) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <p className="text-lg font-semibold text-gray-700">Link expired or invalid</p>
          <p className="text-sm text-gray-400 mt-1">This brief link is no longer valid. Ask the sender for a new link.</p>
        </div>
      </div>
    );
  }

  const brief: SharedBriefData = data.data;
  const health = brief.health_score;
  const healthPct = health !== null ? Math.round((health ?? 0) * 100) : null;
  const ForecastIcon = brief.ai_forecast === "Commit" || brief.ai_forecast === "Best Case"
    ? TrendingUp
    : brief.ai_forecast === "Omit" ? TrendingDown : Minus;

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-2xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center">
              <span className="text-white text-xs font-bold">V</span>
            </div>
            <span className="text-sm font-semibold text-gray-700">Vantage · Account Brief</span>
          </div>
          <span className="text-xs text-gray-400">Read-only · expires in 7 days</span>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-6 py-8 space-y-6">
        {/* Account header */}
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h1 className="text-xl font-bold text-gray-900">{brief.account_name}</h1>
          <div className="flex items-center gap-3 mt-2 flex-wrap">
            {brief.stage && (
              <span className="text-sm text-gray-500 bg-gray-100 px-2.5 py-0.5 rounded-full">{brief.stage}</span>
            )}
            {brief.deal_amount && (
              <span className="text-sm font-semibold text-gray-800">
                {new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(brief.deal_amount)}
              </span>
            )}
            {brief.ai_forecast && (
              <span className={cn("text-xs font-medium px-2.5 py-1 rounded-full flex items-center gap-1", FORECAST_STYLE[brief.ai_forecast] ?? "bg-gray-100 text-gray-600")}>
                <ForecastIcon className="w-3 h-3" />
                {brief.ai_forecast}
                {brief.ai_confidence && ` · ${Math.round(brief.ai_confidence * 100)}%`}
              </span>
            )}
          </div>
          {healthPct !== null && (
            <div className="mt-3 flex items-center gap-2">
              <span className="text-xs text-gray-400">Account health</span>
              <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden max-w-[120px]">
                <div
                  className={cn("h-full rounded-full", healthPct >= 70 ? "bg-green-400" : healthPct >= 40 ? "bg-yellow-400" : "bg-red-400")}
                  style={{ width: `${healthPct}%` }}
                />
              </div>
              <span className="text-xs font-medium text-gray-700">{healthPct}%</span>
            </div>
          )}
          {brief.meddpicc_overall != null && (
            <div className="mt-2 flex items-center gap-2">
              <span className="text-xs text-gray-400">MEDDPICC</span>
              <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden max-w-[120px]">
                <div
                  className={cn("h-full rounded-full", (brief.meddpicc_overall ?? 0) >= 0.7 ? "bg-green-400" : "bg-amber-400")}
                  style={{ width: `${Math.round((brief.meddpicc_overall ?? 0) * 100)}%` }}
                />
              </div>
              <span className="text-xs font-medium text-gray-700">{Math.round((brief.meddpicc_overall ?? 0) * 100)}%</span>
            </div>
          )}
        </div>

        {/* Top signals */}
        {brief.top_signals.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Key Signals</h2>
            <div className="space-y-2">
              {brief.top_signals.map((s, i) => {
                const level = urgencyLevel(0.7);
                return (
                  <div key={i} className={cn("flex items-start gap-2 p-2.5 rounded-lg border text-xs", URGENCY_COLOR[s.urgency] ?? URGENCY_COLOR.medium)}>
                    <span className="font-semibold">{signalLabel(s.type)}</span>
                    <span className="flex-1">{s.detail}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Next actions */}
        {brief.next_actions.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Recommended Actions</h2>
            <div className="space-y-2">
              {brief.next_actions.map((a, i) => (
                <div key={i} className="flex items-start gap-3 py-2">
                  <span className="w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 text-xs font-bold flex items-center justify-center flex-shrink-0 mt-0.5">
                    {i + 1}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800">{a.action}</p>
                    <p className="text-xs text-gray-500 mt-0.5">{a.reason}</p>
                  </div>
                  <span className={cn(
                    "text-xs font-semibold px-2 py-0.5 rounded-full flex-shrink-0",
                    a.urgency_score >= 0.85 ? "bg-red-50 text-red-600" :
                    a.urgency_score >= 0.7 ? "bg-orange-50 text-orange-600" : "bg-gray-100 text-gray-500"
                  )}>
                    {Math.round(a.urgency_score * 100)}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Stakeholders */}
        {brief.stakeholders.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3 flex items-center gap-1.5">
              <Users className="w-3.5 h-3.5" />
              Stakeholders
            </h2>
            <div className="space-y-2">
              {brief.stakeholders.map((s, i) => (
                <div key={i} className="flex items-center gap-3">
                  <div className="w-7 h-7 rounded-full bg-indigo-100 flex items-center justify-center flex-shrink-0">
                    <span className="text-xs font-bold text-indigo-700">{s.name[0]?.toUpperCase()}</span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800">{s.name}</p>
                    <p className="text-xs text-gray-400">{[s.title, s.role].filter(Boolean).join(" · ")}</p>
                  </div>
                  {s.sentiment && (
                    <span className={cn(
                      "text-xs px-1.5 py-0.5 rounded-full",
                      s.sentiment === "positive" ? "bg-green-100 text-green-700" :
                      s.sentiment === "negative" ? "bg-red-100 text-red-600" : "bg-gray-100 text-gray-500"
                    )}>
                      {s.sentiment}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="text-center py-4 border-t border-gray-200">
          <p className="text-xs text-gray-400">
            Powered by <span className="font-semibold text-indigo-600">Vantage</span> · AI-generated account brief · Read-only
          </p>
        </div>
      </div>
    </div>
  );
}

export default function SharePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  return (
    <Providers>
      <SharedBriefPage token={token} />
    </Providers>
  );
}
