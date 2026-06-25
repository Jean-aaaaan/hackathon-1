// Full click-through — every page, every tab, every expandable, every modal.
// Mutating/costly actions (Approve, Decline confirm, Run Agent, Sync, Save) are
// opened but cancelled, never committed.
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const OUT = path.resolve("ux-audit-out/clickthrough");
fs.mkdirSync(OUT, { recursive: true });

const API = "http://localhost:8000";
const WEB = "http://localhost:3000";
const TOKEN = "dev-local";

const acctRes = await fetch(`${API}/v1/accounts?limit=1`, {
  headers: { Authorization: `Bearer ${TOKEN}` },
});
const acctId = (await acctRes.json()).data?.[0]?.id;

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1100, height: 850 } });
const page = await ctx.newPage();

const errors = [];
let current = "";
page.on("console", m => { if (m.type() === "error") errors.push({ at: current, kind: "console", text: m.text().slice(0, 300) }); });
page.on("response", r => { if (r.status() >= 400 && !r.url().includes("hot-update")) errors.push({ at: current, kind: `http${r.status()}`, text: `${r.request().method()} ${r.url()}` }); });
page.on("pageerror", e => errors.push({ at: current, kind: "pageerror", text: String(e).slice(0, 300) }));

let n = 0;
async function snap(name) {
  n++;
  await page.waitForTimeout(900);
  await page.screenshot({ path: path.join(OUT, `${String(n).padStart(2, "0")}-${name}.png`) });
  console.log(`OK ${n} ${name}`);
}
async function tryStep(label, fn) {
  current = label;
  try { await fn(); } catch (e) { errors.push({ at: label, kind: "step-failed", text: e.message.split("\n")[0] }); console.log(`SKIP ${label}: ${e.message.split("\n")[0]}`); }
}
const settle = async (ms = 1500) => {
  await page.waitForLoadState("networkidle", { timeout: 12000 }).catch(() => {});
  await page.waitForTimeout(ms);
};

