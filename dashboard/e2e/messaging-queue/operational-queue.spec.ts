import { expect, test, type Page, type Route } from "playwright/test";

// Browser-level contract for the operational queue (/disparos?tab=fila).
//
// Every backend call is intercepted, so this suite never reaches a backend,
// a worker or WhatsApp: it proves what the browser actually renders and
// sends. The vitest suite (__tests__/actionable-queue.test.tsx) covers the
// same component in jsdom; this one additionally proves the real page shell
// (session resolution, persona scoping, the collapsible <details> history)
// and asserts the exact HTTP payload each click puts on the wire.

const BASE_URL = process.env.E2E_DASHBOARD_URL || "http://127.0.0.1:3100";
const PERSONA_ID = "11111111-1111-1111-1111-111111111111";
const PERSONA_SLUG = "fixture-persona";

type QueueCall = { action: string; body: Record<string, unknown> };

const CUSTOMER_MESSAGE = "Preciso saber quando vocês atendem";
const CUSTOMER_MESSAGE_AT = "2026-09-18T10:00:00Z";
const AGENT_MESSAGE = "Como posso ajudar?";
const AGENT_MESSAGE_AT = "2026-09-18T09:59:00Z";

function demand(overrides: Record<string, unknown> = {}) {
  return {
    id: "demand-1",
    demand_id: "group-1",
    lead_ref: 7,
    persona_id: PERSONA_ID,
    persona: { name: "Persona Fixture", slug: PERSONA_SLUG },
    lead: { nome: "Cliente real" },
    origin: "conversation",
    status: "preview_ready",
    queue_state: "preview_ready",
    created_at: CUSTOMER_MESSAGE_AT,
    available_at: CUSTOMER_MESSAGE_AT,
    customer_message: CUSTOMER_MESSAGE,
    customer_message_at: CUSTOMER_MESSAGE_AT,
    last_agent_message: AGENT_MESSAGE,
    last_agent_message_at: AGENT_MESSAGE_AT,
    recent_context: [
      { id: "i-older", direction: "inbound", content: "Oi, bom dia", created_at: "2026-09-18T08:00:00Z" },
      { id: "i1", direction: "inbound", content: CUSTOMER_MESSAGE, created_at: CUSTOMER_MESSAGE_AT },
      { id: "o1", direction: "outbound", content: AGENT_MESSAGE, created_at: AGENT_MESSAGE_AT },
    ],
    outbound_messages: [{
      buffer_id: "message-1", sequence: 1, kind: "response", text: "Resposta pronta",
      proof_id: "3f8a1c22-0000-4000-8000-000000000001", status: "preview_ready",
      can_retry: true, can_send: true,
    }],
    ...overrides,
  };
}

/** Intercepts the session and the queue projection, and records each action call. */
async function mockQueue(page: Page, options: {
  items: Array<Record<string, unknown>>;
  actionResponse?: (call: QueueCall) => { status?: number; body: unknown };
}) {
  const calls: QueueCall[] = [];

  // Playwright gives priority to the LAST matching handler, so this inert
  // catch-all is registered first and every specific mock below overrides it.
  // Nothing in this suite may reach a real backend.
  await page.route("**/api-brain/**", (route: Route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({}),
  }));

  await page.route("**/api-brain/auth/me", (route: Route) => route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({
      user: { id: "user-1", email: "operador@empresa.com", role: "admin", account_type: "internal" },
      account_type: "internal",
      personas: [{ id: PERSONA_ID, slug: PERSONA_SLUG, name: "Persona Fixture" }],
    }),
  }));

  await page.route("**/api-brain/messaging/queue?**", (route: Route) => route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ items: options.items, next_offset: null }),
  }));

  await page.route("**/api-brain/messaging/queue/*", (route: Route) => {
    const action = new URL(route.request().url()).pathname.split("/").pop() || "";
    const body = JSON.parse(route.request().postData() || "{}");
    const call: QueueCall = { action, body };
    calls.push(call);
    const reply = options.actionResponse?.(call) || { body: { items: [{ buffer_id: body.buffer_ids?.[0], result: "agendado" }] } };
    return route.fulfill({
      status: reply.status ?? 200, contentType: "application/json",
      body: JSON.stringify(reply.body),
    });
  });

  return calls;
}

