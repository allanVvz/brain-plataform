import { expect, test, type Browser, type BrowserContext, type Page } from "playwright/test";

test.describe.configure({ mode: "serial" });

const BAITA = "baita-conveniencia";
const AURORA = "aurora";
const DASHBOARD_URL = required("E2E_DASHBOARD_URL");
const ADMIN_EMAIL = required("E2E_ADMIN_EMAIL");
const ADMIN_PASSWORD = required("E2E_ADMIN_PASSWORD");
const MANAGER_EMAIL = required("E2E_MANAGER_EMAIL");
const OPERATOR_EMAIL = required("E2E_OPERATOR_EMAIL");
const VIEWER_EMAIL = required("E2E_VIEWER_EMAIL");
const FINAL_PASSWORD = required("E2E_FINAL_PASSWORD");
const API_TIMEOUT = 120_000;

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`Missing required E2E variable: ${name}`);
  return value;
}

function ensure(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

const CLIENT_FORBIDDEN_API_PATHS = [
  /^\/api-brain\/health\/score$/,
  /^\/api-brain\/insights(?:\/|$)/,
  /^\/api-brain\/leads(?:\/|$)/,
  /^\/api-brain\/pipeline\/(?:status|metrics|events)(?:\/|$)/,
  /^\/api-brain\/knowledge(?:\/|$)/,
];

function auditPage(page: Page) {
  const failures: string[] = [];
  const forbiddenAdminRequests: string[] = [];
  let enforceConsole = false;
  page.on("pageerror", (error) => failures.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (enforceConsole && message.type() === "error") {
      failures.push(`console: ${message.text()}`);
    }
  });
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (CLIENT_FORBIDDEN_API_PATHS.some((pattern) => pattern.test(pathname))) {
      forbiddenAdminRequests.push(pathname);
    }
  });
  page.on("response", (response) => {
    const pathname = new URL(response.url()).pathname;
    const expectedAnonymousProbe = pathname === "/api-brain/auth/me" && response.status() === 401;
    if (
      pathname.startsWith("/api-brain/")
      && response.status() >= 400
      && !expectedAnonymousProbe
    ) {
      failures.push(`http ${response.status()}: ${pathname}`);
    }
  });
  return {
    failures,
    forbiddenAdminRequests,
    startAuthenticatedAudit: () => {
      enforceConsole = true;
    },
  };
}

async function login(page: Page, email: string, password: string, requested = "/login") {
  await page.goto(requested);
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
  const sessionCheck = await page.context().request.get("/api-brain/auth/me", {
    timeout: API_TIMEOUT,
  });
  if (!sessionCheck.ok()) {
    const cookies = (await page.context().cookies())
      .filter((cookie) => cookie.name === "ai_brain_session")
      .map((cookie) => ({
        domain: cookie.domain,
        path: cookie.path,
        secure: cookie.secure,
        sameSite: cookie.sameSite,
      }));
    throw new Error(
      `Session cookie was stored but /auth/me returned ${sessionCheck.status()}; `
      + `cookie metadata=${JSON.stringify(cookies)} body=${await sessionCheck.text()}`,
    );
  }
}

async function createMember(
  context: BrowserContext,
  email: string,
  role: "user" | "operator" | "viewer",
) {
  const response = await context.request.post(`/api-brain/access/personas/${BAITA}/members`, {
    timeout: API_TIMEOUT,
    data: {
      email,
      role,
      can_view: true,
      can_edit: role !== "viewer",
      can_manage: role === "user",
    },
  });
  ensure(response.status() === 201, `Could not create ${role} fixture: ${response.status()}`);
  const body = await response.json();
  ensure(typeof body.temporary_password === "string", "Temporary password was not returned once.");
  return body.temporary_password as string;
}

async function changeInitialPassword(
  context: BrowserContext,
  email: string,
  temporary: string,
  suffix: string,
) {
  const auth = await context.request.post("/api-brain/auth/login", {
    timeout: API_TIMEOUT,
    data: { identifier: email, password: temporary, remember: false },
  });
  ensure(auth.ok(), `${email} could not authenticate.`);
  const password = `${FINAL_PASSWORD}${suffix}`;
  const changed = await context.request.post("/api-brain/auth/change-password", {
    timeout: API_TIMEOUT,
    data: { current_password: temporary, new_password: password },
  });
  ensure(changed.ok(), `${email} could not change initial password.`);
  return password;
}

async function assertFourRoutes(page: Page, slug: string) {
  for (const route of ["mensagens", "leads", "pipeline", "configuracoes"]) {
    await page.goto(`/clientes/${slug}/${route}`);
    await expect(page).toHaveURL(new RegExp(`/clientes/${slug}/${route}$`));
    await expect(page.locator("main")).toBeVisible();
  }
  const desktopNav = page.locator("aside nav a");
  if (await desktopNav.count()) {
    expect((await desktopNav.allTextContents()).map((label) => label.trim()))
      .toEqual(["Mensagens", "Leads", "Pipeline", "Configurações"]);
  }
}

