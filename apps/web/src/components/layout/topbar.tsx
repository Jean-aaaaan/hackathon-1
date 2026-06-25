"use client";

import { useQueryClient } from "@tanstack/react-query";
import { usePathname } from "next/navigation";
import { accountsApi } from "@/lib/api";
import { Search, RefreshCw, Menu, ChevronDown, X } from "lucide-react";
import { useState, useEffect, useRef } from "react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { useCommandPalette } from "@/components/providers";
import { CommandPalette } from "@/components/ui/command-palette";

const PAGE_META: Record<string, { title: string; subtitle: string }> = {
  "/inbox":      { title: "Today",     subtitle: "Actions to take and drafts to review" },
  "/watchtower": { title: "Watchtower", subtitle: "Portfolio health overview" },
  "/forecast":   { title: "Forecast",  subtitle: "AI pipeline categories and rep overrides" },
  "/deals":      { title: "Deal Book",  subtitle: "Deep intelligence on every deal: people, comms, meetings, gaps" },
  "/assistant":  { title: "Chat",      subtitle: "Ask anything about your pipeline" },
  "/analytics":  { title: "Analytics", subtitle: "DAR trend, cost, rep performance" },
  "/settings":   { title: "Settings",  subtitle: "Workspace, integrations, team" },
};

const STAGE_OPTIONS = [
  { label: "Proposal only",   value: "Proposal" },
  { label: "Demo / Discovery", value: "Demo" },
  { label: "All urgent (top 20)", value: "" },
];

