/**
 * auth.setup.ts
 * Runs once before all chromium tests.
 * Authenticates via WorkOS and saves session state to .auth/user.json.
 *
 * Usage: WORKOS_TEST_EMAIL + WORKOS_TEST_PASSWORD must be set in env.
 * In CI: set as GitHub Actions secrets. Locally: set in .env.test.
 *
 * If WorkOS does not support direct credential login (SSO-only workspace),
 * this setup uses a special bypass header (`X-Test-User-Email`) that the API
 * accepts only when ENVIRONMENT=test, injecting a pre-seeded test user session.
 */

import { test as setup, expect } from "@playwright/test";
import path from "path";

const AUTH_FILE = path.join(__dirname, ".auth/user.json");

setup("authenticate", async ({ page }) => {
  const testEmail =
    process.env.WORKOS_TEST_EMAIL ?? "test@vantage.ai";
  const useBypass = process.env.VANTAGE_TEST_BYPASS === "1";

  if (useBypass) {
    // ── Bypass mode (CI / local without SSO) ──────────────────────────────────
    // The API issues a test session cookie when it receives the bypass header.
    // ENVIRONMENT must be "test" on the API side — never enabled in production.
    const apiBase =
      process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

    const response = await page.request.post(
      `${apiBase}/v1/auth/test-session`,
      {
        headers: { "X-Test-User-Email": testEmail },
      }
    );

    // If test-session endpoint is not implemented yet, fall through to UI flow.
    if (response.ok()) {
      const { session_token } = await response.json();
      await page.context().addCookies([
        {
          name: "vantage_session",
          value: session_token,
          domain: "localhost",
          path: "/",
          httpOnly: true,
          secure: false,
        },
      ]);
      await page.context().storageState({ path: AUTH_FILE });
      return;
    }
  }

  // ── UI auth flow (WorkOS hosted page) ─────────────────────────────────────
  await page.goto("/auth/login");

  // Expect WorkOS-hosted sign-in form or a "Continue with Google" button
  // Vantage shows a sign-in page that redirects to WorkOS
  const signInBtn = page.getByRole("button", { name: /sign in|continue|google/i });
  await expect(signInBtn.first()).toBeVisible({ timeout: 10_000 });
  await signInBtn.first().click();

  // WorkOS might render its own page — handle email + password form if present
  const emailInput = page.getByLabel(/email/i);
  if (await emailInput.isVisible({ timeout: 5_000 }).catch(() => false)) {
    await emailInput.fill(testEmail);
    const passwordInput = page.getByLabel(/password/i);
    if (await passwordInput.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await passwordInput.fill(process.env.WORKOS_TEST_PASSWORD ?? "");
    }
    await page.getByRole("button", { name: /continue|sign in|log in/i }).click();
  }

  // Wait for redirect back to app after auth
  await page.waitForURL(/\/(inbox|\/app)/, { timeout: 30_000 });

  // Verify we are authenticated — sidebar should be visible
  await expect(page.getByRole("navigation")).toBeVisible({ timeout: 10_000 });

  await page.context().storageState({ path: AUTH_FILE });
});
