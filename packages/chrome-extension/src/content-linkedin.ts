/**
 * LinkedIn content script — shows Vantage account match when browsing profiles/companies.
 *
 * Detects:
 *   - linkedin.com/in/{person}     → extracts company from profile DOM
 *   - linkedin.com/company/{slug}  → uses company name directly
 *
 * Injects a subtle floating badge at bottom-right. Clicking expands to full sidebar.
 */

const BADGE_ID = "vantage-linkedin-badge";
const SIDEBAR_ID = "vantage-linkedin-sidebar";
const SIDEBAR_WIDTH = 320;

function esc(s: unknown): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;");
}

// ── Name extraction ───────────────────────────────────────────────────────────

function extractCompanyFromProfile(): string | null {
  // Current company appears in headline or experience section
  const headline = document.querySelector(".pv-text-details__left-panel .text-body-medium");
  if (headline) {
    const text = headline.textContent?.trim() ?? "";
    // "Software Engineer at Acme Corp" → "Acme Corp"
    const atMatch = text.match(/at (.+)$/i);
    if (atMatch) return atMatch[1].trim();
  }

  // Fallback: first experience entry
  const expCompany = document.querySelector(
    ".experience-section .pv-entity__secondary-title, .pvs-entity__secondary-title"
  );
  if (expCompany) return expCompany.textContent?.trim() ?? null;

  return null;
}

function extractCompanyFromCompanyPage(): string | null {
  // Company name from h1 on company page
  const h1 = document.querySelector("h1.org-top-card-summary__title, h1.t-24");
  return h1?.textContent?.trim() ?? null;
}

function getSearchName(): string | null {
  const url = window.location.href;

  if (url.includes("/in/")) {
    // Personal profile — extract current company
    return extractCompanyFromProfile();
  }

  if (url.includes("/company/")) {
    return extractCompanyFromCompanyPage();
  }

  return null;
}

// ── Badge ─────────────────────────────────────────────────────────────────────

function showBadge(accountName: string, urgencyPct: number, accountId: string) {
  removeBadge();

  const badge = document.createElement("div");
  badge.id = BADGE_ID;

  const urgencyColor =
    urgencyPct >= 85 ? "#ef4444" :
    urgencyPct >= 70 ? "#f97316" :
    urgencyPct >= 50 ? "#eab308" : "#22c55e";

  badge.style.cssText = `
    position: fixed;
    bottom: 24px;
    right: 24px;
    z-index: 999999;
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    box-shadow: 0 4px 24px rgba(0,0,0,0.12);
    padding: 10px 14px;
    display: flex;
    align-items: center;
    gap: 10px;
    cursor: pointer;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    transition: box-shadow 0.15s;
    max-width: 260px;
  `;

  badge.innerHTML = `
    <div style="
      width: 32px; height: 32px; border-radius: 8px;
      background: #4f46e5; display: flex; align-items: center;
      justify-content: center; flex-shrink: 0;
    ">
      <span style="color: #fff; font-size: 14px;">⚡</span>
    </div>
    <div style="min-width: 0;">
      <div style="font-size: 11px; font-weight: 700; color: #111827; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
        ${esc(accountName)}
      </div>
      <div style="font-size: 10px; color: ${urgencyColor}; font-weight: 600;">
        Urgency ${urgencyPct}% · In Vantage
      </div>
    </div>
    <button id="vantage-badge-close" style="
      background: none; border: none; color: #9ca3af;
      cursor: pointer; font-size: 16px; padding: 0; margin-left: 4px; flex-shrink: 0;
    ">×</button>
  `;

  badge.addEventListener("click", (e) => {
    if ((e.target as HTMLElement).id === "vantage-badge-close") {
      removeBadge();
      return;
    }
    showLinkedInSidebar(accountId, accountName);
  });

  document.body.appendChild(badge);
}

