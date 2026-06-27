import Link from "next/link";
import {
  Zap, Shield, Brain, Search, FileText, Target,
  ArrowRight, CheckCircle, BarChart3, Database, TrendingUp,
} from "lucide-react";

export const metadata = {
  title: "Vantage — AI-Operated Sales Pipeline",
  description: "One AI agent per deal. Every deal, every night. Vantage monitors 24/7, surfaces what matters, and writes the emails.",
};

const STATS = [
  { value: "$0.17", label: "per agent run" },
  { value: "6", label: "specialized agents" },
  { value: "3 min", label: "to full analysis" },
  { value: "62%", label: "draft acceptance rate" },
];

const FEATURES = [
  {
    icon: Brain,
    title: "Grounded Intelligence",
    desc: "Every insight traces back to a source. Our Audit Panel shows exactly where each fact came from — HubSpot notes, email threads, call transcripts, live signals.",
    tag: "Gold Data Layer",
  },
  {
    icon: Zap,
    title: "Nightly Agent Sweep",
    desc: "Six specialized AI agents run on every deal, every night. Researcher → Risk Scanner → Grounding → Prioritiser → Drafter → State Writer.",
    tag: "Fully automated",
  },
  {
    icon: FileText,
    title: "Ready-to-send Drafts",
    desc: "Agents write the emails. You review, approve, and send — directly from the inbox. Every draft cites the signals that triggered it.",
    tag: "62% acceptance rate",
  },
  {
    icon: Shield,
    title: "Risk Vectors in Real Time",
    desc: "Five risk vectors scored per deal: champion, economic buyer, competitive, timeline, process. Know which deals are bleeding before it shows in the CRM.",
    tag: "5 risk dimensions",
  },
  {
    icon: BarChart3,
    title: "MEDDPICC at a Glance",
    desc: "Each of the 8 qualification components is scored 0–100%. Low scores surface a 'Fix →' button that creates a targeted action directly in your queue.",
    tag: "8 components",
  },
  {
    icon: TrendingUp,
    title: "Forecast Intelligence",
    desc: "AI close-date prediction vs CRM close date. Deal momentum trending. Pipeline movement this week vs last. All surfaced in the Watchtower.",
    tag: "AI predictions",
  },
];

const PIPELINE = [
  { icon: Search,    label: "Researcher",   desc: "HubSpot + emails + Fireflies + Exa web signals" },
  { icon: Shield,    label: "Risk Scanner", desc: "5 risk vectors, health score, deal momentum" },
  { icon: CheckCircle, label: "Grounding",  desc: "Every claim verified against source data" },
  { icon: Target,    label: "Prioritiser",  desc: "Urgency score, MEDDPICC, action queue order" },
  { icon: FileText,  label: "Drafter",      desc: "Personalised email with cited facts" },
  { icon: Database,  label: "State Writer", desc: "All outputs saved, indexed, searchable" },
];

const TESTIMONIAL = {
  quote: "The grounding layer is the difference. Every fact has a source. We stopped arguing about data and started closing deals.",
  author: "VP of Sales",
  company: "Series B SaaS",
};

