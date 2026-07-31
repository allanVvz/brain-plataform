import { expect, test, type Page } from "playwright/test";

// Two-tab E2E: exercises the wa-validator "run-direct" contract for both
// personas (Aurora and Baita), across both conversation modes
// (deterministic and n8n), by driving two browser tabs concurrently.
//
// This mirrors the canonical "Fluxo direto de validacao sem WhatsApp"
// documented in PROJECT_REQUIREMENTS.md §11.5, and the "Aba de validacao
// WhatsApp" vs "Aba /messages" distinction described there — this spec is
// specifically the validation-tab side.
//
// Requires: an environment where BOTH personas already have an active,
// connected transport binding (deterministic and n8n_agents workflow
// bindings). wa-validator's run-direct enqueues a real outbound message
// through commit(), so a synthetic lead without real provider credentials
// will fail at the send step even though the conversation_v1 decide/commit
// logic itself is correct — see docs/sdr/aurora/rules/no-auto-confirm.md
// for why that check exists. Point E2E_DASHBOARD_URL at an environment with
// real bindings for both personas before relying on this test.

test.describe.configure({ mode: "serial" });

const AURORA = "aurora";
const BAITA = "baita-conveniencia";
const AURORA_FLOW_LABEL = "SDR agêntico de agendamento (Aurora)";
const BAITA_FLOW_LABEL = "Fluxo básico";
const DASHBOARD_URL = required("E2E_DASHBOARD_URL");
const ADMIN_EMAIL = required("E2E_ADMIN_EMAIL");
const ADMIN_PASSWORD = required("E2E_ADMIN_PASSWORD");
const API_TIMEOUT = 120_000;
const RUN_TIMEOUT = 180_000;