function removeBadge() {
  document.getElementById(BADGE_ID)?.remove();
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

async function showLinkedInSidebar(accountId: string, accountName: string) {
  removeBadge();

  // Reuse HubSpot sidebar pattern — fetch fresh data
  const response = await chrome.runtime.sendMessage({
    type: "GET_ACCOUNT_BY_NAME",
    payload: { name: accountName },
  });

  if (!response?.account) return;

  let sidebar = document.getElementById(SIDEBAR_ID) as HTMLDivElement | null;
  if (!sidebar) {
    sidebar = document.createElement("div");
    sidebar.id = SIDEBAR_ID;
    sidebar.style.cssText = `
      position: fixed; top: 0; right: 0;
      width: ${SIDEBAR_WIDTH}px; height: 100vh;
      background: #fff; border-left: 1px solid #e5e7eb;
      z-index: 999999; box-shadow: -4px 0 24px rgba(0,0,0,0.08);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      display: flex; flex-direction: column; overflow: hidden;
    `;
    document.body.appendChild(sidebar);
  }

  const { account, state, actions } = response;
  const urgencyScore = (account.urgency_score as number) ?? 0;
  const urgencyPct = Math.round(urgencyScore * 100);
  const healthPct = Math.round(((account.health_score as number) ?? 0) * 100);
  const forecastCat = (account.pov_forecast_cat as string) ?? "—";
  const signals = (state?.signals as Array<{ type: string; detail: string }>) ?? [];
  const topAction = actions?.next_actions?.[0];
  const frontendUrl = "https://vantage.invigilo.ai";

  const urgencyColor =
    urgencyScore >= 0.85 ? "#ef4444" :
    urgencyScore >= 0.7  ? "#f97316" :
    urgencyScore >= 0.5  ? "#eab308" : "#22c55e";

  sidebar.innerHTML = `
    <div style="background:#4f46e5;padding:12px 14px;flex-shrink:0;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <span style="color:rgba(255,255,255,0.7);font-size:10px;font-weight:600;">⚡ VANTAGE</span>
        <button id="vantage-li-close" style="background:none;border:none;color:rgba(255,255,255,0.6);cursor:pointer;font-size:18px;">×</button>
      </div>
      <div style="color:#fff;font-size:14px;font-weight:700;">${esc(account.name)}</div>
      <div style="color:rgba(255,255,255,0.6);font-size:11px;">${esc(account.stage ?? "—")}</div>
    </div>
    <div style="flex:1;overflow-y:auto;padding:14px;">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px;">
        <div style="background:#f9fafb;border-radius:8px;padding:8px;">
          <div style="font-size:9px;color:#6b7280;text-transform:uppercase;font-weight:600;margin-bottom:2px;">Urgency</div>
          <div style="font-size:20px;font-weight:700;color:${urgencyColor};">${urgencyPct}%</div>
        </div>
        <div style="background:#f9fafb;border-radius:8px;padding:8px;">
          <div style="font-size:9px;color:#6b7280;text-transform:uppercase;font-weight:600;margin-bottom:2px;">Health</div>
          <div style="font-size:20px;font-weight:700;color:#374151;">${healthPct}%</div>
        </div>
      </div>
      <div style="margin-bottom:12px;">
        <div style="font-size:9px;color:#6b7280;text-transform:uppercase;font-weight:600;margin-bottom:4px;">AI Forecast</div>
        <span style="font-size:11px;font-weight:600;padding:3px 8px;border-radius:20px;background:#e0e7ff;color:#3730a3;">${forecastCat}</span>
      </div>
      ${topAction ? `
      <div style="padding:10px;background:#eef2ff;border-radius:8px;border-left:3px solid #4f46e5;margin-bottom:12px;">
        <div style="font-size:9px;color:#4f46e5;text-transform:uppercase;font-weight:600;margin-bottom:3px;">Top Action</div>
        <div style="font-size:12px;color:#1e1b4b;font-weight:500;">${esc(topAction.action)}</div>
      </div>
      ` : ""}
      <div>
        <div style="font-size:9px;color:#6b7280;text-transform:uppercase;font-weight:600;margin-bottom:6px;">Signals</div>
        ${signals.slice(0, 3).map(s => `
          <div style="font-size:11px;padding:5px 0;border-bottom:1px solid #f3f4f6;color:#374151;">
            <span style="font-size:9px;font-weight:700;color:#6b7280;text-transform:uppercase;">${esc(s.type)}</span>
            <div style="margin-top:2px;">${esc(s.detail)}</div>
          </div>
        `).join("") || '<div style="font-size:11px;color:#9ca3af;">No active signals</div>'}
      </div>
    </div>
    <div style="padding:10px 14px;border-top:1px solid #f3f4f6;display:flex;gap:6px;">
      <a href="${frontendUrl}/account/${account.id}" target="_blank" style="flex:1;text-align:center;text-decoration:none;background:#4f46e5;color:#fff;padding:8px;border-radius:8px;font-size:11px;font-weight:600;">War Room ↗</a>
      <a href="${frontendUrl}/assistant?account_id=${account.id}&seed=true" target="_blank" style="flex:1;text-align:center;text-decoration:none;background:#f3f4f6;color:#374151;padding:8px;border-radius:8px;font-size:11px;font-weight:600;">Ask Agent</a>
    </div>
  `;

  document.getElementById("vantage-li-close")?.addEventListener("click", () => {
    sidebar!.remove();
  });
}

// ── Init ──────────────────────────────────────────────────────────────────────

async function checkPage() {
  // Wait a bit for LinkedIn DOM to settle
  await new Promise(r => setTimeout(r, 1500));

  const name = getSearchName();
  if (!name) return;

  const response = await chrome.runtime.sendMessage({
    type: "GET_ACCOUNT_BY_NAME",
    payload: { name },
  });

  if (response?.account) {
    const urgencyPct = Math.round(((response.account.urgency_score as number) ?? 0) * 100);
    showBadge(response.account.name as string, urgencyPct, response.account.id as string);
  }
}

// Watch for SPA navigation
let lastUrl = window.location.href;
const navObserver = new MutationObserver(async () => {
  if (window.location.href !== lastUrl) {
    lastUrl = window.location.href;
    removeBadge();
    document.getElementById(SIDEBAR_ID)?.remove();
    await checkPage();
  }
});
navObserver.observe(document.body, { childList: true, subtree: true });

checkPage();
