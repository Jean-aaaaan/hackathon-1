"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, useEffect, useRef } from "react";
import { Search, RefreshCw, ChevronDown, X, Menu, Settings, LogOut, Building2 } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  accountsApi, authApi, draftsApi, setPreferredWorkspace,
  type CurrentUser, type WorkspaceSummary,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { useCommandPalette } from "@/components/providers";
import { CommandPalette } from "@/components/ui/command-palette";

// ── Vantage logo mark ──────────────────────────────────────────────────────────

function VantageMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" fill="none" className={className} aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="#18181B" />
      <path
        d="M16 10.5C12.1 10.5 8.5 14 8.5 16c0 2 3.6 5.5 7.5 5.5s7.5-3.5 7.5-5.5c0-2-3.6-5.5-7.5-5.5z"
        fill="white"
        fillOpacity="0.95"
      />
      <circle cx="16" cy="16" r="2.8" fill="#18181B" />
      <circle cx="16" cy="16" r="1.2" fill="white" />
    </svg>
  );
}

// ── Nav config ─────────────────────────────────────────────────────────────────

const NAV_ITEMS: { href: string; label: string; showBadge?: boolean }[] = [
  { href: "/inbox",        label: "Today",        showBadge: true },
  { href: "/watchtower",   label: "Watchtower" },
  { href: "/deals",        label: "Deal Book" },
  { href: "/forecast",     label: "Forecast" },
  { href: "/intelligence", label: "Intelligence" },
  { href: "/assistant",    label: "Assistant" },
  { href: "/analytics",    label: "Analytics" },
];

const STAGE_OPTIONS = [
  { label: "Proposal only",      value: "Proposal" },
  { label: "Demo / Discovery",   value: "Demo" },
  { label: "All urgent (top 20)", value: "" },
];

// ── Account search results (sweep popover) ─────────────────────────────────────

