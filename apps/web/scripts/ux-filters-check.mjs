// Quick verification of the shared DealFilterBar on Today + Deal Book.
import { chromium } from "@playwright/test";

const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1300, height: 900 } })).newPage();

// Today: open filter popover
await page.goto("http://localhost:3000/inbox", { waitUntil: "domcontentloaded" });
await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
await page.waitForTimeout(2000);
await page.locator('button[title="Filters"]').click();
await page.waitForTimeout(500);
await page.screenshot({ path: "ux-audit-out/clickthrough/filters-today-popover.png" });

// apply Omit category filter
await page.getByRole("button", { name: "Omit", exact: true }).click();
await page.waitForTimeout(600);
await page.screenshot({ path: "ux-audit-out/clickthrough/filters-today-omit.png" });

// Deal Book: filter Poor health + sort by Amount
await page.goto("http://localhost:3000/deals", { waitUntil: "domcontentloaded" });
await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
await page.waitForTimeout(2000);
await page.locator('button[title="Filters"]').click();
await page.waitForTimeout(400);
await page.getByRole("button", { name: "Poor <40%" }).click();
await page.mouse.click(650, 500);
await page.waitForTimeout(400);
await page.getByRole("button", { name: "Amount" }).click();
await page.waitForTimeout(600);
await page.screenshot({ path: "ux-audit-out/clickthrough/filters-dealbook.png" });

await browser.close();
console.log("done");
