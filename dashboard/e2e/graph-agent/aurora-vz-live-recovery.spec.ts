import fs from "node:fs/promises";
import path from "node:path";
import { expect, test, type APIRequestContext, type Page } from "playwright/test";

const DASHBOARD_URL = required("E2E_DASHBOARD_URL");
const ADMIN_EMAIL = required("E2E_ADMIN_EMAIL");
const ADMIN_PASSWORD = required("E2E_ADMIN_PASSWORD");
const MESSAGE = required("E2E_EXISTING_MESSAGE");
const VZ_LEAD_REF = Number(required("E2E_VZ_LEAD_REF"));
const AURORA_LEAD_REF = Number(required("E2E_AURORA_LEAD_REF"));
const ARTIFACT_DIR = process.env.E2E_ARTIFACT_DIR
  || path.resolve(process.cwd(), "..", "test-artifacts", "graph-agent-e2e-live");
const UNSAFE_REPLY_PATTERN =
  /(confirmad[oa]|confirmo\b|fechad[oa]|reservad[oa]|agendad[oa]\s+para|marcad[oa]\s+para).{0,80}(r\$\s?\d|\b\d{1,2}[:h]\d{0,2}\b|\b\d{1,2}\/\d{1,2}\b)/i;

type MessageRow = Record<string, any> & { id: number };

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

