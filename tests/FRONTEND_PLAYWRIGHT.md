# Frontend Playwright — Knowledge Graph plan

Status: **specs prontos, runner não instalado** no `dashboard/`. O esqueleto abaixo
roda assim que o Playwright for adicionado ao dashboard. Razão de não instalar
agora: deixar a decisão de adicionar dependências ao Next no commit que efetivamente
ligar a CI.

## Setup (uma vez)

```powershell
cd dashboard
npm i -D @playwright/test
npx playwright install chromium
```

Criar `dashboard/playwright.config.ts`:

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  use: {
    baseURL: process.env.DASHBOARD_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    // Backend precisa estar rodando separado (uvicorn).
    // O dev server do Next é assumido como já no ar.
    command: "echo dashboard expected on :3000",
    url: "http://localhost:3000",
    reuseExistingServer: true,
  },
});
```

## Specs (a criar em `dashboard/tests/e2e/`)

### `messages-knowledge.spec.ts`

```ts
import { test, expect } from "@playwright/test";

test("knowledge sidebar surfaces Modal + Inverno-2026 + assets", async ({ page }) => {
  await page.goto("/messages");
  // selecionar o lead criado pelo integration_chat_context
  await page.getByText(/graph_modal_test|Modal/i).first().click();

  const sidebar = page.locator("aside:has-text('Conhecimento')");
  await expect(sidebar).toBeVisible();
  await expect(sidebar.getByText("Produtos")).toBeVisible();
  await expect(sidebar.getByText("Modal", { exact: false })).toBeVisible();
  await expect(sidebar.getByText("Inverno 2026")).toBeVisible();
  await expect(sidebar.locator("text=/Assets/")).toBeVisible();

  // Clicar no primeiro asset e validar que /knowledge/file?path=… responde 200.
  const link = sidebar.locator("a[href*='/knowledge/file?path=']").first();
  const href = await link.getAttribute("href");
  expect(href).toBeTruthy();
  const resp = await page.request.get(href!);
  expect(resp.status()).toBe(200);
});
```

### `graph-page.spec.ts`

```ts
import { test, expect } from "@playwright/test";

test("graph view shows persona → product → campaign → asset chain", async ({ page }) => {
  await page.goto("/knowledge/graph?persona_slug=tock-fatal");
  // ReactFlow node label
  await expect(page.locator("text=Modal").first()).toBeVisible();
  await expect(page.locator("text=Inverno 2026").first()).toBeVisible();
  await expect(page.locator("text=Hero Modal Inverno").first()).toBeVisible();
});
```

### `assets-page.spec.ts`

```ts
import { test, expect } from "@playwright/test";

test("assets list contains Modal hero + banner", async ({ page }) => {
  await page.goto("/knowledge/assets?persona=tock-fatal");
  await expect(page.getByText(/Hero Modal Inverno/i)).toBeVisible();
  await expect(page.getByText(/Banner Story Modal Inverno/i)).toBeVisible();
  // pelo menos um <img> ou ícone de mídia deve estar presente
  const tiles = page.locator("[data-asset-tile], img");
  await expect(tiles.first()).toBeVisible();
});
```

## Como rodar

Pré-condição: backend em `:8000`, dashboard em `:3000`, e
`python tests/integration_chat_context.py` já tendo passado (para garantir
que o vault de fixtures foi sincronizado e o lead existe).

```powershell
cd dashboard
npx playwright test
```
