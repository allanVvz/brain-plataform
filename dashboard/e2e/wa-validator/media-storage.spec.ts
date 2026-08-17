import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import { expect, test, type Page, type TestInfo } from "playwright/test";

test.describe.configure({ mode: "serial" });

const DASHBOARD_URL = required("E2E_DASHBOARD_URL");
const ADMIN_EMAIL = required("E2E_ADMIN_EMAIL");
const ADMIN_PASSWORD = required("E2E_ADMIN_PASSWORD");
const PERSONA_SLUG = required("E2E_WA_MEDIA_PERSONA");
const MEDIA_DIR = required("E2E_WA_MEDIA_DIR");
const FIXTURE_NAMES = ["ex 1.png", "ex 2.png", "teste 1.pdf"];
const API_TIMEOUT = 120_000;
const RUN_TIMEOUT = 240_000;

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Missing required E2E variable: ${name}`);
  return value;
}

function fixture(name: string) {
  const absolutePath = path.join(MEDIA_DIR, name);
  if (!fs.existsSync(absolutePath)) throw new Error(`Missing media fixture: ${absolutePath}`);
  const bytes = fs.readFileSync(absolutePath);
  return {
    name,
    absolutePath,
    bytes,
    sha256: crypto.createHash("sha256").update(bytes).digest("hex"),
    mimeType: name.endsWith(".pdf") ? "application/pdf" : "image/png",
  };
}

async function login(page: Page) {
  await page.goto("/login");
  if (!page.url().includes("/login")) return;
  await page.getByPlaceholder("operador@empresa.com").fill(ADMIN_EMAIL);
  await page.getByPlaceholder("Digite sua senha").fill(ADMIN_PASSWORD);
  await Promise.all([
    page.waitForResponse(
      (response) => new URL(response.url()).pathname === "/api-brain/auth/login",
      { timeout: API_TIMEOUT },
    ),
    page.getByRole("button", { name: "Entrar" }).click(),
  ]);
  await expect.poll(async () =>
    (await page.context().cookies()).some((cookie) => cookie.name === "ai_brain_session")
  ).toBe(true);
}

async function selectPersona(page: Page) {
  const selector = page.locator("header select").first();
  await expect(selector).toBeVisible({ timeout: API_TIMEOUT });
  await expect.poll(async () => selector.locator(`option[value="${PERSONA_SLUG}"]`).count()).toBe(1);
  await selector.selectOption(PERSONA_SLUG);
  await expect(selector).toHaveValue(PERSONA_SLUG);
}

async function openValidationWorkspace(page: Page) {
  await page.goto(`/settings?tab=messaging&sub=validacoes&persona=${encodeURIComponent(PERSONA_SLUG)}`);
  await selectPersona(page);
  const flowSelect = page.locator("select").filter({
    has: page.locator('option[value="saudacao_despedida"]'),
  }).first();
  await expect(flowSelect).toBeEnabled({ timeout: API_TIMEOUT });
  await expect.poll(async () => flowSelect.inputValue()).not.toBe("");
  await expect(page.getByRole("button", { name: "Gerar Script de Teste" })).toBeEnabled({
    timeout: API_TIMEOUT,
  });
}

test("armazena e reabre PNG/PDF no WA Validator sem outbound real", async ({ browser }, testInfo: TestInfo) => {
  const fixtures = FIXTURE_NAMES.map(fixture);
  const context = await browser.newContext({ baseURL: DASHBOARD_URL });
  const page = await context.newPage();
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await login(page);
  await openValidationWorkspace(page);
  await page.screenshot({ path: testInfo.outputPath("media-before.png"), fullPage: true });

  const generatedResponsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api-brain/wa-validator/generate-script"
      && response.request().method() === "POST",
    { timeout: API_TIMEOUT },
  );
  await page.getByRole("button", { name: "Gerar Script de Teste" }).click();
  const generatedResponse = await generatedResponsePromise;
  expect(generatedResponse.ok()).toBe(true);
  const generated = await generatedResponse.json();
  const sessionId = String(generated.session_id);
  expect(sessionId).not.toBe("");

  await expect(page.getByRole("button", { name: /Executar Direto/ })).toBeEnabled({ timeout: API_TIMEOUT });
  const runDirectResponsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api-brain/wa-validator/run-direct"
      && response.request().method() === "POST",
    { timeout: API_TIMEOUT },
  );
  await page.getByRole("button", { name: /Executar Direto/ }).click();
  const runDirectResponse = await runDirectResponsePromise;
  expect(runDirectResponse.ok(), await runDirectResponse.text()).toBe(true);
  await expect.poll(async () => {
    const response = await page.request.get(`/api-brain/wa-validator/sessions/${sessionId}`);
    if (!response.ok()) return `http-${response.status()}`;
    return String((await response.json()).status || "");
  }, { timeout: RUN_TIMEOUT }).toBe("done");

  const sessionResponse = await page.request.get(`/api-brain/wa-validator/sessions/${sessionId}`);
  const session = await sessionResponse.json();
  const leadRef = Number(session.lead_ref);
  expect(leadRef).toBeGreaterThan(0);
  const messagesBeforeResponse = await page.request.get(`/api-brain/messages/${leadRef}`);
  expect(messagesBeforeResponse.ok()).toBe(true);

  await expect(page.getByTestId("wa-validator-media-input")).toBeAttached({ timeout: API_TIMEOUT });
  const mediaResponses: Array<{ status: number; body: any }> = [];
  page.on("response", async (response) => {
    if (
      new URL(response.url()).pathname === `/api-brain/wa-validator/sessions/${sessionId}/media`
      && response.request().method() === "POST"
    ) {
      mediaResponses.push({ status: response.status(), body: await response.json() });
    }
  });
  await page.getByTestId("wa-validator-media-input").setInputFiles(
    fixtures.map((item) => item.absolutePath),
  );
  await expect.poll(() => mediaResponses.length, { timeout: API_TIMEOUT }).toBe(fixtures.length);
  await expect(page.getByText(/^armazenado · /)).toHaveCount(fixtures.length, { timeout: API_TIMEOUT });

  const assets = mediaResponses.map(({ status, body }, index) => {
    expect(status, `${fixtures[index].name} upload HTTP`).toBe(200);
    expect(body.outbound_enqueued).toBe(false);
    expect(body.asset.status).toBe("ready");
    expect(body.asset.filename).toBe(fixtures[index].name);
    expect(body.asset.sha256).toBe(fixtures[index].sha256);
    return body.asset;
  });
  expect(new Set(assets.map((asset) => asset.id)).size).toBe(fixtures.length);

  for (let index = 0; index < fixtures.length; index += 1) {
    const stored = await page.request.get(`/api-brain${assets[index].media_url}`);
    expect(stored.ok(), `${fixtures[index].name} private media GET`).toBe(true);
    expect(stored.headers()["content-type"]).toContain(fixtures[index].mimeType);
    const storedBytes = await stored.body();
    expect(crypto.createHash("sha256").update(storedBytes).digest("hex")).toBe(fixtures[index].sha256);
  }

  // Replay the exact first request. It must return the same asset and must not
  // create a second inbound message.
  const replay = await page.request.post(
    `/api-brain/wa-validator/sessions/${sessionId}/media`,
    {
      multipart: {
        file: { name: fixtures[0].name, mimeType: fixtures[0].mimeType, buffer: fixtures[0].bytes },
        idempotency_key: `media-${fixtures[0].sha256}`,
      },
      timeout: API_TIMEOUT,
    },
  );
  expect(replay.ok()).toBe(true);
  const replayBody = await replay.json();
  expect(replayBody.idempotent).toBe(true);
  expect(replayBody.asset.id).toBe(assets[0].id);

  const messagesAfterResponse = await page.request.get(`/api-brain/messages/${leadRef}`);
  expect(messagesAfterResponse.ok()).toBe(true);
  const messagesAfter = await messagesAfterResponse.json();
  const fixtureMessages = messagesAfter.filter((message: any) =>
    String(message.external_message_id || "").startsWith(`validator-media:${sessionId}:`)
  );
  expect(fixtureMessages).toHaveLength(fixtures.length);
  expect(fixtureMessages.every((message: any) => message.direction === "inbound")).toBe(true);
  expect(fixtureMessages.filter((message: any) => message.direction === "outbound")).toHaveLength(0);

  const graphVersion = generated.script?.meta?.graph_version;
  const leadLabel = graphVersion == null ? session.flow_id : `${session.flow_id} v${graphVersion}`;
  await expect(page.getByText(leadLabel, { exact: true }).first()).toBeVisible({ timeout: API_TIMEOUT });
  await page.getByText(leadLabel, { exact: true }).first().click();
  for (const item of fixtures.filter((entry) => entry.mimeType.startsWith("image/"))) {
    const image = page.getByRole("img", { name: item.name });
    await expect(image).toBeVisible({ timeout: API_TIMEOUT });
    await expect.poll(
      async () => image.evaluate((node: HTMLImageElement) => node.naturalWidth),
      { timeout: API_TIMEOUT },
    ).toBeGreaterThan(0);
  }
  await expect(page.getByRole("link", { name: /teste 1\.pdf/ })).toBeVisible({ timeout: API_TIMEOUT });
  await page.screenshot({ path: testInfo.outputPath("media-stored-and-visible.png"), fullPage: true });

  // A browser reload proves that the view is backed by persisted messages and
  // assets rather than transient React state.
  await page.reload();
  await selectPersona(page);
  await expect(page.getByText(leadLabel, { exact: true }).first()).toBeVisible({ timeout: API_TIMEOUT });
  await page.getByText(leadLabel, { exact: true }).first().click();
  for (const name of ["ex 1.png", "ex 2.png"]) {
    const image = page.getByRole("img", { name });
    await expect(image).toBeVisible({ timeout: API_TIMEOUT });
    await expect.poll(
      async () => image.evaluate((node: HTMLImageElement) => node.naturalWidth),
      { timeout: API_TIMEOUT },
    ).toBeGreaterThan(0);
  }
  await expect(page.getByRole("link", { name: /teste 1\.pdf/ })).toBeVisible({ timeout: API_TIMEOUT });

  expect(pageErrors, "uncaught browser errors").toEqual([]);
  expect(
    consoleErrors.filter((message) => !message.includes("favicon")),
    "unexpected browser console errors",
  ).toEqual([]);
  await context.close();
});
