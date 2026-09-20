import os from "node:os";
import path from "node:path";
import { defineConfig } from "playwright/test";

// Unlike playwright.wa-validator.config.ts (which drives a live environment),
// this suite intercepts every /api-brain call in the browser. It proves the
// operational queue's real DOM/interaction behaviour -- column layout, per
// message capabilities, blocked reasons, idempotency keys on the wire --
// without any backend, local stack or WhatsApp traffic, which is what
// AGENTS.md requires for dashboard-only work.
const baseURL = process.env.E2E_DASHBOARD_URL || "http://127.0.0.1:3100";

export default defineConfig({
  testDir: "./e2e/messaging-queue",
  testMatch: "**/*.spec.ts",
  fullyParallel: true,
  workers: 2,
  retries: 0,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  outputDir: process.env.E2E_OUTPUT_DIR || path.join(os.tmpdir(), "brain-messaging-queue-e2e-results"),
  use: {
    baseURL,
    actionTimeout: 10_000,
    navigationTimeout: 60_000,
    screenshot: "off",
    trace: "off",
    video: "off",
  },
  webServer: process.env.E2E_DASHBOARD_URL ? undefined : {
    command: "npm run dev -- --port 3100",
    url: "http://127.0.0.1:3100/login",
    reuseExistingServer: true,
    timeout: 180_000,
  },
});
