"use client";

import { type AccountSearchResult } from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";
import { Search } from "lucide-react";
import { cn } from "@/lib/utils";
import Link from "next/link";

interface Props {
  query: string;
  results: AccountSearchResult[];
  isLoading: boolean;
  onSelect: (id: string) => void;
}

export function SearchResults({ query, results, isLoading, onSelect }: Props) {
  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="flex items-center gap-2 mb-1">
        <Search className="w-4 h-4 text-gray-400" />
        <h1 className="text-base font-semibold text-gray-900">
          Search: <span className="text-brand-600">{query}</span>
        </h1>
      </div>
      <p className="text-xs text-gray-400 mb-6">Semantic search · Ranked by relevance × urgency</p>

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-20 w-full" />)}
        </div>
      ) : results.length === 0 ? (
        <div className="text-center py-12 text-gray-400">
          <p className="text-sm">No accounts match your query</p>
          <p className="text-xs mt-1">Try different keywords or adjust your search</p>
        </div>
      ) : (
        <div className="space-y-3">
          {results.map((account, i) => (
            <button
              key={account.id}
              onClick={() => onSelect(account.id)}
              className="w-full text-left bg-white border border-gray-200 rounded-xl px-5 py-4 hover:border-brand-300 hover:shadow-sm transition-all"
            >
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-sm font-semibold text-gray-900">{account.name}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{account.stage}</p>
                </div>
                <div className="flex items-center gap-3">
                  <div className="text-right">
                    <p className="text-xs text-gray-400">Relevance</p>
                    <p className="text-sm font-medium text-brand-600">{Math.round(account.relevance_score * 100)}%</p>
                  </div>
                  {account.pov_forecast_cat && (
                    <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium",
                      account.pov_forecast_cat === "Commit" ? "forecast-commit" : "forecast-pipeline"
                    )}>
                      {account.pov_forecast_cat}
                    </span>
                  )}
                </div>
              </div>
              {account.signals_summary?.[0] && (
                <p className="text-xs text-gray-500 mt-2 truncate">↑ {account.signals_summary[0].detail}</p>
              )}
            </button>
          ))}
        </div>
      )}

      <div className="mt-4">
        <Link href="/inbox" className="text-xs text-gray-400 hover:text-gray-600">← Back to inbox</Link>
      </div>
    </div>
  );
}
