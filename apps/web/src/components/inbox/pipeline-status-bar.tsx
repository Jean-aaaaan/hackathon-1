"use client";

import { useQuery } from "@tanstack/react-query";
import { workspaceApi, type WorkspaceStatus, type WorkspaceHealthScore } from "@/lib/api";
import { cn } from "@/lib/utils";
import { CheckCircle, XCircle, AlertTriangle, Zap } from "lucide-react";

function IntegrationDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      {ok
        ? <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
        : <XCircle className="w-3.5 h-3.5 text-red-400" />}
      <span className={cn("text-xs", ok ? "text-zinc-300" : "text-red-300")}>{label}</span>
    </div>
  );
}

export function PipelineStatusBar() {
  const { data } = useQuery({
    queryKey: ["workspace-status"],
    queryFn: workspaceApi.getStatus,
    staleTime: 2 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
  });
  const status: WorkspaceStatus | undefined = data?.data;

  const { data: healthData } = useQuery({
    queryKey: ["workspace-health"],
    queryFn: workspaceApi.getHealthScore,
    staleTime: 10 * 60 * 1000,
  });
  const health = healthData?.data as WorkspaceHealthScore | undefined;

  if (!status) return null;

  const { integrations, last_nightly_run, pipeline } = status;
  const lastRun = last_nightly_run.completed_at
    ? new Date(last_nightly_run.completed_at).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" })
    : null;

  return (
    <div className="bg-zinc-900 text-white px-4 py-2 flex items-center gap-5 flex-wrap text-xs flex-shrink-0">
      {/* Integration health */}
      <IntegrationDot ok={integrations.hubspot.connected} label="HubSpot" />
      <IntegrationDot ok={integrations.outlook.connected} label="Outlook" />
      <IntegrationDot ok={integrations.fireflies.configured} label="Fireflies" />

      {/* Last sync */}
      {lastRun && (
        <span className="text-zinc-500">Last sync {lastRun}</span>
      )}

      {/* Critical badge */}
      {pipeline.critical_accounts > 0 && (
        <span className="flex items-center gap-1 text-amber-300">
          <AlertTriangle className="w-3 h-3" />
          {pipeline.critical_accounts} critical
        </span>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* DAR */}
      <span className={cn(
        "font-medium",
        pipeline.dar_pct_30d >= 60 ? "text-emerald-400" :
        pipeline.dar_pct_30d >= 40 ? "text-amber-400" : "text-red-400"
      )}>
        DAR {pipeline.dar_pct_30d}%
      </span>

      {/* Workspace health pill (#10) */}
      {health && health.score < 80 && (
        <a
          href="/settings"
          className={cn(
            "flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full transition-colors",
            health.score >= 60
              ? "bg-amber-800/40 text-amber-300 hover:bg-amber-700/50"
              : "bg-red-800/40 text-red-300 hover:bg-red-700/50"
          )}
          title="Workspace setup incomplete - click to fix"
        >
          <AlertTriangle className="w-2.5 h-2.5" />
          Setup {health.score}%
        </a>
      )}

    </div>
  );
}

// ── Onboarding wizard (4-step setup) — shown until all steps are complete ────

export function OnboardingBanner() {
  const { data: statusData } = useQuery({
    queryKey: ["workspace-status"],
    queryFn: workspaceApi.getStatus,
    staleTime: 5 * 60 * 1000,
  });
  const { data: wsData } = useQuery({
    queryKey: ["workspace"],
    queryFn: workspaceApi.get,
    staleTime: 5 * 60 * 1000,
  });
  const status: WorkspaceStatus | undefined = statusData?.data;

  // Determine step completion
  const step1Done = !!status?.integrations.hubspot.connected;
  const step2Done = step1Done && (status?.pipeline.total_accounts ?? 0) > 0;
  // Step 3: ICP configured — check if product_description is set
  const settings = (wsData?.data as { settings?: Record<string, unknown> } | undefined)?.settings ?? {};
  const step3Done = step2Done && !!(settings.product_description || (settings as { icp_profile?: { product_description?: string } }).icp_profile?.product_description);
  const step4Done = step3Done && !!status?.last_nightly_run.completed_at;

  // Hide banner once all 4 steps are done
  if (step4Done) return null;
  // Also hide if we don't have data yet
  if (!status) return null;

  const steps = [
    { done: step1Done, label: "Connect HubSpot", href: "/settings", cta: "Connect" },
    { done: step2Done, label: "Sync deals", href: "/settings", cta: "Sync" },
    { done: step3Done, label: "Configure AI context", href: "/settings#icp", cta: "Configure" },
    { done: step4Done, label: "Run agents on your pipeline", href: null, cta: null },
  ];

  // Current step is first incomplete
  const currentIdx = steps.findIndex(s => !s.done);
  const currentStep = steps[currentIdx];

  const STEP_MESSAGES = [
    "Vantage monitors your deals 24/7 and generates AI-drafted emails. Connect HubSpot to sync your pipeline in under a minute.",
    "HubSpot is connected. Sync your deals to import your pipeline.",
    "Deals synced. Tell the AI about your product so it can write relevant, specific emails.",
    "AI context is set. Click Run Agents in the top bar to generate action plans and drafts across your pipeline.",
  ];

  return (
    <div className="mx-4 mt-3 rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-2.5 flex items-center gap-3 flex-shrink-0">
      <Zap className="w-3.5 h-3.5 text-indigo-500 flex-shrink-0" />
      <div className="flex items-center gap-2 flex-1 min-w-0 overflow-x-auto">
        {steps.map((step, i) => (
          <div key={step.label} className="flex items-center gap-1.5 flex-shrink-0">
            {i > 0 && <div className="h-px w-3 bg-indigo-200 flex-shrink-0" />}
            {step.done
              ? <CheckCircle className="w-3 h-3 text-emerald-500 flex-shrink-0" />
              : <div className={cn("w-3 h-3 rounded-full border-2 flex-shrink-0", i === currentIdx ? "border-indigo-500" : "border-zinc-300")} />}
            <span className={cn(
              "text-[10px] whitespace-nowrap",
              step.done ? "text-zinc-400 line-through" : i === currentIdx ? "text-indigo-700 font-medium" : "text-zinc-400"
            )}>
              {step.label}
            </span>
          </div>
        ))}
      </div>
      {currentStep?.href && (
        <a href={currentStep.href} className="flex-shrink-0 text-[11px] font-semibold text-indigo-600 hover:text-indigo-700 whitespace-nowrap">
          {currentStep.cta} →
        </a>
      )}
    </div>
  );
}
