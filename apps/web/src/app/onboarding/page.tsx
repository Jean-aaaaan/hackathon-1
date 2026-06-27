"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Zap, Building2, Package, Plug, CheckCircle2, ChevronRight, Plus, X } from "lucide-react";
import { workspaceApi } from "@/lib/api";

type Step = "company" | "product" | "integrations" | "done";

const STEPS: { id: Step; label: string; icon: React.ReactNode }[] = [
  { id: "company", label: "Your Company", icon: <Building2 className="w-4 h-4" /> },
  { id: "product", label: "Your Product", icon: <Package className="w-4 h-4" /> },
  { id: "integrations", label: "Integrations", icon: <Plug className="w-4 h-4" /> },
  { id: "done", label: "Done", icon: <CheckCircle2 className="w-4 h-4" /> },
];

function StepIndicator({ current }: { current: Step }) {
  const idx = STEPS.findIndex((s) => s.id === current);
  return (
    <div className="flex items-center gap-2 mb-8">
      {STEPS.map((step, i) => (
        <div key={step.id} className="flex items-center gap-2">
          <div
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
              i < idx
                ? "bg-zinc-100 text-zinc-600"
                : i === idx
                ? "bg-zinc-900 text-white"
                : "bg-zinc-100 text-zinc-400"
            }`}
          >
            {i < idx ? <CheckCircle2 className="w-3 h-3" /> : step.icon}
            <span className="hidden sm:inline">{step.label}</span>
          </div>
          {i < STEPS.length - 1 && <ChevronRight className="w-3 h-3 text-zinc-300" />}
        </div>
      ))}
    </div>
  );
}

function TagInput({
  value,
  onChange,
  placeholder,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  placeholder: string;
}) {
  const [draft, setDraft] = useState("");

  const add = () => {
    const trimmed = draft.trim();
    if (trimmed && !value.includes(trimmed)) onChange([...value, trimmed]);
    setDraft("");
  };

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              add();
            }
          }}
          placeholder={placeholder}
          className="flex-1 bg-white border border-zinc-200 rounded-lg px-3 py-2 text-sm text-zinc-900 placeholder:text-zinc-400 focus:outline-none focus:border-zinc-900"
        />
        <button
          type="button"
          onClick={add}
          className="p-2 bg-zinc-100 hover:bg-zinc-200 rounded-lg text-zinc-700 transition-colors"
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {value.map((tag) => (
            <span
              key={tag}
              className="flex items-center gap-1 bg-zinc-100 text-zinc-700 text-xs px-2 py-1 rounded-md"
            >
              {tag}
              <button
                type="button"
                onClick={() => onChange(value.filter((t) => t !== tag))}
                className="text-zinc-400 hover:text-zinc-700"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("company");
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [hasWorkspace, setHasWorkspace] = useState(false);
  const [isUpdate, setIsUpdate] = useState(false);
  const [error, setError] = useState("");

  // Step 1 — Company
  const [companyName, setCompanyName] = useState("");
  const [senderName, setSenderName] = useState("");
  const [senderTitle, setSenderTitle] = useState("Account Executive");
  const [sellerDomains, setSellerDomains] = useState<string[]>([]);

  // Step 2 — Product
  const [productName, setProductName] = useState("");
  const [productDesc, setProductDesc] = useState("");
  const [differentiators, setDifferentiators] = useState<string[]>([]);
  const [competitors, setCompetitors] = useState<string[]>([]);
  const [painPoints, setPainPoints] = useState<string[]>([]);
  const [industries, setIndustries] = useState<string[]>([]);
  const [regions, setRegions] = useState<string[]>([]);
  const [dealSize, setDealSize] = useState("");
  const [salesCycle, setSalesCycle] = useState("");

  // Step 3 — Integrations
  const [outlookConnected, setOutlookConnected] = useState(false);
  const [outlookEmail, setOutlookEmail] = useState("");
  const [voiceAnalyzing, setVoiceAnalyzing] = useState(false);
  const [voiceResult, setVoiceResult] = useState<{ emails_analyzed: number; source: string } | null>(null);
  const [firefliesKey, setFirefliesKey] = useState("");
  const [firefliesSaving, setFirefliesSaving] = useState(false);
  const [firefliesConfigured, setFirefliesConfigured] = useState(false);
  const [teamsWebhook, setTeamsWebhook] = useState("");
  const [teamsSaving, setTeamsSaving] = useState(false);
  const [teamsSaved, setTeamsSaved] = useState(false);

  // Backfill from existing workspace settings on mount
  useEffect(() => {
    workspaceApi.get()
      .then(({ data }) => {
        const s = (data.settings ?? {}) as Record<string, unknown>;
        const icp = (s.icp_profile ?? {}) as Record<string, unknown>;
        const hasContext = Boolean(s.sender_name || s.product_description);

        setHasWorkspace(true);
        setIsUpdate(hasContext);

        if (data.name) setCompanyName(data.name);
        if (typeof s.sender_name === "string") setSenderName(s.sender_name);
        if (typeof s.sender_title === "string") setSenderTitle(s.sender_title);
        if (Array.isArray(s.seller_domains)) setSellerDomains(s.seller_domains as string[]);

        if (typeof icp.product_name === "string") setProductName(icp.product_name);
        if (typeof s.product_description === "string") {
          const raw = s.product_description;
          const sep = raw.indexOf(": ");
          setProductDesc(sep > -1 ? raw.slice(sep + 2) : raw);
        }
        if (Array.isArray(icp.differentiators)) setDifferentiators(icp.differentiators as string[]);
        if (Array.isArray(icp.competitors)) setCompetitors(icp.competitors as string[]);
        if (Array.isArray(icp.pain_points)) setPainPoints(icp.pain_points as string[]);
        if (Array.isArray(icp.icp_industries)) setIndustries(icp.icp_industries as string[]);
        if (Array.isArray(icp.icp_regions)) setRegions(icp.icp_regions as string[]);
        if (typeof icp.typical_deal_size === "string") setDealSize(icp.typical_deal_size);
        if (typeof icp.sales_cycle_months === "string") setSalesCycle(icp.sales_cycle_months);

        if (data.integrations?.outlook?.connected) {
          setOutlookConnected(true);
          setOutlookEmail(data.integrations.outlook.user_email ?? "");
        }
        const vp = s.voice_profile as Record<string, unknown> | undefined;
        if (vp && typeof vp.emails_analyzed === "number") {
          setVoiceResult({ emails_analyzed: vp.emails_analyzed, source: String(vp.source ?? "") });
        }
        if ((data.integrations as Record<string, unknown> & { fireflies?: { configured?: boolean } })?.fireflies?.configured) {
          setFirefliesConfigured(true);
        }
        if ((data.integrations as Record<string, unknown> & { teams?: { configured?: boolean } })?.teams?.configured) {
          setTeamsSaved(true);
        }
      })
      .catch(() => {
        setHasWorkspace(false);
        setIsUpdate(false);
      })
      .finally(() => setLoading(false));
  }, []);

  const slugify = (s: string) =>
    s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

  const handleCompanyNext = async () => {
    if (!companyName.trim() || !senderName.trim()) {
      setError("Company name and your name are required.");
      return;
    }
    setError("");

    if (hasWorkspace) {
      setStep("product");
      return;
    }

    setSaving(true);
    try {
      await workspaceApi.create({
        company_name: companyName.trim(),
        slug: slugify(companyName),
        sender_name: senderName.trim(),
        sender_title: senderTitle.trim() || "Account Executive",
        seller_domains: sellerDomains,
      });
      setHasWorkspace(true);
      setStep("product");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to create workspace.");
    } finally {
      setSaving(false);
    }
  };

  const handleProductNext = async () => {
    if (!productName.trim() || !productDesc.trim()) {
      setError("Product name and description are required.");
      return;
    }
    setError("");
    setSaving(true);
    try {
      await workspaceApi.setup({
        sender_name: senderName.trim(),
        sender_title: senderTitle.trim() || "Account Executive",
        sender_company: companyName.trim(),
        product_name: productName.trim(),
        product_description: productDesc.trim(),
        seller_domains: sellerDomains,
        icp_industries: industries,
        icp_regions: regions,
        typical_deal_size: dealSize,
        sales_cycle_months: salesCycle,
        differentiators,
        competitors,
        pain_points: painPoints,
      });
      setStep("integrations");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save product context.");
    } finally {
      setSaving(false);
    }
  };

  const handleConnectOutlook = async () => {
    setError("");
    try {
      const { data } = await workspaceApi.connectOutlook();
      if (typeof window !== "undefined") localStorage.setItem("outlook_oauth_return", "/onboarding");
      window.location.href = data.auth_url;
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start Outlook connection.");
    }
  };

  const handleAnalyzeVoice = async () => {
    setVoiceAnalyzing(true);
    setError("");
    try {
      const { data } = await workspaceApi.analyzeVoiceProfile();
      setVoiceResult({ emails_analyzed: data.emails_analyzed, source: data.source });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to analyze email voice.");
    } finally {
      setVoiceAnalyzing(false);
    }
  };

  const handleSaveFireflies = async () => {
    if (!firefliesKey.trim()) return;
    setFirefliesSaving(true);
    setError("");
    try {
      await workspaceApi.configureFireflies(firefliesKey.trim());
      setFirefliesConfigured(true);
      setFirefliesKey("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save Fireflies key.");
    } finally {
      setFirefliesSaving(false);
    }
  };

  const handleSaveTeams = async () => {
    if (!teamsWebhook.trim()) return;
    setTeamsSaving(true);
    setError("");
    try {
      await workspaceApi.updateSettings({ teams_webhook_url: teamsWebhook.trim() });
      setTeamsSaved(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save Teams webhook.");
    } finally {
      setTeamsSaving(false);
    }
  };

  const inputCls =
    "w-full bg-white border border-zinc-200 rounded-lg px-3 py-2 text-sm text-zinc-900 placeholder:text-zinc-400 focus:outline-none focus:border-zinc-900";
  const labelCls = "block text-xs font-medium text-zinc-500 mb-1";
  const btnPrimary =
    "flex items-center gap-2 bg-zinc-900 hover:bg-zinc-700 text-white text-sm font-medium px-5 py-2.5 rounded-lg transition-colors disabled:opacity-50";
  const btnSecondary =
    "text-sm text-zinc-400 hover:text-zinc-700 transition-colors";

  if (loading) {
    return (
      <div className="w-full max-w-xl flex items-center justify-center py-24">
        <div className="flex flex-col items-center gap-3 text-zinc-400">
          <div className="w-6 h-6 border-2 border-zinc-200 border-t-zinc-900 rounded-full animate-spin" />
          <span className="text-sm">Loading your workspace...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-xl">
      {/* Logo */}
      <div className="flex items-center gap-2.5 mb-6">
        <div className="w-8 h-8 bg-zinc-900 rounded-xl flex items-center justify-center">
          <Zap className="w-4 h-4 text-white" />
        </div>
        <span className="text-lg font-semibold text-zinc-900">Vantage</span>
      </div>

      <StepIndicator current={step} />

      <div className="bg-white border border-zinc-200 rounded-2xl p-8 shadow-sm">
        {error && (
          <div className="mb-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
            {error}
          </div>
        )}

        {/* ── Step 1: Company ────────────────────────────────────────── */}
        {step === "company" && (
          <div className="space-y-5">
            <div>
              <h2 className="text-lg font-semibold text-zinc-900 mb-1">
                {isUpdate ? "Update your workspace" : "Set up your workspace"}
              </h2>
              <p className="text-sm text-zinc-500">
                {isUpdate
                  ? "Your existing settings are pre-filled below. Edit anything and continue."
                  : "Tell us about your company so agents write in the right voice."}
              </p>
            </div>

            <div>
              <label className={labelCls}>Company name *</label>
              <input
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                placeholder="Acme Corp"
                className={inputCls}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>Your name *</label>
                <input
                  value={senderName}
                  onChange={(e) => setSenderName(e.target.value)}
                  placeholder="Alex Johnson"
                  className={inputCls}
                />
              </div>
              <div>
                <label className={labelCls}>Your title</label>
                <input
                  value={senderTitle}
                  onChange={(e) => setSenderTitle(e.target.value)}
                  placeholder="Account Executive"
                  className={inputCls}
                />
              </div>
            </div>

            <div>
              <label className={labelCls}>Your email domains (press Enter to add)</label>
              <TagInput
                value={sellerDomains}
                onChange={setSellerDomains}
                placeholder="acmecorp.com"
              />
              <p className="text-xs text-zinc-400 mt-1">
                Used to filter out your team from buyer participant analysis.
              </p>
            </div>

            <div className="flex justify-end pt-2">
              <button onClick={handleCompanyNext} disabled={saving} className={btnPrimary}>
                {saving ? "Creating..." : "Continue"}
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 2: Product ────────────────────────────────────────── */}
        {step === "product" && (
          <div className="space-y-5">
            <div>
              <h2 className="text-lg font-semibold text-zinc-900 mb-1">Your product</h2>
              <p className="text-sm text-zinc-500">
                Agents use this context to research accounts and draft emails.
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>Product name *</label>
                <input
                  value={productName}
                  onChange={(e) => setProductName(e.target.value)}
                  placeholder="Acme Platform"
                  className={inputCls}
                />
              </div>
              <div>
                <label className={labelCls}>Typical deal size</label>
                <input
                  value={dealSize}
                  onChange={(e) => setDealSize(e.target.value)}
                  placeholder="$50K–$200K"
                  className={inputCls}
                />
              </div>
            </div>

            <div>
              <label className={labelCls}>What does your product do? *</label>
              <textarea
                value={productDesc}
                onChange={(e) => setProductDesc(e.target.value)}
                placeholder="Two sentences: what it does and who it's for."
                rows={3}
                className={`${inputCls} resize-none`}
              />
            </div>

            <div>
              <label className={labelCls}>Key differentiators (press Enter to add)</label>
              <TagInput
                value={differentiators}
                onChange={setDifferentiators}
                placeholder="Easier to deploy than competitors"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>Target industries</label>
                <TagInput value={industries} onChange={setIndustries} placeholder="SaaS" />
              </div>
              <div>
                <label className={labelCls}>Target regions</label>
                <TagInput value={regions} onChange={setRegions} placeholder="North America" />
              </div>
            </div>

            <div>
              <label className={labelCls}>Competitors</label>
              <TagInput value={competitors} onChange={setCompetitors} placeholder="Competitor Inc" />
            </div>

            <div className="flex justify-between pt-2">
              <button onClick={() => setStep("company")} className={btnSecondary}>
                Back
              </button>
              <button onClick={handleProductNext} disabled={saving} className={btnPrimary}>
                {saving ? "Saving..." : "Continue"}
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 3: Integrations ───────────────────────────────────── */}
        {step === "integrations" && (
          <div className="space-y-5">
            <div>
              <h2 className="text-lg font-semibold text-zinc-900 mb-1">Connect your tools</h2>
              <p className="text-sm text-zinc-500">All optional — can be configured later in Settings.</p>
            </div>

            <div className="space-y-3">
              {/* HubSpot */}
              <div className="p-4 bg-zinc-50 rounded-xl border border-zinc-200 flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-zinc-900">HubSpot</span>
                    <span className="text-xs text-zinc-500 bg-zinc-100 px-2 py-0.5 rounded-full">Recommended</span>
                  </div>
                  <p className="text-xs text-zinc-500 mt-0.5">Sync deals and push approved emails directly.</p>
                </div>
                <a href="/api/auth/hubspot" className="text-xs text-zinc-700 hover:text-zinc-900 font-medium shrink-0">
                  Connect →
                </a>
              </div>

              {/* Outlook + Voice Profile */}
              <div className="p-4 bg-zinc-50 rounded-xl border border-zinc-200 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-zinc-900">Outlook</span>
                      {outlookConnected && (
                        <span className="text-xs text-zinc-600 bg-zinc-100 px-2 py-0.5 rounded-full">
                          {outlookEmail}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-zinc-500 mt-0.5">Read sent emails to match your writing voice.</p>
                  </div>
                  {outlookConnected
                    ? <span className="text-zinc-700 text-sm shrink-0">✓</span>
                    : <button onClick={handleConnectOutlook} className="text-xs text-zinc-700 hover:text-zinc-900 font-medium shrink-0">Connect →</button>
                  }
                </div>

                {outlookConnected && (
                  <div className="border-t border-zinc-200 pt-3 flex items-center justify-between">
                    <div>
                      <div className="text-xs font-medium text-zinc-700">Email voice profile</div>
                      <div className="text-xs text-zinc-500 mt-0.5">
                        {voiceResult
                          ? `${voiceResult.emails_analyzed} emails analyzed — agents will write in your tone`
                          : "Analyze sent emails so agents match your writing style."}
                      </div>
                    </div>
                    {!voiceResult
                      ? (
                        <button onClick={handleAnalyzeVoice} disabled={voiceAnalyzing}
                          className="text-xs text-zinc-700 hover:text-zinc-900 font-medium disabled:opacity-50 shrink-0">
                          {voiceAnalyzing ? "Analyzing..." : "Analyze"}
                        </button>
                      ) : (
                        <div className="flex items-center gap-3 shrink-0">
                          <span className="text-xs text-zinc-600">✓ Done</span>
                          <button onClick={handleAnalyzeVoice} disabled={voiceAnalyzing}
                            className="text-xs text-zinc-400 hover:text-zinc-700">
                            Re-run
                          </button>
                        </div>
                      )
                    }
                  </div>
                )}
              </div>

              {/* Fireflies */}
              <div className="p-4 bg-zinc-50 rounded-xl border border-zinc-200 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-zinc-900">Fireflies</span>
                      {firefliesConfigured && (
                        <span className="text-xs text-zinc-600 bg-zinc-100 px-2 py-0.5 rounded-full">Configured</span>
                      )}
                    </div>
                    <p className="text-xs text-zinc-500 mt-0.5">Auto-ingest call transcripts for meeting intelligence.</p>
                  </div>
                </div>
                {!firefliesConfigured ? (
                  <div className="space-y-2">
                    <div className="flex gap-2">
                      <input type="password" value={firefliesKey} onChange={(e) => setFirefliesKey(e.target.value)}
                        placeholder="Fireflies API key"
                        className="flex-1 bg-white border border-zinc-200 rounded-lg px-3 py-1.5 text-sm text-zinc-900 placeholder:text-zinc-400 focus:outline-none focus:border-zinc-900" />
                      <button onClick={handleSaveFireflies} disabled={firefliesSaving || !firefliesKey.trim()}
                        className="text-xs px-3 py-1.5 bg-zinc-900 hover:bg-zinc-700 text-white rounded-lg disabled:opacity-50 transition-colors shrink-0">
                        {firefliesSaving ? "Saving..." : "Save"}
                      </button>
                    </div>
                    <p className="text-xs text-zinc-400">
                      Get your key at <span className="text-zinc-600">fireflies.ai → Settings → API</span>. Then register this webhook:
                    </p>
                    <div className="flex items-center gap-2 bg-white border border-zinc-200 rounded-lg px-3 py-1.5">
                      <code className="text-xs text-zinc-500 flex-1 truncate">
                        {(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000")}/webhooks/fireflies
                      </code>
                      <button
                        onClick={() => navigator.clipboard.writeText(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/webhooks/fireflies`)}
                        className="text-xs text-zinc-400 hover:text-zinc-700 shrink-0">
                        Copy
                      </button>
                    </div>
                  </div>
                ) : (
                  <p className="text-xs text-zinc-500">
                    Key saved. Register the webhook at <span className="text-zinc-600">fireflies.ai → Settings → Webhooks</span>.
                  </p>
                )}
              </div>

              {/* Microsoft Teams */}
              <div className="p-4 bg-zinc-50 rounded-xl border border-zinc-200 space-y-3">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-zinc-900">Microsoft Teams</span>
                    {teamsSaved && (
                      <span className="text-xs text-zinc-600 bg-zinc-100 px-2 py-0.5 rounded-full">Saved</span>
                    )}
                  </div>
                  <p className="text-xs text-zinc-500 mt-0.5">Signal alerts and morning briefs in your sales channel.</p>
                </div>
                {!teamsSaved ? (
                  <div className="flex gap-2">
                    <input type="url" value={teamsWebhook} onChange={(e) => setTeamsWebhook(e.target.value)}
                      placeholder="https://outlook.office.com/webhook/..."
                      className="flex-1 bg-white border border-zinc-200 rounded-lg px-3 py-1.5 text-sm text-zinc-900 placeholder:text-zinc-400 focus:outline-none focus:border-zinc-900" />
                    <button onClick={handleSaveTeams} disabled={teamsSaving || !teamsWebhook.trim()}
                      className="text-xs px-3 py-1.5 bg-zinc-900 hover:bg-zinc-700 text-white rounded-lg disabled:opacity-50 transition-colors shrink-0">
                      {teamsSaving ? "Saving..." : "Save"}
                    </button>
                  </div>
                ) : (
                  <p className="text-xs text-zinc-500">Webhook saved — alerts will post to your channel.</p>
                )}
              </div>
            </div>

            <div className="flex justify-between pt-2">
              <button onClick={() => setStep("product")} className={btnSecondary}>Back</button>
              <button onClick={() => setStep("done")} className={btnPrimary}>
                Finish setup
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}

        {/* ── Step 4: Done ───────────────────────────────────────────── */}
        {step === "done" && (
          <div className="text-center space-y-4 py-4">
            <div className="flex justify-center">
              <div className="w-14 h-14 bg-zinc-100 rounded-full flex items-center justify-center">
                <CheckCircle2 className="w-7 h-7 text-zinc-700" />
              </div>
            </div>
            <h2 className="text-lg font-semibold text-zinc-900">
              {isUpdate ? "Settings updated" : "You're all set"}
            </h2>
            <p className="text-sm text-zinc-500 max-w-sm mx-auto">
              {isUpdate
                ? "Your agent context has been saved. The next sweep will use your updated product and ICP settings."
                : "Vantage is ready. Add your HubSpot deals and run your first agent sweep from the Inbox."}
            </p>
            <div className="flex flex-col gap-2 pt-2">
              <button
                onClick={() => router.push("/inbox")}
                className={`${btnPrimary} mx-auto`}
              >
                Go to Inbox
                <ChevronRight className="w-4 h-4" />
              </button>
              <button
                onClick={() => router.push("/settings")}
                className="text-xs text-zinc-400 hover:text-zinc-700 transition-colors"
              >
                Manage settings
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
