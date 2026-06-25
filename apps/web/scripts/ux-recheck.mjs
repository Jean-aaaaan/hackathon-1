// Re-verify the three click-through fixes: palette name fallback,
// war-room chat single seed, timeline endpoint in History tab.
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const OUT = path.resolve("ux-audit-out/clickthrough");
const API = "http://localhost:8000";
const WEB = "http://localhost:3000";

const acctRes = await fetch(`${API}/v1/accounts?limit=1`, {
  headers: { Authorization: "Bearer dev-local" },
});
const acctId = (await acctRes.json()).data?.[0]?.id;

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1100, height: 850 } });
const page = await ctx.newPage();
const errors = [];
page.on("response", r => { if (r.status() >= 400 && !r.url().includes("hot-update")) errors.push(`${r.status()} ${r.url()}`); });

// 1. Palette fallback search
await page.goto(`${WEB}/inbox`, { waitUntil: "domcontentloaded" });
await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
await page.waitForTimeout(1500);
await page.keyboard.press("Control+k");
await page.waitForTimeout(400);
await page.keyboard.type("singapore");
await page.waitForTimeout(1500);
await page.screenshot({ path: path.join(OUT, "recheck-palette-fallback.png") });
await page.keyboard.press("Escape");
console.log("OK palette");

// 2. War room History tab (timeline endpoint) + chat single-seed
await page.goto(`${WEB}/account/${acctId}`, { waitUntil: "domcontentloaded" });
await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
await page.waitForTimeout(1500);
await page.getByRole("button", { name: "History" }).click();
await page.waitForTimeout(2500);
await page.screenshot({ path: path.join(OUT, "recheck-history-timeline.png") });
console.log("OK history");

await page.getByRole("button", { name: "Chat", exact: true }).first().click();
await page.waitForTimeout(4000);
await page.screenshot({ path: path.join(OUT, "recheck-chat-single-seed.png") });
console.log("OK chat");

fs.writeFileSync(path.join(OUT, "recheck-errors.json"), JSON.stringify(errors, null, 2));
console.log(`${errors.length} http errors`);
await browser.close();
