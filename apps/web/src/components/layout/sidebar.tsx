"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Inbox, Eye, MessageSquare, Settings, BarChart3, LogOut, TrendingUp, X, Building2, ChevronDown, BookOpen, Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { authApi, draftsApi, setPreferredWorkspace, type CurrentUser, type WorkspaceSummary } from "@/lib/api";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState as useSt } from "react";

// ── Invigilo logo mark ─────────────────────────────────────────────────────────

function InvigiloMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" fill="none" className={className} aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="#6366F1" />
      <path
        d="M16 10.5C12.1 10.5 8.5 14 8.5 16c0 2 3.6 5.5 7.5 5.5s7.5-3.5 7.5-5.5c0-2-3.6-5.5-7.5-5.5z"
        fill="white"
        fillOpacity="0.95"
      />
      <circle cx="16" cy="16" r="2.8" fill="#6366F1" />
      <circle cx="16" cy="16" r="1.2" fill="white" />
    </svg>
  );
}

// ── Nav config ─────────────────────────────────────────────────────────────────

// Labels must match the page headings they lead to — a sidebar that says
// "Pipeline" landing on a page titled "Watchtower" reads as two products.
const CORE_NAV = [
  { href: "/inbox",        icon: Inbox,        label: "Today",         showBadge: true },
  { href: "/watchtower",   icon: Eye,           label: "Watchtower" },
  { href: "/deals",        icon: BookOpen,      label: "Deal Book"  },
  { href: "/forecast",     icon: TrendingUp,    label: "Forecast"   },
  { href: "/intelligence", icon: Sparkles,      label: "Intelligence" },
  { href: "/assistant",    icon: MessageSquare, label: "Assistant"  },
  { href: "/analytics",    icon: BarChart3,     label: "Analytics"  },
];

// ── Component ──────────────────────────────────────────────────────────────────

export function Sidebar({ onClose }: { onClose?: () => void }) {
  const pathname = usePathname();
  const router   = useRouter();
  const qc       = useQueryClient();
  const [wsOpen, setWsOpen] = useSt(false);

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

  const handleLogout = async () => {
    await authApi.logout();
    router.push("/auth/login");
  };

  const initials = user?.email
    ? user.email.slice(0, 2).toUpperCase()
    : "?";

  return (
    <aside className="w-56 bg-white border-r border-zinc-100 flex flex-col h-full">

      {/* ── Brand ────────────────────────────────────────────────────────────── */}
      <div className="px-4 py-4 border-b border-zinc-100">
        <div className="flex items-center gap-2.5">
          <InvigiloMark className="w-8 h-8 flex-shrink-0" />
          <p className="text-sm font-semibold text-zinc-900 leading-tight flex-1">
            Vantage
          </p>
          {onClose && (
            <button onClick={onClose} className="md:hidden text-zinc-400 hover:text-zinc-700 transition-colors">
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>

      {/* ── Navigation ───────────────────────────────────────────────────────── */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {CORE_NAV.map(({ href, icon: Icon, label, showBadge }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          const badge  = showBadge && pendingCount > 0 ? pendingCount : null;
          return (
            <Link
              key={href}
              href={href}
              onClick={onClose}
              className={cn(
                "flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] transition-colors relative",
                active
                  ? "bg-zinc-100 text-zinc-900 font-medium"
                  : "text-zinc-500 hover:bg-zinc-50 hover:text-zinc-800 font-medium"
              )}
            >
              <Icon
                className={cn(
                  "w-4 h-4 flex-shrink-0",
                  active ? "text-zinc-700" : "text-zinc-400"
                )}
              />
              <span className="flex-1 truncate">{label}</span>
              {badge !== null && (
                <span className="text-[10px] font-bold bg-zinc-800 text-white px-1.5 py-0.5 rounded-full min-w-[1.25rem] text-center leading-none">
                  {badge > 99 ? "99+" : badge}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* ── Footer ───────────────────────────────────────────────────────────── */}
      <div className="px-3 pb-4 border-t border-zinc-100 pt-3 space-y-0.5">

        {/* Workspace switcher - only shown when user belongs to multiple workspaces */}
        {workspaces.length > 1 && (
          <div className="relative mb-1">
            <button
              onClick={() => setWsOpen(o => !o)}
              className="w-full flex items-center gap-2 px-3 py-2 rounded-xl text-[13px] text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 border-l-2 border-transparent transition-colors"
            >
              <Building2 className="w-4 h-4 text-zinc-400 flex-shrink-0" />
              <span className="flex-1 truncate text-left">
                {workspaces.find(w => w.is_current)?.name ?? "Workspace"}
              </span>
              <ChevronDown className={cn("w-3 h-3 text-zinc-400 transition-transform", wsOpen && "rotate-180")} />
            </button>
            {wsOpen && (
              <div className="absolute bottom-full left-0 right-0 mb-1 bg-white border border-zinc-200 rounded-xl shadow-lg overflow-hidden z-50">
                {workspaces.map(ws => (
                  <button
                    key={ws.workspace_id}
                    onClick={() => {
                      setPreferredWorkspace(ws.workspace_id);
                      setWsOpen(false);
                      qc.clear();
                      router.refresh();
                    }}
                    className={cn(
                      "w-full flex items-center gap-2 px-3 py-2.5 text-[12px] text-left transition-colors",
                      ws.is_current
                        ? "bg-zinc-100 text-zinc-900 font-medium"
                        : "text-zinc-600 hover:bg-zinc-50"
                    )}
                  >
                    <span className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0", ws.is_current ? "bg-zinc-600" : "bg-zinc-300")} />
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
          className={cn(
            "flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13px] transition-colors",
            pathname.startsWith("/settings")
              ? "bg-zinc-100 text-zinc-900 font-medium"
              : "text-zinc-500 hover:bg-zinc-50 hover:text-zinc-800 font-medium"
          )}
        >
          <Settings
            className={cn(
              "w-4 h-4 flex-shrink-0",
              pathname.startsWith("/settings") ? "text-zinc-700" : "text-zinc-400"
            )}
          />
          Settings
        </Link>

        {user && (
          <div className="flex items-center gap-2.5 px-3 py-2 rounded-xl group mt-1">
            <div className="w-7 h-7 rounded-full bg-zinc-200 flex items-center justify-center flex-shrink-0">
              <span className="text-[10px] font-semibold text-zinc-600">{initials}</span>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-zinc-700 truncate leading-tight">
                {user.email.split("@")[0]}
              </p>
              <p className="text-[10px] text-zinc-400 leading-tight truncate">
                {user.email.split("@")[1] ?? user.role}
              </p>
            </div>
            <button
              onClick={handleLogout}
              title="Sign out"
              className="text-zinc-300 hover:text-zinc-600 transition-colors flex-shrink-0 opacity-0 group-hover:opacity-100"
            >
              <LogOut className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