// ════ 1. INBOX ════════════════════════════════════════════════════════════════
await tryStep("inbox: load", async () => {
  await page.goto(`${WEB}/inbox`, { waitUntil: "domcontentloaded" });
  await settle();
  await snap("inbox-default");
});
await tryStep("inbox: drafts filter", async () => {
  await page.getByRole("button", { name: /^Drafts/ }).first().click();
  await snap("inbox-filter-drafts");
});
await tryStep("inbox: urgent filter", async () => {
  await page.getByRole("button", { name: /^Urgent/ }).first().click();
  await snap("inbox-filter-urgent");
});
await tryStep("inbox: back to all + search", async () => {
  await page.getByRole("button", { name: /^All \(/ }).first().click();
  await page.getByPlaceholder("Search deals...").fill("sing");
  await page.waitForTimeout(600);
  await snap("inbox-search");
  await page.getByPlaceholder("Search deals...").fill("");
});
await tryStep("inbox: J/K keyboard nav", async () => {
  await page.keyboard.press("j");
  await page.keyboard.press("j");
  await snap("inbox-after-jj");
  await page.keyboard.press("k");
});
await tryStep("inbox: decline flow open + cancel", async () => {
  const decline = page.getByRole("button", { name: "Decline", exact: true }).first();
  if (await decline.count()) {
    await decline.click();
    await snap("inbox-decline-categories");
    await page.getByRole("button", { name: "Cancel" }).first().click();
  }
});
await tryStep("inbox: third deal click", async () => {
  const cards = page.locator("[data-deal-card]");
  if (await cards.count() >= 3) { await cards.nth(2).click(); await snap("inbox-third-deal"); }
});

// ════ 2. COMMAND PALETTE ══════════════════════════════════════════════════════
await tryStep("palette: open + browse", async () => {
  await page.keyboard.press("Control+k");
  await page.waitForTimeout(500);
  await snap("palette-open");
  await page.keyboard.type("sing");
  await page.waitForTimeout(1200);
  await snap("palette-search");
  await page.keyboard.press("Escape");
});

// ════ 3. VANTAGE SWEEP POPOVER (open only — never run) ════════════════════════
await tryStep("sweep popover: open + close", async () => {
  await page.getByRole("button", { name: /Vantage Sweep/ }).click();
  await page.waitForTimeout(400);
  await snap("sweep-popover");
  await page.keyboard.press("Escape");
  await page.mouse.click(400, 500); // close via outside click
});

// ════ 4. DEAL BOOK ════════════════════════════════════════════════════════════
await tryStep("dealbook: load + select deal", async () => {
  await page.goto(`${WEB}/deals`, { waitUntil: "domcontentloaded" });
  await settle();
  await page.locator("button", { hasText: "Nam Long" }).first().click();
  await settle(2000);
  await snap("dealbook-selected");
});
for (const sort of ["Amount", "Close", "Health", "Urgent"]) {
  await tryStep(`dealbook: sort ${sort}`, async () => {
    await page.getByRole("button", { name: sort }).first().click();
    await page.waitForTimeout(700);
    if (sort === "Health") await snap("dealbook-sort-health");
  });
}
await tryStep("dealbook: scroll detail panel", async () => {
  await page.mouse.move(700, 400);
  await page.mouse.wheel(0, 1500);
  await snap("dealbook-scrolled");
});

// ════ 5. WATCHTOWER — all 4 tabs + cluster expand ═════════════════════════════
await tryStep("watchtower: pipeline + cluster expand", async () => {
  await page.goto(`${WEB}/watchtower`, { waitUntil: "domcontentloaded" });
  await settle();
  await page.getByRole("button", { name: /MEDDPICC Gap/ }).first().click();
  await page.waitForTimeout(800);
  await snap("watchtower-cluster-expanded");
  await page.getByText("Clear filter ×").click().catch(() => {});
});
await tryStep("watchtower: signal urgency filters", async () => {
  const high = page.getByRole("button", { name: "high", exact: true });
  if (await high.count()) { await high.first().click(); await page.waitForTimeout(500); await snap("watchtower-filter-high"); }
});
await tryStep("watchtower: board tab", async () => {
  await page.getByRole("button", { name: "board", exact: true }).click();
  await settle(2000);
  await snap("watchtower-board");
});
await tryStep("watchtower: forecast tab", async () => {
  await page.getByRole("button", { name: "forecast", exact: true }).click();
  await settle(2000);
  await snap("watchtower-forecast-tab");
});
await tryStep("watchtower: this week tab", async () => {
  await page.getByRole("button", { name: "This Week", exact: true }).click();
  await settle(2500);
  await snap("watchtower-thisweek");
});

// ════ 6. FORECAST — expand everything, open modal, cancel ═════════════════════
await tryStep("forecast: expand all categories", async () => {
  await page.goto(`${WEB}/forecast`, { waitUntil: "domcontentloaded" });
  await settle();
  for (const cat of ["Pipeline", "Omit"]) {
    const header = page.locator("button", { hasText: cat }).filter({ hasText: "deals" }).first();
    if (await header.count()) await header.click();
    await page.waitForTimeout(400);
  }
  await snap("forecast-all-expanded");
});
await tryStep("forecast: override modal open + cancel", async () => {
  const btn = page.getByRole("button", { name: "Override" }).first();
  if (await btn.count()) {
    await btn.click();
    await page.waitForTimeout(400);
    await snap("forecast-override-modal");
    await page.getByRole("button", { name: "Cancel" }).click();
  }
});
await tryStep("forecast: AI vs CRM table expand", async () => {
  const tbl = page.getByText("AI vs CRM Disagreements");
  if (await tbl.count()) { await tbl.click(); await page.waitForTimeout(500); await snap("forecast-ai-vs-crm"); }
});

// ════ 7. ASSISTANT — suggestion chip (one cheap chat call) ════════════════════
await tryStep("assistant: load + suggestion chip", async () => {
  await page.goto(`${WEB}/assistant`, { waitUntil: "domcontentloaded" });
  await settle();
  await snap("assistant-empty");
  const chip = page.getByText("Which deals are most at risk this quarter?");
  if (await chip.count()) {
    await chip.click();
    await page.waitForTimeout(15000); // allow SSE response
    await snap("assistant-response");
  }
});

// ════ 8. ANALYTICS — range toggles + scroll ═══════════════════════════════════
await tryStep("analytics: load + toggles", async () => {
  await page.goto(`${WEB}/analytics`, { waitUntil: "domcontentloaded" });
  await settle(2500);
  await snap("analytics-top");
  for (const range of ["60d", "90d"]) {
    const b = page.getByRole("button", { name: range, exact: true }).first();
    if (await b.count()) { await b.click(); await page.waitForTimeout(800); }
  }
  await snap("analytics-90d");
  await page.mouse.wheel(0, 1800);
  await snap("analytics-scrolled");
});

// ════ 9. SETTINGS — open every form, cancel everything ════════════════════════
await tryStep("settings: load", async () => {
  await page.goto(`${WEB}/settings`, { waitUntil: "domcontentloaded" });
  await settle();
  await snap("settings-top");
});
await tryStep("settings: ICP edit open + cancel", async () => {
  const edit = page.getByText(/Edit ICP →|Configure ICP →/);
  if (await edit.count()) {
    await edit.scrollIntoViewIfNeeded();
    await edit.click();
    await page.waitForTimeout(500);
    await snap("settings-icp-edit");
    await page.getByRole("button", { name: "Cancel" }).first().click().catch(() => {});
  }
});
await tryStep("settings: new automation rule form + cancel", async () => {
  const newRule = page.getByRole("button", { name: "New Rule" });
  if (await newRule.count()) {
    await newRule.scrollIntoViewIfNeeded();
    await newRule.click();
    await page.waitForTimeout(500);
    await snap("settings-rule-form");
    // flip trigger type to health_drop to verify the signal_type input hides
    await page.locator("select").first().selectOption("health_drop");
    await page.waitForTimeout(300);
    await snap("settings-rule-healthdrop");
    await page.getByRole("button", { name: "Cancel" }).last().click().catch(() => {});
  }
});
await tryStep("settings: scroll bottom", async () => {
  await page.mouse.wheel(0, 4000);
  await snap("settings-bottom");
});

// ════ 10. WAR ROOM — all tabs, chat, generate menu, audit panel ═══════════════
if (acctId) {
  await tryStep("warroom: act tab", async () => {
    await page.goto(`${WEB}/account/${acctId}`, { waitUntil: "domcontentloaded" });
    await settle(2000);
    await snap("warroom-act");
  });
  await tryStep("warroom: expand a signal group", async () => {
    const sig = page.getByText(/MEDDPICC G/).first();
    if (await sig.count()) { await sig.click(); await page.waitForTimeout(500); await snap("warroom-signal-expanded"); }
  });
  await tryStep("warroom: intelligence tab", async () => {
    await page.getByRole("button", { name: "Intelligence" }).click();
    await settle(1500);
    await snap("warroom-intelligence");
    await page.mouse.wheel(0, 1500);
    await snap("warroom-intelligence-scrolled");
  });
  await tryStep("warroom: history tab", async () => {
    await page.getByRole("button", { name: "History" }).click();
    await settle(1500);
    await snap("warroom-history");
  });
  await tryStep("warroom: generate menu open + close", async () => {
    await page.getByRole("button", { name: /Generate/ }).first().click();
    await page.waitForTimeout(400);
    await snap("warroom-generate-menu");
    await page.keyboard.press("Escape");
    await page.mouse.click(300, 600);
  });
  await tryStep("warroom: chat open", async () => {
    await page.getByRole("button", { name: "Chat", exact: true }).first().click();
    await page.waitForTimeout(800);
    await snap("warroom-chat");
  });
}

fs.writeFileSync(path.join(OUT, "errors.json"), JSON.stringify(errors, null, 2));
console.log(`\n${errors.length} issues logged → ux-audit-out/clickthrough/errors.json`);
await browser.close();
