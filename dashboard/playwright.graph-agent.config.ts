import os from "node:os";
import path from "node:path";
import { defineConfig } from "playwright/test";

const baseURL = process.env.E2E_DASHBOARD_URL || "http://127.0.0.1:3000";

export default defineConfig({
  testDir: "./e2e/graph-agent",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 30_000 },
  reporter: [["list"]],
  outputDir:
    process.env.E2E_OUTPUT_DIR
    || path.join(os.tmpdir(), "brain-graph-agent-e2e-results"),
  use: {
    baseURL,
    actionTimeout: 20_000,
    navigationTimeout: 120_000,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "off",
  },
});