async function switchPersona(page: Page, slug: string) {
  await page.goto("/");
  const selector = page.locator("header select");
  await expect(selector).toBeVisible();
  await selector.selectOption(slug);
  await expect(selector).toHaveValue(slug);
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

test("recovery: reprocessa o mesmo inbound após corrigir o template, sem novo envio", async ({ browser }) => {
  test.setTimeout(360_000);
  await fs.mkdir(ARTIFACT_DIR, { recursive: true });
  const startedAt = new Date().toISOString();
  const sourceContext = await browser.newContext({ baseURL: DASHBOARD_URL });
  const auroraContext = await browser.newContext({ baseURL: DASHBOARD_URL });
  const sourcePage = await sourceContext.newPage();
  const auroraPage = await auroraContext.newPage();

  try {
    await login(sourcePage);
    await login(auroraPage);
    await switchPersona(sourcePage, "vz-lupas");
    await switchPersona(auroraPage, "aurora");

    const [vzBefore, auroraBefore, vzLead, auroraLead] = await Promise.all([
      messages(sourcePage.request, VZ_LEAD_REF),
      messages(auroraPage.request, AURORA_LEAD_REF),
      leadState(sourcePage.request, VZ_LEAD_REF),
      leadState(auroraPage.request, AURORA_LEAD_REF),
    ]);
    const sourceOutbound = vzBefore.filter((row) => row.direction === "outbound" && textOf(row) === MESSAGE);
    const auroraInbound = auroraBefore.filter((row) => row.direction === "inbound" && textOf(row) === MESSAGE);
    expect(sourceOutbound, "A mensagem original deve existir uma única vez na VZ").toHaveLength(1);
    expect(auroraInbound, "O inbound original deve existir uma única vez na Aurora").toHaveLength(1);
    expect(vzLead.ai_paused, "A IA da VZ deve permanecer pausada").toBe(true);
    expect(auroraLead.ai_paused, "A falha técnica anterior deve ter pausado esta lead da Aurora").toBe(true);

    const inboundAt = Date.parse(String(auroraInbound[0].created_at));
    const existingAuroraReplies = auroraBefore.filter((row) =>
      row.direction === "outbound" && Date.parse(String(row.created_at || "")) >= inboundAt);
    expect(existingAuroraReplies, "Não pode existir decisão/outbound anterior para este inbound").toHaveLength(0);

    await auroraPage.goto(`/messages/${AURORA_LEAD_REF}`);
    await expect(auroraPage.getByText(MESSAGE, { exact: true })).toBeVisible({ timeout: 120_000 });
    const resumeButton = auroraPage.getByTitle(/IA pausada/);
    await expect(resumeButton).toBeVisible();
    const [resumeResponse] = await Promise.all([
      auroraPage.waitForResponse((response) =>
        new URL(response.url()).pathname === `/api-brain/leads/${AURORA_LEAD_REF}/resume-ai`
        && response.request().method() === "POST", { timeout: 120_000 }),
      resumeButton.click(),
    ]);
    expect(resumeResponse.ok()).toBe(true);
    const resumeResult = await resumeResponse.json();
    expect(resumeResult.ai_paused).toBe(false);

    let auroraOutbound: MessageRow | undefined;
    await expect.poll(async () => {
      const rows = await messages(auroraPage.request, AURORA_LEAD_REF);
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

    await sourcePage.waitForTimeout(10_000);
    const [vzAfter, auroraAfter, vzLeadAfter] = await Promise.all([
      messages(sourcePage.request, VZ_LEAD_REF),
      messages(auroraPage.request, AURORA_LEAD_REF),
      leadState(sourcePage.request, VZ_LEAD_REF),
    ]);
    expect(vzLeadAfter.ai_paused).toBe(true);
    expect(vzAfter.filter((row) => row.direction === "outbound" && textOf(row) === MESSAGE)).toHaveLength(1);
    expect(auroraAfter.filter((row) => row.direction === "inbound" && textOf(row) === MESSAGE)).toHaveLength(1);
    expect(auroraAfter.filter((row) => row.direction === "outbound" && textOf(row) === reply
      && Date.parse(String(row.created_at || "")) >= inboundAt)).toHaveLength(1);
    expect(vzAfter.filter((row) => row.direction === "inbound" && textOf(row) === reply
      && Date.parse(String(row.created_at || "")) >= inboundAt)).toHaveLength(1);

    await sourcePage.goto(`/messages/${VZ_LEAD_REF}`);
    await expect(sourcePage.getByText(MESSAGE, { exact: true })).toBeVisible({ timeout: 120_000 });
    await expect(sourcePage.getByText(reply, { exact: true })).toBeVisible({ timeout: 120_000 });
    await sourcePage.screenshot({
      path: path.join(ARTIFACT_DIR, "04-vz-source-and-destination-persisted.png"),
      fullPage: true,
    });
    await auroraPage.reload();
    await expect(auroraPage.getByText(MESSAGE, { exact: true })).toBeVisible({ timeout: 120_000 });
    await expect(auroraPage.getByText(reply, { exact: true })).toBeVisible({ timeout: 120_000 });
    await auroraPage.screenshot({
      path: path.join(ARTIFACT_DIR, "05-aurora-inbound-and-single-reply.png"),
      fullPage: true,
    });

    await fs.writeFile(
      path.join(ARTIFACT_DIR, "live-evidence.json"),
      `${JSON.stringify({
        test: "same inbound recovery after canonical n8n template repair",
        started_at: startedAt,
        finished_at: new Date().toISOString(),
        source: { persona_slug: "vz-lupas", lead: vzLeadAfter, message: safeMessage(sourceOutbound[0]) },
        aurora: {
          persona_slug: "aurora",
          lead_before_resume: auroraLead,
          inbound: safeMessage(auroraInbound[0]),
          outbound: safeMessage(auroraOutbound!),
        },
        destination: { persona_slug: "vz-lupas", lead: vzLeadAfter, message: safeMessage(vzInbound!) },
        resume: resumeResult,
        invariants: {
          new_source_send_count: 0,
          source_outbound_count: 1,
          aurora_inbound_count: 1,
          aurora_outbound_count: 1,
          destination_inbound_count: 1,
          vz_ai_remained_paused: true,
          unsafe_commercial_confirmation: false,
          provider_status_used_as_destination_proof: false,
        },
        screenshots: [
          "04-vz-source-and-destination-persisted.png",
          "05-aurora-inbound-and-single-reply.png",
        ],
      }, null, 2)}\n`,
      "utf8",
    );
  } finally {
    await sourceContext.close();
    await auroraContext.close();
  }
});
