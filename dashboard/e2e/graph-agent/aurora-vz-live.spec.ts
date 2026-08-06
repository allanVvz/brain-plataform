import fs from "node:fs/promises";
import path from "node:path";
import { expect, test, type APIRequestContext, type Page } from "playwright/test";

const AURORA = "aurora";
const VZ_LUPAS = "vz-lupas";
const DASHBOARD_URL = required("E2E_DASHBOARD_URL");
const VZ_LEAD_REF = Number(required("E2E_VZ_LEAD_REF"));
const AURORA_LEAD_REF = Number(required("E2E_AURORA_LEAD_REF"));
const ADMIN_EMAIL = required("E2E_ADMIN_EMAIL");
const ADMIN_PASSWORD = required("E2E_ADMIN_PASSWORD");
const NONCE = required("E2E_NONCE");
const ARTIFACT_DIR = process.env.E2E_ARTIFACT_DIR
  || path.resolve(process.cwd(), "..", "test-artifacts", "graph-agent-e2e-live");
const MESSAGE = `E2E GraphRAG ${NONCE}: Quero fazer higienização interna no meu veículo.`;
const UNSAFE_REPLY_PATTERN =
  /(confirmad[oa]|confirmo\b|fechad[oa]|reservad[oa]|agendad[oa]\s+para|marcad[oa]\s+para).{0,80}(r\$\s?\d|\b\d{1,2}[:h]\d{0,2}\b|\b\d{1,2}\/\d{1,2}\b)/i;

