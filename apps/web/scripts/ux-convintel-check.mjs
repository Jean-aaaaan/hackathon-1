// Verify the Conversation Intelligence card + upgraded transcripts render.
import { chromium } from "@playwright/test";

const ACCT = "10314bde-bc0f-438a-875a-c6a80490f3fe";
const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1300, height: 950 } })).newPage();

await page.goto(`http://localhost:3000/account/${ACCT}`, { waitUntil: "domcontentloaded" });
await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
await page.waitForTimeout(2000);

// Intelligence tab → scroll to the conversation card
await page.getByRole("button", { name: "Intelligence" }).click();
await page.waitForTimeout(1500);
await page.getByText("Conversation Intelligence").scrollIntoViewIfNeeded();
await page.waitForTimeout(400);
await page.screenshot({ path: "ux-audit-out/clickthrough/convintel-card.png" });

// History tab → expand the first transcript
await page.getByRole("button", { name: "History" }).click();
await page.waitForTimeout(1500);
const card = page.getByText("proposal walkthrough").first();
await card.scrollIntoViewIfNeeded();
await card.click();
await page.waitForTimeout(500);
await page.screenshot({ path: "ux-audit-out/clickthrough/convintel-transcript.png" });

await browser.close();
console.log("done");
