import { createHmac, randomBytes } from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const dashboardDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(dashboardDir, "..");
const envFile = path.join(repoRoot, ".env.compose");
const stateFile = path.join(repoRoot, ".demo-baita-state.json");
const emailArg = process.argv.findIndex((value) => value === "--email");
const email = emailArg >= 0 ? String(process.argv[emailArg + 1] || "").trim().toLowerCase() : "";
let dashboardProcess;
let browser;
let runtimeEnv;

function parseEnv(contents) {
  const result = {};
  for (const raw of contents.split(/\r?\n/)) {
    const match = raw.trim().match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!match) continue;
    let value = match[2].trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
    result[match[1]] = value;
  }
  return result;
}

function deriveRuntimeSecret(rootSecret, label, bytes = 32) {
  if (!rootSecret || rootSecret.length < 32) {
    throw new Error("AI_BRAIN_AUTH_SECRET forte é obrigatório para derivar os segredos locais da Evolution.");
  }
  return createHmac("sha256", rootSecret)
    .update(`brain-local-evolution:${label}`)
    .digest()
    .subarray(0, bytes)
    .toString("base64url");
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || repoRoot,
    env: options.env || process.env,
    input: options.input,
    encoding: "utf8",
    stdio: options.stdio || "pipe",
    timeout: options.timeout || 120_000,
    windowsHide: true,
    maxBuffer: 10 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(String(result.stderr || result.stdout || `${command} failed`).trim().slice(0, 1200));
  return String(result.stdout || "").trim();
}

function compose(args, options = {}) {
  return run("docker", ["compose", "--env-file", envFile, "--profile", "evolution", ...args], {
    ...options,
    env: options.env || runtimeEnv || process.env,
  });
}

function ensureEvolutionCaBundle() {
  const runtimeDir = path.join(repoRoot, ".runtime", "evolution");
  const bundlePath = path.join(runtimeDir, "ca.pem");
  const result = spawnSync(process.execPath, [
    "--use-system-ca",
    "-e",
    "const tls=require('node:tls');process.stdout.write(tls.getCACertificates('system').join('\\n'))",
  ], { encoding: "utf8", windowsHide: true, timeout: 30_000 });
  if (result.status !== 0 || !String(result.stdout || "").includes("BEGIN CERTIFICATE")) {
    throw new Error("Não foi possível exportar as CAs confiáveis do host para a Evolution.");
  }
  fs.mkdirSync(runtimeDir, { recursive: true });
  fs.writeFileSync(bundlePath, result.stdout, { mode: 0o600 });
  return bundlePath.replaceAll("\\", "/");
}

async function waitFor(url, timeout = 300_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(4_000) });
      if (response.ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
  throw new Error(`Timeout waiting for ${url}`);
}

async function waitForEvolution(timeout = 300_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      compose([
        "exec", "-T", "evolution-api", "node", "-e",
        "fetch('http://localhost:8080').then(r=>process.exit(r.status<500?0:1)).catch(()=>process.exit(1))",
      ], { timeout: 10_000 });
      return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
  throw new Error("Timeout aguardando a Evolution API ficar saudável.");
}

