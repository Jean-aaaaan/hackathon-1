/**
 * HubSpot content script — injects Vantage sidebar on deal pages.
 *
 * Detects URL pattern: app.hubspot.com/contacts/{portal}/deal/{dealId}
 * Extracts deal ID → asks background to fetch ASO → renders sidebar.
 *
 * The sidebar is a floating panel injected into the DOM, positioned
 * on the right edge of the HubSpot UI. It shows:
 *   - Urgency score + health bar
 *   - AI forecast vs CRM stage
 *   - Top 3 signals
 *   - Top next action
 *   - "Open War Room" deep link
 */

const SIDEBAR_ID = "vantage-sidebar-root";
const SIDEBAR_WIDTH = 320;

function esc(s: unknown): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;");
}

// ── Sidebar HTML ──────────────────────────────────────────────────────────────

function buildSidebarHTML(data: {
  account: Record<string, unknown>;
  state?: Record<string, unknown>;
  actions?: { next_actions?: Array<{ action: string; urgency_score: number }> };
}): string {
  const { account, state, actions } = data;
  const urgencyScore = (account.urgency_score as number) ?? 0;
  const healthScore = (account.health_score as number) ?? 0;
  const urgencyPct = Math.round(urgencyScore * 100);
  const healthPct = Math.round(healthScore * 100);
  const forecastCat = (account.pov_forecast_cat as string) ?? "—";
  const name = (account.name as string) ?? "Account";
  const stage = (account.stage as string) ?? "—";

  const urgencyColor =
    urgencyScore >= 0.85 ? "#ef4444" :
    urgencyScore >= 0.7  ? "#f97316" :
    urgencyScore >= 0.5  ? "#eab308" : "#22c55e";

  const healthColor =
    healthScore >= 0.7 ? "#22c55e" :
    healthScore >= 0.4 ? "#eab308" : "#ef4444";

  // Signals from state ASO
  const signals = (state?.signals as Array<{ type: string; detail: string; urgency: string }>) ?? [];
  const signalsHTML = signals.slice(0, 3).map(s => `
    <div style="font-size:11px;padding:4px 0;border-bottom:1px solid #f3f4f6;color:#374151;">
      <span style="text-transform:uppercase;font-weight:600;font-size:9px;color:#6b7280;">${esc(s.type)}</span>
      <div style="margin-top:2px;">${esc(s.detail)}</div>
    </div>
  `).join("") || '<div style="font-size:11px;color:#9ca3af;padding:4px 0;">No active signals</div>';

  // Top action
  const topAction = actions?.next_actions?.[0];

  const frontendUrl = "https://vantage.invigilo.ai";
  const accountId = account.id as string;

  return `
    <div style="
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      font-size: 13px;
      color: #111827;
      height: 100%;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    ">
      <!-- Header -->
      <div style="background:#4f46e5;padding:12px 14px;flex-shrink:0;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:2px;">
          <span style="color:rgba(255,255,255,0.7);font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">⚡ Vantage</span>
          <button id="vantage-close-btn" style="
            background:none;border:none;color:rgba(255,255,255,0.6);cursor:pointer;
            font-size:16px;line-height:1;padding:0;
          ">×</button>
        </div>
        <div style="color:#fff;font-size:14px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${esc(name)}</div>
        <div style="color:rgba(255,255,255,0.6);font-size:11px;">${esc(stage)}</div>
      </div>

      <!-- Scrollable body -->
      <div style="flex:1;overflow-y:auto;padding:12px 14px;background:#fff;">

        <!-- KPIs -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px;">
          <div style="background:#f9fafb;border-radius:8px;padding:8px;">
            <div style="font-size:9px;color:#6b7280;text-transform:uppercase;font-weight:600;margin-bottom:3px;">Urgency</div>
            <div style="font-size:18px;font-weight:700;color:${urgencyColor};">${urgencyPct}%</div>
            <div style="height:3px;background:#e5e7eb;border-radius:4px;margin-top:4px;overflow:hidden;">
              <div style="width:${urgencyPct}%;height:100%;background:${urgencyColor};border-radius:4px;"></div>
            </div>
          </div>
          <div style="background:#f9fafb;border-radius:8px;padding:8px;">
            <div style="font-size:9px;color:#6b7280;text-transform:uppercase;font-weight:600;margin-bottom:3px;">Health</div>
            <div style="font-size:18px;font-weight:700;color:${healthColor};">${healthPct}%</div>
            <div style="height:3px;background:#e5e7eb;border-radius:4px;margin-top:4px;overflow:hidden;">
              <div style="width:${healthPct}%;height:100%;background:${healthColor};border-radius:4px;"></div>
            </div>
          </div>
        </div>

        <!-- AI Forecast -->
        <div style="margin-bottom:14px;">
          <div style="font-size:9px;color:#6b7280;text-transform:uppercase;font-weight:600;margin-bottom:4px;">AI Forecast</div>
          <span style="
            display:inline-block;font-size:11px;font-weight:600;
            padding:3px 8px;border-radius:20px;
            background:${forecastCat === "Commit" ? "#dcfce7" : forecastCat === "Omit" ? "#fee2e2" : "#f3f4f6"};
            color:${forecastCat === "Commit" ? "#166534" : forecastCat === "Omit" ? "#991b1b" : "#374151"};
          ">${forecastCat}</span>
        </div>

        <!-- Top action -->
        ${topAction ? `
        <div style="margin-bottom:14px;padding:10px;background:#eef2ff;border-radius:8px;border-left:3px solid #4f46e5;">
          <div style="font-size:9px;color:#4f46e5;text-transform:uppercase;font-weight:600;margin-bottom:4px;">Top Action</div>
          <div style="font-size:12px;color:#1e1b4b;font-weight:500;">${esc(topAction.action)}</div>
        </div>
        ` : ""}

        <!-- Signals -->
        <div style="margin-bottom:14px;">
          <div style="font-size:9px;color:#6b7280;text-transform:uppercase;font-weight:600;margin-bottom:6px;">Signals</div>
          ${signalsHTML}
        </div>

      </div>

      <!-- Footer CTA -->
      <div style="padding:10px 14px;border-top:1px solid #f3f4f6;flex-shrink:0;display:flex;gap:6px;">
        <a href="${frontendUrl}/account/${accountId}" target="_blank" style="
          flex:1;text-align:center;text-decoration:none;
          background:#4f46e5;color:#fff;
          padding:8px;border-radius:8px;font-size:11px;font-weight:600;
        ">Open War Room ↗</a>
        <a href="${frontendUrl}/assistant?account_id=${accountId}&seed=true" target="_blank" style="
          flex:1;text-align:center;text-decoration:none;
          background:#f3f4f6;color:#374151;
          padding:8px;border-radius:8px;font-size:11px;font-weight:600;
        ">Ask Agent</a>
      </div>
    </div>
  `;
}

