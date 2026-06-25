"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { accountsApi, type AccountListItem, type AccountSearchResult } from "@/lib/api";
import { Search, BarChart3, Settings, Zap, X, Inbox, Eye, BookOpen, TrendingUp, MessageSquare } from "lucide-react";
import { cn, urgencyLevel } from "@/lib/utils";

function UrgencyDot({ score }: { score: number | null }) {
  const level = urgencyLevel(score);
  return (
    <span className={cn("dot mt-0.5 flex-shrink-0", `dot-${level}`)} />
  );
}

// ── Quick actions ──────────────────────────────────────────────────────────────

const QUICK_ACTIONS = [
  { id: "today",      label: "Go to Today",      icon: Inbox,         href: "/inbox" },
  { id: "watchtower", label: "Go to Watchtower", icon: Eye,           href: "/watchtower" },
  { id: "deals",      label: "Go to Deal Book",  icon: BookOpen,      href: "/deals" },
  { id: "forecast",   label: "Go to Forecast",   icon: TrendingUp,    href: "/forecast" },
  { id: "assistant",  label: "Ask the Assistant", icon: MessageSquare, href: "/assistant" },
  { id: "analytics",  label: "Go to Analytics",  icon: BarChart3,     href: "/analytics" },
  { id: "settings",   label: "Go to Settings",   icon: Settings,      href: "/settings"  },
];

// ── Component ──────────────────────────────────────────────────────────────────

interface Props {
  open: boolean;
  onClose: () => void;
}

