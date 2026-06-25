"use client";

import { useState } from "react";
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
                ? "bg-emerald-500/20 text-emerald-400"
                : i === idx
                ? "bg-brand-600 text-white"
                : "bg-zinc-800 text-zinc-500"
            }`}
          >
            {i < idx ? <CheckCircle2 className="w-3 h-3" /> : step.icon}
            <span className="hidden sm:inline">{step.label}</span>
          </div>
          {i < STEPS.length - 1 && <ChevronRight className="w-3 h-3 text-zinc-600" />}
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
          className="flex-1 bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:border-brand-500"
        />
        <button
          type="button"
          onClick={add}
          className="p-2 bg-zinc-700 hover:bg-zinc-600 rounded-lg text-zinc-300 transition-colors"
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {value.map((tag) => (
            <span
              key={tag}
              className="flex items-center gap-1 bg-zinc-700 text-zinc-200 text-xs px-2 py-1 rounded-md"
            >
              {tag}
              <button
                type="button"
                onClick={() => onChange(value.filter((t) => t !== tag))}
                className="text-zinc-400 hover:text-zinc-200"
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

  const slugify = (s: string) =>
    s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

  const handleCompanyNext = async () => {
    if (!companyName.trim() || !senderName.trim()) {
      setError("Company name and your name are required.");
      return;
    }
    setError("");
    setSaving(true);
    try {
      await workspaceApi.create({
        company_name: companyName.trim(),
        slug: slugify(companyName),
        sender_name: senderName.trim(),
        sender_title: senderTitle.trim() || "Account Executive",
        seller_domains: sellerDomains,
      });
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

  const inputCls =
    "w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:border-brand-500";
  const labelCls = "block text-xs font-medium text-zinc-400 mb-1";
  const btnPrimary =
    "flex items-center gap-2 bg-brand-600 hover:bg-brand-500 text-white text-sm font-medium px-5 py-2.5 rounded-lg transition-colors disabled:opacity-50";
  const btnSecondary =
    "text-sm text-zinc-400 hover:text-zinc-200 transition-colors";

  return (
    <div className="w-full max-w-xl">
      {/* Logo */}
      <div className="flex items-center gap-2.5 mb-6">
        <div className="w-8 h-8 bg-brand-600 rounded-xl flex items-center justify-center">
          <Zap className="w-4 h-4 text-white" />
        </div>
        <span className="text-lg font-semibold text-zinc-100">Vantage</span>
      </div>

      <StepIndicator current={step} />

      <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-8">
        {error && (
          <div className="mb-4 text-sm text-red-400 bg-red-950/40 border border-red-900/50 rounded-lg px-3 py-2">
            {error}
          </div>
        )}

        {/* ── Step 1: Company ────────────────────────────────────────── */}
        {step === "company" && (
          <div className="space-y-5">
            <div>
              <h2 className="text-lg font-semibold text-zinc-100 mb-1">Set up your workspace</h2>
              <p className="text-sm text-zinc-500">Tell us about your company so agents write in the right voice.</p>
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
              <p className="text-xs text-zinc-600 mt-1">
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
              <h2 className="text-lg font-semibold text-zinc-100 mb-1">Your product</h2>
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
                  placeholder="$50K-$200K"
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
              <h2 className="text-lg font-semibold text-zinc-100 mb-1">Connect your tools</h2>
              <p className="text-sm text-zinc-500">
                These can be set up now or later in Settings.
              </p>
            </div>

            <div className="space-y-3">
              {[
                {
                  name: "HubSpot",
                  desc: "Sync deals and push approved drafts as emails.",
                  href: "/api/auth/hubspot",
                  badge: "Recommended",
                },
                {
                  name: "Fireflies",
                  desc: "Auto-ingest call transcripts for meeting intelligence.",
                  href: null,
                  badge: "Configure in Settings",
                },
                {
                  name: "Microsoft Teams",
                  desc: "Get signal alerts and morning briefs in your sales channel.",
                  href: null,
                  badge: "Configure in Settings",
                },
              ].map((integration) => (
                <div
                  key={integration.name}
                  className="flex items-center justify-between p-4 bg-zinc-800 rounded-xl border border-zinc-700"
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-zinc-200">{integration.name}</span>
                      <span className="text-xs text-zinc-500 bg-zinc-700 px-2 py-0.5 rounded-full">
                        {integration.badge}
                      </span>
                    </div>
                    <p className="text-xs text-zinc-500 mt-0.5">{integration.desc}</p>
                  </div>
                  {integration.href ? (
                    <a
                      href={integration.href}
                      className="text-xs text-brand-400 hover:text-brand-300 font-medium"
                    >
                      Connect
                    </a>
                  ) : (
                    <span className="text-xs text-zinc-600">Later</span>
                  )}
                </div>
              ))}
            </div>

            <div className="flex justify-between pt-2">
              <button onClick={() => setStep("product")} className={btnSecondary}>
                Back
              </button>
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
              <div className="w-14 h-14 bg-emerald-500/20 rounded-full flex items-center justify-center">
                <CheckCircle2 className="w-7 h-7 text-emerald-400" />
              </div>
            </div>
            <h2 className="text-lg font-semibold text-zinc-100">You're all set</h2>
            <p className="text-sm text-zinc-500 max-w-sm mx-auto">
              Vantage is ready. Add your HubSpot deals and run your first agent sweep from the Inbox.
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
                className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
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
