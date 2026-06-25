// Post-revamp verification — narrower viewport for legible screenshots,
// plus tab interactions the plain audit can't reach.
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const OUT = path.resolve("ux-audit-out/verify");
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

async function snap(name) {
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(1200);
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: false });
  console.log(`OK ${name}`);
}

// 1. Inbox — queue + auto-select
await page.goto(`${WEB}/inbox`, { waitUntil: "domcontentloaded" });
await snap("01-inbox-queue");

// 2. Inbox — expand rest of pipeline
const restBtn = page.getByText(/Show rest of pipeline/);
if (await restBtn.count()) {
  await restBtn.click();
  await page.waitForTimeout(600);
  await snap("02-inbox-rest-expanded");
}

// 3. Forecast — rep chips + week movement
await page.goto(`${WEB}/forecast`, { waitUntil: "domcontentloaded" });
await snap("03-forecast");

// 4. Watchtower — clusters
await page.goto(`${WEB}/watchtower`, { waitUntil: "domcontentloaded" });
await snap("04-watchtower-clusters");

// 5. Watchtower — This Week tab (pipeline review)
const weekTab = page.getByRole("button", { name: "This Week", exact: true });
if (await weekTab.count()) {
  await weekTab.click();
  await page.waitForTimeout(2500);
  await snap("05-watchtower-thisweek");
  await page.mouse.wheel(0, 1200);
  await page.waitForTimeout(500);
  await snap("06-watchtower-review-scrolled");
}

// 6. Deals — forecast badge fallback
await page.goto(`${WEB}/deals`, { waitUntil: "domcontentloaded" });
await snap("07-deals");

// 7. War room
if (acctId) {
  await page.goto(`${WEB}/account/${acctId}`, { waitUntil: "domcontentloaded" });
  await snap("08-warroom");
}

await browser.close();
console.log("done");
