// Interactive UX sweep — clicks through key flows, screenshots each state.
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const OUT = path.resolve("ux-audit-out/interact");
fs.mkdirSync(OUT, { recursive: true });

const WEB = "http://localhost:3000";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await ctx.newPage();

const errors = [];
let step = "init";
page.on("console", (m) => { if (m.type() === "error") errors.push({ step, text: m.text().slice(0, 400) }); });
page.on("response", (r) => { if (r.status() >= 400) errors.push({ step, text: `HTTP ${r.status()} ${r.request().method()} ${r.url()}` }); });

async function shot(name) {
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
  console.log(`shot: ${name}`);
}

// ── 1. Inbox: select first deal ──
step = "inbox-select-deal";
await page.goto(`${WEB}/inbox`, { waitUntil: "domcontentloaded" });
await page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => {});
const firstCard = page.locator('[class*="cursor-pointer"]').filter({ hasText: "Proposal" }).first();
if (await firstCard.count()) {
  await firstCard.click();
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  await shot("01-inbox-deal-selected");
  // scroll the detail pane
  await page.mouse.wheel(0, 600);
  await shot("02-inbox-deal-scrolled");
} else {
  console.log("no deal card found on inbox");
  await shot("01-inbox-no-card");
}

// ── 2. Drafts tab in inbox ──
step = "inbox-drafts-tab";
const draftsTab = page.getByText(/Drafts · \d+/).first();
if (await draftsTab.count()) {
  await draftsTab.click();
  await page.waitForTimeout(1200);
  await shot("03-inbox-drafts-tab");
}

// ── 3. Deal Book: select first deal ──
step = "dealbook-select";
await page.goto(`${WEB}/deals`, { waitUntil: "domcontentloaded" });
await page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => {});
const dbCard = page.locator("text=Proposal").first();
if (await dbCard.count()) {
  await dbCard.click();
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  await shot("04-dealbook-selected");
  await page.mouse.wheel(0, 800);
  await shot("05-dealbook-scrolled");
}

// ── 4. Watchtower: switch tabs ──
step = "watchtower-tabs";
await page.goto(`${WEB}/watchtower`, { waitUntil: "domcontentloaded" });
await page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => {});
for (const tab of ["Board", "Forecast", "This Week"]) {
  const t = page.getByText(tab, { exact: true }).first();
  if (await t.count()) {
    await t.click();
    await page.waitForTimeout(1500);
    await shot(`06-watchtower-${tab.toLowerCase().replace(" ", "")}`);
  }
}

// ── 5. Account War Room: tabs + verify stream-token ──
step = "warroom";
const streamTokenStatus = [];
page.on("response", (r) => { if (r.url().includes("stream-token")) streamTokenStatus.push(r.status()); });
await page.goto(`${WEB}/inbox`, { waitUntil: "domcontentloaded" });
await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
// find a war room link via first card click then a link, fallback: direct nav
const acctRes = await fetch("http://localhost:8000/v1/accounts?limit=1", { headers: { Authorization: "Bearer dev-local" } });
const acctId = (await acctRes.json()).data?.[0]?.id;
await page.goto(`${WEB}/account/${acctId}`, { waitUntil: "domcontentloaded" });
await page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => {});
await shot("07-warroom-act");
for (const tab of ["Intelligence", "History"]) {
  const t = page.getByText(tab, { exact: true }).first();
  if (await t.count()) {
    await t.click();
    await page.waitForTimeout(2000);
    await shot(`08-warroom-${tab.toLowerCase()}`);
  }
}
console.log("stream-token statuses:", JSON.stringify(streamTokenStatus));

// ── 6. Chat drawer on war room ──
step = "warroom-chat";
const chatBtn = page.getByRole("button", { name: /chat/i }).first();
if (await chatBtn.count()) {
  await chatBtn.click();
  await page.waitForTimeout(1500);
  await shot("09-warroom-chat-open");
}

// ── 7. Assistant: send a message ──
step = "assistant-send";
await page.goto(`${WEB}/assistant`, { waitUntil: "domcontentloaded" });
await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
const input = page.locator('input[placeholder*="Ask"], textarea[placeholder*="Ask"]').first();
if (await input.count()) {
  await input.fill("Which deals are most at risk this quarter?");
  await input.press("Enter");
  await page.waitForTimeout(3000);
  await shot("10-assistant-sent");
  // wait up to 45s for a streamed response to accumulate
  await page.waitForTimeout(25000);
  await shot("11-assistant-response");
}

fs.writeFileSync(path.join(OUT, "errors.json"), JSON.stringify(errors, null, 2));
console.log(`${errors.length} errors → interact/errors.json`);
await browser.close();