export function CommandPalette({ open, onClose }: Props) {
  const router        = useRouter();
  const queryClient   = useQueryClient();
  const inputRef      = useRef<HTMLInputElement>(null);
  const [query, setQuery]       = useState("");
  const [activeIdx, setActiveIdx] = useState(0);

  // Debounced search query
  const [debouncedQuery, setDebouncedQuery] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query), 280);
    return () => clearTimeout(t);
  }, [query]);

  // Reset on open
  useEffect(() => {
    if (open) {
      setQuery("");
      setDebouncedQuery("");
      setActiveIdx(0);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);

  // Semantic search
  const { data: searchData, isFetching } = useQuery({
    queryKey: ["command-search", debouncedQuery],
    queryFn: () => accountsApi.search({ query: debouncedQuery, limit: 6 }),
    enabled: debouncedQuery.length >= 2,
    staleTime: 30 * 1000,
  });

  // Accounts from whatever accounts query any page has already cached
  // (inbox uses ["accounts","inbox"], watchtower ["accounts","all"], …)
  const cachedLists = queryClient.getQueriesData<{ data: AccountListItem[] }>({ queryKey: ["accounts"] });
  const allCached: AccountListItem[] = [];
  const seenIds = new Set<string>();
  for (const [, value] of cachedLists) {
    for (const acc of value?.data ?? []) {
      if (acc?.id && acc?.name && !seenIds.has(acc.id)) {
        seenIds.add(acc.id);
        allCached.push(acc);
      }
    }
  }
  const recentAccounts = allCached.slice(0, 5);

  const showSearch = debouncedQuery.length >= 2;
  const semanticResults: AccountSearchResult[] = searchData?.data ?? [];
  // Semantic search needs embeddings (generated per agent run); until then it
  // returns nothing — fall back to plain name matching over cached accounts
  const nameMatches = showSearch && semanticResults.length === 0
    ? allCached.filter(a => a.name.toLowerCase().includes(debouncedQuery.toLowerCase())).slice(0, 6)
    : [];
  const searchResults: AccountSearchResult[] = semanticResults.length > 0
    ? semanticResults
    : (nameMatches as unknown as AccountSearchResult[]);

  // Build flat item list for keyboard nav
  type NavItem =
    | { kind: "account"; account: AccountListItem }
    | { kind: "action";  action: typeof QUICK_ACTIONS[number] };

  const items: NavItem[] = showSearch
    ? searchResults.map(a => ({ kind: "account", account: a }))
    : [
        ...recentAccounts.map(a => ({ kind: "account" as const, account: a })),
        ...QUICK_ACTIONS.map(a => ({ kind: "action" as const, action: a })),
      ];

  const navigate = useCallback((item: NavItem) => {
    if (item.kind === "account") {
      router.push(`/account/${item.account.id}`);
    } else {
      router.push(item.action.href);
    }
    onClose();
  }, [router, onClose]);

  // Keyboard handler
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIdx(i => Math.min(i + 1, items.length - 1));
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIdx(i => Math.max(i - 1, 0));
      }
      if (e.key === "Enter") {
        e.preventDefault();
        const item = items[activeIdx];
        if (item) navigate(item);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, items, activeIdx, navigate, onClose]);

  // Reset active when results change
  useEffect(() => { setActiveIdx(0); }, [debouncedQuery]);

  if (!open) return null;

  const formatAmount = (v: number | null) =>
    v ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(v) : null;

  return (
    <div className="palette-overlay" onClick={onClose}>
      <div className="px-4">
        <div className="palette-box" onClick={e => e.stopPropagation()}>

          {/* Search input */}
          <div className="flex items-center gap-3 px-4 py-3 border-b border-zinc-100">
            <Search className="w-4 h-4 text-zinc-400 flex-shrink-0" />
            <input
              ref={inputRef}
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search deals, ask anything..."
              className="flex-1 bg-transparent text-[15px] text-zinc-900 placeholder-zinc-400 outline-none"
            />
            {query && (
              <button onClick={() => setQuery("")} className="text-zinc-400 hover:text-zinc-600">
                <X className="w-3.5 h-3.5" />
              </button>
            )}
            {isFetching && (
              <span className="flex gap-0.5">
                <span className="thinking-dot" />
                <span className="thinking-dot" />
                <span className="thinking-dot" />
              </span>
            )}
          </div>

          {/* Results */}
          <div className="py-2 max-h-[360px] overflow-y-auto">

            {showSearch ? (
              searchResults.length === 0 && !isFetching ? (
                <p className="px-4 py-6 text-sm text-zinc-400 text-center">
                  No deals found for &ldquo;{debouncedQuery}&rdquo;
                </p>
              ) : (
                <>
                  <p className="section-header px-4 pb-1.5 pt-1">Results</p>
                  {searchResults.map((acc, i) => (
                    <AccountRow
                      key={acc.id}
                      account={acc}
                      active={activeIdx === i}
                      onHover={() => setActiveIdx(i)}
                      onClick={() => navigate({ kind: "account", account: acc })}
                      formatAmount={formatAmount}
                    />
                  ))}
                </>
              )
            ) : (
              <>
                {recentAccounts.length > 0 && (
                  <>
                    <p className="section-header px-4 pb-1.5 pt-1">Recent</p>
                    {recentAccounts.map((acc, i) => (
                      <AccountRow
                        key={acc.id}
                        account={acc}
                        active={activeIdx === i}
                        onHover={() => setActiveIdx(i)}
                        onClick={() => navigate({ kind: "account", account: acc })}
                        formatAmount={formatAmount}
                      />
                    ))}
                  </>
                )}
                <p className="section-header px-4 pb-1.5 pt-3">Quick actions</p>
                {QUICK_ACTIONS.map((action, i) => {
                  const globalIdx = recentAccounts.length + i;
                  const Icon = action.icon;
                  return (
                    <button
                      key={action.id}
                      onMouseEnter={() => setActiveIdx(globalIdx)}
                      onClick={() => navigate({ kind: "action", action })}
                      className={cn(
                        "w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-colors text-left",
                        activeIdx === globalIdx ? "bg-indigo-50 text-indigo-700" : "text-zinc-700 hover:bg-zinc-50"
                      )}
                    >
                      <Icon className="w-4 h-4 flex-shrink-0 text-zinc-400" />
                      {action.label}
                    </button>
                  );
                })}
              </>
            )}
          </div>

          {/* Footer */}
          <div className="border-t border-zinc-100 px-4 py-2 flex items-center gap-3 text-[11px] text-zinc-400">
            <span><kbd className="font-sans">↑↓</kbd> navigate</span>
            <span><kbd className="font-sans">↵</kbd> open</span>
            <span><kbd className="font-sans">esc</kbd> close</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Account row ────────────────────────────────────────────────────────────────

function AccountRow({
  account,
  active,
  onHover,
  onClick,
  formatAmount,
}: {
  account: AccountListItem;
  active: boolean;
  onHover: () => void;
  onClick: () => void;
  formatAmount: (v: number | null) => string | null;
}) {
  const isRawId = account.stage ? /^\d{6,}$/.test(account.stage) : false;
  const stage   = !account.stage || isRawId ? null : account.stage;
  const amount  = formatAmount(account.deal_amount);

  return (
    <button
      onMouseEnter={onHover}
      onClick={onClick}
      className={cn(
        "w-full flex items-center gap-3 px-4 py-2.5 transition-colors text-left",
        active ? "bg-indigo-50" : "hover:bg-zinc-50"
      )}
    >
      <UrgencyDot score={account.urgency_score} />
      <div className="flex-1 min-w-0">
        <p className={cn("text-sm font-medium truncate", active ? "text-indigo-700" : "text-zinc-900")}>
          {account.name}
        </p>
        {(stage || amount) && (
          <p className="text-xs text-zinc-400 truncate">
            {[stage, amount].filter(Boolean).join(" · ")}
          </p>
        )}
      </div>
      {account.pending_drafts > 0 && (
        <span className="text-[10px] font-bold bg-indigo-600 text-white px-1.5 py-0.5 rounded-full leading-none flex-shrink-0">
          {account.pending_drafts}
        </span>
      )}
    </button>
  );
}