type MessageRow = {
  id: number;
  lead_ref?: number;
  message_id?: string;
  sender_id?: string;
  external_message_id?: string;
  correlation_id?: string;
  direction?: string;
  sender_type?: string;
  role?: string;
  texto?: string;
  content?: string;
  status?: string;
  created_at?: string;
  channel_binding_id?: string;
};

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Missing required E2E variable: ${name}`);
  return value;
}

function ensure(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function textOf(row: MessageRow): string {
  return String(row.texto ?? row.content ?? "").trim();
}

function safeMessage(row: MessageRow) {
  return {
    id: row.id,
    lead_ref: row.lead_ref,
    message_id: row.message_id || row.sender_id || null,
    external_message_id: row.external_message_id || null,
    correlation_id: row.correlation_id || null,
    direction: row.direction || null,
    sender_type: row.sender_type || row.role || null,
    status: row.status || null,
    created_at: row.created_at || null,
    channel_binding_id: row.channel_binding_id || null,
    text: textOf(row),
  };
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
  await page.goto("/");
  const selector = page.locator("header select");
  await expect(selector).toBeVisible();
  await selector.selectOption(slug);
  await expect(selector).toHaveValue(slug);
  await expect.poll(() => page.evaluate(() =>
    window.localStorage.getItem("ai-brain-persona-slug")),
  ).toBe(slug);
}

async function messages(request: APIRequestContext, leadRef: number): Promise<MessageRow[]> {
  const response = await request.get(
    `/api-brain/messages/by-ref/${leadRef}?limit=500&validation_scope=all`,
    { timeout: 120_000 },
  );
  ensure(response.ok(), `messages lead_ref=${leadRef} returned HTTP ${response.status()}`);
  return await response.json() as MessageRow[];
}

async function leadState(request: APIRequestContext, leadRef: number) {
  const response = await request.get(`/api-brain/leads/${leadRef}`, { timeout: 120_000 });
  ensure(response.ok(), `lead_ref=${leadRef} returned HTTP ${response.status()}`);
  const row = await response.json();
  return {
    id: row.id,
    persona_id: row.persona_id,
    channel_binding_id: row.channel_binding_id,
    ai_enabled: row.ai_enabled,
    ai_paused: row.ai_paused,
    updated_at: row.updated_at,
  };
}

async function graphDocument(request: APIRequestContext, slug: string) {
  const response = await request.get(
    `/api-brain/graph-documents/current?persona_slug=${slug}`,
    { timeout: 120_000 },
  );
  ensure(response.ok(), `graph document ${slug} returned HTTP ${response.status()}`);
  const row = await response.json();
  return { version: row.version, checksum: row.checksum };
}

test("live: VZ envia uma vez, Aurora GraphRAG decide uma vez e VZ persiste a resposta", async ({ browser }) => {
  test.setTimeout(360_000);
  await fs.mkdir(ARTIFACT_DIR, { recursive: true });
  const startedAt = new Date().toISOString();
  const sourceContext = await browser.newContext({ baseURL: DASHBOARD_URL });
  const destinationContext = await browser.newContext({ baseURL: DASHBOARD_URL });
  const sourcePage = await sourceContext.newPage();
  const destinationPage = await destinationContext.newPage();
  const network: Array<Record<string, unknown>> = [];

  for (const page of [sourcePage, destinationPage]) {
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
  }

  try {
    await login(sourcePage);
    await login(destinationPage);
    await switchPersona(sourcePage, VZ_LUPAS);
    await switchPersona(destinationPage, AURORA);

    const [vzBefore, auroraBefore, vzLeadBefore, auroraLeadBefore, auroraGraph] = await Promise.all([
      messages(sourcePage.request, VZ_LEAD_REF),
      messages(destinationPage.request, AURORA_LEAD_REF),
      leadState(sourcePage.request, VZ_LEAD_REF),
      leadState(destinationPage.request, AURORA_LEAD_REF),
      graphDocument(destinationPage.request, AURORA),
    ]);
    expect(vzLeadBefore.ai_paused, "A IA da VZ deve permanecer pausada").toBe(true);
    expect(auroraLeadBefore.ai_paused, "A IA da Aurora deve estar ativa").toBe(false);

    await sourcePage.goto(`/messages/${VZ_LEAD_REF}`);
    await expect(sourcePage.getByTitle(/IA pausada/)).toBeVisible({ timeout: 120_000 });
    const composer = sourcePage.locator("textarea").last();
    await expect(composer).toBeVisible();
    await composer.fill(MESSAGE);

    const sendStartedAt = new Date().toISOString();
    const [sendResponse] = await Promise.all([
      sourcePage.waitForResponse((response) =>
        new URL(response.url()).pathname === "/api-brain/messages/send"
        && response.request().method() === "POST", { timeout: 120_000 }),
      sourcePage.getByRole("button", { name: /^enviar$/i }).click(),
    ]);
    expect(sendResponse.status()).toBe(200);
    const sendDecision = await sendResponse.json();
    expect(sendDecision.ok).toBe(true);
    expect(sendDecision.deduplicated).toBe(false);
    expect(String(sendDecision.message_id)).toMatch(/^manual:/);

    let sourceOutbound: MessageRow | undefined;
    await expect.poll(async () => {
      const rows = await messages(sourcePage.request, VZ_LEAD_REF);
      const matches = rows.filter((row) =>
        row.direction === "outbound"
        && textOf(row) === MESSAGE
        && !vzBefore.some((before) => before.id === row.id));
      sourceOutbound = matches[0];
      return matches.length;
    }, { timeout: 120_000, intervals: [1_000, 2_000, 3_000] }).toBe(1);

    let auroraInbound: MessageRow | undefined;
    await expect.poll(async () => {
      const rows = await messages(destinationPage.request, AURORA_LEAD_REF);
      const matches = rows.filter((row) =>
        row.direction === "inbound"
        && textOf(row) === MESSAGE
        && !auroraBefore.some((before) => before.id === row.id));
      auroraInbound = matches[0];
      return matches.length;
    }, { timeout: 150_000, intervals: [2_000, 3_000, 5_000] }).toBe(1);

    let auroraOutbound: MessageRow | undefined;
    await expect.poll(async () => {
      const rows = await messages(destinationPage.request, AURORA_LEAD_REF);
      const inboundAt = Date.parse(String(auroraInbound?.created_at || sendStartedAt));
      const matches = rows.filter((row) =>
        row.direction === "outbound"
        && Date.parse(String(row.created_at || "")) >= inboundAt
        && !auroraBefore.some((before) => before.id === row.id));
      auroraOutbound = matches[0];
      return matches.length;
    }, { timeout: 180_000, intervals: [2_000, 3_000, 5_000] }).toBe(1);

    const reply = textOf(auroraOutbound!);
    expect(reply.length).toBeGreaterThan(0);
    expect(UNSAFE_REPLY_PATTERN.test(reply), `Resposta insegura: ${reply}`).toBe(false);
    expect(reply.toLowerCase()).not.toContain("vz lupas");

    let vzInbound: MessageRow | undefined;
    await expect.poll(async () => {
      const rows = await messages(sourcePage.request, VZ_LEAD_REF);
      const matches = rows.filter((row) =>
        row.direction === "inbound"
        && textOf(row) === reply
        && !vzBefore.some((before) => before.id === row.id));
      vzInbound = matches[0];
      return matches.length;
    }, { timeout: 150_000, intervals: [2_000, 3_000, 5_000] }).toBe(1);

    // Allow delayed provider retries to surface before asserting exact-once.
    await sourcePage.waitForTimeout(10_000);
    const [vzAfter, auroraAfter, vzLeadAfter] = await Promise.all([
      messages(sourcePage.request, VZ_LEAD_REF),
      messages(destinationPage.request, AURORA_LEAD_REF),
      leadState(sourcePage.request, VZ_LEAD_REF),
    ]);
    expect(vzLeadAfter.ai_paused, "O ensaio não pode retomar a IA da VZ").toBe(true);
    expect(vzAfter.filter((row) => row.direction === "outbound" && textOf(row) === MESSAGE)).toHaveLength(1);
    expect(auroraAfter.filter((row) => row.direction === "inbound" && textOf(row) === MESSAGE)).toHaveLength(1);
    expect(auroraAfter.filter((row) => row.direction === "outbound" && textOf(row) === reply
      && Date.parse(String(row.created_at || "")) >= Date.parse(sendStartedAt))).toHaveLength(1);
    expect(vzAfter.filter((row) => row.direction === "inbound" && textOf(row) === reply
      && Date.parse(String(row.created_at || "")) >= Date.parse(sendStartedAt))).toHaveLength(1);

    await sourcePage.reload();
    await expect(sourcePage.getByText(MESSAGE, { exact: true })).toBeVisible({ timeout: 120_000 });
    await expect(sourcePage.getByText(reply, { exact: true })).toBeVisible({ timeout: 120_000 });
    await sourcePage.screenshot({
      path: path.join(ARTIFACT_DIR, "04-vz-source-and-destination-persisted.png"),
      fullPage: true,
    });

    await destinationPage.goto(`/messages/${AURORA_LEAD_REF}`);
    await expect(destinationPage.getByText(MESSAGE, { exact: true })).toBeVisible({ timeout: 120_000 });
    await expect(destinationPage.getByText(reply, { exact: true })).toBeVisible({ timeout: 120_000 });
    await destinationPage.screenshot({
      path: path.join(ARTIFACT_DIR, "05-aurora-inbound-and-single-reply.png"),
      fullPage: true,
    });

    const evidence = {
      test: "Aurora GraphRAG v3 live transport round-trip with VZ Lupas human-only",
      started_at: startedAt,
      send_started_at: sendStartedAt,
      finished_at: new Date().toISOString(),
      nonce: NONCE,
      graph: { persona_slug: AURORA, ...auroraGraph },
      source: { persona_slug: VZ_LUPAS, lead: vzLeadAfter, message: safeMessage(sourceOutbound!) },
      aurora: {
        persona_slug: AURORA,
        lead: auroraLeadBefore,
        inbound: safeMessage(auroraInbound!),
        outbound: safeMessage(auroraOutbound!),
      },
      destination: { persona_slug: VZ_LUPAS, lead: vzLeadAfter, message: safeMessage(vzInbound!) },
      invariants: {
        vz_ai_remained_paused: true,
        source_outbound_count: 1,
        aurora_inbound_count: 1,
        aurora_outbound_count: 1,
        destination_inbound_count: 1,
        unsafe_commercial_confirmation: false,
        wrong_persona_copy: false,
        provider_status_used_as_delivery_proof: false,
      },
      transport_enqueue: sendDecision,
      network,
      screenshots: [
        "04-vz-source-and-destination-persisted.png",
        "05-aurora-inbound-and-single-reply.png",
      ],
    };
    await fs.writeFile(
      path.join(ARTIFACT_DIR, "live-evidence.json"),
      `${JSON.stringify(evidence, null, 2)}\n`,
      "utf8",
    );
  } finally {
    await sourceContext.close();
    await destinationContext.close();
  }
});