export function TopBar({ onMenuClick }: { onMenuClick?: () => void }) {
  const queryClient  = useQueryClient();
  const pathname     = usePathname();
  const { openPalette, open: paletteOpen, closePalette } = useCommandPalette();

  const [isRefreshing, setIsRefreshing]   = useState(false);
  const [popoverOpen, setPopoverOpen]     = useState(false);
  const [selectedStage, setSelectedStage] = useState("Proposal");
  const [accountSearch, setAccountSearch] = useState("");
  const popoverRef = useRef<HTMLDivElement>(null);

  const pageKey = Object.keys(PAGE_META).find(k => pathname === k || pathname.startsWith(k + "/"));
  const page    = pageKey ? PAGE_META[pageKey] : null;

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

  // Close popover on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setPopoverOpen(false);
      }
    };
    if (popoverOpen) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [popoverOpen]);

  // If on a War Room page, bypass the popover — run just that account immediately
  const accountIdFromPath = pathname.match(/^\/account\/([^/]+)/)?.[1] ?? null;

  const runSweep = async (opts: { accountIds?: string[]; stageFilter?: string }) => {
    setIsRefreshing(true);
    setPopoverOpen(false);
    try {
      const res = await accountsApi.batchRefresh(opts.accountIds, opts.stageFilter);
      const count = (res as any)?.data?.account_count;
      const label = opts.accountIds?.length === 1
        ? "1 account"
        : opts.stageFilter
          ? `${count ?? "?"} ${opts.stageFilter} accounts`
          : `${count ?? "top 20"} accounts`;
      toast.success(`Agents queued for ${label}.`);
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["accounts"] });
        queryClient.invalidateQueries({ queryKey: ["drafts"] });
        queryClient.invalidateQueries({ queryKey: ["pov",    accountIdFromPath] });
        queryClient.invalidateQueries({ queryKey: ["signals", accountIdFromPath] });
        setIsRefreshing(false);
      }, 30000);
    } catch {
      toast.error("Could not start agent run.");
      setIsRefreshing(false);
    }
  };

  const handleButtonClick = () => {
    if (accountIdFromPath) {
      runSweep({ accountIds: [accountIdFromPath] });
    } else {
      setPopoverOpen(v => !v);
    }
  };

  return (
    <>
      <header className="h-14 bg-white border-b border-zinc-100 flex items-center gap-4 px-4 md:px-6 flex-shrink-0">

        {/* Hamburger - mobile only */}
        {onMenuClick && (
          <button
            onClick={onMenuClick}
            className="md:hidden text-zinc-400 hover:text-zinc-700 transition-colors flex-shrink-0"
            aria-label="Open menu"
          >
            <Menu className="w-5 h-5" />
          </button>
        )}

        {/* Page title */}
        {page && (
          <div className="flex-shrink-0 hidden md:block min-w-0">
            <p className="text-sm font-semibold text-zinc-900 leading-tight">{page.title}</p>
            <p className="text-[11px] text-zinc-400 leading-tight">{page.subtitle}</p>
          </div>
        )}

        {/* ⌘K search trigger */}
        <div className="flex-1 flex justify-center">
          <button
            onClick={openPalette}
            className="flex items-center gap-2.5 px-3 py-1.5 w-72 bg-zinc-100 hover:bg-zinc-200
                       text-zinc-400 text-sm rounded-xl border border-zinc-200 transition-colors text-left"
          >
            <Search className="w-3.5 h-3.5 flex-shrink-0" />
            <span className="flex-1 text-sm">Search or ask anything...</span>
            <kbd className="bg-white border border-zinc-200 rounded text-[10px] px-1.5 py-0.5 text-zinc-400 font-sans">
              ⌘K
            </kbd>
          </button>
        </div>

        {/* Vantage Sweep — popover trigger */}
        <div className="relative flex-shrink-0" ref={popoverRef}>
          <button
            onClick={handleButtonClick}
            disabled={isRefreshing}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-sm font-medium transition-all",
              isRefreshing
                ? "bg-zinc-100 text-zinc-600 border border-zinc-200"
                : "border border-zinc-200 text-zinc-700 bg-white hover:bg-zinc-50"
            )}
          >
            <RefreshCw className={cn("w-3.5 h-3.5", isRefreshing && "animate-spin")} />
            {isRefreshing ? (
              <span className="flex items-center gap-1">
                Sweeping
                <span className="flex gap-0.5 ml-0.5">
                  <span className="thinking-dot" />
                  <span className="thinking-dot" />
                  <span className="thinking-dot" />
                </span>
              </span>
            ) : (
              <>
                Vantage Sweep
                {!accountIdFromPath && (
                  <ChevronDown className={cn("w-3 h-3 transition-transform", popoverOpen && "rotate-180")} />
                )}
              </>
            )}
          </button>

          {/* Sweep popover */}
          {popoverOpen && !isRefreshing && (
            <div className="absolute right-0 top-full mt-2 w-72 bg-white border border-zinc-200 rounded-xl shadow-lg z-50 p-4 flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold text-zinc-700 uppercase tracking-wide">Sweep scope</p>
                <button onClick={() => setPopoverOpen(false)} className="text-zinc-400 hover:text-zinc-600">
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>

              {/* Stage filter */}
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

              {/* Account search (run single account by name via ID from URL or type) */}
              <div className="flex flex-col gap-1.5">
                <p className="text-[11px] text-zinc-400 font-medium">Or sweep a specific account</p>
                <div className="flex gap-2">
                  <input
                    type="text"
                    placeholder="Account name..."
                    value={accountSearch}
                    onChange={e => setAccountSearch(e.target.value)}
                    className="flex-1 text-sm px-2.5 py-1.5 border border-zinc-200 rounded-lg
                               text-zinc-800 placeholder-zinc-400 focus:outline-none focus:border-zinc-400"
                  />
                </div>
                {accountSearch.trim() && (
                  <AccountSearchResults
                    query={accountSearch}
                    onSelect={id => {
                      setAccountSearch("");
                      runSweep({ accountIds: [id] });
                    }}
                  />
                )}
              </div>

              {/* Run button */}
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
      </header>

      {/* Command palette (rendered outside the header flow) */}
      <CommandPalette open={paletteOpen} onClose={closePalette} />
    </>
  );
}

/** Inline account search results — queries the existing accounts list and filters client-side */
function AccountSearchResults({
  query,
  onSelect,
}: {
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

  if (!results.length) return (
    <p className="text-xs text-zinc-400 px-1">No matches</p>
  );

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
