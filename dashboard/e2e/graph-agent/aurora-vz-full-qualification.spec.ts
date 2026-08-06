import fs from "node:fs/promises";
import path from "node:path";
import { expect, test, type APIRequestContext, type Page } from "playwright/test";

const DASHBOARD_URL = required("E2E_DASHBOARD_URL");
const ADMIN_EMAIL = required("E2E_ADMIN_EMAIL");
const ADMIN_PASSWORD = required("E2E_ADMIN_PASSWORD");
const VZ_LEAD_REF = Number(required("E2E_VZ_LEAD_REF"));
const AURORA_LEAD_REF = Number(required("E2E_AURORA_LEAD_REF"));
const ARTIFACT_DIR = process.env.E2E_ARTIFACT_DIR
  || path.resolve(process.cwd(), "..", "test-artifacts", "graph-agent-e2e-full-qualification");

type MessageRow = Record<string, unknown> & { id: number; direction?: string; created_at?: string };
type Turn = { field_key: string; answer: string; source: object; aurora_inbound: object; aurora_reply: object; vz_inbound: object; latency_ms: number };

// These are test facts, not runtime policy. The expected question text is read
// from the published graph document before every send.
const ANSWERS: Record<string, string> = {
  nome_cliente: "Allan",
  modelo_veiculo: "Toyota Corolla",
  vehicle_year: "2020",
  objective: "Vou continuar com o carro e investir em conservação.",
  can_visit_in_person: "Consigo levar o carro para avaliação presencial.",
  condicao: "O interior está com manchas nos bancos e odor leve.",
};
const REQUIRED_FIELDS = new Set(["nome_cliente", "modelo_veiculo", "vehicle_year", "objective", "can_visit_in_person", "condicao"]);
const UNSAFE_REPLY_PATTERN = /(confirmad[oa]|confirmo\b|fechad[oa]|reservad[oa]|agendad[oa]\s+para|marcad[oa]\s+para).{0,80}(r\$\s?\d|\b\d{1,2}[:h]\d{0,2}\b|\b\d{1,2}\/\d{1,2}\b)/i;

function required(name: string): string { const value = process.env[name]?.trim(); if (!value) throw new Error(`Missing required E2E variable: ${name}`); return value; }
function ensure(condition: unknown, message: string): asserts condition { if (!condition) throw new Error(message); }
function textOf(row: MessageRow): string { return String(row.texto ?? row.content ?? "").trim(); }
function compact(row: MessageRow) { return { id: row.id, message_id: row.message_id ?? row.sender_id ?? null, correlation_id: row.correlation_id ?? null, direction: row.direction ?? null, created_at: row.created_at ?? null, status: row.status ?? null, text: textOf(row) }; }
function normal(text: string) { return text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim(); }

async function login(page: Page) {
  await page.goto("/login");
  if (!page.url().includes("/login")) return;
  await page.getByPlaceholder("operador@empresa.com").fill(ADMIN_EMAIL);
  await page.getByPlaceholder("Digite sua senha").fill(ADMIN_PASSWORD);
  await Promise.all([page.waitForResponse((r) => new URL(r.url()).pathname === "/api-brain/auth/login" && r.request().method() === "POST"), page.getByRole("button", { name: "Entrar" }).click()]);
  await expect.poll(async () => (await page.context().cookies()).some((c) => c.name === "ai_brain_session")).toBe(true);
}
async function persona(page: Page, slug: string) { await page.goto("/"); const select = page.locator("header select"); await expect(select).toBeVisible(); await select.selectOption(slug); await expect(select).toHaveValue(slug); }
async function rows(request: APIRequestContext, ref: number): Promise<MessageRow[]> { const r = await request.get(`/api-brain/messages/by-ref/${ref}?limit=500&validation_scope=all`, { timeout: 120_000 }); ensure(r.ok(), `messages ${ref}: ${r.status()}`); return await r.json() as MessageRow[]; }
async function lead(request: APIRequestContext, ref: number) { const r = await request.get(`/api-brain/leads/${ref}`, { timeout: 120_000 }); ensure(r.ok(), `lead ${ref}: ${r.status()}`); const x = await r.json(); return { id: x.id, ai_enabled: x.ai_enabled, ai_paused: x.ai_paused, updated_at: x.updated_at }; }

