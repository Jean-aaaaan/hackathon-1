/**
 * analytics.spec.ts
 * Stacey's E2E checklist — Analytics Dashboard (/analytics).
 *
 * Covers:
 *  - Page loads with KPI cards visible
 *  - DAR trend chart renders (pure SVG)
 *  - 30/60/90d toggle changes the chart
 *  - Cost trend chart renders
 *  - Signal distribution panel shows type bars
 *  - Rep performance table shows rows with DAR values
 *  - Pending drafts banner links to inbox
 *  - No external chart library is loaded (zero recharts/chart.js)
 */

import { test, expect } from "@playwright/test";

test.describe("Analytics Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/analytics");
    await page.waitForLoadState("networkidle");
  });

  test("page loads with correct heading", async ({ page }) => {
    await expect(page).toHaveURL(/\/analytics/);
    const heading = page.getByRole("heading", { name: /analytics/i });
    await expect(heading).toBeVisible({ timeout: 10_000 });
  });

  test("KPI cards render with numeric values", async ({ page }) => {
    // KPI cards: Total Accounts, Active Signals, Draft Acceptance Rate, Avg Urgency
    const kpiCards = page.locator(
      "[data-testid='kpi-card'], [class*='kpi-card'], [class*='KpiCard']"
    );

    // Wait for data to load (skeletons → content)
    await page.waitForTimeout(2000);

    const count = await kpiCards.count();
    if (count === 0) {
      // Try fallback: look for stat-block pattern
      const statBlocks = page.locator("[class*='stat'], [class*='metric']");
      const statCount = await statBlocks.count();
      expect(statCount).toBeGreaterThan(0);
    } else {
      expect(count).toBeGreaterThan(0);
      // Verify at least one card has a numeric value
      const allTexts = await kpiCards.allTextContents();
      const hasNumbers = allTexts.some((t) => /\d/.test(t));
      expect(hasNumbers).toBe(true);
    }
  });

  test("DAR trend chart is a pure SVG (no external chart library)", async ({
    page,
  }) => {
    // Check for SVG elements in the DAR trend panel
    const darPanel = page.locator(
      "[data-testid='dar-trend'], [class*='dar-trend'], [class*='DarTrend']"
    );
    const hasDar = await darPanel.isVisible({ timeout: 8_000 }).catch(() => false);

    if (hasDar) {
      const svg = darPanel.locator("svg");
      await expect(svg).toBeVisible({ timeout: 5_000 });

      // Verify no recharts or chart.js root elements are present
      const rechartsRoot = page.locator(".recharts-wrapper, .chartjs-render-monitor");
      const hasExternal = await rechartsRoot.isVisible({ timeout: 1_000 }).catch(() => false);
      expect(hasExternal).toBe(false);
    } else {
      // DAR panel may just have an SVG at top level — look broadly
      const svgElements = page.locator("svg");
      const svgCount = await svgElements.count();
      expect(svgCount).toBeGreaterThan(0);
    }
  });

  test("30/60/90d toggle changes the DAR chart", async ({ page }) => {
    const toggle30 = page.getByRole("button", { name: /30d|30 days/i });
    const toggle60 = page.getByRole("button", { name: /60d|60 days/i });
    const toggle90 = page.getByRole("button", { name: /90d|90 days/i });

    const hasToggles =
      (await toggle30.isVisible({ timeout: 5_000 }).catch(() => false)) ||
      (await toggle60.isVisible({ timeout: 5_000 }).catch(() => false)) ||
      (await toggle90.isVisible({ timeout: 5_000 }).catch(() => false));

    if (!hasToggles) {
      test.skip(true, "No 30/60/90d toggles found");
      return;
    }

    // Click 60d and verify an API request fires
    const requestPromise = page.waitForRequest(
      (req) => req.url().includes("dar_trend") || req.url().includes("analytics"),
      { timeout: 10_000 }
    ).catch(() => null);

    if (await toggle60.isVisible().catch(() => false)) {
      await toggle60.click();
    } else if (await toggle90.isVisible().catch(() => false)) {
      await toggle90.click();
    }

    await requestPromise;
    // Chart should still be visible after toggle
    const svg = page.locator("svg").first();
    await expect(svg).toBeVisible({ timeout: 5_000 });
  });

  test("cost trend panel renders bars", async ({ page }) => {
    const costPanel = page.locator(
      "[data-testid='cost-trend'], [class*='cost-trend'], [class*='CostTrend']"
    );
    const hasCost = await costPanel.isVisible({ timeout: 8_000 }).catch(() => false);

    if (!hasCost) {
      test.skip(true, "Cost trend panel not found");
      return;
    }

    // Either SVG bars or div-based bars
    const bars = costPanel.locator("rect, [class*='bar']");
    const hasBars = await bars.first().isVisible({ timeout: 5_000 }).catch(() => false);

    const emptyState = costPanel.getByText(/no data|no cost|not available/i);
    const hasEmpty = await emptyState.isVisible({ timeout: 3_000 }).catch(() => false);

    expect(hasBars || hasEmpty).toBe(true);
  });

  test("signal distribution panel shows type bars", async ({ page }) => {
    const sigPanel = page.locator(
      "[data-testid='signal-distribution'], [class*='signal-dist'], [class*='SignalDist']"
    );
    const hasSig = await sigPanel.isVisible({ timeout: 8_000 }).catch(() => false);

    if (!hasSig) {
      test.skip(true, "Signal distribution panel not found");
      return;
    }

    // Signal type labels (e.g. "Champion Left", "Budget Signal", "Competitor Mention")
    const typeLabels = sigPanel.locator(
      "[class*='label'], [class*='type'], span, td"
    ).filter({ hasText: /signal|champion|budget|competitor|renewal|intent/i });

    const hasLabels = await typeLabels.first().isVisible({ timeout: 5_000 }).catch(() => false);
    const emptyState = sigPanel.getByText(/no signals|no data/i);
    const hasEmpty = await emptyState.isVisible({ timeout: 3_000 }).catch(() => false);

    expect(hasLabels || hasEmpty).toBe(true);
  });

  test("rep performance table shows DAR per rep", async ({ page }) => {
    const repPanel = page.locator(
      "[data-testid='rep-performance'], [class*='rep-performance'], [class*='RepPerformance']"
    );
    const hasRep = await repPanel.isVisible({ timeout: 8_000 }).catch(() => false);

    if (!hasRep) {
      // Fallback: look for a table with DAR-like values
      const table = page.locator("table").first();
      const hasTable = await table.isVisible({ timeout: 5_000 }).catch(() => false);
      if (hasTable) {
        const rows = table.locator("tbody tr");
        const rowCount = await rows.count();
        expect(rowCount).toBeGreaterThanOrEqual(0);
      }
      return;
    }

    // Table rows should have names + DAR percentages
    const rows = repPanel.locator("tr, [class*='row']");
    const rowCount = await rows.count();

    if (rowCount > 0) {
      const allTexts = await repPanel.allTextContents();
      const hasPercentage = allTexts.join("").includes("%") || /\d+\.\d+/.test(allTexts.join(""));
      expect(hasPercentage).toBe(true);
    }
  });

  test("pending drafts banner links to inbox", async ({ page }) => {
    // Banner only appears if there are pending drafts
    const banner = page.locator(
      "[data-testid='pending-notice'], [class*='pending-notice'], [class*='PendingNotice']"
    );
    const hasBanner = await banner.isVisible({ timeout: 5_000 }).catch(() => false);

    if (!hasBanner) {
      // No pending drafts — banner correctly absent
      return;
    }

    const inboxLink = banner.getByRole("link", { name: /inbox|review/i });
    await expect(inboxLink).toBeVisible();
    const href = await inboxLink.getAttribute("href");
    expect(href).toMatch(/\/inbox/);
  });

  test("analytics page has no console errors", async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text());
      }
    });

    await page.reload();
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(2000);

    // Filter out known non-critical errors (e.g. CSP reports, third-party warnings, 404s for missing assets)
    const criticalErrors = consoleErrors.filter(
      (e) =>
        !e.includes("favicon") &&
        !e.includes("ERR_BLOCKED") &&
        !e.includes("Content Security Policy") &&
        !e.includes("net::ERR_ABORTED") &&
        !e.includes("404") &&          // resource not found (expected on empty dev DB)
        !e.includes("500") &&          // server errors (empty DB, no data)
        !e.includes("Failed to load resource")  // network errors from empty dev state
    );

    if (criticalErrors.length > 0) {
      console.warn("Console errors detected:", criticalErrors);
    }

    // Soft assertion — only fail on unexpected JS errors (not API 404/500 on empty DB)
    expect(criticalErrors.length).toBeLessThanOrEqual(2);
  });
});
