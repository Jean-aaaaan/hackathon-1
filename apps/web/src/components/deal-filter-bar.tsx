"use client";

/**
 * Shared deal filter/sort bar — the single UI for the canonical engine in
 * lib/deal-filters.ts. Used by Today and Deal Book (and any future deal list).
 */
import { useEffect, useRef, useState } from "react";
import { Search, X, ChevronDown, ChevronUp, SlidersHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AccountListItem } from "@/lib/api";
import {
  type DealFilterState, type DealSortKey,
  FORECAST_CATEGORIES, stageOptions, hasActiveFilters, defaultDirFor,
} from "@/lib/deal-filters";

const SORT_LABELS: Record<DealSortKey, string> = {
  priority: "AI Priority",
  urgency:  "Urgency",
  amount:   "Deal Size",
  close:    "Close Date",
  health:   "Health",
  swept:    "Last Run",
  name:     "Name A–Z",
};

const SORT_TITLES: Record<DealSortKey, string> = {
  priority: "Dollar-weighted urgency. High-value urgent deals first.",
  urgency:  "Raw AI urgency score (0–1)",
  amount:   "Largest deal value first",
  close:    "Soonest close date first",
  health:   "Healthiest deals first (engagement, momentum)",
  swept:    "Most recently agent-run first",
  name:     "Alphabetical by deal name",
};

export function DealFilterBar({
  accounts,
  state,
  onChange,
  sortOptions,
  placeholder = "Search deals...",
}: {
  accounts: AccountListItem[];
  state: DealFilterState;
  onChange: (next: DealFilterState) => void;
  sortOptions: DealSortKey[];
  placeholder?: string;
}) {
  const [filtersOpen, setFiltersOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const stages = stageOptions(accounts);
  const active = hasActiveFilters(state);
  const activeCount =
    (state.stages.length ? 1 : 0) + (state.categories.length ? 1 : 0) +
    (state.health !== "all" ? 1 : 0) + (state.draftsOnly ? 1 : 0);

  useEffect(() => {
    if (!filtersOpen) return;
    const handler = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setFiltersOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [filtersOpen]);

  const set = (patch: Partial<DealFilterState>) => onChange({ ...state, ...patch });
  const toggleIn = (list: string[], value: string) =>
    list.includes(value) ? list.filter(v => v !== value) : [...list, value];

  const setSort = (k: DealSortKey) => {
    if (state.sort === k) set({ dir: state.dir === "desc" ? "asc" : "desc" });
    else set({ sort: k, dir: defaultDirFor(k) });
  };

  return (
    <div className="space-y-2">
      {/* Search + filter toggle */}
      <div className="flex items-center gap-1.5">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-400 pointer-events-none" />
          <input
            type="text"
            placeholder={placeholder}
            value={state.q}
            onChange={e => set({ q: e.target.value })}
            className="input-field pl-8 pr-7 py-2"
          />
          {state.q && (
            <button
              onClick={() => set({ q: "" })}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-zinc-600"
            >
              <X className="w-3 h-3" />
            </button>
          )}
        </div>
        <div className="relative" ref={popoverRef}>
          <button
            onClick={() => setFiltersOpen(o => !o)}
            className={cn(
              "flex items-center gap-1 px-2.5 py-2 rounded-md border text-[11px] font-medium transition-colors",
              activeCount > 0
                ? "border-zinc-300 bg-lily-wash text-zinc-800"
                : "border-zinc-100 text-zinc-500 hover:bg-lily-wash"
            )}
            title="Filters"
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
            {activeCount > 0 && <span className="font-bold">{activeCount}</span>}
          </button>

          {/* Filter popover */}
          {filtersOpen && (
            <div className="absolute right-0 top-full mt-1.5 w-64 bg-white border border-zinc-100 rounded-xl shadow-lg z-40 p-3 space-y-3">
              {/* Stage */}
              {stages.length > 0 && (
                <div>
                  <p className="text-[10px] font-medium text-zinc-400 uppercase tracking-wide mb-1.5">Stage</p>
                  <div className="flex flex-wrap gap-1">
                    {stages.map(s => (
                      <button
                        key={s}
                        onClick={() => set({ stages: toggleIn(state.stages, s) })}
                        className={cn(
                          "text-[10px] px-2 py-1 rounded border transition-colors",
                          state.stages.includes(s)
                            ? "bg-zinc-900 text-white border-zinc-900"
                            : "border-zinc-100 text-zinc-500 hover:border-zinc-300"
                        )}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* AI forecast category */}
              <div>
                <p className="text-[10px] font-medium text-zinc-400 uppercase tracking-wide mb-1.5">AI Forecast</p>
                <div className="flex flex-wrap gap-1">
                  {FORECAST_CATEGORIES.map(c => (
                    <button
                      key={c}
                      onClick={() => set({ categories: toggleIn(state.categories, c) })}
                      className={cn(
                        "text-[10px] px-2 py-1 rounded border transition-colors",
                        state.categories.includes(c)
                          ? "bg-zinc-900 text-white border-zinc-900"
                          : "border-zinc-100 text-zinc-500 hover:border-zinc-300"
                      )}
                    >
                      {c}
                    </button>
                  ))}
                </div>
              </div>

              {/* Health */}
              <div>
                <p className="text-[10px] font-medium text-zinc-400 uppercase tracking-wide mb-1.5">Health</p>
                <div className="flex gap-1">
                  {([
                    { v: "all",  label: "All" },
                    { v: "good", label: "Good 70%+" },
                    { v: "fair", label: "Fair" },
                    { v: "poor", label: "Poor <40%" },
                  ] as { v: DealFilterState["health"]; label: string }[]).map(({ v, label }) => (
                    <button
                      key={v}
                      onClick={() => set({ health: v })}
                      className={cn(
                        "text-[10px] px-2 py-1 rounded border transition-colors",
                        state.health === v
                          ? "bg-zinc-900 text-white border-zinc-900"
                          : "border-zinc-100 text-zinc-500 hover:border-zinc-300"
                      )}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Drafts toggle + clear */}
              <div className="flex items-center justify-between pt-1 border-t border-zinc-100">
                <label className="flex items-center gap-1.5 text-[11px] text-zinc-600 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={state.draftsOnly}
                    onChange={e => set({ draftsOnly: e.target.checked })}
                    className="rounded border-zinc-300"
                  />
                  Has pending drafts
                </label>
                {active && (
                  <button
                    onClick={() => set({ q: "", stages: [], categories: [], health: "all", draftsOnly: false })}
                    className="text-[11px] text-zinc-500 hover:text-zinc-800 font-medium"
                  >
                    Clear all
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Sort pills */}
      <div className="flex items-center gap-1 overflow-x-auto pb-0.5">
        {sortOptions.map(k => (
          <button
            key={k}
            onClick={() => setSort(k)}
            title={SORT_TITLES[k]}
            className={cn(
              "flex-shrink-0 text-[12px] px-2.5 py-1 rounded-md transition-colors flex items-center gap-0.5 whitespace-nowrap",
              state.sort === k
                ? "font-semibold text-zinc-900 bg-white border border-zinc-200 shadow-sm"
                : "font-medium text-zinc-500 hover:text-zinc-800 hover:bg-lily-wash border border-transparent"
            )}
          >
            {SORT_LABELS[k]}
            {state.sort === k && (state.dir === "desc" ? <ChevronDown className="w-3 h-3" /> : <ChevronUp className="w-3 h-3" />)}
          </button>
        ))}
      </div>
    </div>
  );
}
