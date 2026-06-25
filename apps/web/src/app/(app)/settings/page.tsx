"use client";

/**
 * Settings - Workspace configuration, team management, integrations, API keys.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { workspaceApi, authApi, type AiField, type AutomationRule, type TeamMember, type VoiceProfile, type WebhookSubscription, type IcpProfile } from "@/lib/api";
import { cn, signalLabel, draftTypeLabel } from "@/lib/utils";
import {
  Settings,
  Users,
  Link as LinkIcon,
  Key,
  CheckCircle,
  XCircle,
  Copy,
  Eye,
  EyeOff,
  Trash2,
  Plus,
  RefreshCw,
  ExternalLink,
  Shield,
  Zap,
} from "lucide-react";

// ── Section wrapper ───────────────────────────────────────────────────────────

function Section({ title, description, children }: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
      <div className="px-6 py-4 border-b border-gray-100">
        <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
        {description && <p className="text-xs text-gray-400 mt-0.5">{description}</p>}
      </div>
      <div className="px-6 py-5">{children}</div>
    </div>
  );
}

// ── Integration row ───────────────────────────────────────────────────────────

function IntegrationRow({
  name,
  description,
  icon: Icon,
  connected,
  detail,
  onConnect,
  onDisconnect,
  onSync,
  syncPending,
  syncResult,
}: {
  name: string;
  description: string;
  icon: React.FC<{ className?: string }>;
  connected: boolean;
  detail?: string;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onSync?: () => void;
  syncPending?: boolean;
  syncResult?: string | null;
}) {
  return (
    <div className="py-4 border-b border-gray-50 last:border-0">
      <div className="flex items-center gap-4">
        <div className="w-10 h-10 rounded-lg bg-gray-100 flex items-center justify-center flex-shrink-0">
          <Icon className="w-5 h-5 text-gray-600" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium text-gray-900">{name}</p>
            <span className={cn(
              "text-xs px-1.5 py-0.5 rounded-full font-medium",
              connected ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"
            )}>
              {connected ? "Connected" : "Not connected"}
            </span>
          </div>
          <p className="text-xs text-gray-500 mt-0.5">{description}</p>
          {detail && <p className="text-xs text-gray-400 mt-0.5">{detail}</p>}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {connected && onSync && (
            <button
              onClick={onSync}
              disabled={syncPending}
              className="flex items-center gap-1.5 text-xs font-medium text-gray-600 hover:text-gray-800 px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
              title="Re-pull all deals from HubSpot and resolve stage labels"
            >
              <RefreshCw className={cn("w-3.5 h-3.5", syncPending && "animate-spin")} />
              {syncPending ? "Syncing..." : "Sync now"}
            </button>
          )}
          {connected ? (
            <button
              onClick={onDisconnect}
              className="text-xs text-red-500 hover:text-red-700 font-medium transition-colors"
            >
              Disconnect
            </button>
          ) : (
            <button
              onClick={onConnect}
              className="flex items-center gap-1.5 text-xs font-medium text-brand-600 hover:text-brand-700 px-3 py-1.5 border border-brand-200 rounded-lg hover:bg-brand-50 transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              Connect
            </button>
          )}
        </div>
      </div>
      {syncResult && (
        <p className="text-xs text-green-600 mt-2 ml-14">{syncResult}</p>
      )}
    </div>
  );
}

// ── Team member row ───────────────────────────────────────────────────────────

function TeamRow({ member }: { member: TeamMember }) {
  const roleStyle: Record<string, string> = {
    admin:   "bg-brand-100 text-brand-700",
    manager: "bg-purple-100 text-purple-700",
    rep:     "bg-gray-100 text-gray-600",
  };

  return (
    <div className="flex items-center gap-3 py-3 border-b border-gray-50 last:border-0">
      <div className="w-8 h-8 rounded-full bg-brand-100 flex items-center justify-center flex-shrink-0">
        <span className="text-sm font-semibold text-brand-700">
          {member.email[0].toUpperCase()}
        </span>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900 truncate">{member.email}</p>
        {member.hubspot_owner_id && (
          <p className="text-xs text-gray-400">HubSpot owner: {member.hubspot_owner_id}</p>
        )}
      </div>
      <span className={cn("text-xs font-medium px-2 py-0.5 rounded-full capitalize", roleStyle[member.role] ?? "bg-gray-100 text-gray-600")}>
        {member.role}
      </span>
    </div>
  );
}

// ── API Key display ───────────────────────────────────────────────────────────

function ApiKeyRow({ apiKey, onDelete }: { apiKey: { id: string; name: string; prefix: string; created_at?: string }; onDelete: (id: string) => void }) {
  const [revealed, setRevealed] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(apiKey.prefix + "...");
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex items-center gap-3 py-3 border-b border-gray-50 last:border-0">
      <div className="w-8 h-8 rounded-lg bg-gray-100 flex items-center justify-center flex-shrink-0">
        <Key className="w-4 h-4 text-gray-500" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-900">{apiKey.name}</p>
        <div className="flex items-center gap-1.5 mt-0.5">
          <code className="text-xs text-gray-400 font-mono">
            {revealed ? apiKey.prefix + "••••••••••••••••" : "vnt_live_••••••••••••"}
          </code>
          <button onClick={() => setRevealed(!revealed)} className="text-gray-300 hover:text-gray-500">
            {revealed ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
          </button>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={handleCopy}
          className="text-gray-400 hover:text-gray-600 transition-colors"
          title="Copy prefix"
        >
          {copied ? <CheckCircle className="w-4 h-4 text-green-500" /> : <Copy className="w-4 h-4" />}
        </button>
        <button
          onClick={() => onDelete(apiKey.id)}
          className="text-gray-300 hover:text-red-500 transition-colors"
          title="Revoke key"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [newKeyName, setNewKeyName] = useState("");
  const [freshKey, setFreshKey] = useState<string | null>(null);
  const [copiedFreshKey, setCopiedFreshKey] = useState(false);
  const [syncResult, setSyncResult] = useState<string | null>(null);
  const [templateUploading, setTemplateUploading] = useState(false);
  const [templateStatus, setTemplateStatus] = useState<string | null>(null);

  // Data
  const { data: wsData, isLoading: wsLoading } = useQuery({
    queryKey: ["workspace"],
    queryFn: workspaceApi.get,
    staleTime: 2 * 60 * 1000,
  });

  const { data: usageData } = useQuery({
    queryKey: ["workspace", "usage"],
    queryFn: workspaceApi.getUsage,
    staleTime: 2 * 60 * 1000,
  });

  const { data: teamData } = useQuery({
    queryKey: ["workspace", "team"],
    queryFn: workspaceApi.getTeam,
    staleTime: 5 * 60 * 1000,
  });

  const { data: meData } = useQuery({
    queryKey: ["me"],
    queryFn: authApi.me,
    staleTime: 5 * 60 * 1000,
  });

  const ws = wsData?.data;
  const usage = usageData?.data;
  const team = teamData?.data ?? [];
  const me = meData?.data;
  const isAdmin = me?.role === "admin" || me?.is_manager;

  // HubSpot connect
  const connectHubspot = () => {
    window.location.href = "/auth/hubspot";
  };

  const disconnectHubspot = useMutation({
    mutationFn: () => workspaceApi.updateSettings({ hubspot_tokens: null }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workspace"] }),
  });

  // HubSpot manual sync
  const syncHubspot = useMutation({
    mutationFn: workspaceApi.syncHubspot,
    onSuccess: (data) => {
      const d = data.data;
      setSyncResult(`Sync complete: ${d.created} created, ${d.updated} updated, ${d.unchanged} unchanged${d.errors ? `, ${d.errors} errors` : ""}`);
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      setTimeout(() => setSyncResult(null), 8000);
    },
    onError: () => setSyncResult("Sync failed - check API connection"),
  });

  // API key creation (calls a hypothetical endpoint - wired through workspace router)
  const createApiKey = useMutation({
    mutationFn: async (name: string) => {
      const res = await fetch("/v1/workspace/api-keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ name }),
      });
      if (!res.ok) throw new Error("Failed to create key");
      return res.json() as Promise<{ data: { raw_key: string; id: string; name: string } }>;
    },
    onSuccess: (data) => {
      setFreshKey(data.data.raw_key);
      setNewKeyName("");
      queryClient.invalidateQueries({ queryKey: ["workspace"] });
    },
  });

  // AI fields config
  const [newFieldQuestion, setNewFieldQuestion] = useState("");
  const [newFieldKey, setNewFieldKey] = useState("");

  // Automation rules
  const [ruleForm, setRuleForm] = useState<{ name: string; trigger_type: string; signal_type: string; action_type: string; draft_type: string; cooldown: string } | null>(null);

  // Webhook subscriptions
  const [webhookUrl, setWebhookUrl] = useState("");

  const addAiField = useMutation({
    mutationFn: () => {
      const current: AiField[] = (ws?.settings?.ai_fields as AiField[] | undefined) ?? [];
      const newField: AiField = { id: crypto.randomUUID(), question: newFieldQuestion.trim(), key: newFieldKey.trim() || newFieldQuestion.trim().toLowerCase().replace(/\W+/g, "_").slice(0, 30) };
      return workspaceApi.updateSettings({ ai_fields: [...current, newField] });
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["workspace"] }); setNewFieldQuestion(""); setNewFieldKey(""); },
  });

  const removeAiField = useMutation({
    mutationFn: (fieldId: string) => {
      const current: AiField[] = (ws?.settings?.ai_fields as AiField[] | undefined) ?? [];
      return workspaceApi.updateSettings({ ai_fields: current.filter(f => f.id !== fieldId) });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workspace"] }),
  });

  const saveRule = useMutation({
    mutationFn: (rule: AutomationRule) => {
      const current: AutomationRule[] = (ws?.settings?.automation_rules as AutomationRule[] | undefined) ?? [];
      const existing = current.findIndex(r => r.id === rule.id);
      const updated = existing >= 0 ? current.map((r, i) => i === existing ? rule : r) : [...current, rule];
      return workspaceApi.updateSettings({ automation_rules: updated });
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["workspace"] }); setRuleForm(null); },
  });

  const toggleRule = useMutation({
    mutationFn: (ruleId: string) => {
      const current: AutomationRule[] = (ws?.settings?.automation_rules as AutomationRule[] | undefined) ?? [];
      return workspaceApi.updateSettings({ automation_rules: current.map(r => r.id === ruleId ? { ...r, enabled: !r.enabled } : r) });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workspace"] }),
  });

  const addWebhook = useMutation({
    mutationFn: () => workspaceApi.addWebhook({ url: webhookUrl.trim(), events: ["all"] }),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["workspace"] }); setWebhookUrl(""); },
  });

  const deleteWebhook = useMutation({
    mutationFn: (id: string) => workspaceApi.deleteWebhook(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workspace"] }),
  });

  // Voice profile
  const analyzeVoice = useMutation({
    mutationFn: workspaceApi.analyzeVoiceProfile,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workspace"] }),
  });

  const deleteApiKey = useMutation({
    mutationFn: async (keyId: string) => {
      const res = await fetch(`/v1/workspace/api-keys/${keyId}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (!res.ok) throw new Error("Failed to delete key");
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workspace"] }),
  });

  // Sender identity
  const [senderDraft, setSenderDraft] = useState({
    sender_name: "",
    sender_title: "",
    sender_company: "",
    seller_domains: "",
  });
  const [senderEditing, setSenderEditing] = useState(false);
  const [senderSaving, setSenderSaving] = useState(false);

  const openSenderEdit = () => {
    setSenderDraft({
      sender_name: (ws?.settings?.sender_name as string) ?? "",
      sender_title: (ws?.settings?.sender_title as string) ?? "",
      sender_company: (ws?.settings?.sender_company as string) ?? "",
      seller_domains: ((ws?.settings?.seller_domains as string[]) ?? []).join(", "),
    });
    setSenderEditing(true);
  };

  const saveSender = async () => {
    if (senderSaving) return;
    setSenderSaving(true);
    try {
      await workspaceApi.updateSettings({
        sender_name: senderDraft.sender_name,
        sender_title: senderDraft.sender_title,
        sender_company: senderDraft.sender_company,
        seller_domains: senderDraft.seller_domains.split(",").map((s: string) => s.trim()).filter(Boolean),
      });
      queryClient.invalidateQueries({ queryKey: ["workspace"] });
      setSenderEditing(false);
    } catch { /* silent */ } finally { setSenderSaving(false); }
  };

  // ICP builder
  const icpProfile = (ws?.settings?.icp_profile as import("@/lib/api").IcpProfile | undefined) ?? {};
  const [icpDraft, setIcpDraft] = useState<import("@/lib/api").IcpProfile>({});
  const [icpEditing, setIcpEditing] = useState(false);
  const [icpSaving, setIcpSaving] = useState(false);

  const saveIcp = async () => {
    if (icpSaving) return;
    setIcpSaving(true);
    try {
      await workspaceApi.updateSettings({ icp_profile: icpDraft });
      queryClient.invalidateQueries({ queryKey: ["workspace"] });
      setIcpEditing(false);
    } catch { /* silent */ } finally { setIcpSaving(false); }
  };

  // Rules log
  const { data: rulesLogData } = useQuery({
    queryKey: ["rules-log"],
    queryFn: workspaceApi.getRulesLog,
    staleTime: 60 * 1000,
  });

  // Health score
  const { data: healthData } = useQuery({
    queryKey: ["workspace-health"],
    queryFn: workspaceApi.getHealthScore,
    staleTime: 5 * 60 * 1000,
  });

  if (wsLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-6 h-6 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-3xl space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Settings</h1>
        <p className="text-sm text-gray-400 mt-0.5">Workspace configuration and integrations</p>
      </div>

      {/* Agent config completeness banner */}
      {ws && (!ws.settings?.sender_name || !ws.settings?.product_description) && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 flex items-start gap-3">
          <span className="text-yellow-500 text-base mt-0.5">&#9888;</span>
          <div>
            <div className="font-medium text-yellow-900 text-sm">Agent context not configured</div>
            <div className="text-yellow-700 text-sm mt-0.5">
              Your agents need your product and ICP context to generate accurate emails and scores.
              Fill in the <strong>Sender Identity</strong> and <strong>Sales Intelligence</strong> sections below.
            </div>
          </div>
        </div>
      )}

      {/* Workspace overview */}
      <Section title="Workspace" description="Your Vantage workspace details and usage">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium text-gray-400 uppercase tracking-wide">Workspace</label>
            <p className="text-sm font-medium text-gray-900 mt-1">{ws?.name ?? "-"}</p>
            <p className="text-xs text-gray-400">{ws?.slug}</p>
          </div>
          <div>
            <label className="text-xs font-medium text-gray-400 uppercase tracking-wide">Plan</label>
            <p className="text-sm font-medium text-gray-900 mt-1 capitalize">{ws?.plan ?? "-"}</p>
          </div>
          {usage && (
            <>
              <div>
                <label className="text-xs font-medium text-gray-400 uppercase tracking-wide">DAR (all time)</label>
                <div className="mt-1 flex items-center gap-2">
                  <span className={cn(
                    "text-lg font-bold",
                    usage.drafts.dar >= 0.6 ? "text-green-600" : "text-amber-600"
                  )}>
                    {Math.round(usage.drafts.dar * 100)}%
                  </span>
                  <span className="text-xs text-gray-400">target 60%</span>
                </div>
              </div>
              <div>
                <label className="text-xs font-medium text-gray-400 uppercase tracking-wide">LLM Cost (30d)</label>
                <p className="text-lg font-bold text-gray-900 mt-1">${usage.llm_costs_30d.total_usd.toFixed(2)}</p>
                <p className="text-xs text-gray-400">{usage.llm_costs_30d.run_count} runs · ${usage.llm_costs_30d.cost_per_run.toFixed(4)} each</p>
              </div>
            </>
          )}
        </div>
      </Section>

      {/* Integrations */}
      <Section title="Integrations" description="Connect your CRM and research tools">
        <IntegrationRow
          name="HubSpot"
          description="Sync deals, log drafted emails, receive webhooks on deal changes"
          icon={({ className }) => (
            <svg className={className} viewBox="0 0 24 24" fill="currentColor">
              <path d="M18.164 7.93V5.998a1.56 1.56 0 0 0 .912-1.42V4.56a1.56 1.56 0 0 0-1.56-1.56h-.018a1.56 1.56 0 0 0-1.56 1.56v.018a1.56 1.56 0 0 0 .913 1.42V7.93a4.45 4.45 0 0 0-2.12.924L7.786 4.386a1.74 1.74 0 1 0-.938.938l6.831 4.384A4.47 4.47 0 0 0 13.22 12a4.47 4.47 0 0 0 .459 1.956L7.848 17.94a1.74 1.74 0 1 0 .938.938l5.834-3.987a4.45 4.45 0 1 0 3.544-6.96z"/>
            </svg>
          )}
          connected={ws?.integrations.hubspot.connected ?? false}
          detail={ws?.integrations.hubspot.portal_id ? `Portal: ${ws.integrations.hubspot.portal_id}` : undefined}
          onConnect={connectHubspot}
          onDisconnect={() => disconnectHubspot.mutate()}
          onSync={() => syncHubspot.mutate()}
          syncPending={syncHubspot.isPending}
          syncResult={syncResult}
        />
        <IntegrationRow
          name="Perplexity"
          description="Real-time web research for account intelligence (sonar-pro)"
          icon={Zap}
          connected={ws?.integrations.perplexity.connected ?? false}
          detail="Configured via API key in environment"
        />
        <IntegrationRow
          name="Microsoft Outlook"
          description="Send drafted emails directly via your Outlook mailbox (Approve &amp; Send)"
          icon={({ className }) => (
            <svg className={className} viewBox="0 0 24 24" fill="currentColor">
              <path d="M7.88 12.04q0 .45-.11.87-.1.41-.33.74-.22.33-.58.52-.37.2-.87.2t-.85-.2q-.35-.21-.57-.55-.22-.33-.33-.75-.1-.42-.1-.86t.1-.87q.1-.43.34-.76.22-.34.59-.54.36-.2.87-.2t.86.2q.35.21.57.55.22.34.31.77.1.43.1.88zM24 12v9.38q0 .46-.33.8-.33.32-.8.32H7.13q-.46 0-.8-.33-.32-.33-.32-.8V18H1q-.41 0-.7-.3-.3-.29-.3-.7V7q0-.41.3-.7Q.58 6 1 6h6.5V2.55q0-.44.3-.75.3-.3.75-.3h12.9q.44 0 .75.3.3.3.3.75V10.85l1.24.72q.07.04.11.12.03.08.04.17-.01.07-.04.17-.04.1-.1.14zm-5.9 4.65L14 14.35v3.65zm0-9.3v4.28l1.01.59 3.23-3.79zm-12.71 5.2q-.7 0-1.2-.27-.49-.27-.83-.72-.34-.46-.51-1.05-.17-.59-.17-1.24 0-.65.17-1.25.17-.59.52-1.04.35-.45.86-.72.5-.27 1.17-.27.66 0 1.15.27.5.28.83.74.34.46.51 1.05.17.6.17 1.24 0 .66-.17 1.24-.17.6-.52 1.06-.34.46-.84.72-.5.27-1.15.27zm6.2 4.12V9.95l-4.76 2.76 4.76 2.96z"/>
            </svg>
          )}
          connected={ws?.integrations?.outlook?.connected ?? false}
          detail={ws?.integrations?.outlook?.user_email ? `Sending as: ${ws.integrations.outlook.user_email}` : "Connect to enable Approve & Send from War Room"}
          onConnect={() => {
            fetch("/api/v1/workspace/integrations/outlook/connect", { credentials: "include" })
              .then(r => r.json())
              .then(d => {
                const url = d.data?.auth_url;
                if (url) {
                  const allowed = ["login.microsoftonline.com", "login.live.com", "microsoft.com"];
                  try {
                    const host = new URL(url).hostname;
                    if (allowed.some(a => host === a || host.endsWith("." + a))) {
                      window.location.href = url;
                    }
                  } catch {}
                }
              });
          }}
          onDisconnect={() => {
            fetch("/api/v1/workspace/integrations/outlook/disconnect", { method: "POST", credentials: "include" })
              .then(() => window.location.reload());
          }}
        />
        <IntegrationRow
          name="Gong"
          description="Sync call transcripts — past conversations surface automatically in every account's War Room"
          icon={({ className }) => <svg className={className} viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="10"/></svg>}
          connected={ws?.integrations.gong.connected ?? false}
          detail="GraphQL API · transcripts are matched to accounts within minutes of call end"
        />
      </Section>

      {/* Writing Voice Profile (C2) */}
      <Section title="Writing Voice Profile" description="Teach the AI to match your email style - auto-detected from sent emails">
        {(() => {
          const vp = ws?.settings?.voice_profile as VoiceProfile | undefined;
          return (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  {vp ? (
                    <p className="text-xs text-gray-500">
                      Analyzed {vp.emails_analyzed} emails from {vp.source} ·{" "}
                      {vp.analyzed_at ? new Date(vp.analyzed_at).toLocaleDateString() : ""}
                    </p>
                  ) : (
                    <p className="text-xs text-gray-400">
                      Not yet analyzed. Run analysis to have drafts match your writing style automatically.
                    </p>
                  )}
                </div>
                <button
                  onClick={() => analyzeVoice.mutate()}
                  disabled={analyzeVoice.isPending}
                  className="flex items-center gap-1.5 text-xs font-medium bg-brand-600 text-white px-3 py-1.5 rounded-lg hover:bg-brand-700 transition-colors disabled:opacity-50"
                >
                  <RefreshCw className={cn("w-3.5 h-3.5", analyzeVoice.isPending && "animate-spin")} />
                  {analyzeVoice.isPending ? "Analyzing..." : vp ? "Re-analyze" : "Analyze from Emails"}
                </button>
              </div>
              {analyzeVoice.isError && (
                <p className="text-xs text-red-600">
                  {(analyzeVoice.error as Error)?.message ?? "Analysis failed"}
                </p>
              )}
              {vp && (
                <div className="bg-gray-50 border border-gray-100 rounded-xl p-4 space-y-2">
                  <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
                    <div>
                      <span className="text-gray-400 font-medium">Tone</span>
                      <p className="text-gray-700 mt-0.5">{vp.tone}</p>
                    </div>
                    <div>
                      <span className="text-gray-400 font-medium">Avg length</span>
                      <p className="text-gray-700 mt-0.5">{vp.avg_word_count} words</p>
                    </div>
                    {vp.common_openers?.length > 0 && (
                      <div className="col-span-2">
                        <span className="text-gray-400 font-medium">Opens with</span>
                        <p className="text-gray-700 mt-0.5">{vp.common_openers.slice(0, 3).join(", ")}</p>
                      </div>
                    )}
                    {vp.common_ctas?.length > 0 && (
                      <div className="col-span-2">
                        <span className="text-gray-400 font-medium">Calls to action</span>
                        <p className="text-gray-700 mt-0.5">{vp.common_ctas.slice(0, 2).join(", ")}</p>
                      </div>
                    )}
                    {vp.avoids?.length > 0 && (
                      <div className="col-span-2">
                        <span className="text-gray-400 font-medium">Avoids</span>
                        <p className="text-gray-700 mt-0.5">{vp.avoids.slice(0, 3).join(", ")}</p>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })()}
      </Section>

      {/* Team */}
      <Section title="Team" description={`${team.length} member${team.length !== 1 ? "s" : ""}`}>
        <div>
          {team.map(m => <TeamRow key={m.id} member={m} />)}
          {team.length === 0 && (
            <p className="text-sm text-gray-400 text-center py-4">No team members yet</p>
          )}
        </div>
        {isAdmin && (
          <div className="mt-4 pt-4 border-t border-gray-100">
            <button className="flex items-center gap-2 text-sm font-medium text-brand-600 hover:text-brand-700">
              <Plus className="w-4 h-4" />
              Invite team member via WorkOS
            </button>
            <p className="text-xs text-gray-400 mt-1">Invitations go through WorkOS. Members sign in with Google SSO.</p>
          </div>
        )}
      </Section>

      {/* API Keys */}
      {isAdmin && (
        <Section title="API Keys" description="For MCP server and direct API access">
          {/* Fresh key banner - shown once after creation */}
          {freshKey && (
            <div className="mb-4 p-4 bg-green-50 border border-green-200 rounded-xl">
              <div className="flex items-start gap-2">
                <CheckCircle className="w-4 h-4 text-green-600 mt-0.5 flex-shrink-0" />
                <div className="flex-1">
                  <p className="text-sm font-semibold text-green-800">API key created</p>
                  <p className="text-xs text-green-600 mt-0.5">Copy this key now. It will not be shown again.</p>
                  <div className="flex items-center gap-2 mt-2">
                    <code className="flex-1 text-xs font-mono bg-white border border-green-200 rounded-lg px-3 py-2 text-gray-700 break-all">
                      {freshKey}
                    </code>
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(freshKey);
                        setCopiedFreshKey(true);
                        setTimeout(() => setCopiedFreshKey(false), 2000);
                      }}
                      className="flex-shrink-0 p-2 text-green-700 hover:bg-green-100 rounded-lg transition-colors"
                    >
                      {copiedFreshKey ? <CheckCircle className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                    </button>
                  </div>
                </div>
                <button onClick={() => setFreshKey(null)} className="text-green-400 hover:text-green-600">
                  <XCircle className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}

          {/* Existing keys */}
          <div className="mb-4">
            {/* Placeholder - real list would come from workspace API */}
            <p className="text-xs text-gray-400 italic">Keys are listed here when created.</p>
          </div>

          {/* Create new key */}
          <div className="pt-4 border-t border-gray-100">
            <p className="text-sm font-medium text-gray-800 mb-2">Create new key</p>
            <div className="flex items-center gap-2">
              <input
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                placeholder="Key name (e.g. MCP Server, Claude Desktop)"
                className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:border-brand-400"
                onKeyDown={(e) => e.key === "Enter" && newKeyName.trim() && createApiKey.mutate(newKeyName)}
              />
              <button
                onClick={() => newKeyName.trim() && createApiKey.mutate(newKeyName)}
                disabled={!newKeyName.trim() || createApiKey.isPending}
                className="flex items-center gap-1.5 px-4 py-2 bg-brand-600 text-white text-sm font-medium rounded-lg hover:bg-brand-700 disabled:opacity-40 transition-colors"
              >
                {createApiKey.isPending ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <Plus className="w-4 h-4" />
                )}
                Create
              </button>
            </div>
            <p className="text-xs text-gray-400 mt-1.5">
              Use this key with the{" "}
              <a href="https://github.com/vantage-ai/mcp-server" className="text-brand-600 hover:underline" target="_blank" rel="noopener">
                Vantage MCP Server
              </a>
              {" "}to query account context from Claude Desktop.
            </p>
          </div>
        </Section>
      )}

      {/* AI Field Extraction (L1) */}
      {isAdmin && (
        <Section title="AI Fields" description="Custom questions the agent answers for every account on every run">
          <div className="space-y-3">
            {((ws?.settings?.ai_fields as AiField[] | undefined) ?? []).map((field: AiField) => (
              <div key={field.id} className="flex items-start justify-between gap-3 py-2 border-b border-gray-50 last:border-0">
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-800">{field.question}</p>
                  <p className="text-xs text-gray-400 mt-0.5">Stored as: <code className="font-mono">{field.key}</code></p>
                </div>
                <button onClick={() => removeAiField.mutate(field.id)} className="text-gray-300 hover:text-red-400 flex-shrink-0">
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
            <div className="pt-3 space-y-2">
              <input
                value={newFieldQuestion}
                onChange={e => setNewFieldQuestion(e.target.value)}
                placeholder="Question, e.g. What is the buyer's strategic priority?"
                className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:border-brand-400"
              />
              <div className="flex items-center gap-2">
                <input
                  value={newFieldKey}
                  onChange={e => setNewFieldKey(e.target.value)}
                  placeholder="Field key (auto-generated if blank)"
                  className="flex-1 text-xs border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:border-brand-400 font-mono"
                />
                <button
                  onClick={() => newFieldQuestion.trim() && addAiField.mutate()}
                  disabled={!newFieldQuestion.trim() || addAiField.isPending}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-brand-600 text-white text-xs font-medium rounded-lg hover:bg-brand-700 disabled:opacity-40 transition-colors"
                >
                  <Plus className="w-3.5 h-3.5" />
                  Add Field
                </button>
              </div>
            </div>
          </div>
        </Section>
      )}

      {/* Automation Rules (K2) */}
      {isAdmin && (
        <Section title="Automation Rules" description="Trigger drafts or alerts automatically based on deal conditions">
          <div className="space-y-3">
            {((ws?.settings?.automation_rules as AutomationRule[] | undefined) ?? []).map((rule: AutomationRule) => (
              <div key={rule.id} className={cn("flex items-start justify-between gap-3 p-3 rounded-xl border", rule.enabled ? "bg-white border-gray-200" : "bg-gray-50 border-gray-100")}>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={cn("w-2 h-2 rounded-full flex-shrink-0", rule.enabled ? "bg-green-400" : "bg-gray-300")} />
                    <p className="text-sm font-medium text-gray-800">{rule.name}</p>
                  </div>
                  <p className="text-xs text-gray-400 mt-0.5 ml-4">
                    When: {rule.trigger.type.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}{rule.trigger.signal_type ? ` (${signalLabel(rule.trigger.signal_type)})` : ""}
                    {" · "}Then: {rule.action.type.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}{rule.action.draft_type ? ` (${draftTypeLabel(rule.action.draft_type)})` : ""}
                    {" · "}{rule.cooldown_hours / 24}d cooldown
                  </p>
                </div>
                <button onClick={() => toggleRule.mutate(rule.id)} className={cn("text-xs px-2 py-1 rounded-lg border transition-colors", rule.enabled ? "border-green-200 text-green-700 hover:bg-green-50" : "border-gray-200 text-gray-500 hover:bg-gray-50")}>
                  {rule.enabled ? "Disable" : "Enable"}
                </button>
              </div>
            ))}
            {((ws?.settings?.automation_rules as AutomationRule[] | undefined) ?? []).length === 0 && (
              <p className="text-xs text-gray-400 italic">No rules yet. Add one below.</p>
            )}
            {ruleForm ? (
              <div className="p-3 bg-gray-50 rounded-xl border border-gray-200 space-y-2">
                <input value={ruleForm.name} onChange={e => setRuleForm(f => f ? { ...f, name: e.target.value } : f)} placeholder="Rule name" className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none" />
                <div className="grid grid-cols-2 gap-2">
                  <select value={ruleForm.trigger_type} onChange={e => setRuleForm(f => f ? { ...f, trigger_type: e.target.value } : f)} className="text-xs border border-gray-200 rounded-lg px-2 py-1.5">
                    <option value="signal_detected">Signal detected</option>
                    <option value="health_drop">Health drop</option>
                    <option value="stage_changed">Stage changed</option>
                    <option value="close_date_passed">Close date passed</option>
                  </select>
                  {ruleForm.trigger_type === "signal_detected" && (
                    <input value={ruleForm.signal_type} onChange={e => setRuleForm(f => f ? { ...f, signal_type: e.target.value } : f)} placeholder="Signal type (e.g. champion_dark)" className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 font-mono" />
                  )}
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <select value={ruleForm.action_type} onChange={e => setRuleForm(f => f ? { ...f, action_type: e.target.value } : f)} className="text-xs border border-gray-200 rounded-lg px-2 py-1.5">
                    <option value="create_draft">Create draft</option>
                    <option value="send_teams_alert">Send Teams alert</option>
                    <option value="set_next_step">Set next step</option>
                  </select>
                  {ruleForm.action_type === "create_draft" && (
                    <select value={ruleForm.draft_type} onChange={e => setRuleForm(f => f ? { ...f, draft_type: e.target.value } : f)} className="text-xs border border-gray-200 rounded-lg px-2 py-1.5">
                      <option value="champion_reengagement">Champion reengagement</option>
                      <option value="close_plan_proposal">Close plan proposal</option>
                      <option value="executive_alignment">Executive alignment</option>
                      <option value="competitive_displacement">Competitive displacement</option>
                    </select>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <input value={ruleForm.cooldown} onChange={e => setRuleForm(f => f ? { ...f, cooldown: e.target.value } : f)} placeholder="Cooldown hours (e.g. 168)" className="w-28 text-xs border border-gray-200 rounded-lg px-2 py-1.5" type="number" min="1" />
                  <span className="text-xs text-gray-400">hours cooldown</span>
                  <div className="ml-auto flex items-center gap-2">
                    <button onClick={() => saveRule.mutate({ id: crypto.randomUUID(), name: ruleForm.name, trigger: { type: ruleForm.trigger_type, signal_type: ruleForm.signal_type || undefined }, action: { type: ruleForm.action_type, draft_type: ruleForm.draft_type || undefined }, enabled: true, cooldown_hours: parseInt(ruleForm.cooldown) || 168 })} className="text-xs font-medium px-3 py-1.5 bg-brand-600 text-white rounded-lg hover:bg-brand-700">Save</button>
                    <button onClick={() => setRuleForm(null)} className="text-xs text-gray-500 px-2 py-1.5">Cancel</button>
                  </div>
                </div>
              </div>
            ) : (
              <button onClick={() => setRuleForm({ name: "", trigger_type: "signal_detected", signal_type: "", action_type: "create_draft", draft_type: "champion_reengagement", cooldown: "168" })} className="flex items-center gap-1.5 text-xs font-medium text-brand-600 hover:text-brand-700 px-3 py-2 border border-brand-200 rounded-lg hover:bg-brand-50 transition-colors">
                <Plus className="w-3.5 h-3.5" />
                New Rule
              </button>
            )}
          </div>
        </Section>
      )}

      {/* Outbound Webhooks (Q2) */}
      {isAdmin && (
        <Section title="Outbound Webhooks" description="Receive Vantage events in Zapier, Make, or any HTTP endpoint">
          <div className="space-y-3">
            {((ws?.settings?.webhook_subscriptions as WebhookSubscription[] | undefined) ?? []).map((sub: WebhookSubscription) => (
              <div key={sub.id} className="flex items-center justify-between gap-3 py-2 border-b border-gray-50 last:border-0">
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-mono text-gray-700 truncate">{sub.url}</p>
                  <p className="text-xs text-gray-400 mt-0.5">{sub.events.join(", ")}</p>
                </div>
                <button onClick={() => deleteWebhook.mutate(sub.id)} className="text-gray-300 hover:text-red-400 flex-shrink-0">
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
            <div className="pt-2 flex items-center gap-2">
              <input
                value={webhookUrl}
                onChange={e => setWebhookUrl(e.target.value)}
                placeholder="https://hooks.zapier.com/..."
                className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:border-brand-400"
              />
              <button
                onClick={() => webhookUrl.trim() && addWebhook.mutate()}
                disabled={!webhookUrl.trim() || addWebhook.isPending}
                className="flex items-center gap-1.5 px-3 py-2 bg-brand-600 text-white text-xs font-medium rounded-lg hover:bg-brand-700 disabled:opacity-40 transition-colors flex-shrink-0"
              >
                <Plus className="w-3.5 h-3.5" />
                Add
              </button>
            </div>
            <p className="text-xs text-gray-400">Events: signal.critical, draft.created, draft.approved, agent.run_complete, and more. Signed with HMAC-SHA256.</p>
          </div>
        </Section>
      )}

      {/* ── Workspace Health Score ─────────────────────────────────────────────── */}
      {healthData && (
        <Section title="Workspace Health" description="Configuration completeness - higher = better agent output">
          <div className="flex items-center gap-4 mb-4">
            <div className={cn(
              "text-3xl font-bold tabular",
              (healthData.data.score ?? 0) >= 80 ? "text-green-600" :
              (healthData.data.score ?? 0) >= 60 ? "text-amber-600" : "text-red-600"
            )}>
              {healthData.data.score}<span className="text-base font-normal text-gray-400">/{healthData.data.max}</span>
            </div>
            <span className={cn(
              "text-xs px-2 py-1 rounded-full font-medium capitalize",
              healthData.data.status === "excellent" ? "bg-green-100 text-green-700" :
              healthData.data.status === "good" ? "bg-amber-100 text-amber-700" :
              "bg-red-100 text-red-700"
            )}>{healthData.data.status.replace("_", " ")}</span>
          </div>
          <div className="space-y-2">
            {healthData.data.checks.map((c, i) => (
              <div key={i} className="flex items-center gap-3">
                {c.ok
                  ? <CheckCircle className="w-4 h-4 text-green-500 flex-shrink-0" />
                  : <XCircle className="w-4 h-4 text-red-400 flex-shrink-0" />}
                <span className={cn("text-xs flex-1", c.ok ? "text-gray-600" : "text-gray-700 font-medium")}>{c.name}</span>
                {!c.ok && <span className="text-[10px] text-gray-400 truncate max-w-[200px]">{c.fix}</span>}
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* ── Document Templates ───────────────────────────────────────────────────── */}
      <Section title="Document Templates" description="Upload a reference proposal to teach the AI your preferred style, structure, and formatting">
        {(() => {
          const tmplName = ws?.settings?.proposal_template_name as string | undefined;
          const tmplSize = ws?.settings?.proposal_template_size_bytes as number | undefined;
          return (
            <div className="space-y-4">
              {tmplName ? (
                <div className="flex items-center gap-3 p-4 bg-green-50 border border-green-200 rounded-xl">
                  <div className="w-8 h-8 rounded-lg bg-green-100 flex items-center justify-center flex-shrink-0">
                    <svg className="w-4 h-4 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-green-800">{tmplName}</p>
                    <p className="text-xs text-green-600">{tmplSize ? `${Math.round(tmplSize / 1024)}KB` : ""} · Used as base for all AI-generated proposals</p>
                  </div>
                  <button
                    onClick={async () => {
                      await workspaceApi.deleteProposalTemplate();
                      window.location.reload();
                    }}
                    className="text-xs text-red-500 hover:text-red-700 font-medium"
                  >
                    Remove
                  </button>
                </div>
              ) : (
                <div className="p-4 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-500">
                  No template uploaded. Upload a .docx proposal to use as the structural reference.
                </div>
              )}

              <div className="space-y-2">
                <p className="text-xs text-gray-500">
                  Upload your best reference proposal (.docx). The AI will inherit its formatting, styles, and structure.
                  Claude will write new content on top using this deal&apos;s account data.
                </p>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="file"
                    accept=".docx"
                    className="hidden"
                    onChange={async (e) => {
                      const file = e.target.files?.[0];
                      if (!file) return;
                      setTemplateUploading(true);
                      setTemplateStatus(null);
                      try {
                        const buffer = await file.arrayBuffer();
                        const b64 = btoa(String.fromCharCode(...new Uint8Array(buffer)));
                        await workspaceApi.uploadProposalTemplate(b64, file.name.replace(".docx", ""));
                        setTemplateStatus(`Uploaded: ${file.name}`);
                        setTimeout(() => window.location.reload(), 800);
                      } catch (err: any) {
                        setTemplateStatus(`Error: ${err?.message ?? "Upload failed"}`);
                      } finally {
                        setTemplateUploading(false);
                      }
                    }}
                  />
                  <span className={`inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-xl border transition-colors ${
                    templateUploading ? "opacity-50 cursor-not-allowed border-gray-200 text-gray-400" : "border-brand-300 text-brand-700 hover:bg-brand-50 cursor-pointer"
                  }`}>
                    {templateUploading ? "Uploading…" : "Upload .docx Template"}
                  </span>
                </label>
                {templateStatus && (
                  <p className={`text-xs font-medium ${templateStatus.startsWith("Error") ? "text-red-600" : "text-green-600"}`}>
                    {templateStatus}
                  </p>
                )}
              </div>
            </div>
          );
        })()}
      </Section>

      {/* ── Sender Identity ───────────────────────────────────────────────────────── */}
      <Section title="Sender Identity" description="How agents sign emails and which domains to exclude from buyer analysis">
        {!senderEditing ? (
          <div className="space-y-3">
            {ws?.settings?.sender_name ? (
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div><span className="text-xs text-gray-500 block mb-0.5">Name</span><span className="font-medium">{ws.settings.sender_name as string}</span></div>
                <div><span className="text-xs text-gray-500 block mb-0.5">Title</span><span>{(ws.settings.sender_title as string) || "-"}</span></div>
                <div><span className="text-xs text-gray-500 block mb-0.5">Company</span><span>{(ws.settings.sender_company as string) || "-"}</span></div>
                <div><span className="text-xs text-gray-500 block mb-0.5">Seller domains</span><span>{((ws.settings.seller_domains as string[]) ?? []).join(", ") || "-"}</span></div>
              </div>
            ) : (
              <p className="text-sm text-gray-400">Not configured. Agents will use placeholder names in generated emails.</p>
            )}
            <button onClick={openSenderEdit} className="text-sm text-brand-600 hover:underline font-medium">
              {ws?.settings?.sender_name ? "Edit sender →" : "Configure sender →"}
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {[
              { key: "sender_name",    label: "Your name *",          placeholder: "Alex Johnson" },
              { key: "sender_title",   label: "Your title",           placeholder: "Account Executive" },
              { key: "sender_company", label: "Company name",         placeholder: "Acme Corp" },
              { key: "seller_domains", label: "Seller email domains", placeholder: "acmecorp.com, acme.io" },
            ].map(f => (
              <div key={f.key}>
                <label className="text-xs font-medium text-gray-700 block mb-1">{f.label}</label>
                <input
                  type="text"
                  value={(senderDraft as Record<string, string>)[f.key] ?? ""}
                  onChange={e => setSenderDraft(d => ({ ...d, [f.key]: e.target.value }))}
                  placeholder={f.placeholder}
                  className="w-full text-xs border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:border-brand-400"
                />
                {f.key === "seller_domains" && (
                  <p className="text-xs text-gray-400 mt-1">Comma-separated. These domains are excluded from buyer analysis.</p>
                )}
              </div>
            ))}
            <div className="flex gap-2 pt-1">
              <button onClick={saveSender} disabled={senderSaving}
                className="px-4 py-1.5 bg-brand-600 text-white text-xs rounded-lg hover:bg-brand-700 disabled:opacity-50">
                {senderSaving ? "Saving..." : "Save"}
              </button>
              <button onClick={() => setSenderEditing(false)} className="px-4 py-1.5 border border-gray-200 text-gray-600 text-xs rounded-lg hover:bg-gray-50">
                Cancel
              </button>
            </div>
          </div>
        )}
      </Section>

      {/* ── Sales Intelligence (ICP) ────────────────────────────────────────────── */}
      <Section title="Sales Intelligence" description="Define your ICP, product context, and competitive positioning for the AI agents">
        {!icpEditing ? (
          <div className="space-y-3">
            {icpProfile.product_name ? (
              <>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div><span className="text-xs text-gray-500 block mb-0.5">Product</span><span className="font-medium">{icpProfile.product_name}</span></div>
                  <div><span className="text-xs text-gray-500 block mb-0.5">Ideal Customer</span><span>{icpProfile.ideal_customer || "-"}</span></div>
                </div>
                {icpProfile.product_description && (
                  <p className="text-sm text-gray-600">{icpProfile.product_description}</p>
                )}
                {(icpProfile.differentiators ?? []).length > 0 && (
                  <div>
                    <p className="text-xs text-gray-500 mb-1">Differentiators</p>
                    <div className="flex flex-wrap gap-1.5">
                      {(icpProfile.differentiators ?? []).map((d, i) => (
                        <span key={i} className="text-xs bg-brand-50 text-brand-700 px-2 py-0.5 rounded-full">{d}</span>
                      ))}
                    </div>
                  </div>
                )}
                {(icpProfile.competitors ?? []).length > 0 && (
                  <div>
                    <p className="text-xs text-gray-500 mb-1">Main Competitors</p>
                    <div className="flex flex-wrap gap-1.5">
                      {(icpProfile.competitors ?? []).map((c, i) => (
                        <span key={i} className="text-xs bg-red-50 text-red-700 px-2 py-0.5 rounded-full">{c}</span>
                      ))}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <p className="text-sm text-gray-400">No ICP configured. Agents are using default context. Configure to get personalised drafts for your product.</p>
            )}
            <button
              onClick={() => { setIcpDraft({ ...icpProfile }); setIcpEditing(true); }}
              className="text-xs font-medium text-brand-600 hover:text-brand-700"
            >
              {icpProfile.product_name ? "Edit ICP →" : "Configure ICP →"}
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {[
              { key: "product_name",        label: "Product name",         placeholder: "e.g. Acme Analytics" },
              { key: "ideal_customer",      label: "Ideal customer",        placeholder: "HSE Director at an O&G contractor in MENA with 500+ workers" },
              { key: "product_description", label: "Product description",   placeholder: "What you sell, who it's for, top 3 capabilities" },
            ].map(f => (
              <div key={f.key}>
                <label className="text-xs font-medium text-gray-700 block mb-1">{f.label}</label>
                {f.key === "product_description" ? (
                  <textarea
                    value={(icpDraft as Record<string, string>)[f.key] ?? ""}
                    onChange={e => setIcpDraft(d => ({ ...d, [f.key]: e.target.value }))}
                    placeholder={f.placeholder} rows={3}
                    className="w-full text-xs border border-gray-200 rounded-lg px-3 py-2 resize-none focus:outline-none focus:border-brand-400"
                  />
                ) : (
                  <input type="text" value={(icpDraft as Record<string, string>)[f.key] ?? ""}
                    onChange={e => setIcpDraft(d => ({ ...d, [f.key]: e.target.value }))}
                    placeholder={f.placeholder}
                    className="w-full text-xs border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:border-brand-400"
                  />
                )}
              </div>
            ))}
            {[
              { key: "differentiators", label: "Differentiators (one per line)", placeholder: "ISO 27001 certified\nWorks with existing cameras\n60+ safety detections" },
              { key: "competitors",     label: "Main competitors (one per line)", placeholder: "Voxel AI\nChooch AI\nIntenseye" },
            ].map(f => (
              <div key={f.key}>
                <label className="text-xs font-medium text-gray-700 block mb-1">{f.label}</label>
                <textarea
                  value={((icpDraft as Record<string, string[]>)[f.key] ?? []).join("\n")}
                  onChange={e => setIcpDraft(d => ({ ...d, [f.key]: e.target.value.split("\n").map(s => s.trim()).filter(Boolean) }))}
                  placeholder={f.placeholder} rows={3}
                  className="w-full text-xs border border-gray-200 rounded-lg px-3 py-2 resize-none focus:outline-none focus:border-brand-400"
                />
              </div>
            ))}
            <div className="flex gap-2 pt-1">
              <button onClick={saveIcp} disabled={icpSaving}
                className="text-xs font-medium px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-40 transition-colors">
                {icpSaving ? "Saving..." : "Save ICP"}
              </button>
              <button onClick={() => setIcpEditing(false)} className="text-xs text-gray-400 hover:text-gray-600">Cancel</button>
            </div>
          </div>
        )}
      </Section>

      {/* ── Automation Rules Execution Log ──────────────────────────────────────── */}
      {isAdmin && (rulesLogData?.data ?? []).length > 0 && (
        <Section title="Rules Execution Log" description="Last 50 automation rule firings">
          <div className="divide-y divide-gray-50 max-h-64 overflow-y-auto">
            {(rulesLogData?.data ?? []).map(entry => (
              <div key={entry.id} className="flex items-start gap-3 py-2.5">
                <Zap className="w-3.5 h-3.5 text-brand-500 flex-shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-gray-800 truncate">{entry.account_name}</span>
                    <span className="text-xs text-gray-400">·</span>
                    <span className="text-xs text-gray-600 truncate">{entry.rule_name}</span>
                    <span className="text-xs text-gray-400 ml-auto flex-shrink-0">
                      {entry.occurred_at ? new Date(entry.occurred_at).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : ""}
                    </span>
                  </div>
                  {entry.action_taken && <p className="text-xs text-gray-400 truncate mt-0.5">{entry.action_taken}</p>}
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Security footer */}
      <div className="flex items-center gap-2 text-xs text-gray-400">
        <Shield className="w-3.5 h-3.5" />
        <span>All data is encrypted at rest and in transit. Auth via WorkOS · SOC2-ready audit log active.</span>
      </div>
    </div>
  );
}
