"use client";

/**
 * Audit Panel - Our #1 differentiator over Actively AI.
 * Shows the full Gold Data audit trail for any fact.
 * Every claim is traceable to its source with confidence score.
 * Actively AI's Gold Data is opaque - ours is fully visible.
 */

import { useQuery } from "@tanstack/react-query";
import { accountsApi } from "@/lib/api";
import { X, Shield, AlertTriangle, CheckCircle, Info } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  accountId: string;
  factKey: string;
  onClose: () => void;
}

export function AuditPanel({ accountId, factKey, onClose }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ["account-state", accountId],
    queryFn: () => accountsApi.getState(accountId),
  });

  const state = data?.data ?? {};
  const goldData = (state.gold_data ?? {}) as Record<string, GoldDataPoint>;
  const point = goldData[factKey];
  const pov = (state.pov ?? {}) as Record<string, unknown>;
  const grounding = {
    confidence: state.grounding_confidence as number,
    summary: state.grounding_summary as string,
  };

  return (
    <div className="fixed inset-y-0 right-0 w-96 bg-white shadow-2xl border-l border-zinc-200 z-50 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-200">
        <div className="flex items-center gap-2">
          <Shield className="w-4 h-4 text-brand-600" />
          <h2 className="text-sm font-semibold text-zinc-900">Gold Data Audit Trail</h2>
        </div>
        <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 transition-colors">
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Grounding summary */}
      {grounding.summary && (
        <div className="px-5 py-3 bg-amber-50 border-b border-amber-100">
          <div className="flex items-start gap-2">
            <Info className="w-3.5 h-3.5 text-amber-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-xs font-medium text-amber-800">Grounding Agent Summary</p>
              <p className="text-xs text-amber-700 mt-0.5">{grounding.summary}</p>
              {grounding.confidence !== undefined && (
                <p className="text-xs text-amber-600 mt-1">
                  Overall confidence: {Math.round(grounding.confidence * 100)}%
                </p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Gold Data points */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="h-20 bg-zinc-100 rounded-lg animate-pulse" />
            ))}
          </div>
        ) : Object.keys(goldData).length === 0 ? (
          <div className="text-center py-8 text-zinc-400">
            <Shield className="w-8 h-8 mx-auto mb-2 text-zinc-300" />
            <p className="text-sm">No Gold Data available yet</p>
            <p className="text-xs mt-1">Run the agent on this account first to populate source data</p>
          </div>
        ) : (
          <div className="space-y-4">
            {Object.entries(goldData).map(([key, gd]) => (
              <GoldDataCard key={key} factKey={key} point={gd} />
            ))}
          </div>
        )}
      </div>

      {/* Footer: what this means */}
      <div className="px-5 py-4 border-t border-zinc-100 bg-zinc-50">
        <p className="text-xs text-zinc-500 leading-relaxed">
          <strong className="text-zinc-700">Source audit</strong>: Every fact is cross-referenced
          across HubSpot, Gong, Perplexity, and rep notes. Conflicts are flagged,
          not hidden. Confidence reflects how much the sources agree.
        </p>
      </div>
    </div>
  );
}


interface GoldDataPoint {
  resolved_value: string | number | boolean;
  confidence: number;
  confidence_explanation: string;
  sources: Array<{ source: string; raw_value: unknown; weight: number; last_updated: string }>;
  audit_trail: Array<{ timestamp: string; action: string; reason: string }>;
  resolved_at: string;
}

function GoldDataCard({ factKey, point }: { factKey: string; point: GoldDataPoint }) {
  const confidence = point.confidence ?? 0;
  const confidenceColor =
    confidence >= 0.85 ? "text-green-600" :
    confidence >= 0.65 ? "text-yellow-600" : "text-red-600";

  const confidenceIcon =
    confidence >= 0.85 ? <CheckCircle className="w-3.5 h-3.5 text-green-500" /> :
    confidence >= 0.65 ? <Info className="w-3.5 h-3.5 text-yellow-500" /> :
    <AlertTriangle className="w-3.5 h-3.5 text-red-500" />;

  return (
    <div className="bg-white border border-zinc-200 rounded-lg overflow-hidden">
      {/* Fact header */}
      <div className="px-3 py-2.5 border-b border-zinc-100 flex items-start justify-between">
        <div>
          <p className="text-xs font-medium text-zinc-500 uppercase tracking-wider">{factKey.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}</p>
          <p className="text-sm font-semibold text-zinc-900 mt-0.5">{String(point.resolved_value ?? "-")}</p>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {confidenceIcon}
          <span className={cn("text-xs font-medium", confidenceColor)}>
            {Math.round(confidence * 100)}%
          </span>
        </div>
      </div>

      {/* Confidence explanation */}
      {point.confidence_explanation && (
        <div className="px-3 py-2 bg-zinc-50 border-b border-zinc-100">
          <p className="text-xs text-zinc-500">{point.confidence_explanation}</p>
        </div>
      )}

      {/* Sources */}
      {point.sources?.length > 0 && (
        <div className="px-3 py-2.5">
          <p className="text-xs font-medium text-zinc-500 mb-2">Sources</p>
          <div className="space-y-1.5">
            {point.sources.map((s, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-zinc-700">{s.source}</span>
                  <span className="text-zinc-400">{String(s.raw_value ?? "-")}</span>
                </div>
                <span className="text-zinc-400">weight: {Math.round((s.weight ?? 0) * 100)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Audit trail */}
      {point.audit_trail?.length > 0 && (
        <div className="px-3 py-2.5 border-t border-zinc-100">
          <p className="text-xs font-medium text-zinc-500 mb-2">Audit Trail</p>
          <div className="space-y-1">
            {point.audit_trail.slice(-3).map((entry, i) => (
              <div key={i} className="text-xs text-zinc-400">
                <span className="text-zinc-600">{entry.action}</span>
                {entry.reason && <span>: {entry.reason}</span>}
                <span className="ml-1">{new Date(entry.timestamp).toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