export default function LandingPage() {
  return (
    <div className="bg-zinc-950 text-zinc-50 min-h-screen font-sans antialiased">
      {/* ── Nav ─────────────────────────────────────────────────────── */}
      <nav className="fixed top-0 inset-x-0 z-50 border-b border-zinc-800/60 bg-zinc-950/80 backdrop-blur-md">
        <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-brand-600 flex items-center justify-center">
              <Zap className="w-3.5 h-3.5 text-white" />
            </div>
            <span className="text-sm font-bold tracking-tight text-zinc-50">Vantage</span>
          </div>
          <div className="flex items-center gap-3">
            <Link href="/auth/login"
              className="text-xs font-medium text-zinc-400 hover:text-zinc-200 transition-colors px-3 py-1.5">
              Sign in
            </Link>
            <Link href="/auth/login"
              className="text-xs font-semibold bg-brand-600 hover:bg-brand-500 text-white px-4 py-2 rounded-lg transition-colors">
              Get started
            </Link>
          </div>
        </div>
      </nav>

      {/* ── Hero ────────────────────────────────────────────────────── */}
      <section className="relative pt-32 pb-24 px-6 overflow-hidden">
        {/* glow blobs */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[500px] bg-brand-600/10 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute top-40 left-1/3 w-[400px] h-[300px] bg-violet-600/8 rounded-full blur-3xl pointer-events-none" />

        <div className="relative max-w-4xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 text-xs font-medium text-brand-400 bg-brand-600/10 border border-brand-500/20 px-3.5 py-1.5 rounded-full mb-8">
            <span className="w-1.5 h-1.5 rounded-full bg-brand-400 animate-pulse" />
            One AI agent per deal, every night
          </div>

          <h1 className="text-5xl sm:text-6xl lg:text-7xl font-bold tracking-tight leading-[1.05] mb-6">
            Your pipeline,{" "}
            <span className="bg-gradient-to-r from-brand-400 via-brand-500 to-violet-400 bg-clip-text text-transparent">
              AI&#8209;operated.
            </span>
          </h1>

          <p className="text-lg text-zinc-400 max-w-2xl mx-auto leading-relaxed mb-10">
            Vantage runs six specialized AI agents on every deal, every night.
            It surfaces risks before they cost you the close, writes the emails,
            and shows its work — every fact cited.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link href="/auth/login"
              className="inline-flex items-center gap-2 bg-brand-600 hover:bg-brand-500 text-white font-semibold text-sm px-6 py-3 rounded-xl transition-colors shadow-lg shadow-brand-600/25">
              Start free — connect HubSpot
              <ArrowRight className="w-4 h-4" />
            </Link>
            <Link href="/inbox"
              className="inline-flex items-center gap-2 text-zinc-300 hover:text-zinc-100 font-medium text-sm px-6 py-3 rounded-xl border border-zinc-700/60 hover:border-zinc-600 transition-colors">
              View live demo
            </Link>
          </div>

          <p className="mt-5 text-xs text-zinc-600">No credit card · HubSpot OAuth in 30s · First sweep in under 3 minutes</p>
        </div>

        {/* Dashboard mockup */}
        <div className="relative max-w-5xl mx-auto mt-16">
          <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/60 backdrop-blur-sm overflow-hidden shadow-2xl shadow-black/50">
            {/* Fake topbar */}
            <div className="flex items-center gap-1.5 px-4 py-3 border-b border-zinc-800/60 bg-zinc-900/80">
              <div className="w-3 h-3 rounded-full bg-zinc-700" />
              <div className="w-3 h-3 rounded-full bg-zinc-700" />
              <div className="w-3 h-3 rounded-full bg-zinc-700" />
              <div className="flex-1 ml-4 flex items-center gap-2">
                <div className="h-5 w-36 bg-zinc-800 rounded-md" />
                <div className="ml-auto flex gap-2">
                  <div className="h-5 w-20 bg-zinc-800 rounded-md" />
                  <div className="h-5 w-8 bg-brand-600/40 rounded-md" />
                </div>
              </div>
            </div>

            {/* Fake inbox grid */}
            <div className="grid grid-cols-12 min-h-[340px]">
              {/* Sidebar */}
              <div className="col-span-2 border-r border-zinc-800/60 p-3 space-y-1">
                {["Inbox", "Watchtower", "Assistant", "Analytics"].map((item, i) => (
                  <div key={item} className={`flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs ${i === 0 ? "bg-brand-600/20 text-brand-400" : "text-zinc-600"}`}>
                    <div className={`w-1.5 h-1.5 rounded-full ${i === 0 ? "bg-brand-400" : "bg-zinc-700"}`} />
                    {item}
                  </div>
                ))}
              </div>

              {/* Main — deal cards */}
              <div className="col-span-6 border-r border-zinc-800/60 p-4 space-y-2.5">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-semibold text-zinc-300">Action Queue</span>
                  <span className="text-[10px] text-zinc-600 bg-zinc-800 px-2 py-0.5 rounded-full">7 urgent</span>
                </div>
                {[
                  { name: "Meridian Ops", stage: "Proposal", urgency: 94, risk: "Champion gap", amount: "$240K" },
                  { name: "Nexus Health", stage: "Negotiation", urgency: 87, risk: "Economic buyer silent", amount: "$180K" },
                  { name: "Apex Logistics", stage: "Discovery", urgency: 71, risk: "Competitive threat", amount: "$95K" },
                ].map(deal => (
                  <div key={deal.name} className="bg-zinc-800/60 border border-zinc-700/50 rounded-xl p-3">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="text-xs font-semibold text-zinc-100">{deal.name}</p>
                        <p className="text-[10px] text-zinc-500 mt-0.5">{deal.stage} · {deal.amount}</p>
                      </div>
                      <div className="flex flex-col items-end gap-1">
                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-md ${deal.urgency >= 90 ? "bg-red-900/60 text-red-400" : deal.urgency >= 80 ? "bg-zinc-700 text-zinc-300" : "bg-zinc-800 text-zinc-400"}`}>
                          {deal.urgency}% urgency
                        </span>
                      </div>
                    </div>
                    <p className="text-[10px] text-zinc-500 mt-2 flex items-center gap-1">
                      <span className="w-1 h-1 rounded-full bg-red-500 flex-shrink-0" />
                      {deal.risk}
                    </p>
                  </div>
                ))}
              </div>

              {/* Right panel */}
              <div className="col-span-4 p-4">
                <div className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wider mb-3">Meridian Ops · AI Brief</div>
                <div className="space-y-2.5">
                  <div className="bg-zinc-800/50 rounded-lg p-2.5">
                    <p className="text-[10px] font-semibold text-zinc-400 mb-1">Urgency drivers</p>
                    <p className="text-[10px] text-zinc-500 leading-relaxed">Close date in 18 days. Champion Alex Chen on leave. No EB contacted since Oct 14.</p>
                  </div>
                  <div className="bg-brand-600/10 border border-brand-500/20 rounded-lg p-2.5">
                    <p className="text-[10px] font-semibold text-brand-400 mb-1">Draft ready</p>
                    <p className="text-[10px] text-zinc-400 leading-relaxed">"Hi Sarah, I noticed we haven't connected since your promotion to VP…"</p>
                  </div>
                  <div className="grid grid-cols-5 gap-1 mt-3">
                    {["M","E","D","D","I","C","C","P"].slice(0,5).map((l, i) => (
                      <div key={i} className="text-center">
                        <div className="text-[8px] font-black text-zinc-600 mb-1">{l}</div>
                        <div className="h-1 rounded-full bg-zinc-700 overflow-hidden">
                          <div className="h-full bg-brand-500 rounded-full" style={{ width: `${[80,45,70,30,60][i]}%` }} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
          {/* bottom glow */}
          <div className="absolute -bottom-8 left-1/2 -translate-x-1/2 w-3/4 h-16 bg-brand-600/15 blur-2xl rounded-full pointer-events-none" />
        </div>
      </section>

      {/* ── Stats bar ───────────────────────────────────────────────── */}
      <section className="border-y border-zinc-800/60 bg-zinc-900/40">
        <div className="max-w-4xl mx-auto px-6 py-10 grid grid-cols-2 md:grid-cols-4 gap-8">
          {STATS.map(s => (
            <div key={s.label} className="text-center">
              <p className="text-3xl font-bold text-zinc-50 tabular-nums">{s.value}</p>
              <p className="text-xs text-zinc-500 mt-1">{s.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Features grid ───────────────────────────────────────────── */}
      <section className="py-24 px-6">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-16">
            <p className="text-xs font-semibold text-brand-400 uppercase tracking-widest mb-3">Everything you need</p>
            <h2 className="text-3xl sm:text-4xl font-bold text-zinc-50 tracking-tight">
              Built for reps who hate busywork.
            </h2>
            <p className="mt-4 text-zinc-400 max-w-xl mx-auto text-sm leading-relaxed">
              No dashboards to maintain. No manual updates. Vantage reads your CRM, your email, your calls —
              and tells you exactly what to do next.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {FEATURES.map((f, i) => {
              const Icon = f.icon;
              return (
                <div key={i} className="group relative bg-zinc-900/60 border border-zinc-800/60 hover:border-zinc-700/80 rounded-2xl p-6 transition-all duration-200 hover:bg-zinc-900/80">
                  <div className="w-9 h-9 rounded-xl bg-brand-600/15 border border-brand-500/20 flex items-center justify-center mb-4">
                    <Icon className="w-4 h-4 text-brand-400" />
                  </div>
                  <span className="inline-block text-[10px] font-semibold text-zinc-600 uppercase tracking-wider mb-2">{f.tag}</span>
                  <h3 className="text-sm font-semibold text-zinc-100 mb-2">{f.title}</h3>
                  <p className="text-xs text-zinc-500 leading-relaxed">{f.desc}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ── Pipeline ────────────────────────────────────────────────── */}
      <section className="py-20 px-6 border-t border-zinc-800/40">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-12">
            <p className="text-xs font-semibold text-brand-400 uppercase tracking-widest mb-3">The Vantage Sweep</p>
            <h2 className="text-3xl font-bold text-zinc-50 tracking-tight">Six agents. One pipeline pass.</h2>
            <p className="mt-3 text-zinc-400 text-sm max-w-lg mx-auto">
              Every night at 2 AM — or on-demand — a coordinated pipeline runs on every deal. Each agent is specialised; each output feeds the next.
            </p>
          </div>

          <div className="relative">
            {/* connector line */}
            <div className="absolute top-8 left-8 right-8 h-px bg-gradient-to-r from-transparent via-brand-500/30 to-transparent hidden lg:block" />
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
              {PIPELINE.map((step, i) => {
                const Icon = step.icon;
                return (
                  <div key={i} className="relative flex flex-col items-center text-center">
                    <div className="relative w-16 h-16 rounded-2xl bg-zinc-900 border border-zinc-800 flex items-center justify-center mb-3 z-10">
                      <Icon className="w-6 h-6 text-brand-400" />
                      <span className="absolute -top-2 -right-2 w-4 h-4 rounded-full bg-zinc-950 border border-zinc-800 text-[9px] font-bold text-zinc-500 flex items-center justify-center">
                        {i + 1}
                      </span>
                    </div>
                    <p className="text-xs font-semibold text-zinc-200 mb-1">{step.label}</p>
                    <p className="text-[10px] text-zinc-600 leading-tight">{step.desc}</p>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="mt-10 p-4 rounded-xl bg-zinc-900/60 border border-zinc-800/60 text-center">
            <p className="text-xs text-zinc-500">
              Average cost per account: <span className="text-zinc-300 font-semibold">$0.17</span>
              {" · "}Runtime: <span className="text-zinc-300 font-semibold">under 3 minutes</span>
              {" · "}Fully SIGTERM-safe for Azure Container Jobs
            </p>
          </div>
        </div>
      </section>

      {/* ── Differentiators ─────────────────────────────────────────── */}
      <section className="py-20 px-6 border-t border-zinc-800/40">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-12">
            <p className="text-xs font-semibold text-brand-400 uppercase tracking-widest mb-3">Why Vantage</p>
            <h2 className="text-3xl font-bold text-zinc-50 tracking-tight">
              Not just another AI wrapper.
            </h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[
              {
                title: "Audit Panel — GA from day one",
                desc: "Every fact the agent surfaces is traceable. Click any claim to see the exact source: which email, which note, which call. Our competitors have this in beta.",
                accent: true,
              },
              {
                title: "pgvector semantic search",
                desc: "Semantic search lives in the same Postgres DB. No Pinecone, no extra vendor, zero added latency. Ask the assistant anything across your whole portfolio.",
                accent: false,
              },
              {
                title: "Self-serve HubSpot OAuth",
                desc: "Connect in 30 seconds. No Salesforce required. No Gong contract. HubSpot OAuth → Sync → first sweep in under 3 minutes.",
                accent: false,
              },
              {
                title: "MCP server for Claude Desktop",
                desc: "Query account context, next actions, and drafts directly from Claude Desktop. Your reps get Vantage intelligence wherever they work.",
                accent: false,
              },
            ].map((item, i) => (
              <div key={i} className={`rounded-2xl p-6 border ${item.accent ? "bg-brand-600/10 border-brand-500/30" : "bg-zinc-900/50 border-zinc-800/60"}`}>
                <h3 className={`text-sm font-semibold mb-2 ${item.accent ? "text-brand-300" : "text-zinc-100"}`}>{item.title}</h3>
                <p className="text-xs text-zinc-500 leading-relaxed">{item.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Testimonial ─────────────────────────────────────────────── */}
      <section className="py-20 px-6 border-t border-zinc-800/40">
        <div className="max-w-2xl mx-auto text-center">
          <div className="flex justify-center mb-6">
            {[...Array(5)].map((_, i) => (
              <svg key={i} className="w-4 h-4 text-brand-400" fill="currentColor" viewBox="0 0 20 20">
                <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
              </svg>
            ))}
          </div>
          <blockquote className="text-xl font-medium text-zinc-200 leading-relaxed mb-6">
            &ldquo;{TESTIMONIAL.quote}&rdquo;
          </blockquote>
          <p className="text-xs text-zinc-600">
            {TESTIMONIAL.author} · {TESTIMONIAL.company}
          </p>
        </div>
      </section>

      {/* ── Final CTA ───────────────────────────────────────────────── */}
      <section className="py-24 px-6 border-t border-zinc-800/40 relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-brand-600/8 via-transparent to-violet-600/8 pointer-events-none" />
        <div className="relative max-w-2xl mx-auto text-center">
          <h2 className="text-4xl font-bold tracking-tight text-zinc-50 mb-4">
            Ready to run your pipeline on autopilot?
          </h2>
          <p className="text-zinc-400 text-sm mb-8 leading-relaxed">
            Connect HubSpot in 30 seconds. First agent sweep in under 3 minutes.
            No engineers required.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <Link href="/auth/login"
              className="inline-flex items-center gap-2 bg-brand-600 hover:bg-brand-500 text-white font-semibold text-sm px-8 py-3.5 rounded-xl transition-colors shadow-xl shadow-brand-600/30">
              Get started free
              <ArrowRight className="w-4 h-4" />
            </Link>
            <Link href="/inbox"
              className="text-sm text-zinc-400 hover:text-zinc-200 transition-colors">
              Explore the live demo →
            </Link>
          </div>
        </div>
      </section>

      {/* ── Footer ──────────────────────────────────────────────────── */}
      <footer className="border-t border-zinc-800/60 py-8 px-6">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-md bg-brand-600 flex items-center justify-center">
              <Zap className="w-3 h-3 text-white" />
            </div>
            <span className="text-sm font-bold text-zinc-400">Vantage</span>
          </div>
          <p className="text-xs text-zinc-700">
            Built for enterprise sales teams · Powered by Claude · pgvector · HubSpot
          </p>
          <div className="flex items-center gap-4">
            <Link href="/auth/login" className="text-xs text-zinc-600 hover:text-zinc-400 transition-colors">Sign in</Link>
            <Link href="/inbox" className="text-xs text-zinc-600 hover:text-zinc-400 transition-colors">Demo</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
