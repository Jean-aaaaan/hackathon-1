/**
 * Vantage Chrome Extension — Service Worker (background.js)
 * Handles API calls, storage, and message routing between content scripts and popup.
 */

const DEFAULT_API_URL = "https://api.vantage.ai";

// Only allow fetching from the production API or localhost in development
const ALLOWED_API_ORIGINS = new Set([
  "https://api.vantage.ai",
]);

function _isAllowedApiUrl(url: string): boolean {
  try {
    const { protocol, hostname, origin } = new URL(url);
    if (ALLOWED_API_ORIGINS.has(origin)) return true;
    // Permit localhost on any port for local development builds
    if ((protocol === "http:" || protocol === "https:") && hostname === "localhost") return true;
    return false;
  } catch {
    return false;
  }
}

// ── Message types ────────────────────────────────────────────────────────────

interface VantageMessage {
  type:
    | "GET_ACCOUNT_BY_HUBSPOT"
    | "GET_ACCOUNT_BY_NAME"
    | "GET_SETTINGS"
    | "SAVE_SETTINGS"
    | "SIDEBAR_READY";
  payload?: Record<string, unknown>;
}

// ── Storage helpers ───────────────────────────────────────────────────────────

async function getSettings(): Promise<{ apiKey: string; apiUrl: string }> {
  const result = await chrome.storage.sync.get(["apiKey", "apiUrl"]);
  const stored = (result.apiUrl as string) || DEFAULT_API_URL;
  return {
    apiKey: (result.apiKey as string) || "",
    apiUrl: _isAllowedApiUrl(stored) ? stored : DEFAULT_API_URL,
  };
}

// ── Vantage API calls ─────────────────────────────────────────────────────────

async function fetchFromVantage(path: string, { apiKey, apiUrl }: { apiKey: string; apiUrl: string }) {
  if (!apiKey) return null;

  const res = await fetch(`${apiUrl}${path}`, {
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
  });

  if (!res.ok) return null;
  return res.json();
}

async function getAccountByHubspotId(hubspotDealId: string) {
  const settings = await getSettings();
  // Search by HubSpot deal ID via accounts list endpoint
  const data = await fetchFromVantage(
    `/v1/accounts?hubspot_deal_id=${encodeURIComponent(hubspotDealId)}&limit=1`,
    settings
  );
  return data?.data?.[0] || null;
}

async function getAccountByName(name: string) {
  const settings = await getSettings();
  if (!name) return null;

  // Use semantic search to find the closest matching account
  const res = await fetch(`${settings.apiUrl}/v1/accounts/search`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${settings.apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ query: name, limit: 1 }),
  });

  if (!res.ok) return null;
  const data = await res.json();
  return data?.data?.[0] || null;
}

async function getAccountState(accountId: string) {
  const settings = await getSettings();
  return fetchFromVantage(`/v1/accounts/${accountId}/state`, settings);
}

async function getNextActions(accountId: string) {
  const settings = await getSettings();
  return fetchFromVantage(`/v1/accounts/${accountId}/next-actions`, settings);
}

// ── Message handler ───────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message: VantageMessage, sender, sendResponse) => {
  (async () => {
    try {
      switch (message.type) {
        case "GET_ACCOUNT_BY_HUBSPOT": {
          const dealId = message.payload?.dealId as string;
          const account = await getAccountByHubspotId(dealId);
          if (account) {
            const [state, actions] = await Promise.all([
              getAccountState(account.id),
              getNextActions(account.id),
            ]);
            sendResponse({ account, state: state?.data, actions: actions?.data });
          } else {
            sendResponse({ account: null });
          }
          break;
        }

        case "GET_ACCOUNT_BY_NAME": {
          const name = message.payload?.name as string;
          const account = await getAccountByName(name);
          if (account) {
            const [state, actions] = await Promise.all([
              getAccountState(account.id),
              getNextActions(account.id),
            ]);
            sendResponse({ account, state: state?.data, actions: actions?.data });
          } else {
            sendResponse({ account: null });
          }
          break;
        }

        case "GET_SETTINGS": {
          const settings = await getSettings();
          sendResponse(settings);
          break;
        }

        case "SAVE_SETTINGS": {
          // Only the extension's own popup may write settings
          if (sender.id !== chrome.runtime.id) {
            sendResponse({ error: "Unauthorized" });
            break;
          }
          await chrome.storage.sync.set(message.payload);
          sendResponse({ saved: true });
          break;
        }

        default:
          sendResponse({ error: "Unknown message type" });
      }
    } catch (err) {
      sendResponse({ error: String(err) });
    }
  })();

  return true; // Keep message channel open for async response
});

// ── Tab change listener — auto-detect CRM context ────────────────────────────

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete" || !tab.url) return;

  // HubSpot deal URL detection
  const hubspotMatch = tab.url.match(/app\.hubspot\.com\/contacts\/\d+\/deal\/(\d+)/);
  if (hubspotMatch) {
    chrome.tabs.sendMessage(tabId, {
      type: "DEAL_DETECTED",
      payload: { dealId: hubspotMatch[1] },
    }).catch(() => {
      // Content script not ready yet — ignore
    });
  }
});
