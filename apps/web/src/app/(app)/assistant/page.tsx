"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { accountsApi, streamChat } from "@/lib/api";
import { AuditPanel } from "@/components/audit/audit-panel";
import { Send, Bot, User, Loader, Shield, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import { Suspense } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Message {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  isStreaming?: boolean;
}

interface Citation {
  source: string;
  date: string;
  gold_data: Record<string, unknown>;
}

const STARTER_PROMPTS = [
  "Which deals are most at risk this quarter?",
  "Summarise the top 3 deals I should focus on today",
  "What changed in my pipeline last week?",
  "Which accounts have competitive threats?",
];

// ── Inner component (reads search params inside Suspense) ──────────────────────

function AssistantInner() {
  const searchParams = useSearchParams();
  const seedAccountId = searchParams.get("account_id") ?? "";
  const shouldSeed = searchParams.get("seed") === "true";

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [selectedAccountId, setSelectedAccountId] = useState<string>(seedAccountId);
  const [threadId, setThreadId] = useState<string | undefined>();
  const [useWebResearch, setUseWebResearch] = useState(false);
  const [auditTarget, setAuditTarget] = useState<{ fact: string } | null>(null);
  // Ref, not state: Strict Mode double-fires effects before a state update
  // re-renders, which would post the seed question twice when the account
  // list is already cached
  const seededRef = useRef(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Account list for selector
  const { data: accountsData } = useQuery({
    queryKey: ["accounts", "all"],
    queryFn: () => accountsApi.list({ limit: 100 }),
    staleTime: 5 * 60 * 1000,
  });
  const accounts = accountsData?.data ?? [];

  // Find the seeded account name for prompt construction
  const seedAccount = accounts.find(a => a.id === seedAccountId);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Core send function
  const handleSend = useCallback(async (text?: string) => {
    const userMessage = (text ?? input).trim();
    if (!userMessage || isLoading) return;

    if (!text) setInput("");
    setMessages(prev => [...prev, { role: "user", content: userMessage }]);
    setIsLoading(true);
    setMessages(prev => [...prev, { role: "assistant", content: "", isStreaming: true, citations: [] }]);

    try {
      let fullText = "";
      const citations: Citation[] = [];

      for await (const chunk of streamChat({
        message: userMessage,
        account_id: selectedAccountId || undefined,
        thread_id: threadId,
        use_web_research: useWebResearch,
      })) {
        if (chunk.type === "thread") {
          setThreadId(chunk.thread_id);
        } else if (chunk.type === "text") {
          fullText += chunk.delta ?? chunk.content ?? "";
          setMessages(prev => {
            const copy = [...prev];
            copy[copy.length - 1] = { ...copy[copy.length - 1], content: fullText };
            return copy;
          });
        } else if (chunk.type === "citation" || chunk.type === "citations") {
          const incoming = chunk.citation ? [chunk.citation] : chunk.citations ?? [];
          citations.push(...incoming);
        } else if (chunk.type === "done") {
          setMessages(prev => {
            const copy = [...prev];
            copy[copy.length - 1] = { ...copy[copy.length - 1], content: fullText, citations, isStreaming: false };
            return copy;
          });
        }
      }
    } catch {
      setMessages(prev => {
        const copy = [...prev];
        copy[copy.length - 1] = { role: "assistant", content: "Sorry, something went wrong. Please try again.", isStreaming: false };
        return copy;
      });
    } finally {
      setIsLoading(false);
    }
  }, [input, isLoading, selectedAccountId, threadId, useWebResearch]);

  // Auto-seed the conversation when ?seed=true is in the URL
  useEffect(() => {
    if (!shouldSeed || seededRef.current || !selectedAccountId) return;
    if (accounts.length === 0) return; // wait for account list
    const name = seedAccount?.name ?? "this account";
    seededRef.current = true;
    handleSend(
      `I just opened the War Room for ${name}. Give me a sharp situation brief: ` +
      `the single biggest risk, the most urgent action I should take today, and the best opening line if I call them right now.`
    );
  }, [shouldSeed, selectedAccountId, accounts, seedAccount, handleSend]);

  return (
    <div className="flex h-full">
      {/* Chat panel */}
      <div className="flex flex-col flex-1">
        {/* Header */}
        <div className="bg-white border-b border-zinc-200 px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-base font-semibold text-zinc-900">Assistant</h1>
            <p className="text-xs text-zinc-500 mt-0.5">
              Answers sourced from your account data · Every fact has a citation
            </p>
          </div>
          <div className="flex items-center gap-4">
            {/* Account scope selector */}
            <select
              value={selectedAccountId}
              onChange={e => {
                setSelectedAccountId(e.target.value);
                setThreadId(undefined);
                setMessages([]);
                seededRef.current = false;
              }}
              className="text-sm border border-zinc-200 rounded-lg px-3 py-1.5 bg-zinc-50 focus:outline-none focus:ring-2 focus:ring-brand-500"
            >
              <option value="">All accounts</option>
              {accounts.map(a => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>

            {/* Exa web research toggle */}
            <label className="flex items-center gap-1.5 text-xs text-zinc-600 cursor-pointer select-none">
              <div className="relative">
                <input
                  type="checkbox"
                  checked={useWebResearch}
                  onChange={e => setUseWebResearch(e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-8 h-4 bg-zinc-200 peer-checked:bg-zinc-800 rounded-full transition-colors" />
                <div className="absolute top-0.5 left-0.5 w-3 h-3 bg-white rounded-full transition-transform peer-checked:translate-x-4" />
              </div>
              <Zap className="w-3 h-3" />
              Live web
            </label>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center min-h-[400px]">
              <div className="w-12 h-12 bg-brand-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
                <Bot className="w-6 h-6 text-brand-600" />
              </div>
              <p className="text-sm font-semibold text-zinc-700 mb-1">
                {selectedAccountId && seedAccount
                  ? `Ask me anything about ${seedAccount.name}`
                  : "Start a conversation"
                }
              </p>
              <p className="text-xs text-zinc-400 mb-6">
                Answers are sourced from your account data. Every response cites where each fact came from.
              </p>
              <div className="grid grid-cols-2 gap-2 max-w-lg mx-auto">
                {(selectedAccountId && seedAccount
                  ? [
                      `What's the biggest risk with ${seedAccount.name}?`,
                      `Draft a follow-up for ${seedAccount.name}`,
                      `Who are the stakeholders at ${seedAccount.name}?`,
                      `What's the deal history for ${seedAccount.name}?`,
                    ]
                  : STARTER_PROMPTS
                ).map((prompt, i) => (
                  <button
                    key={i}
                    onClick={() => handleSend(prompt)}
                    className="text-left text-xs text-zinc-600 border border-zinc-200 rounded-xl px-3.5 py-2.5 hover:bg-zinc-50 hover:border-zinc-300 transition-colors"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className={cn("flex gap-3", msg.role === "user" ? "justify-end" : "justify-start")}>
              {msg.role === "assistant" && (
                <div className="w-7 h-7 bg-brand-100 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Bot className="w-4 h-4 text-brand-600" />
                </div>
              )}

              <div className={cn("max-w-2xl", msg.role === "user" ? "order-first" : "")}>
                <div
                  data-testid={msg.role === "assistant" ? "assistant-message" : undefined}
                  className={cn(
                    "rounded-2xl px-4 py-3 text-sm leading-relaxed",
                    msg.role === "user"
                      ? "bg-brand-600 text-white rounded-br-sm"
                      : "bg-white border border-zinc-200 text-zinc-800 rounded-bl-sm"
                  )}>
                  {msg.role === "user" ? (
                    msg.content
                  ) : msg.content ? (
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        // Headings
                        h1: ({ children }) => <h1 className="text-base font-bold text-zinc-900 mt-3 mb-1.5 first:mt-0">{children}</h1>,
                        h2: ({ children }) => <h2 className="text-sm font-bold text-zinc-900 mt-3 mb-1.5 first:mt-0">{children}</h2>,
                        h3: ({ children }) => <h3 className="text-sm font-semibold text-zinc-800 mt-2.5 mb-1 first:mt-0">{children}</h3>,
                        // Paragraphs
                        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                        // Lists
                        ul: ({ children }) => <ul className="mb-2 pl-4 space-y-0.5 list-disc">{children}</ul>,
                        ol: ({ children }) => <ol className="mb-2 pl-4 space-y-0.5 list-decimal">{children}</ol>,
                        li: ({ children }) => <li className="text-zinc-700">{children}</li>,
                        // Inline emphasis
                        strong: ({ children }) => <strong className="font-semibold text-zinc-900">{children}</strong>,
                        em: ({ children }) => <em className="italic text-zinc-700">{children}</em>,
                        // Horizontal rule
                        hr: () => <hr className="my-3 border-zinc-200" />,
                        // Blockquote
                        blockquote: ({ children }) => (
                          <blockquote className="border-l-2 border-brand-400 pl-3 my-2 text-zinc-600 italic text-xs">
                            {children}
                          </blockquote>
                        ),
                        // Inline code & code blocks
                        code: ({ children, className }) =>
                          className ? (
                            <pre className="bg-zinc-50 border border-zinc-200 rounded-lg px-3 py-2 my-2 text-xs font-mono overflow-x-auto">
                              <code>{children}</code>
                            </pre>
                          ) : (
                            <code className="bg-zinc-100 rounded px-1 py-0.5 text-xs font-mono text-zinc-800">{children}</code>
                          ),
                        // Tables (GFM)
                        table: ({ children }) => (
                          <div className="overflow-x-auto my-2">
                            <table className="min-w-full text-xs border-collapse">{children}</table>
                          </div>
                        ),
                        th: ({ children }) => <th className="border border-zinc-200 px-2 py-1 bg-zinc-50 font-semibold text-left">{children}</th>,
                        td: ({ children }) => <td className="border border-zinc-200 px-2 py-1">{children}</td>,
                      }}
                    >
                      {msg.content}
                    </ReactMarkdown>
                  ) : msg.isStreaming ? (
                    <span data-testid="typing-indicator" className="flex items-center gap-1.5 text-zinc-400">
                      <Loader className="w-3.5 h-3.5 animate-spin" />
                      Thinking…
                    </span>
                  ) : null}
                </div>

                {/* Citations */}
                {msg.citations && msg.citations.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {msg.citations.map((c, ci) => (
                      <button
                        key={ci}
                        onClick={() => setAuditTarget({ fact: c.source })}
                        className="citation-chip"
                      >
                        <Shield className="w-2.5 h-2.5" />
                        {c.source}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {msg.role === "user" && (
                <div className="w-7 h-7 bg-zinc-200 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5">
                  <User className="w-4 h-4 text-zinc-500" />
                </div>
              )}
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="bg-white border-t border-zinc-200 px-6 py-4">
          <div className="flex gap-3">
            <input
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === "Enter" && !e.shiftKey && handleSend()}
              placeholder={
                selectedAccountId && seedAccount
                  ? `Ask about ${seedAccount.name}…`
                  : "Ask about any account, or search across your portfolio…"
              }
              className="flex-1 text-sm border border-zinc-200 rounded-xl px-4 py-3 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent"
            />
            <button
              onClick={() => handleSend()}
              disabled={isLoading || !input.trim()}
              aria-label="Send"
              className="px-4 py-3 bg-brand-600 text-white rounded-xl hover:bg-brand-700 transition-colors disabled:opacity-50 flex items-center gap-2"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
          {selectedAccountId && seedAccount && (
            <p className="text-xs text-zinc-400 mt-1.5 flex items-center gap-1">
              <Shield className="w-3 h-3" />
              Scoped to {seedAccount.name}. Click any source citation to see where each fact came from.
            </p>
          )}
        </div>
      </div>

      {/* Audit Panel */}
      {auditTarget && selectedAccountId && (
        <AuditPanel
          accountId={selectedAccountId}
          factKey={auditTarget.fact}
          onClose={() => setAuditTarget(null)}
        />
      )}
    </div>
  );
}

// ── Page export with Suspense for useSearchParams ──────────────────────────────

export default function AssistantPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center h-full">
        <div className="w-6 h-6 border-2 border-brand-600 border-t-transparent rounded-full animate-spin" />
      </div>
    }>
      <AssistantInner />
    </Suspense>
  );
}
