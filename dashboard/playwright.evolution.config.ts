import os from "node:os";
import path from "node:path";
import { defineConfig } from "playwright/test";

const baseURL = process.env.E2E_DASHBOARD_URL || "http://127.0.0.1:3000";

export default defineConfig({
  testDir: "./e2e/evolution",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 480_000,
  expect: {
    timeout: 20_000,
  },
  reporter: [["list"]],
  outputDir: process.env.E2E_OUTPUT_DIR || path.join(os.tmpdir(), "brain-evolution-e2e-results"),
  use: {
    baseURL,
    actionTimeout: 20_000,
    navigationTimeout: 120_000,
    screenshot: "off",
    trace: "off",
    video: "off",
  },
});