function fieldQuestions(graph: any): Record<string, string> {
  const nodes = Array.isArray(graph?.graph_json?.nodes) ? graph.graph_json.nodes : Array.isArray(graph?.nodes) ? graph.nodes : [];
  const root = nodes.find((n: any) => n.node_type === "persona");
  const map = root?.data?.appointment_policy?.field_questions || root?.metadata?.appointment_policy?.field_questions || {};
  const selected = Object.fromEntries(Object.entries(map).filter(([key, value]) => REQUIRED_FIELDS.has(key) && typeof value === "string" && value.trim()));
  ensure(Object.keys(selected).length === REQUIRED_FIELDS.size, "Published Aurora graph lacks a complete field_questions contract");
  return selected as Record<string, string>;
}
function questionField(reply: string, questions: Record<string, string>): string | null {
  const received = normal(reply);
  return Object.entries(questions).find(([, question]) => received.includes(normal(question)))?.[0] || null;
}

test("live full qualification: VZ paused, Aurora asks every graph question once and emits one safe handoff", async ({ browser }) => {
  test.setTimeout(900_000);
  await fs.mkdir(ARTIFACT_DIR, { recursive: true });
  const startedAt = new Date().toISOString();
  const vzContext = await browser.newContext({ baseURL: DASHBOARD_URL });
  const auroraContext = await browser.newContext({ baseURL: DASHBOARD_URL });
  const vz = await vzContext.newPage(); const aurora = await auroraContext.newPage();
  const turns: Turn[] = [];
  try {
    await login(vz); await login(aurora); await persona(vz, "vz-lupas"); await persona(aurora, "aurora");
    const graphResponse = await aurora.request.get("/api-brain/graph-documents/current?persona_slug=aurora", { timeout: 120_000 });
    ensure(graphResponse.ok(), `Aurora graph: ${graphResponse.status()}`);
    const graph = await graphResponse.json(); const questions = fieldQuestions(graph);
    const [vzBefore, auroraBefore, vzLead, auroraLead] = await Promise.all([rows(vz.request, VZ_LEAD_REF), rows(aurora.request, AURORA_LEAD_REF), lead(vz.request, VZ_LEAD_REF), lead(aurora.request, AURORA_LEAD_REF)]);
    expect(vzLead.ai_paused, "VZ transport agent must remain paused").toBe(true);
    expect(auroraLead.ai_paused, "Aurora must be active before qualification").toBe(false);
    const initialReplies = auroraBefore.filter((x) => x.direction === "outbound");
    let currentReply = textOf(initialReplies.at(-1)!);
    let currentField = questionField(currentReply, questions);
    ensure(currentField, `Latest Aurora response is not a published qualification question: ${currentReply}`);
    const sent = new Set<string>();

    while (currentField) {
      ensure(!sent.has(currentField), `Aurora repeated published question for ${currentField}`);
      const answer = ANSWERS[currentField]; ensure(answer, `No test answer for ${currentField}`);
      const beforeVZ = await rows(vz.request, VZ_LEAD_REF); const beforeAurora = await rows(aurora.request, AURORA_LEAD_REF);
      await vz.goto(`/messages/${VZ_LEAD_REF}`); await expect(vz.getByTitle(/IA pausada/)).toBeVisible({ timeout: 120_000 });
      const composer = vz.locator("textarea").last(); await composer.fill(answer);
      const started = Date.now();
      const [sendResponse] = await Promise.all([vz.waitForResponse((r) => new URL(r.url()).pathname === "/api-brain/messages/send" && r.request().method() === "POST", { timeout: 120_000 }), vz.getByRole("button", { name: /^enviar$/i }).click()]);
      expect(sendResponse.ok()).toBe(true); const decision = await sendResponse.json(); expect(decision.deduplicated).toBe(false);
      let source: MessageRow | undefined; let inbound: MessageRow | undefined; let reply: MessageRow | undefined; let delivered: MessageRow | undefined;
      await expect.poll(async () => { const result = (await rows(vz.request, VZ_LEAD_REF)).filter((x) => x.direction === "outbound" && textOf(x) === answer && !beforeVZ.some((b) => b.id === x.id)); source = result[0]; return result.length; }, { timeout: 120_000 }).toBe(1);
      await expect.poll(async () => { const result = (await rows(aurora.request, AURORA_LEAD_REF)).filter((x) => x.direction === "inbound" && textOf(x) === answer && !beforeAurora.some((b) => b.id === x.id)); inbound = result[0]; return result.length; }, { timeout: 150_000, intervals: [1000, 2000, 5000] }).toBe(1);
      await expect.poll(async () => { const result = (await rows(aurora.request, AURORA_LEAD_REF)).filter((x) => x.direction === "outbound" && !beforeAurora.some((b) => b.id === x.id)); reply = result[0]; return result.length; }, { timeout: 180_000, intervals: [2000, 3000, 5000] }).toBe(1);
      const replyText = textOf(reply!); expect(replyText).not.toEqual(""); expect(UNSAFE_REPLY_PATTERN.test(replyText), replyText).toBe(false); expect(replyText.toLowerCase()).not.toContain("vz lupas");
      await expect.poll(async () => { const result = (await rows(vz.request, VZ_LEAD_REF)).filter((x) => x.direction === "inbound" && textOf(x) === replyText && !beforeVZ.some((b) => b.id === x.id)); delivered = result[0]; return result.length; }, { timeout: 150_000, intervals: [1000, 2000, 5000] }).toBe(1);
      await vz.waitForTimeout(10_000);
      const [vzAfter, auroraAfter, vzAfterLead] = await Promise.all([rows(vz.request, VZ_LEAD_REF), rows(aurora.request, AURORA_LEAD_REF), lead(vz.request, VZ_LEAD_REF)]);
      expect(vzAfterLead.ai_paused).toBe(true);
      expect(vzAfter.filter((x) => x.direction === "outbound" && textOf(x) === answer && !beforeVZ.some((b) => b.id === x.id))).toHaveLength(1);
      expect(auroraAfter.filter((x) => x.direction === "inbound" && textOf(x) === answer && !beforeAurora.some((b) => b.id === x.id))).toHaveLength(1);
      expect(auroraAfter.filter((x) => x.direction === "outbound" && !beforeAurora.some((b) => b.id === x.id))).toHaveLength(1);
      expect(vzAfter.filter((x) => x.direction === "inbound" && textOf(x) === replyText && !beforeVZ.some((b) => b.id === x.id))).toHaveLength(1);
      turns.push({ field_key: currentField, answer, source: compact(source!), aurora_inbound: compact(inbound!), aurora_reply: compact(reply!), vz_inbound: compact(delivered!), latency_ms: Date.now() - started });
      sent.add(currentField); currentReply = replyText; currentField = questionField(currentReply, questions);
      if (!currentField) break;
    }
    expect([...sent].sort()).toEqual([...REQUIRED_FIELDS].sort());
    expect(normal(currentReply)).toContain("confirm");
    await vz.goto(`/messages/${VZ_LEAD_REF}`); await expect(vz.getByText(currentReply, { exact: true }).last()).toBeVisible({ timeout: 120_000 }); await vz.screenshot({ path: path.join(ARTIFACT_DIR, "vz-full-qualification.png"), fullPage: true });
    await aurora.goto(`/messages/${AURORA_LEAD_REF}`); await expect(aurora.getByText(currentReply, { exact: true }).last()).toBeVisible({ timeout: 120_000 }); await aurora.screenshot({ path: path.join(ARTIFACT_DIR, "aurora-full-qualification.png"), fullPage: true });
    await fs.writeFile(path.join(ARTIFACT_DIR, "full-qualification-evidence.json"), `${JSON.stringify({ test: "Aurora GraphRAG full qualification via VZ Lupas paused transport", started_at: startedAt, finished_at: new Date().toISOString(), graph: { version: graph.version, checksum: graph.checksum }, required_fields: [...REQUIRED_FIELDS], published_questions: questions, turns, final_handoff_reply: currentReply, score_inputs: { fields_answered: sent.size, exactly_once_each_turn: true, vz_ai_remained_paused: true, unsafe_confirmation: false } }, null, 2)}\n`);
  } finally { await vzContext.close(); await auroraContext.close(); }
});