async function openQueue(page: Page) {
  // proxy.ts redirects every non-/login route without this cookie. Its value
  // is never validated in the browser -- the backend does that, and here the
  // backend is intercepted -- so a placeholder is enough to reach the page.
  await page.context().addCookies([{
    name: "ai_brain_session", value: "e2e-intercepted-session", url: BASE_URL,
  }]);
  await page.goto(`/disparos?persona=${PERSONA_SLUG}`);
  await expect(page.getByRole("columnheader", { name: "Contexto da conversa" })).toBeVisible();
}

test.describe("operational queue", () => {
  test("renders every operator column and never uses the inbound text as the preview", async ({ page }) => {
    await mockQueue(page, { items: [demand()] });
    await openQueue(page);

    for (const column of ["Contexto da conversa", "Prévia atual", "Lead", "Origem", "Horário", "Estado", "Ações"]) {
      await expect(page.getByRole("columnheader", { name: column })).toBeVisible();
    }
    await expect(page.getByText(CUSTOMER_MESSAGE)).toBeVisible();
    await expect(page.getByText("Última resposta efetiva do agente")).toBeVisible();

    const preview = page.locator("td").nth(1);
    await expect(preview).toContainText("Resposta pronta");
    await expect(preview).not.toContainText(CUSTOMER_MESSAGE);
    await expect(preview).toContainText("proof 3f8a1c22");
  });

  test("expands the history without repeating the two headline messages", async ({ page }) => {
    await mockQueue(page, { items: [demand()] });
    await openQueue(page);

    // 3 context rows, 2 of which are already the headline -> only 1 remains.
    const history = page.getByText("Histórico recente (1)");
    await expect(history).toBeVisible();
    await history.click();
    await expect(page.getByText("Oi, bom dia")).toBeVisible();
    const historyBlock = page.locator("details");
    await expect(historyBlock).toContainText("Cliente ·");
    await expect(historyBlock).not.toContainText(AGENT_MESSAGE);
  });

  test("shows three demands for one lead without a local two-row cap", async ({ page }) => {
    await mockQueue(page, {
      items: [1, 2, 3].map((index) => demand({
        id: `demand-${index}`, demand_id: `group-${index}`,
        customer_message: `Demanda ${index}`,
        outbound_messages: [{
          buffer_id: `message-${index}`, sequence: 1, kind: "response", text: `Resposta ${index}`,
          proof_id: null, status: "preview_ready", can_retry: true, can_send: true,
        }],
      })),
    });
    await openQueue(page);

    await expect(page.getByRole("row")).toHaveCount(4); // header + 3 demands
    for (const index of [1, 2, 3]) await expect(page.getByText(`Demanda ${index}`)).toBeVisible();
  });

  test("renders two messages of one demand and keeps message 2 blocked with its exact reason", async ({ page }) => {
    await mockQueue(page, {
      items: [demand({
        outbound_messages: [
          { buffer_id: "first", sequence: 1, kind: "apology", text: "Aviso de horário", proof_id: "p1", status: "preview_ready", can_retry: true, can_send: true },
          { buffer_id: "second", sequence: 2, kind: "context", text: "Resposta contextual", proof_id: "p2", status: "preview_ready", can_retry: true, can_send: false, send_reason: "A mensagem 1 ainda não foi confirmada" },
        ],
      })],
    });
    await openQueue(page);

    await expect(page.getByText("Mensagem 1 de 2")).toBeVisible();
    await expect(page.getByText("Mensagem 2 de 2")).toBeVisible();
    await expect(page.getByRole("button", { name: "Enviar mensagem 2" })).toBeDisabled();
    // A blocked action stays visible with its exact reason, never hidden.
    await expect(page.getByText("Enviar: A mensagem 1 ainda não foi confirmada")).toBeVisible();
  });

  test("retries only the selected message and sends an idempotency key", async ({ page }) => {
    const calls = await mockQueue(page, { items: [demand()] });
    await openQueue(page);

    await page.getByRole("button", { name: "Retry mensagem 1" }).click();
    await expect.poll(() => calls.length).toBe(1);
    expect(calls[0].action).toBe("regenerate-preview");
    expect(calls[0].body.buffer_ids).toEqual(["message-1"]);
    expect(String(calls[0].body.idempotency_key || "")).not.toHaveLength(0);
    expect(calls.some((call) => call.action === "send-preview")).toBe(false);
  });

  test("generates an inert preview from a blocked inbound only after explicit confirmation", async ({ page }) => {
    const calls = await mockQueue(page, {
      items: [demand({
        queue_state: "blocked",
        outbound_messages: [{
          buffer_id: "canonical-inbound", sequence: 1, kind: "response", status: "blocked",
          can_retry: false, retry_reason: "Demanda sem falha técnica recuperável",
          can_generate_preview: true, can_send: false, send_reason: "Gere uma resposta válida antes de enviar",
        }],
      })],
      actionResponse: () => ({ body: { items: [{ buffer_id: "canonical-inbound", result: "recuperando_tentativa_antiga" }] } }),
    });
    await openQueue(page);

    page.once("dialog", (dialog) => {
      expect(dialog.message()).toContain("mensagem original");
      void dialog.accept();
    });
    await page.getByRole("button", { name: "Gerar prévia da mensagem 1" }).click();

    await expect.poll(() => calls.length).toBe(1);
    expect(calls[0].action).toBe("operator-preview");
    // A recovered stale claim is reported as its own operational state.
    await expect(page.getByRole("status")).toContainText("Recuperando tentativa antiga");
  });

  test("sends one message per click and suppresses the double click", async ({ page }) => {
    const calls = await mockQueue(page, { items: [demand()] });
    await openQueue(page);

    const button = page.getByRole("button", { name: "Enviar mensagem 1" });
    await button.click();
    await button.click({ force: true, noWaitAfter: true }).catch(() => undefined);
    await expect.poll(() => calls.filter((call) => call.action === "send-preview").length).toBe(1);
  });

  test("reports a conflict as a stale-context instruction, never as backend unavailable", async ({ page }) => {
    await mockQueue(page, {
      items: [demand()],
      actionResponse: () => ({ status: 409, body: { detail: "inbound superseded by a newer customer message" } }),
    });
    await openQueue(page);

    await page.getByRole("button", { name: "Enviar mensagem 1" }).click();
    // p[role=alert], not getByRole("alert"): Next.js keeps its own empty
    // route-announcer node with the same role on every page.
    const alert = page.locator('p[role="alert"]');
    await expect(alert).toContainText("atualize a fila");
    await expect(alert).toContainText("request_id");
    await expect(alert).not.toContainText("Backend indisponivel");
  });

  test("reports an authorization failure as a permission problem, never as an outage", async ({ page }) => {
    await mockQueue(page, {
      items: [demand()],
      actionResponse: () => ({ status: 403, body: { detail: "Acesso negado." } }),
    });
    await openQueue(page);

    await page.getByRole("button", { name: "Enviar mensagem 1" }).click();
    const alert = page.locator('p[role="alert"]');
    await expect(alert).toContainText("Sem permissão");
    await expect(alert).not.toContainText("indisponível");
  });

  test("labels a preview blocked by an invalid proof instead of calling it ready", async ({ page }) => {
    await mockQueue(page, {
      items: [demand({
        outbound_messages: [{
          buffer_id: "message-1", sequence: 1, kind: "response", text: "Resposta pronta",
          proof_id: null, status: "preview_ready", can_retry: true,
          can_send: false, send_reason: "Proof ou publicação inválida",
        }],
      })],
    });
    await openQueue(page);

    await expect(page.getByText("Proof inválida").first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Enviar mensagem 1" })).toBeDisabled();
  });
});
