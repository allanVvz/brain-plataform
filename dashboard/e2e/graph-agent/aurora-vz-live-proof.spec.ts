import fs from "node:fs/promises";
import path from "node:path";
import { expect, test, type APIRequestContext, type Page } from "playwright/test";

const DASHBOARD_URL = required("E2E_DASHBOARD_URL");
const ADMIN_EMAIL = required("E2E_ADMIN_EMAIL");
const ADMIN_PASSWORD = required("E2E_ADMIN_PASSWORD");
const MESSAGE = required("E2E_EXISTING_MESSAGE");
const REPLY = required("E2E_EXISTING_REPLY");
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

test("proof: uma decisão e um outbound persistidos nos dois lados, sem novo envio", async ({ browser }) => {
  test.setTimeout(300_000);
  await fs.mkdir(ARTIFACT_DIR, { recursive: true });
  const startedAt = new Date().toISOString();
  const vzContext = await browser.newContext({ baseURL: DASHBOARD_URL });
  const auroraContext = await browser.newContext({ baseURL: DASHBOARD_URL });
  const vzPage = await vzContext.newPage();
  const auroraPage = await auroraContext.newPage();

  try {
    await login(vzPage);
    await login(auroraPage);
    await switchPersona(vzPage, "vz-lupas");
    await switchPersona(auroraPage, "aurora");

    const [vzRows, auroraRows, vzLeadBefore, auroraLeadBefore, graphResponse] = await Promise.all([
      messages(vzPage.request, VZ_LEAD_REF),
      messages(auroraPage.request, AURORA_LEAD_REF),
      leadState(vzPage.request, VZ_LEAD_REF),
      leadState(auroraPage.request, AURORA_LEAD_REF),
      auroraPage.request.get("/api-brain/graph-documents/current?persona_slug=aurora"),
    ]);
    expect(vzLeadBefore.ai_paused, "A IA da VZ deve permanecer pausada").toBe(true);
    expect(graphResponse.ok()).toBe(true);
    const graphDocument = await graphResponse.json();

    const sourceOutbound = vzRows.filter((row) => row.direction === "outbound" && textOf(row) === MESSAGE);
    const auroraInbound = auroraRows.filter((row) => row.direction === "inbound" && textOf(row) === MESSAGE);
    expect(sourceOutbound).toHaveLength(1);
    expect(auroraInbound).toHaveLength(1);
    const inboundAt = Date.parse(String(auroraInbound[0].created_at));
    const auroraOutbound = auroraRows.filter((row) =>
      row.direction === "outbound"
      && textOf(row) === REPLY
      && Date.parse(String(row.created_at || "")) >= inboundAt);
    const destinationInbound = vzRows.filter((row) =>
      row.direction === "inbound"
      && textOf(row) === REPLY
      && Date.parse(String(row.created_at || "")) >= inboundAt);
    expect(auroraOutbound).toHaveLength(1);
    expect(destinationInbound).toHaveLength(1);
    expect(UNSAFE_REPLY_PATTERN.test(REPLY)).toBe(false);
    expect(REPLY.toLowerCase()).not.toContain("vz lupas");

    // The target may have been safety-paused by the failed pre-decision
    // attempt. Resume it only after VZ (the transport/source persona) is
    // proved paused. Completed inbound turns are not requeued by this action.
    let resumeResult: Record<string, any> | null = null;
    if (auroraLeadBefore.ai_paused) {
      await auroraPage.goto(`/messages/${AURORA_LEAD_REF}`);
      const resumeButton = auroraPage.getByTitle(/IA pausada/);
      await expect(resumeButton).toBeVisible({ timeout: 120_000 });
      const [response] = await Promise.all([
        auroraPage.waitForResponse((candidate) =>
          new URL(candidate.url()).pathname === `/api-brain/leads/${AURORA_LEAD_REF}/resume-ai`
          && candidate.request().method() === "POST", { timeout: 120_000 }),
        resumeButton.click(),
      ]);
      expect(response.ok()).toBe(true);
      resumeResult = await response.json();
      expect(resumeResult?.ai_paused).toBe(false);
    }

    await vzPage.goto(`/messages/${VZ_LEAD_REF}`);
    await expect(vzPage.getByText(MESSAGE, { exact: true })).toBeVisible({ timeout: 120_000 });
    await expect(vzPage.getByText(REPLY, { exact: true }).last()).toBeVisible({ timeout: 120_000 });
    await vzPage.screenshot({
      path: path.join(ARTIFACT_DIR, "04-vz-source-and-destination-persisted.png"),
      fullPage: true,
    });

    await auroraPage.goto(`/messages/${AURORA_LEAD_REF}`);
    await expect(auroraPage.getByText(MESSAGE, { exact: true })).toBeVisible({ timeout: 120_000 });
    await expect(auroraPage.getByText(REPLY, { exact: true }).last()).toBeVisible({ timeout: 120_000 });
    await auroraPage.screenshot({
      path: path.join(ARTIFACT_DIR, "05-aurora-inbound-and-single-reply.png"),
      fullPage: true,
    });

    await vzPage.waitForTimeout(10_000);
    const [vzAfter, auroraAfter, vzLeadAfter, auroraLeadAfter] = await Promise.all([
      messages(vzPage.request, VZ_LEAD_REF),
      messages(auroraPage.request, AURORA_LEAD_REF),
      leadState(vzPage.request, VZ_LEAD_REF),
      leadState(auroraPage.request, AURORA_LEAD_REF),
    ]);
    expect(vzLeadAfter.ai_paused).toBe(true);
    expect(auroraLeadAfter.ai_paused).toBe(false);
    expect(vzAfter.filter((row) => row.direction === "outbound" && textOf(row) === MESSAGE)).toHaveLength(1);
    expect(auroraAfter.filter((row) => row.direction === "inbound" && textOf(row) === MESSAGE)).toHaveLength(1);
    expect(auroraAfter.filter((row) => row.direction === "outbound" && textOf(row) === REPLY
      && Date.parse(String(row.created_at || "")) >= inboundAt)).toHaveLength(1);
    expect(vzAfter.filter((row) => row.direction === "inbound" && textOf(row) === REPLY
      && Date.parse(String(row.created_at || "")) >= inboundAt)).toHaveLength(1);

    await fs.writeFile(
      path.join(ARTIFACT_DIR, "live-evidence.json"),
      `${JSON.stringify({
        test: "Aurora GraphRAG v3 live transport persisted proof",
        started_at: startedAt,
        finished_at: new Date().toISOString(),
        graph: {
          publication_version: 4,
          graph_json_version: graphDocument.version,
          graph_json_checksum: graphDocument.checksum,
        },
        source: { persona_slug: "vz-lupas", lead: vzLeadAfter, message: safeMessage(sourceOutbound[0]) },
        aurora: {
          persona_slug: "aurora",
          lead: auroraLeadAfter,
          inbound: safeMessage(auroraInbound[0]),
          outbound: safeMessage(auroraOutbound[0]),
        },
        destination: { persona_slug: "vz-lupas", lead: vzLeadAfter, message: safeMessage(destinationInbound[0]) },
        resume: resumeResult,
        invariants: {
          new_source_send_count: 0,
          source_outbound_count: 1,
          aurora_inbound_count: 1,
          aurora_outbound_count: 1,
          destination_inbound_count: 1,
          vz_ai_remained_paused: true,
          aurora_ai_active_after_transport_pause_confirmation: true,
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
    await vzContext.close();
    await auroraContext.close();
  }
});
