// UX audit driver — visits every page, screenshots, logs console + network errors.
// Usage: node scripts/ux-audit.mjs [routesCsv]
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const OUT = path.resolve("ux-audit-out");
fs.mkdirSync(OUT, { recursive: true });

const API = "http://localhost:8000";
const WEB = "http://localhost:3000";
const TOKEN = "dev-local";

// Grab a real account id for the war room page
const acctRes = await fetch(`${API}/v1/accounts?limit=1`, {
  headers: { Authorization: `Bearer ${TOKEN}` },
});
const acctJson = await acctRes.json();
const acctId = acctJson.data?.[0]?.id;

const DEFAULT_ROUTES = [
  "/inbox",
  "/deals",
  "/watchtower",
  "/forecast",
  "/assistant",
  "/analytics",
  "/settings",
  ...(acctId ? [`/account/${acctId}`] : []),
];
const routes = process.argv[2] ? process.argv[2].split(",") : DEFAULT_ROUTES;

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
const page = await ctx.newPage();

const report = [];
page.on("console", (msg) => {
  if (msg.type() === "error") report.push({ route: current, kind: "console", text: msg.text().slice(0, 500) });
});
page.on("requestfailed", (req) => {
  report.push({ route: current, kind: "requestfailed", text: `${req.method()} ${req.url()} — ${req.failure()?.errorText}` });
});
page.on("response", (res) => {
  if (res.status() >= 400) report.push({ route: current, kind: `http${res.status()}`, text: `${res.request().method()} ${res.url()}` });
});

let current = "";
for (const route of routes) {
  current = route;
  const slug = route.replace(/[\/\[\]]/g, "_").replace(/^_/, "") || "root";
  try {
    await page.goto(WEB + route, { waitUntil: "domcontentloaded", timeout

: 60000 });
    // Let data fetches settle
    await page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => {});
    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(OUT, `${slug}.png`), fullPage: false });
    await page.screenshot({ path: path.join(OUT, `${slug}_full.png`), fullPage: true });
    console.log(`OK ${route}`);
  } catch (e) {
    console.log(`FAIL ${route}: ${e.message.split("\n")[0]}`);
    await page.screenshot({ path: path.join(OUT, `${slug}_error.png`) }).catch(() => {});
  }
}

fs.writeFileSync(path.join(OUT, "errors.json"), JSON.stringify(report, null, 2));
console.log(`\n${report.length} errors logged → ux-audit-out/errors.json`);
await browser.close();