// Currency/confirmation patterns the reply must never contain — mirrors the
// server-side guard-rail in conversation_runtime._reply_confirms_price_or_schedule.
const UNSAFE_REPLY_PATTERN =
  /(confirmad[oa]|confirmo\b|fechad[oa]|reservad[oa]|agendad[oa]\s+para|marcad[oa]\s+para).{0,80}(r\$\s?\d|\b\d{1,2}[:h]\d{0,2}\b|\b\d{1,2}\/\d{1,2}\b)/i;

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Missing required E2E variable: ${name}`);
  return value;
}

function ensure(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

async function login(page: Page, email: string, password: string) {
  await page.goto("/login");
  if (!page.url().includes("/login")) return;
  await page.getByPlaceholder("operador@empresa.com").fill(email);
  await page.getByPlaceholder("Digite sua senha").fill(password);
  await Promise.all([
    page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api-brain/auth/login"
        && response.request().method() === "POST",
      { timeout: API_TIMEOUT },
    ),
    page.getByRole("button", { name: "Entrar" }).click(),
  ]);
  await expect.poll(async () =>
    (await page.context().cookies()).some((cookie) => cookie.name === "ai_brain_session")
  ).toBe(true);
}

async function getProcessMode(page: Page, slug: string): Promise<string> {
  const response = await page.request.get(`/api-brain/personas/${slug}/routing`, {
    timeout: API_TIMEOUT,
  });
  ensure(response.ok(), `Failed to read routing for ${slug}: ${response.status()}`);
  const body = await response.json();
  return String(body.process_mode || "internal");
}

async function setProcessMode(page: Page, slug: string, mode: "internal" | "n8n") {
  const response = await page.request.patch(`/api-brain/personas/${slug}/routing`, {
    timeout: API_TIMEOUT,
    data: { process_mode: mode },
  });
  ensure(response.ok(), `Failed to set ${slug} process_mode=${mode}: ${response.status()}`);
}

type FlowResult = { status: string; turns: Array<{ role: string; text: string }> };

// Drives the left "Configurar Teste" form + "Executar Direto (sem WA)"
// button and reads the resulting conversation feed. See
// dashboard/app/wa-validator/page.tsx for the exact markup this mirrors.
async function runValidatorFlow(
  page: Page,
  botNamePattern: RegExp,
  flowLabel: string,
): Promise<FlowResult> {
  await page.goto("/wa-validator");
  await page.getByRole("button", { name: botNamePattern }).first().click();
  // "Fluxo a Testar" is the first <select> on the page; "Classificador" is
  // the second and is always disabled.
  await page.locator("select").first().selectOption({ label: flowLabel });
  await Promise.all([
    page.waitForResponse(
      (response) => new URL(response.url()).pathname === "/api-brain/wa-validator/generate-script",
      { timeout: API_TIMEOUT },
    ),
    page.getByRole("button", { name: "Gerar Script de Teste" }).click(),
  ]);
  await expect(page.getByRole("button", { name: /Executar Direto/ })).toBeEnabled({
    timeout: API_TIMEOUT,
  });
  await page.getByRole("button", { name: /Executar Direto/ }).click();
  await expect
    .poll(
      async () => (await page.locator("text=/^(done|error)$/").count()) > 0,
      { timeout: RUN_TIMEOUT },
    )
    .toBe(true);
  const status = (await page.locator("text=/^(done|error)$/").first().innerText()).trim();
  const turnLocators = await page.locator('[class*="rounded-xl px-3 py-2 text-sm"]').all();
  const turns: Array<{ role: string; text: string }> = [];
  for (const turn of turnLocators) {
    const text = (await turn.innerText()).trim();
    if (!text) continue;
    turns.push({ role: text.includes("Validador IA") ? "validator" : "bot", text });
  }
  return { status, turns };
}

test("Aurora e Baita respondem via wa-validator em 2 abas, determinístico e n8n", async ({ browser }) => {
  const setup = await browser.newContext({ baseURL: DASHBOARD_URL });
  const setupPage = await setup.newPage();
  await login(setupPage, ADMIN_EMAIL, ADMIN_PASSWORD);

  const originalAuroraMode = await getProcessMode(setupPage, AURORA);
  const originalBaitaMode = await getProcessMode(setupPage, BAITA);

  const auroraContext = await browser.newContext({ baseURL: DASHBOARD_URL });
  const baitaContext = await browser.newContext({ baseURL: DASHBOARD_URL });
  const auroraTab = await auroraContext.newPage();
  const baitaTab = await baitaContext.newPage();
  await login(auroraTab, ADMIN_EMAIL, ADMIN_PASSWORD);
  await login(baitaTab, ADMIN_EMAIL, ADMIN_PASSWORD);

  try {
    for (const mode of ["internal", "n8n"] as const) {
      await setProcessMode(setupPage, AURORA, mode);
      await setProcessMode(setupPage, BAITA, mode);

      const [auroraResult, baitaResult] = await Promise.all([
        runValidatorFlow(auroraTab, /Aurora/i, AURORA_FLOW_LABEL),
        runValidatorFlow(baitaTab, /Baita/i, BAITA_FLOW_LABEL),
      ]);

      expect(auroraResult.status, `Aurora (${mode}) session status`).toBe("done");
      expect(baitaResult.status, `Baita (${mode}) session status`).toBe("done");

      const auroraBotTurns = auroraResult.turns.filter((t) => t.role === "bot");
      expect(auroraBotTurns.length, `Aurora (${mode}) produced bot replies`).toBeGreaterThan(0);
      for (const turn of auroraBotTurns) {
        expect(
          UNSAFE_REPLY_PATTERN.test(turn.text),
          `Aurora (${mode}) must never confirm price or schedule: "${turn.text}"`,
        ).toBe(false);
      }

      const baitaBotTurns = baitaResult.turns.filter((t) => t.role === "bot");
      expect(baitaBotTurns.length, `Baita (${mode}) produced bot replies`).toBeGreaterThan(0);
    }
  } finally {
    await setProcessMode(setupPage, AURORA, originalAuroraMode as "internal" | "n8n");
    await setProcessMode(setupPage, BAITA, originalBaitaMode as "internal" | "n8n");
    await setup.close();
    await auroraContext.close();
    await baitaContext.close();
  }
});
