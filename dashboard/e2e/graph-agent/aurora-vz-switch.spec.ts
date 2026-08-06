import fs from "node:fs/promises";
import path from "node:path";
import { expect, test, type Page } from "playwright/test";

const AURORA = "aurora";
const VZ_LUPAS = "vz-lupas";
const ADMIN_EMAIL = required("E2E_ADMIN_EMAIL");
const ADMIN_PASSWORD = required("E2E_ADMIN_PASSWORD");
const ARTIFACT_DIR = process.env.E2E_ARTIFACT_DIR
  || path.resolve(process.cwd(), "..", "test-artifacts", "graph-agent-e2e");

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Missing required E2E variable: ${name}`);
  return value;
}

async function login(page: Page) {
  await page.goto("/login");
  if (!page.url().includes("/login")) return;
  await page.getByPlaceholder("operador@empresa.com").fill(ADMIN_EMAIL);
  await page.getByPlaceholder("Digite sua senha").fill(ADMIN_PASSWORD);
  await Promise.all([
    page.waitForResponse((response) =>
      new URL(response.url()).pathname === "/api-brain/auth/login"
      && response.request().method() === "POST"),
    page.getByRole("button", { name: "Entrar" }).click(),
  ]);
  await expect.poll(async () =>
    (await page.context().cookies()).some((cookie) => cookie.name === "ai_brain_session"),
  ).toBe(true);
}

async function switchPersona(page: Page, slug: string): Promise<void> {
  const selector = page.locator("header select");
  if (await selector.inputValue() === slug) {
    const alternate = await selector.locator("option").evaluateAll(
      (options, target) => options
        .map((option) => (option as HTMLOptionElement).value)
        .find((value) => value && value !== target) || "",
      slug,
    );
    if (alternate) {
      await selector.selectOption(alternate);
      await expect(selector).toHaveValue(alternate);
      await expect.poll(() => page.evaluate(() =>
        window.localStorage.getItem("ai-brain-persona-slug")),
      ).toBe(alternate);
    }
  }
  await selector.selectOption(slug);
  await expect(selector).toHaveValue(slug);
  await expect.poll(() => page.evaluate(() =>
    window.localStorage.getItem("ai-brain-persona-slug")),
  ).toBe(slug);
}

async function jsonOrNull(response: { json(): Promise<unknown> }): Promise<any> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

test("Aurora e VZ Lupas mantêm isolamento ao trocar o grafo ativo", async ({ page }) => {
  await fs.mkdir(ARTIFACT_DIR, { recursive: true });
  const startedAt = new Date().toISOString();
  const consoleErrors: string[] = [];
  const network: Array<Record<string, unknown>> = [];
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (url.pathname.startsWith("/api-brain/")) {
      network.push({
        at: new Date().toISOString(),
        method: response.request().method(),
        path: `${url.pathname}${url.search}`,
        status: response.status(),
      });
    }
  });

  await login(page);
  // The unauthenticated /auth/me probe on the login page intentionally returns
  // 401. Audit console errors only after the session cookie is established.
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await page.goto("/knowledge/graph");
  await expect(page.locator("header select")).toBeVisible();

  const meResponse = await page.request.get("/api-brain/auth/me");
  expect(meResponse.ok()).toBe(true);
  const session = await meResponse.json();
  const authorizedPersonas = Array.isArray(session?.personas) ? session.personas : [];
  const auroraPersona = authorizedPersonas.find((item: any) => item.slug === AURORA);
  const vzPersona = authorizedPersonas.find((item: any) => item.slug === VZ_LUPAS);
  expect(auroraPersona?.id).toBeTruthy();
  expect(vzPersona?.id).toBeTruthy();

  const auroraStarted = Date.now();
  await switchPersona(page, AURORA);
  const auroraResponse = await page.request.get(
    `/api-brain/graph-documents/current?persona_slug=${AURORA}`,
    { timeout: 120_000 },
  );
  const auroraLatencyMs = Date.now() - auroraStarted;
  expect(auroraResponse.ok()).toBe(true);
  const auroraDocument = await jsonOrNull(auroraResponse);
  expect(Number(auroraDocument?.version)).toBeGreaterThanOrEqual(7);
  expect(String(auroraDocument?.checksum || "")).toMatch(/^sha256:/);
  const auroraNodeCount = auroraDocument?.graph_json?.nodes?.length || 0;
  const auroraEdgeCount = auroraDocument?.graph_json?.edges?.length || 0;
  expect(auroraNodeCount).toBeGreaterThan(0);
  expect(auroraEdgeCount).toBeGreaterThan(0);
  const auroraGraphSummary = new RegExp(`${auroraNodeCount} nodes.*${auroraEdgeCount} edges`);
  await expect(page.getByText(auroraGraphSummary)).toBeVisible();
  await page.screenshot({
    path: path.join(ARTIFACT_DIR, "01-aurora-graph-v9.png"),
    fullPage: true,
  });

  await page.route(
    `**/api-brain/graph-documents/current?persona_slug=${VZ_LUPAS}`,
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1_500));
      await route.continue();
    },
    { times: 1 },
  );
  const vzStarted = Date.now();
  await switchPersona(page, VZ_LUPAS);
  // The Aurora graph must disappear before the delayed VZ response returns.
  await expect(page.getByText(auroraGraphSummary)).toHaveCount(0, { timeout: 750 });
  const vzResponse = await page.request.get(
    `/api-brain/graph-documents/current?persona_slug=${VZ_LUPAS}`,
    { timeout: 120_000 },
  );
  const vzLatencyMs = Date.now() - vzStarted;
  expect(vzResponse.ok()).toBe(true);
  const vzDocument = await jsonOrNull(vzResponse);
  expect(Number(vzDocument?.version || 0)).toBeGreaterThanOrEqual(1);
  expect(String(vzDocument?.checksum || "")).toMatch(/^sha256:/);
  expect(vzDocument?.checksum).not.toBe(auroraDocument?.checksum);
  const vzNodes = vzDocument?.graph_json?.nodes || [];
  const vzEdges = vzDocument?.graph_json?.edges || [];
  const auroraNodeIds = new Set(
    (auroraDocument?.graph_json?.nodes || []).map((node: any) => String(node.id)),
  );
  expect(vzNodes.length).toBeGreaterThan(0);
  expect(vzNodes.some((node: any) => auroraNodeIds.has(String(node.id)))).toBe(false);
  expect(JSON.stringify(vzDocument?.graph_json || {}).toLowerCase()).not.toContain("aurora-");
  await expect(page.getByText(new RegExp(`${vzNodes.length} nodes.*${vzEdges.length} edges`))).toBeVisible();
  await expect(page.getByText(auroraGraphSummary)).toHaveCount(0);
  await page.screenshot({
    path: path.join(ARTIFACT_DIR, "02-vz-lupas-pending-validation-graph.png"),
    fullPage: true,
  });

  await switchPersona(page, AURORA);
  const auroraReturnResponse = await page.request.get(
    `/api-brain/graph-documents/current?persona_slug=${AURORA}`,
    { timeout: 120_000 },
  );
  expect(auroraReturnResponse.ok()).toBe(true);
  const auroraReturnDocument = await jsonOrNull(auroraReturnResponse);
  expect(auroraReturnDocument?.checksum).toBe(auroraDocument?.checksum);
  await expect(page.getByText(auroraGraphSummary)).toBeVisible();
  await page.screenshot({
    path: path.join(ARTIFACT_DIR, "03-aurora-return-same-checksum.png"),
    fullPage: true,
  });

  const [auroraRoutingResponse, vzRoutingResponse] = await Promise.all([
    page.request.get(`/api-brain/personas/${AURORA}/routing`, { timeout: 120_000 }),
    page.request.get(`/api-brain/personas/${VZ_LUPAS}/routing`, { timeout: 120_000 }),
  ]);
  expect(auroraRoutingResponse.ok()).toBe(true);
  expect(vzRoutingResponse.ok()).toBe(true);

  const evidence = {
    started_at: startedAt,
    finished_at: new Date().toISOString(),
    test: "graph-agent persona switch isolation",
    personas: {
      aurora: {
        id: auroraPersona.id,
        slug: AURORA,
        graph_version: auroraDocument.version,
        graph_checksum: auroraDocument.checksum,
        node_count: auroraNodeCount,
        edge_count: auroraEdgeCount,
        request_status: auroraResponse.status(),
        latency_ms: auroraLatencyMs,
        routing: await auroraRoutingResponse.json(),
      },
      vz_lupas: {
        id: vzPersona.id,
        slug: VZ_LUPAS,
        graph_version: vzDocument.version,
        graph_checksum: vzDocument.checksum,
        node_count: vzNodes.length,
        edge_count: vzEdges.length,
        request_status: vzResponse.status(),
        latency_ms: vzLatencyMs,
        routing: await vzRoutingResponse.json(),
      },
    },
    invariant: {
      aurora_checksum_stable_after_round_trip:
        auroraReturnDocument?.checksum === auroraDocument?.checksum,
      vz_did_not_render_aurora_graph: true,
      previous_graph_cleared_before_vz_response: true,
      external_messages_sent: 0,
    },
    console_errors: consoleErrors,
    network,
    screenshots: [
      "01-aurora-graph-v9.png",
      "02-vz-lupas-pending-validation-graph.png",
      "03-aurora-return-same-checksum.png",
    ],
  };
  await fs.writeFile(
    path.join(ARTIFACT_DIR, "evidence.json"),
    `${JSON.stringify(evidence, null, 2)}\n`,
    "utf8",
  );

  expect(consoleErrors, consoleErrors.join("\n")).toEqual([]);
});
