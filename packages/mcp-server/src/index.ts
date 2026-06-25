#!/usr/bin/env node
/**
 * Vantage MCP Server — 6 tools for per-account sales intelligence in Claude.
 * Transport: stdio (Claude Desktop) + HTTP (hosted endpoint)
 *
 * Tools:
 *   get_account_context  — full ASO for an account
 *   get_next_actions     — prioritised actions + urgency
 *   get_pov              — AI Point of View with CRM delta
 *   get_draft            — retrieve a specific draft
 *   log_interaction      — log a call/meeting/note to episodic memory
 *   search_accounts      — semantic search across portfolio
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  ErrorCode,
  McpError,
} from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";
import axios, { type AxiosInstance } from "axios";

// ── API client ────────────────────────────────────────────────────────────────

function createApiClient(): AxiosInstance {
  const apiUrl = process.env.VANTAGE_API_URL || "http://localhost:8000";
  const apiKey = process.env.VANTAGE_API_KEY;

  // Fail fast: undefined key produces "Bearer undefined" headers and silent 401s otherwise.
  if (!apiKey) {
    throw new Error("[Vantage MCP] VANTAGE_API_KEY is required. Set it in your Claude Desktop MCP config env.");
  }

  return axios.create({
    baseURL: apiUrl,
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    timeout: 30000,
  });
}

// ── Tool schemas ──────────────────────────────────────────────────────────────

const GetAccountContextSchema = z.object({
  account_id: z.string().describe("Account ID from Vantage"),
});

const GetNextActionsSchema = z.object({
  account_id: z.string().describe("Account ID"),
});

const GetPovSchema = z.object({
  account_id: z.string().describe("Account ID"),
});

const GetDraftSchema = z.object({
  draft_id: z.string().describe("Draft ID"),
});

const LogInteractionSchema = z.object({
  account_id: z.string().describe("Account ID"),
  interaction_type: z.enum(["call", "email_sent", "email_received", "meeting", "note", "api_feedback"]),
  notes: z.string().describe("Notes about the interaction"),
  outcome: z.string().optional().describe("What happened / next step"),
  is_training_signal: z.boolean().optional().default(false),
  training_category: z.enum(["wrong_tone", "wrong_timing", "wrong_content", "hallucination", "other"]).optional(),
});

const SearchAccountsSchema = z.object({
  query: z.string().describe("Natural language search query, e.g. 'accounts with competitive risk'"),
  limit: z.number().optional().default(10),
  min_urgency: z.number().optional().describe("Filter by minimum urgency (0-1)"),
  stage: z.string().optional().describe("Filter by deal stage"),
});


// Shared inputSchema for tools whose only parameter is account_id.
// Defined once here so ListTools and GET_ROUTES stay in sync without a manual diff step.
const ACCOUNT_ID_INPUT_SCHEMA = {
  type: "object",
  properties: {
    account_id: { type: "string", description: "The Vantage account ID" },
  },
  required: ["account_id"],
} as const;

const GET_DRAFT_INPUT_SCHEMA = {
  type: "object",
  properties: { draft_id: { type: "string" } },
  required: ["draft_id"],
} as const;

const LOG_INTERACTION_INPUT_SCHEMA = {
  type: "object",
  properties: {
    account_id: { type: "string" },
    interaction_type: {
      type: "string",
      enum: ["call", "email_sent", "email_received", "meeting", "note", "api_feedback"],
    },
    notes: { type: "string" },
    outcome: { type: "string" },
    is_training_signal: { type: "boolean" },
    training_category: {
      type: "string",
      enum: ["wrong_tone", "wrong_timing", "wrong_content", "hallucination", "other"],
    },
  },
  required: ["account_id", "interaction_type", "notes"],
} as const;

const SEARCH_ACCOUNTS_INPUT_SCHEMA = {
  type: "object",
  properties: {
    query: { type: "string" },
    limit: { type: "number" },
    min_urgency: { type: "number" },
    stage: { type: "string" },
  },
  required: ["query"],
} as const;

// ── Server ─────────────────────────────────────────────────────────────────────

const server = new Server(
  {
    name: "vantage",
    version: "0.1.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// Eager singleton: axios reuses the same connection pool across all tool calls.
const api = createApiClient();

// List tools
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "get_account_context",
      description:
        "Get the full Account State Object (ASO) for a specific account. " +
        "Includes signals, POV, health score, urgency, stakeholders, and episodic memory. " +
        "Use this to understand everything about an account before drafting comms or preparing for a meeting.",
      inputSchema: ACCOUNT_ID_INPUT_SCHEMA,
    },
    {
      name: "get_next_actions",
      description:
        "Get AI-prioritised next actions for an account, ranked by urgency. " +
        "Each action includes a rationale, deadline, and whether a draft is recommended.",
      inputSchema: ACCOUNT_ID_INPUT_SCHEMA,
    },
    {
      name: "get_pov",
      description:
        "Get the AI Point of View for an account — AI forecast category, confidence, risks, and signals. " +
        "Also shows the delta between AI POV and CRM data (our key differentiator).",
      inputSchema: ACCOUNT_ID_INPUT_SCHEMA,
    },
    {
      name: "get_draft",
      description: "Retrieve a specific AI-generated draft email or meeting brief by ID.",
      inputSchema: GET_DRAFT_INPUT_SCHEMA,
    },
    {
      name: "log_interaction",
      description:
        "Log an interaction (call, email, meeting, note) to an account's episodic memory. " +
        "This updates the agent's context for future runs. " +
        "If is_training_signal=true, also flags the interaction to improve agent quality.",
      inputSchema: LOG_INTERACTION_INPUT_SCHEMA,
    },
    {
      name: "search_accounts",
      description:
        "Semantic search across all accounts in your portfolio. " +
        "Uses pgvector similarity search ranked by relevance × urgency. " +
        "Example queries: 'accounts with competitive threat', 'deals stalling in legal review', " +
        "'accounts where champion went dark'.",
      inputSchema: SEARCH_ACCOUNTS_INPUT_SCHEMA,
    },
  ],
}));

// ── Dispatch helpers ──────────────────────────────────────────────────────────

type GetRoute = { schema: z.ZodObject<z.ZodRawShape>; url: (p: Record<string, string>) => string };

const GET_ROUTES: Record<string, GetRoute> = {
  get_account_context: { schema: GetAccountContextSchema, url: ({ account_id }) => `/v1/accounts/${account_id}/state` },
  get_next_actions:    { schema: GetNextActionsSchema,    url: ({ account_id }) => `/v1/accounts/${account_id}/next-actions` },
  get_pov:             { schema: GetPovSchema,            url: ({ account_id }) => `/v1/accounts/${account_id}/pov` },
  get_draft:           { schema: GetDraftSchema,          url: ({ draft_id })   => `/v1/drafts/${draft_id}` },
};

async function dispatchGet(name: string, args: unknown) {
  const route = GET_ROUTES[name];
  // Zod strips non-string fields; cast is safe because all route schemas only use z.string() values.
  const parsed = route.schema.parse(args) as Record<string, string>;
  const res = await api.get(route.url(parsed));
  return { content: [{ type: "text", text: JSON.stringify(res.data, null, 2) }] };
}

// Prose-formatted (not JSON.stringify) so Claude can read results inline without parsing.
function formatSearchResults(results: Record<string, unknown>[]): string {
  if (results.length === 0) return "No accounts found matching your query.";
  return (
    `Found ${results.length} accounts:\n\n` +
    results
      .map((r, i) =>
        `${i + 1}. **${r.name}** (${r.stage})\n` +
        `   Relevance: ${Math.round((r.relevance_score as number) * 100)}% | ` +
        `Urgency: ${Math.round(((r.urgency_score as number) ?? 0) * 100)}% | ` +
        `AI Forecast: ${r.pov_forecast_cat ?? "—"}\n` +
        `   ID: ${r.id}`
      )
      .join("\n\n")
  );
}

// Handle tool calls
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case "get_account_context":
      case "get_next_actions":
      case "get_pov":
      case "get_draft":
        return await dispatchGet(name, args);

      case "log_interaction": {
        const body = LogInteractionSchema.parse(args);
        const { account_id, ...rest } = body;
        // Endpoint is /feedback — the backend uses the same route for both training signals and interaction logs.
        const res = await api.post(`/v1/accounts/${account_id}/feedback`, rest);
        // res.data = axios envelope; res.data.data = FastAPI { data: { interaction_id } } body
        return {
          content: [{ type: "text", text: `Interaction logged. ID: ${res.data?.data?.interaction_id}` }],
        };
      }

      case "search_accounts": {
        const body = SearchAccountsSchema.parse(args);
        const res = await api.post("/v1/accounts/search", body);
        // res.data.data: FastAPI search envelope wraps the results array one level deep
        const results: Record<string, unknown>[] = res.data?.data ?? [];
        return { content: [{ type: "text", text: formatSearchResults(results) }] };
      }

      default:
        throw new McpError(ErrorCode.MethodNotFound, `Unknown tool: ${name}`);
    }
  } catch (error: unknown) {
    if (error instanceof McpError) throw error;

    const message = error instanceof Error ? error.message : String(error);
    throw new McpError(ErrorCode.InternalError, `Tool error: ${message}`);
  }
});

// Start server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  // stdio transport uses stdout for MCP framing; all logging must go to stderr to avoid protocol corruption.
  console.error("[Vantage MCP] Server running on stdio");
}

main().catch((err) => {
  console.error("[Vantage MCP] Fatal error:", err);
  process.exit(1);
});