async function api(pathname, cookie, options = {}) {
  let lastError;
  for (let attempt = 0; attempt < 8; attempt += 1) {
    try {
      const response = await fetch(`http://localhost:8080${pathname}`, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          ...(cookie ? { Cookie: cookie } : {}),
          ...(options.headers || {}),
        },
      });
      const body = await response.json().catch(() => ({}));
      if (response.ok) return { response, body };
      if (response.status < 500) {
        throw new Error(`HTTP ${response.status} ${pathname}: ${body.detail || "request failed"}`);
      }
      lastError = new Error(`HTTP ${response.status} ${pathname}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 1_500));
  }
  throw lastError || new Error(`Request failed: ${pathname}`);
}

async function ensureDashboard(runtimeEnv) {
  try {
    const response = await fetch("http://localhost:3000/login", { signal: AbortSignal.timeout(2_000) });
    if (response.ok) return;
  } catch {}
  dashboardProcess = spawn(process.execPath, [path.join(dashboardDir, "node_modules", "next", "dist", "bin", "next"), "dev", "-p", "3000"], {
    cwd: dashboardDir,
    env: { ...process.env, ...runtimeEnv, API_INTERNAL_BASE_URL: "http://localhost:8080", NEXT_PUBLIC_API_BASE_URL: "/api-brain" },
    stdio: "inherit",
    windowsHide: true,
  });
  await waitFor("http://localhost:3000/login");
}

async function requestEvolutionSession(cookie) {
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const result = await api(
      "/portal/personas/baita-conveniencia/channels/whatsapp/evolution/connect",
      cookie,
      { method: "POST", body: "{}" },
    );
    if (result.body?.status === "connected") return { connected: true, qr: null };
    const qr = result.body?.qr?.base64;
    if (typeof qr === "string" && qr.startsWith("data:image/png;base64,")) {
      return { connected: false, qr };
    }
    await new Promise((resolve) => setTimeout(resolve, 1_500));
  }
  throw new Error("Evolution não conectou nem entregou um QR PNG dentro do prazo.");
}

async function cleanup() {
  if (!fs.existsSync(stateFile)) return;
  const state = fs.readFileSync(stateFile, "utf8");
  compose(["exec", "-T", "api", "python", "scripts/demo_baita_fixture.py", "cleanup"], { input: state, timeout: 120_000, stdio: "pipe" });
  fs.unlinkSync(stateFile);
  process.stdout.write("Binding Meta restaurado; instância, lead e convite da demonstração removidos.\n");
}

async function main() {
  if (process.argv.includes("--cleanup")) {
    await cleanup();
    return;
  }
  if (!email || !email.includes("@")) throw new Error("Use --email <email-novo-do-gestor>.");
  if (!fs.existsSync(envFile)) throw new Error(".env.compose não encontrado.");
  const pendingState = fs.existsSync(stateFile) ? fs.readFileSync(stateFile, "utf8") : "";
  const localEnv = parseEnv(fs.readFileSync(envFile, "utf8"));
  if ((localEnv.ENVIRONMENT || "").toLowerCase() !== "qa") throw new Error("ENVIRONMENT=qa é obrigatório.");
  runtimeEnv = {
    ...process.env,
    ...localEnv,
    EVOLUTION_ENABLED: "true",
    EVOLUTION_API_URL: "http://evolution-api:8080",
    EVOLUTION_API_VERSION: "2.3.7",
    EVOLUTION_AUTHENTICATION_API_KEY: deriveRuntimeSecret(localEnv.AI_BRAIN_AUTH_SECRET, "api-key"),
    EVOLUTION_DB_PASSWORD: deriveRuntimeSecret(localEnv.AI_BRAIN_AUTH_SECRET, "database"),
    EVOLUTION_REDIS_PASSWORD: deriveRuntimeSecret(localEnv.AI_BRAIN_AUTH_SECRET, "redis"),
    EVOLUTION_WEBHOOK_HMAC_SECRET: deriveRuntimeSecret(localEnv.AI_BRAIN_AUTH_SECRET, "webhook"),
    EVOLUTION_CA_BUNDLE_HOST: ensureEvolutionCaBundle(),
    AI_BRAIN_PUBLIC_API_URL: "http://api:8080",
    AI_BRAIN_COOKIE_SECURE: "false",
    PIP_TRUSTED_HOST: localEnv.PIP_TRUSTED_HOST?.trim() || "pypi.org files.pythonhosted.org",
  };
  process.stdout.write("Subindo a stack QA local com Evolution API...\n");
  compose(["up", "-d", "--build"], { stdio: "inherit", timeout: 30 * 60_000 });
  await waitFor("http://localhost:8080/health/ready");
  await waitForEvolution();
  await ensureDashboard(localEnv);

  const preparedRaw = pendingState
    ? compose(["exec", "-T", "api", "python", "scripts/demo_baita_fixture.py", "resume"], { input: pendingState })
    : compose(["exec", "-T", "api", "python", "scripts/demo_baita_fixture.py", "prepare", "--email", email]);
  const prepared = JSON.parse(preparedRaw.split(/\r?\n/).filter(Boolean).at(-1));
  const temporaryPassword = prepared.temporary_password;
  delete prepared.temporary_password;
  fs.writeFileSync(stateFile, JSON.stringify(prepared), { mode: 0o600 });

  const login = await api("/auth/login", "", {
    method: "POST",
    body: JSON.stringify({ identifier: email, password: temporaryPassword, remember: false }),
  });
  const setCookie = login.response.headers.get("set-cookie") || "";
  const sessionCookie = setCookie.split(";")[0];
  if (!sessionCookie.startsWith("ai_brain_session=")) throw new Error("Sessão do gestor descartável não foi criada.");
  const disposablePassword = `Demo!9-${randomBytes(18).toString("base64url")}`;
  await api("/auth/change-password", sessionCookie, {
    method: "POST",
    body: JSON.stringify({ current_password: temporaryPassword, new_password: disposablePassword }),
  });
  process.stdout.write(`Link: http://localhost:3000${prepared.portal_url}\n`);
  process.stdout.write(`Login: ${email}\n`);
  process.stdout.write(`Senha temporária (exibida uma vez e consumida pela sessão descartável): ${temporaryPassword}\n`);

  await api("/portal/personas/baita-conveniencia/channels/whatsapp/provider", sessionCookie, {
    method: "POST",
    body: JSON.stringify({ provider: "evolution_baileys", confirmed: true }),
  });
  const evolutionSession = await requestEvolutionSession(sessionCookie);
  const qrDataUrl = evolutionSession.qr;

  browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();
  await context.addCookies([{
    name: "ai_brain_session",
    value: sessionCookie.slice("ai_brain_session=".length),
    url: "http://localhost:3000",
    httpOnly: true,
    sameSite: "Lax",
  }]);
  const page = await context.newPage();
  if (qrDataUrl) await page.setContent(`
    <!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Conectar Baita ao Evolution</title>
    <style>body{margin:0;background:#111827;color:#fff;font:16px system-ui;display:grid;place-items:center;min-height:100vh}.card{text-align:center;background:#1f2937;padding:28px;border-radius:18px;box-shadow:0 20px 60px #0008}img{width:360px;height:360px;background:#fff;padding:12px;border-radius:12px}p{max-width:480px;color:#d1d5db}</style></head>
    <body><main class="card"><h1>Conectar linha Baita</h1><p>Escaneie este QR no WhatsApp da linha Baita. Ele existe somente nesta página em memória.</p><img alt="QR Code para conectar WhatsApp" src="${qrDataUrl}"></main></body></html>
  `);
  else await page.goto("http://localhost:3000/clientes/baita-conveniencia/mensagens");
  if (qrDataUrl) await page.getByAltText("QR Code para conectar WhatsApp").waitFor();
  let refreshQr = Boolean(qrDataUrl);
  const qrRefreshTask = (async () => {
    let currentQr = qrDataUrl;
    while (refreshQr) {
      await new Promise((resolve) => setTimeout(resolve, 15_000));
      if (!refreshQr) break;
      try {
        const nextSession = await requestEvolutionSession(sessionCookie);
        if (nextSession.connected) {
          refreshQr = false;
          process.stdout.write("Linha Baita conectada ao Evolution.\n");
          break;
        }
        const nextQr = nextSession.qr;
        if (nextQr !== currentQr && !page.isClosed()) {
          currentQr = nextQr;
          await page.getByAltText("QR Code para conectar WhatsApp").evaluate((image, src) => {
            image.src = src;
          }, nextQr);
          process.stdout.write("QR renovado automaticamente.\n");
        }
      } catch {}
    }
  })();
  process.stdout.write(
    qrDataUrl
      ? "QR visível e com renovação automática. Escaneie com a linha Baita e envie uma mensagem usando uma segunda conta WhatsApp.\n"
      : "Linha Baita já conectada ao Evolution. Envie uma mensagem usando uma segunda conta WhatsApp.\n",
  );

  const startedAt = Date.now();
  let confirmed = false;
  while (!confirmed) {
    const conversations = (await api("/portal/conversations?persona_slug=baita-conveniencia", sessionCookie)).body || [];
    for (const conversation of conversations) {
      const leadRef = conversation.lead_ref || conversation.id;
      if (!leadRef) continue;
      const messages = (await api(`/portal/conversations/${leadRef}/messages?persona_slug=baita-conveniencia`, sessionCookie)).body || [];
      const recent = messages.filter((message) => Date.parse(message.created_at || 0) >= startedAt);
      const inbound = recent.find((message) => message.direction === "inbound");
      const outbound = recent.find((message) =>
        message.direction === "outbound"
        && ["sent", "delivered", "read"].includes(String(message.status || "").toLowerCase())
        && Array.isArray(message.metadata?.evidence_node_ids)
        && message.metadata.evidence_node_ids.length > 0
      );
      if (inbound && outbound) {
        confirmed = true;
        refreshQr = false;
        process.stdout.write("Resposta determinística confirmada no portal e enviada pelo binding Evolution.\n");
        await page.goto("http://localhost:3000/clientes/baita-conveniencia/mensagens");
        break;
      }
    }
    if (!confirmed) await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
  refreshQr = false;
  await qrRefreshTask;
  await browser.close();
  browser = undefined;
  process.stdout.write("Validação concluída. O binding Evolution permanece ativo; nenhuma restauração para Meta foi executada.\n");
}

try {
  await main();
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.stderr.write("O canal atual foi preservado. Nenhuma limpeza automática foi executada.\n");
  process.exitCode = 1;
} finally {
  if (browser) await browser.close().catch(() => {});
  if (dashboardProcess && dashboardProcess.exitCode === null) dashboardProcess.kill();
}