function AccountSearchResults({ query, onSelect }: {
  query: string;
  onSelect: (id: string) => void;
}) {
  const [results, setResults] = useState<{ id: string; name: string }[]>([]);

  useEffect(() => {
    let cancelled = false;
    accountsApi
      .list({ sort_by: "urgency_score", sort_dir: "desc", limit: 100 })
      .then((res: any) => {
        if (cancelled) return;
        const accounts: { id: string; name: string }[] = res?.data ?? [];
        const q = query.toLowerCase();
        setResults(accounts.filter(a => a.name?.toLowerCase().includes(q)).slice(0, 5));
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [query]);

  if (!results.length) return <p className="text-xs text-zinc-400 px-1">No matches</p>;

  return (
    <div className="flex flex-col gap-0.5">
      {results.map(a => (
        <button
          key={a.id}
          onClick={() => onSelect(a.id)}
          className="text-left text-sm px-2.5 py-1.5 rounded-lg hover:bg-zinc-100
                     hover:text-zinc-900 text-zinc-700 transition-colors truncate"
        >
          {a.name}
        </button>
      ))}
    </div>
  );
}

// ── NavBar ─────────────────────────────────────────────────────────────────────

export function NavBar({ onMobileMenuClick }: { onMobileMenuClick?: () => void }) {
  const pathname = usePathname();
  const router   = useRouter();
  const qc       = useQueryClient();
  const { openPalette, open: paletteOpen, closePalette } = useCommandPalette();

  const [isRefreshing, setIsRefreshing]   = useState(false);
  const [sweepOpen, setSweepOpen]         = useState(false);
  const [selectedStage, setSelectedStage] = useState("Proposal");
  const [accountSearch, setAccountSearch] = useState("");
  const [avatarOpen, setAvatarOpen]       = useState(false);
  const [wsOpen, setWsOpen]               = useState(false);

  const sweepRef  = useRef<HTMLDivElement>(null);
  const avatarRef = useRef<HTMLDivElement>(null);

  const { data: meData } = useQuery({
    queryKey: ["me"],
    queryFn: authApi.me,
    staleTime: 5 * 60 * 1000,
  });
  const user: CurrentUser | undefined = meData?.data;

  const { data: wsData } = useQuery({
    queryKey: ["workspaces"],
    queryFn: authApi.workspaces,
    staleTime: 10 * 60 * 1000,
    enabled: !!user,
  });
  const workspaces: WorkspaceSummary[] = wsData?.data ?? [];

  const { data: pendingData } = useQuery({
    queryKey: ["drafts", "pending", "count"],
    queryFn: () => draftsApi.list({ status: "pending", limit: 1 }),
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
  });
  const pendingCount = pendingData?.pagination?.total ?? 0;

  // ⌘K global shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        openPalette();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [openPalette]);

  // Close popovers on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (sweepRef.current && !sweepRef.current.contains(e.target as Node)) setSweepOpen(false);
      if (avatarRef.current && !avatarRef.current.contains(e.target as Node)) {
        setAvatarOpen(false);
        setWsOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const accountIdFromPath = pathname.match(/^\/account\/([^/]+)/)?.[1] ?? null;

  const runSweep = async (opts: { accountIds?: string[]; stageFilter?: string }) => {
    setIsRefreshing(true);
    setSweepOpen(false);
    try {
      const res = await accountsApi.batchRefresh(opts.accountIds, opts.stageFilter);
      const count = (res as any)?.data?.account_count;
      const label = opts.accountIds?.length === 1
        ? "1 account"
        : opts.stageFilter
          ? `${count ?? "?"} ${opts.stageFilter} accounts`
          : `${count ?? "top 20"} accounts`;
      const toastId = toast.loading(`Agents running on ${label}… (~2 min)`);
      let elapsed = 0;
      const poll = setInterval(() => {
        elapsed += 20;
        qc.invalidateQueries({ queryKey: ["accounts"] });
        qc.invalidateQueries({ queryKey: ["drafts"] });
        qc.invalidateQueries({ queryKey: ["pov", accountIdFromPath] });
        qc.invalidateQueries({ queryKey: ["signals", accountIdFromPath] });
        if (elapsed >= 120) {
          clearInterval(poll);
          toast.success("Agents finished — check drafts and War Room for updates.", { id: toastId });
          setIsRefreshing(false);
        }
      }, 20_000);
    } catch {
      toast.error("Could not start agent run.");
      setIsRefreshing(false);
    }
  };

  const handleSweepClick = () => {
    if (accountIdFromPath) runSweep({ accountIds: [accountIdFromPath] });
    else setSweepOpen(v => !v);
  };

  const handleLogout = async () => {
    setAvatarOpen(false);
    await authApi.logout();
    router.push("/auth/login");
  };

  const initials = user?.email ? user.email.slice(0, 2).toUpperCase() : "?";

  return (
    <>
      <header className="h-14 bg-white border-b border-zinc-100 flex items-center px-4 md:px-6 gap-3 flex-shrink-0 sticky top-0 z-50">

        {/* Mobile hamburger */}
        <button
          onClick={onMobileMenuClick}
          className="md:hidden text-zinc-400 hover:text-zinc-700 transition-colors flex-shrink-0"
          aria-label="Open menu"
        >
          <Menu className="w-5 h-5" />
        </button>

        {/* Brand */}
        <Link href="/inbox" className="flex items-center gap-2 flex-shrink-0">
          <VantageMark className="w-7 h-7" />
          <span className="text-sm font-semibold text-zinc-900 hidden lg:block">Vantage</span>
        </Link>

        {/* Divider */}
        <div className="hidden md:block w-px h-5 bg-zinc-200 flex-shrink-0" />

        {/* Primary nav — horizontal text links */}
        <nav className="hidden md:flex items-center gap-0.5 flex-1 min-w-0">
          {NAV_ITEMS.map(({ href, label, showBadge }) => {
            const active = pathname === href || (href !== "/inbox" && pathname.startsWith(href + "/"));
            const badge  = showBadge && pendingCount > 0 ? pendingCount : null;
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "relative flex items-center gap-1.5 px-3 py-1.5 text-[13px] font-medium rounded-md transition-colors whitespace-nowrap",
                  active
                    ? "text-zinc-900 bg-zinc-100"
                    : "text-zinc-500 hover:text-zinc-800 hover:bg-zinc-50"
                )}
              >
                {label}
                {badge !== null && (
                  <span className="text-[10px] font-bold bg-zinc-900 text-white px-1.5 py-0.5 rounded-full leading-none min-w-[1.1rem] text-center">
                    {badge > 99 ? "99+" : badge}
                  </span>
                )}
                {active && (
                  <span className="absolute bottom-0 left-2 right-2 h-0.5 bg-zinc-900 rounded-full" />
                )}
              </Link>
            );
          })}
        </nav>

        {/* Right cluster */}
        <div className="flex items-center gap-2 ml-auto flex-shrink-0">

          {/* ⌘K search — desktop */}
          <button
            onClick={openPalette}
            className="hidden md:flex items-center gap-2 px-3 py-1.5 w-48 lg:w-56 bg-zinc-50 hover:bg-zinc-100
                       rounded-lg border border-zinc-200 transition-colors"
          >
            <Search className="w-3.5 h-3.5 text-zinc-400 flex-shrink-0" />
            <span className="flex-1 text-left text-[13px] text-zinc-400">Search...</span>
            <kbd className="bg-white border border-zinc-200 rounded text-[10px] px-1.5 py-0.5 text-zinc-400 font-sans hidden lg:block">
              ⌘K
            </kbd>
          </button>

          {/* ⌘K search — mobile icon */}
          <button onClick={openPalette} className="md:hidden text-zinc-400 hover:text-zinc-700 transition-colors">
            <Search className="w-5 h-5" />
          </button>

          {/* Vantage Sweep */}
          <div className="relative" ref={sweepRef}>
            <button
              onClick={handleSweepClick}
              disabled={isRefreshing}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[13px] font-medium transition-all",
                isRefreshing
                  ? "bg-zinc-100 text-zinc-600 border border-zinc-200"
                  : "bg-zinc-900 hover:bg-zinc-800 text-white"
              )}
            >
              <RefreshCw className={cn("w-3.5 h-3.5", isRefreshing && "animate-spin")} />
              <span className="hidden md:inline">
                {isRefreshing ? (
                  <span className="flex items-center gap-1">
                    Sweeping
                    <span className="flex gap-0.5 ml-0.5">
                      <span className="thinking-dot" />
                      <span className="thinking-dot" />
                      <span className="thinking-dot" />
                    </span>
                  </span>
                ) : "Run Agents"}
              </span>
              {!isRefreshing && !accountIdFromPath && (
                <ChevronDown className={cn("w-3 h-3 transition-transform hidden md:block", sweepOpen && "rotate-180")} />
              )}
            </button>

            {sweepOpen && !isRefreshing && (
              <div className="absolute right-0 top-full mt-2 w-72 bg-white border border-zinc-200 rounded-xl shadow-lg z-50 p-4 flex flex-col gap-3">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-semibold text-zinc-700 uppercase tracking-wide">Sweep scope</p>
                  <button onClick={() => setSweepOpen(false)} className="text-zinc-400 hover:text-zinc-600">
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>

                <div className="flex flex-col gap-1.5">
                  <p className="text-[11px] text-zinc-400 font-medium">Filter by stage</p>
                  <div className="flex flex-col gap-1">
                    {STAGE_OPTIONS.map(opt => (
                      <button
                        key={opt.value}
                        onClick={() => setSelectedStage(opt.value)}
                        className={cn(
                          "flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-colors text-left",
                          selectedStage === opt.value
                            ? "bg-zinc-100 text-zinc-900 border border-zinc-300 font-medium"
                            : "text-zinc-600 hover:bg-zinc-50 border border-transparent"
                        )}
                      >
                        {opt.label}
                        {selectedStage === opt.value && (
                          <span className="w-1.5 h-1.5 rounded-full bg-zinc-600" />
                        )}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex flex-col gap-1.5">
                  <p className="text-[11px] text-zinc-400 font-medium">Or sweep a specific account</p>
                  <input
                    type="text"
                    placeholder="Account name..."
                    value={accountSearch}
                    onChange={e => setAccountSearch(e.target.value)}
                    className="text-sm px-2.5 py-1.5 border border-zinc-200 rounded-lg
                               text-zinc-800 placeholder-zinc-400 focus:outline-none focus:border-zinc-400"
                  />
                  {accountSearch.trim() && (
                    <AccountSearchResults
                      query={accountSearch}
                      onSelect={id => { setAccountSearch(""); runSweep({ accountIds: [id] }); }}
                    />
                  )}
                </div>

                {!accountSearch.trim() && (
                  <button
                    onClick={() => runSweep({ stageFilter: selectedStage || undefined })}
                    className="w-full py-2 bg-zinc-900 hover:bg-zinc-800 text-white text-sm
                               font-medium rounded-lg transition-colors"
                  >
                    {selectedStage ? `Sweep ${selectedStage} accounts` : "Sweep top 20 (all stages)"}
                  </button>
                )}
              </div>
            )}
          </div>

          {/* User avatar + dropdown */}
          <div className="relative" ref={avatarRef}>
            <button
              onClick={() => setAvatarOpen(v => !v)}
              className="w-8 h-8 rounded-full bg-zinc-100 hover:bg-zinc-200 flex items-center justify-center transition-colors flex-shrink-0"
            >
              <span className="text-[11px] font-semibold text-zinc-700">{initials}</span>
            </button>

            {avatarOpen && (
              <div className="absolute right-0 top-full mt-2 w-56 bg-white border border-zinc-200 rounded-xl shadow-lg z-50 overflow-hidden">
                {user && (
                  <div className="px-3 py-3 border-b border-zinc-100">
                    <p className="text-xs font-semibold text-zinc-900 truncate">{user.email.split("@")[0]}</p>
                    <p className="text-[11px] text-zinc-400 truncate">{user.email}</p>
                  </div>
                )}

                {workspaces.length > 1 && (
                  <div className="border-b border-zinc-100">
                    <button
                      onClick={() => setWsOpen(o => !o)}
                      className="w-full flex items-center gap-2 px-3 py-2.5 text-[13px] text-zinc-600 hover:bg-zinc-50 transition-colors"
                    >
                      <Building2 className="w-4 h-4 text-zinc-400 flex-shrink-0" />
                      <span className="flex-1 text-left truncate">
                        {workspaces.find(w => w.is_current)?.name ?? "Workspace"}
                      </span>
                      <ChevronDown className={cn("w-3 h-3 text-zinc-400 transition-transform", wsOpen && "rotate-180")} />
                    </button>
                    {wsOpen && (
                      <div className="border-t border-zinc-100 bg-zinc-50">
                        {workspaces.map(ws => (
                          <button
                            key={ws.workspace_id}
                            onClick={() => {
                              setPreferredWorkspace(ws.workspace_id);
                              setWsOpen(false);
                              setAvatarOpen(false);
                              qc.clear();
                              router.refresh();
                            }}
                            className={cn(
                              "w-full flex items-center gap-2 px-4 py-2 text-[12px] text-left transition-colors",
                              ws.is_current ? "text-zinc-900 font-medium" : "text-zinc-600 hover:bg-zinc-100"
                            )}
                          >
                            <span className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0", ws.is_current ? "bg-zinc-900" : "bg-zinc-300")} />
                            <span className="flex-1 truncate">{ws.name}</span>
                            <span className="text-[10px] text-zinc-400">{ws.role}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <Link
                  href="/settings"
                  onClick={() => setAvatarOpen(false)}
                  className="flex items-center gap-2.5 px-3 py-2.5 text-[13px] text-zinc-600 hover:bg-zinc-50 transition-colors"
                >
                  <Settings className="w-4 h-4 text-zinc-400 flex-shrink-0" />
                  Settings
                </Link>
                <button
                  onClick={handleLogout}
                  className="w-full flex items-center gap-2.5 px-3 py-2.5 text-[13px] text-zinc-600 hover:bg-zinc-50 transition-colors border-t border-zinc-100"
                >
                  <LogOut className="w-4 h-4 text-zinc-400 flex-shrink-0" />
                  Sign out
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <CommandPalette open={paletteOpen} onClose={closePalette} />
    </>
  );
}
