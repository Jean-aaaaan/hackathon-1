/**
 * Shared renderer for agent-generated draft/brief content.
 * Handles the markdown subset drafts use: # / ## / ### headings, **bold**,
 * *italic*, - bullet lists, | pipe tables |, > blockquotes, --- rules,
 * blank-line spacing.
 *
 * Every surface that shows draft content must use this (or stripMarkdown for
 * compact previews) — raw `<pre>{content}</pre>` shows reps literal ## and **.
 */
import React from "react";

export function MarkdownContent({ content }: { content: string }) {
  if (!content) return null;

  const lines = content.split("\n");
  const nodes: React.ReactNode[] = [];
  let listBuffer: string[] = [];
  let tableBuffer: string[] = [];
  let quoteBuffer: string[] = [];

  const flushList = (key: string) => {
    if (listBuffer.length === 0) return;
    nodes.push(
      <ul key={`list-${key}`} className="space-y-0.5 my-1.5 ml-1">
        {listBuffer.map((item, i) => (
          <li key={i} className="flex items-start gap-2 text-sm text-gray-800 leading-relaxed">
            <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-gray-400 flex-shrink-0" />
            <span>{renderInline(item)}</span>
          </li>
        ))}
      </ul>
    );
    listBuffer = [];
  };

  const flushTable = (key: string) => {
    if (tableBuffer.length === 0) return;
    const rows = tableBuffer
      .map(r => r.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(c => c.trim()))
      .filter(cells => !cells.every(c => /^:?-{2,}:?$/.test(c) || c === "")); // drop |---|---| separators
    if (rows.length > 0) {
      const [head, ...body] = rows;
      nodes.push(
        <div key={`table-${key}`} className="my-2 overflow-x-auto">
          <table className="w-full text-xs border border-gray-200 rounded-lg overflow-hidden">
            <thead>
              <tr className="bg-gray-50">
                {head.map((c, i) => (
                  <th key={i} className="text-left font-semibold text-gray-700 px-2.5 py-1.5 border-b border-gray-200">
                    {renderInline(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {body.map((cells, ri) => (
                <tr key={ri} className={ri % 2 ? "bg-gray-50/50" : ""}>
                  {cells.map((c, ci) => (
                    <td key={ci} className="text-gray-700 px-2.5 py-1.5 border-b border-gray-100 align-top leading-relaxed">
                      {renderInline(c)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    tableBuffer = [];
  };

  const flushQuote = (key: string) => {
    if (quoteBuffer.length === 0) return;
    nodes.push(
      <div key={`quote-${key}`} className="my-2 border-l-2 border-amber-300 bg-amber-50/60 rounded-r-lg px-3 py-2 space-y-1">
        {quoteBuffer.map((q, i) =>
          q.trim() === "" ? <div key={i} className="h-1" /> : (
            <p key={i} className="text-sm text-gray-700 leading-relaxed">{renderInline(q)}</p>
          )
        )}
      </div>
    );
    quoteBuffer = [];
  };

  const flushAll = (key: string) => {
    flushList(key);
    flushTable(key);
    flushQuote(key);
  };

  lines.forEach((line, idx) => {
    const trimmed = line.trim();

    // table row
    if (trimmed.startsWith("|") && trimmed.includes("|", 1)) {
      flushList(String(idx));
      flushQuote(String(idx));
      tableBuffer.push(trimmed);
      return;
    }
    if (tableBuffer.length > 0) flushTable(String(idx));

    // blockquote
    if (trimmed.startsWith(">")) {
      flushList(String(idx));
      quoteBuffer.push(trimmed.replace(/^>\s?/, ""));
      return;
    }
    if (quoteBuffer.length > 0) flushQuote(String(idx));

    // horizontal rule
    if (/^[-_*]{3,}$/.test(trimmed)) {
      flushAll(String(idx));
      nodes.push(<hr key={idx} className="my-2.5 border-gray-100" />);
      return;
    }

    // h1 / h2
    if (trimmed.startsWith("# ") || trimmed.startsWith("## ")) {
      flushAll(String(idx));
      nodes.push(
        <h3 key={idx} className="text-sm font-bold text-gray-900 mt-3 mb-1 first:mt-0">
          {renderInline(trimmed.replace(/^#{1,2}\s/, ""))}
        </h3>
      );
      return;
    }

    // h3
    if (trimmed.startsWith("### ")) {
      flushAll(String(idx));
      nodes.push(
        <h4 key={idx} className="text-xs font-semibold text-gray-700 uppercase tracking-wide mt-2.5 mb-1">
          {renderInline(trimmed.slice(4))}
        </h4>
      );
      return;
    }

    // bullet
    if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
      listBuffer.push(trimmed.slice(2));
      return;
    }

    // blank line
    if (trimmed === "") {
      flushAll(String(idx));
      nodes.push(<div key={idx} className="h-1.5" />);
      return;
    }

    // paragraph (may be "**Label:** value" style)
    flushAll(String(idx));
    nodes.push(
      <p key={idx} className="text-sm text-gray-800 leading-relaxed">
        {renderInline(trimmed)}
      </p>
    );
  });

  flushAll("end");

  return <div className="space-y-0.5">{nodes}</div>;
}

/** Renders inline markdown: **bold**, *italic*, `code`. */
function renderInline(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return <strong key={i} className="font-semibold text-gray-900">{part.slice(2, -2)}</strong>;
        }
        if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
          return <code key={i} className="text-[12px] bg-gray-100 rounded px-1 py-0.5 font-mono">{part.slice(1, -1)}</code>;
        }
        if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
          return <em key={i}>{part.slice(1, -1)}</em>;
        }
        return part;
      })}
    </>
  );
}

/** Strips markdown tokens for compact line-clamped previews. */
export function stripMarkdown(content: string): string {
  if (!content) return "";
  return content
    .replace(/^#{1,4}\s+/gm, "")      // heading markers
    .replace(/\*\*([^*]+)\*\*/g, "$1") // bold
    .replace(/\*([^*]+)\*/g, "$1")     // italic
    .replace(/`([^`]+)`/g, "$1")       // inline code
    .replace(/^>\s?/gm, "")            // blockquote markers
    .replace(/^\|.*\|$/gm, "")         // table rows (too dense for previews)
    .replace(/^[-_*]{3,}$/gm, "")      // horizontal rules
    .replace(/^[-*]\s+/gm, "")         // bullet markers
    .replace(/\n{2,}/g, " · ")         // paragraph breaks in one-line previews
    .replace(/\n/g, " ")
    .trim();
}