test("Baita mantém Evolution intacto e o portal usa somente APIs cliente", async ({ browser }) => {
  const admin = await browser.newContext({ baseURL: DASHBOARD_URL });
  const adminPage = await admin.newPage();
  const adminAudit = auditPage(adminPage);
  await login(adminPage, ADMIN_EMAIL, ADMIN_PASSWORD);
  adminAudit.startAuthenticatedAudit();
  await expect(adminPage).toHaveURL(new RegExp(`${DASHBOARD_URL}/?$`), {
    timeout: 120_000,
  });
  await expect.poll(() => adminAudit.forbiddenAdminRequests.length).toBeGreaterThan(0);
  const managerTemp = await createMember(admin, MANAGER_EMAIL, "user");
  const operatorTemp = await createMember(admin, OPERATOR_EMAIL, "operator");
  const viewerTemp = await createMember(admin, VIEWER_EMAIL, "viewer");
  expect(adminAudit.failures).toEqual([]);
  await admin.close();

  const manager = await browser.newContext({ baseURL: DASHBOARD_URL });
  const managerPassword = await changeInitialPassword(manager, MANAGER_EMAIL, managerTemp, "-Manager!9");
  await manager.clearCookies();
  const page = await manager.newPage();
  const managerAudit = auditPage(page);
  await login(page, MANAGER_EMAIL, managerPassword, "/leads");
  managerAudit.startAuthenticatedAudit();
  await expect(page).toHaveURL(new RegExp(`/clientes/${BAITA}/mensagens$`));
  expect(managerAudit.forbiddenAdminRequests).toEqual([]);
  await assertFourRoutes(page, BAITA);

  await page.goto(`/clientes/${BAITA}/whatsapp`);
  await expect(page).toHaveURL(
    new RegExp(`/clientes/${BAITA}/configuracoes$`),
    { timeout: 120_000 },
  );
  await page.goto(`/clientes/${BAITA}/minha-conta`);
  await expect(page).toHaveURL(
    new RegExp(`/clientes/${BAITA}/configuracoes$`),
    { timeout: 120_000 },
  );

  const channel = await manager.request.get(
    `/api-brain/portal/personas/${BAITA}/channels/whatsapp`,
    { timeout: API_TIMEOUT },
  );
  ensure(channel.ok(), "Baita channel state is unavailable.");
  const channelState = await channel.json();
  ensure(channelState.configured === true, "Existing Baita binding was lost.");
  ensure(channelState.provider === "evolution_baileys", "Baita provider changed during the test.");
  ensure(channelState.status === "connected", "Baita connected state changed during the test.");
  ensure(
    (await manager.request.get(
      `/api-brain/portal/personas/${AURORA}/channels/whatsapp`,
      { timeout: API_TIMEOUT },
    )).status() === 403,
    "Baita manager escaped persona isolation.",
  );
  ensure(
    (await manager.request.get(
      "/api-brain/pipeline/status",
      { timeout: API_TIMEOUT },
    )).status() === 403,
    "Client reached administrative pipeline API.",
  );
  expect(managerAudit.forbiddenAdminRequests).toEqual([]);
  expect(managerAudit.failures).toEqual([]);
  await manager.close();

  for (const [email, temporary, suffix] of [
    [OPERATOR_EMAIL, operatorTemp, "-Operator!9"],
    [VIEWER_EMAIL, viewerTemp, "-Viewer!9"],
  ] as const) {
    const context = await browser.newContext({ baseURL: DASHBOARD_URL });
    await changeInitialPassword(context, email, temporary, suffix);
    const memberPage = await context.newPage();
    const memberAudit = auditPage(memberPage);
    await memberPage.goto(`/clientes/${BAITA}/configuracoes`);
    memberAudit.startAuthenticatedAudit();
    await expect(memberPage).toHaveURL(new RegExp(`/clientes/${BAITA}/configuracoes$`));
    expect(memberAudit.forbiddenAdminRequests).toEqual([]);
    expect(memberAudit.failures).toEqual([]);
    const provider = await context.request.post(
      `/api-brain/portal/personas/${BAITA}/channels/whatsapp/provider`,
      {
        timeout: API_TIMEOUT,
        data: { provider: "evolution_baileys", confirmed: true },
      },
    );
    ensure(provider.status() === 403, `${email} unexpectedly changed the provider.`);
    await context.close();
  }
});

test("Aurora apresenta onboarding útil em desktop e mobile", async ({ browser }) => {
  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    const context = await browser.newContext({ baseURL: DASHBOARD_URL, viewport });
    const page = await context.newPage();
    const audit = auditPage(page);
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD, `/clientes/${AURORA}/mensagens`);
    audit.startAuthenticatedAudit();
    await assertFourRoutes(page, AURORA);
    await page.goto(`/clientes/${AURORA}/mensagens`);
    await expect(page.getByText("Conecte seu canal para começar")).toBeVisible();
    expect(await page.evaluate(() =>
      document.documentElement.scrollWidth > document.documentElement.clientWidth + 1
    )).toBe(false);
    if (viewport.width < 1024) {
      const labels = await page
        .locator("nav[aria-label='Navegação do portal']")
        .last()
        .locator("a")
        .allTextContents();
      expect(labels.map((label) => label.trim()))
        .toEqual(["Mensagens", "Leads", "Pipeline", "Configurações"]);
    }
    expect(audit.forbiddenAdminRequests).toEqual([]);
    expect(audit.failures).toEqual([]);
    await context.close();
  }
});