// ── Sidebar injection ─────────────────────────────────────────────────────────

function createSidebar(): HTMLDivElement {
  const sidebar = document.createElement("div");
  sidebar.id = SIDEBAR_ID;
  sidebar.style.cssText = `
    position: fixed;
    top: 0;
    right: 0;
    width: ${SIDEBAR_WIDTH}px;
    height: 100vh;
    background: #fff;
    border-left: 1px solid #e5e7eb;
    z-index: 999999;
    box-shadow: -4px 0 24px rgba(0,0,0,0.08);
    transition: transform 0.25s ease;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  `;
  return sidebar;
}

function getOrCreateSidebar(): HTMLDivElement {
  let sidebar = document.getElementById(SIDEBAR_ID) as HTMLDivElement | null;
  if (!sidebar) {
    sidebar = createSidebar();
    document.body.appendChild(sidebar);
  }
  return sidebar;
}

function showSidebar(html: string) {
  const sidebar = getOrCreateSidebar();
  sidebar.innerHTML = html;
  sidebar.style.transform = "translateX(0)";

  document.getElementById("vantage-close-btn")?.addEventListener("click", () => {
    sidebar!.style.transform = `translateX(${SIDEBAR_WIDTH}px)`;
  });
}

function showLoadingState() {
  const sidebar = getOrCreateSidebar();
  sidebar.innerHTML = `
    <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:12px;font-family:-apple-system,sans-serif;">
      <div style="width:32px;height:32px;border:3px solid #e5e7eb;border-top-color:#4f46e5;border-radius:50%;animation:vantage-spin 0.8s linear infinite;"></div>
      <p style="font-size:13px;color:#6b7280;">Loading Vantage…</p>
      <style>@keyframes vantage-spin{to{transform:rotate(360deg)}}</style>
    </div>
  `;
  sidebar.style.transform = "translateX(0)";
}

function showNotFound(label: string) {
  const sidebar = getOrCreateSidebar();
  sidebar.innerHTML = `
    <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:8px;font-family:-apple-system,sans-serif;padding:20px;text-align:center;">
      <div style="font-size:32px;">🔍</div>
      <p style="font-size:13px;font-weight:600;color:#374151;">No match found</p>
      <p style="font-size:12px;color:#9ca3af;">Vantage couldn't find an account matching "${label}"</p>
      <button id="vantage-close-btn" style="margin-top:8px;padding:6px 16px;background:#4f46e5;color:#fff;border:none;border-radius:8px;font-size:12px;cursor:pointer;">Close</button>
    </div>
  `;
  sidebar.style.transform = "translateX(0)";
  document.getElementById("vantage-close-btn")?.addEventListener("click", () => {
    sidebar!.style.transform = `translateX(${SIDEBAR_WIDTH}px)`;
  });
}

// ── Deal detection ────────────────────────────────────────────────────────────

function extractDealIdFromUrl(url: string): string | null {
  const match = url.match(/\/deal\/(\d+)/);
  return match ? match[1] : null;
}

async function loadForDeal(dealId: string) {
  showLoadingState();

  const response = await chrome.runtime.sendMessage({
    type: "GET_ACCOUNT_BY_HUBSPOT",
    payload: { dealId },
  });

  if (!response?.account) {
    showNotFound(`Deal ${dealId}`);
    return;
  }

  showSidebar(buildSidebarHTML(response));
}

// ── Init ──────────────────────────────────────────────────────────────────────

function init() {
  // Check current URL
  const dealId = extractDealIdFromUrl(window.location.href);
  if (dealId) loadForDeal(dealId);

  // Watch for URL changes (HubSpot is a SPA)
  let lastUrl = window.location.href;
  const observer = new MutationObserver(() => {
    if (window.location.href !== lastUrl) {
      lastUrl = window.location.href;
      const newDealId = extractDealIdFromUrl(lastUrl);
      if (newDealId) loadForDeal(newDealId);
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });

  // Listen for messages from background
  chrome.runtime.onMessage.addListener((message) => {
    if (message.type === "DEAL_DETECTED") {
      loadForDeal(message.payload.dealId);
    }
  });
}

init();
