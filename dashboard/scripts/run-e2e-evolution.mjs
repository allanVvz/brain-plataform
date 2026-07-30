import { createHmac, randomBytes, X509Certificate } from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const dashboardDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(dashboardDir, "..");
const envFile = path.join(repoRoot, ".env.compose");
const projectName = "brain-e2e-evolution";
const personaSlug = "baita-conveniencia";
const lockPath = path.join(os.tmpdir(), `${projectName}.lock`);
const tempPrefix = `${projectName}-`;
const e2eNextDir = path.join(dashboardDir, ".next-e2e-evolution");
const localHosts = new Set([
  "localhost",
  "127.0.0.1",
  "::1",
  "api",
  "kong",
  "rest",
  "storage",
  "db",
  "evolution-api",
  "evolution-redis",
  "n8n",
  "wa-validator",
]);

let dashboardProcess;
let fixtureSnapshot;
let runtimeEnv;
let tempDir;
let composeOverrideFile;
let lockHeld = false;
let composeStarted = false;
let cleanupPromise;
let e2eApiPort;
let e2eDashboardPort;
let dashboardConfigSnapshots;

function log(message) {
  process.stdout.write(`[e2e:evolution] ${message}\n`);
}

function parseEnvFile(contents) {
  const parsed = {};
  for (const rawLine of contents.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const match = line.match(/^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!match) continue;
    let value = match[2].trim();
    if (
      (value.startsWith('"') && value.endsWith('"'))
      || (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    parsed[match[1]] = value;
  }
  return parsed;
}

function isLocalHostname(hostname) {
  const normalized = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  return localHosts.has(normalized) || normalized.endsWith(".localhost");
}

function assertLocalUrl(name, rawValue) {
  for (const raw of rawValue.split(",").map((value) => value.trim()).filter(Boolean)) {
    let parsed;
    try {
      parsed = new URL(raw);
    } catch {
      throw new Error(`${name} must contain only absolute local URLs.`);
    }
    if (!["http:", "https:"].includes(parsed.protocol) || !isLocalHostname(parsed.hostname)) {
      throw new Error(`${name} points to a non-local destination.`);
    }
  }
}

function assertSafeBaseEnvironment(baseEnv) {
  if ((baseEnv.ENVIRONMENT || "").trim().toLowerCase() !== "qa") {
    throw new Error("ENVIRONMENT=qa is required in .env.compose.");
  }
  const urlKeys = [
    "SUPABASE_PUBLIC_URL",
    "ALLOWED_ORIGINS",
    "API_INTERNAL_BASE_URL",
    "N8N_EDITOR_BASE_URL",
    "N8N_WEBHOOK_URL",
    "N8N_OUTBOUND_WEBHOOK_URL",
    "EVOLUTION_API_URL",
    "AI_BRAIN_PUBLIC_API_URL",
    "WA_VALIDATOR_RUNNER_URL",
  ];
  for (const key of urlKeys) {
    const value = (baseEnv[key] || "").trim();
    if (value) assertLocalUrl(key, value);
  }
}

function base64urlJson(value) {
  return Buffer.from(JSON.stringify(value)).toString("base64url");
}

function signSupabaseJwt(secret, role) {
  const now = Math.floor(Date.now() / 1000);
  const header = base64urlJson({ alg: "HS256", typ: "JWT" });
  const payload = base64urlJson({
    role,
    iss: "supabase",
    iat: now,
    exp: now + 10 * 365 * 24 * 60 * 60,
  });
  const signature = createHmac("sha256", secret)
    .update(`${header}.${payload}`)
    .digest("base64url");
  return `${header}.${payload}.${signature}`;
}

function secret(bytes = 32) {
  return randomBytes(bytes).toString("base64url");
}

function buildRuntimeEnv(baseEnv, apiPort, dashboardPort) {
  const jwtSecret = secret(48);
  const runId = `${Date.now().toString(36)}-${randomBytes(4).toString("hex")}`;
  const adminPassword = `Aa9!${secret(20)}`;
  const finalPassword = `Bb8!${secret(20)}`;
  return {
    ...process.env,
    ...baseEnv,
    COMPOSE_PROJECT_NAME: projectName,
    ENVIRONMENT: "qa",
    POSTGRES_DB: "brain",
    POSTGRES_USER: "postgres",
    POSTGRES_PASSWORD: secret(32),
    JWT_SECRET: jwtSecret,
    ANON_KEY: signSupabaseJwt(jwtSecret, "anon"),
    SERVICE_ROLE_KEY: signSupabaseJwt(jwtSecret, "service_role"),
    AI_BRAIN_AUTH_SECRET: secret(48),
    AI_BRAIN_WEBHOOK_TOKEN: secret(32),
    AI_BRAIN_SECRETS_KEY: secret(48),
    AI_BRAIN_COOKIE_SECURE: "false",
    N8N_ENCRYPTION_KEY: secret(32),
    SUPABASE_PUBLIC_URL: "http://127.0.0.1:8000",
    ALLOWED_ORIGINS: `http://127.0.0.1:${dashboardPort},http://localhost:${dashboardPort}`,
    ALLOWED_ORIGIN_REGEX: "",
    API_DOMAIN: "api.localhost",
    STORAGE_DOMAIN: "storage.localhost",
    N8N_DOMAIN: "localhost",
    ACME_EMAIL: "qa@example.invalid",
    API_PORT: String(apiPort),
    EVOLUTION_ENABLED: "true",
    EVOLUTION_API_URL: "http://evolution-api:8080",
    EVOLUTION_API_VERSION: "2.3.7",
    EVOLUTION_API_IMAGE:
      "evoapicloud/evolution-api@sha256:1bd8afc4a6cf48822e6cf02469aeae7bd35a12a6b616eacd1291926307f4d339",
    EVOLUTION_AUTHENTICATION_API_KEY: secret(40),
    EVOLUTION_DB_PASSWORD: secret(32),
    EVOLUTION_REDIS_PASSWORD: secret(32),
    EVOLUTION_WEBHOOK_HMAC_SECRET: secret(48),
    AI_BRAIN_PUBLIC_API_URL: "http://api:8080",
    API_INTERNAL_BASE_URL: "http://api:8080",
    AI_BRAIN_SEED_ADMIN_EMAIL: `qa+baita-evolution-${runId}-admin@example.invalid`,
    AI_BRAIN_SEED_ADMIN_USERNAME: `qa-evolution-${runId}`,
    AI_BRAIN_SEED_ADMIN_PASSWORD: adminPassword,
    AI_BRAIN_SEED_ADMIN_ROLE: "admin",
    META_WHATSAPP_APP_SECRET: "",
    META_WHATSAPP_VERIFY_TOKEN: "",
    META_WHATSAPP_ACCESS_TOKEN: "",
    META_WHATSAPP_ALLOW_UNSIGNED_LOCAL: "false",
    OPENAI_API_KEY: "",
    ANTHROPIC_API_KEY: "",
    // Docker Desktop on this workstation is behind an intercepting TLS proxy.
    // Scope the workaround to PyPI hosts and only to this ephemeral build.
    PIP_TRUSTED_HOST: baseEnv.PIP_TRUSTED_HOST?.trim()
      || "pypi.org files.pythonhosted.org",
    E2E_DASHBOARD_URL: `http://127.0.0.1:${dashboardPort}`,
    E2E_ADMIN_EMAIL: `qa+baita-evolution-${runId}-admin@example.invalid`,
    E2E_ADMIN_PASSWORD: adminPassword,
    E2E_MANAGER_EMAIL: `qa+baita-evolution-${runId}@example.invalid`,
    E2E_OPERATOR_EMAIL: `qa+baita-evolution-${runId}-operator@example.invalid`,
    E2E_VIEWER_EMAIL: `qa+baita-evolution-${runId}-viewer@example.invalid`,
    E2E_FINAL_PASSWORD: finalPassword,
  };
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || repoRoot,
    env: options.env || runtimeEnv || process.env,
    encoding: "utf8",
    input: options.input,
    stdio: options.stdio || "pipe",
    timeout: options.timeout || 60_000,
    windowsHide: true,
    maxBuffer: 10 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    const detail = options.stdio === "inherit"
      ? ""
      : ` ${String(result.stderr || result.stdout || "").trim().slice(0, 800)}`;
    throw new Error(`${command} exited with status ${result.status}.${detail}`);
  }
  return String(result.stdout || "").trim();
}

function docker(args, options = {}) {
  return run("docker", args, options);
}

function compose(args, options = {}) {
  const files = ["-f", path.join(repoRoot, "docker-compose.yml")];
  if (composeOverrideFile) files.push("-f", composeOverrideFile);
  return docker([
    "compose",
    ...files,
    "-p",
    projectName,
    "--env-file",
    envFile,
    "--profile",
    "evolution",
    ...args,
  ], options);
}

function removeEphemeralProjectResources() {
  const projectFilter = `label=com.docker.compose.project=${projectName}`;
  const containerIds = docker(
    ["ps", "-aq", "--filter", projectFilter],
    { timeout: 15_000 },
  ).split(/\r?\n/).filter(Boolean);
  if (containerIds.length) {
    docker(["rm", "-f", ...containerIds], { timeout: 90_000 });
  }

  const volumeNames = docker(
    ["volume", "ls", "-q", "--filter", projectFilter],
    { timeout: 15_000 },
  ).split(/\r?\n/).filter(Boolean);
  if (volumeNames.length) {
    docker(["volume", "rm", "-f", ...volumeNames], { timeout: 60_000 });
  }

  const networkIds = docker(
    ["network", "ls", "-q", "--filter", projectFilter],
    { timeout: 15_000 },
  ).split(/\r?\n/).filter(Boolean);
  if (networkIds.length) {
    docker(["network", "rm", ...networkIds], { timeout: 30_000 });
  }
}

function configureEvolutionTrust() {
  if (process.platform !== "win32") return;
  const command = [
    "$ErrorActionPreference = 'Stop';",
    "$seen = @{};",
    "Get-ChildItem -Path 'Cert:\\CurrentUser\\Root','Cert:\\LocalMachine\\Root' |",
    "ForEach-Object { if (-not $seen.ContainsKey($_.Thumbprint)) {",
    "$seen[$_.Thumbprint] = $true;",
    "[Convert]::ToBase64String($_.RawData)",
    "} }",
  ].join(" ");
  const encodedRoots = run(
    "powershell.exe",
    ["-NoProfile", "-NonInteractive", "-Command", command],
    { env: process.env, timeout: 30_000 },
  );
  const pemBlocks = [];
  for (const encoded of new Set(encodedRoots.split(/\r?\n/).map((line) => line.trim()).filter(Boolean))) {
    try {
      const der = Buffer.from(encoded, "base64");
      new X509Certificate(der);
      const lines = encoded.match(/.{1,64}/g) || [];
      pemBlocks.push(`-----BEGIN CERTIFICATE-----\n${lines.join("\n")}\n-----END CERTIFICATE-----`);
    } catch {
      // Ignore malformed/non-certificate rows from the Windows store.
    }
  }
  if (!pemBlocks.length) {
    throw new Error("Could not export the Windows trusted root certificates for Evolution TLS.");
  }

  const caPath = path.join(tempDir, "windows-trusted-roots.pem");
  fs.writeFileSync(caPath, `${pemBlocks.join("\n")}\n`, { mode: 0o600 });
  composeOverrideFile = path.join(tempDir, "compose.evolution-ca.yml");
  fs.writeFileSync(
    composeOverrideFile,
    [
      "services:",
      "  evolution-api:",
      "    environment:",
      "      NODE_EXTRA_CA_CERTS: /run/e2e/windows-trusted-roots.pem",
      "    volumes:",
      "      - type: bind",
      `        source: ${JSON.stringify(caPath.replace(/\\/g, "/"))}`,
      "        target: /run/e2e/windows-trusted-roots.pem",
      "        read_only: true",
      "",
    ].join("\n"),
    { mode: 0o600 },
  );
  log("confianca TLS da Evolution vinculada ao repositorio de CAs do Windows");
}

async function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen({ host: "127.0.0.1", port: 0 }, () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => {
        if (!port) reject(new Error("Could not allocate an isolated local E2E port."));
        else resolve(port);
      });
    });
  });
}

function acquireLock() {
  try {
    fs.writeFileSync(lockPath, String(process.pid), { flag: "wx", mode: 0o600 });
    lockHeld = true;
    return;
  } catch (error) {
    if (error.code !== "EEXIST") throw error;
  }
  const pid = Number(fs.readFileSync(lockPath, "utf8").trim());
  try {
    process.kill(pid, 0);
    throw new Error("Another Evolution E2E run is active.");
  } catch (error) {
    if (error.message === "Another Evolution E2E run is active.") throw error;
    fs.unlinkSync(lockPath);
    fs.writeFileSync(lockPath, String(process.pid), { flag: "wx", mode: 0o600 });
    lockHeld = true;
  }
}

async function waitFor(label, check, timeoutMs = 180_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      if (await check()) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
  throw new Error(`${label} did not become ready.${lastError ? ` ${lastError.message}` : ""}`);
}

function containerState(service) {
  const id = compose(["ps", "--all", "--quiet", service], { timeout: 15_000 });
  if (!id) return null;
  return JSON.parse(docker(["inspect", "--format", "{{json .State}}", id], { timeout: 15_000 }));
}

async function waitForOneShot(service) {
  await waitFor(`${service} completion`, () => {
    const state = containerState(service);
    if (!state || state.Running) return false;
    if (state.ExitCode !== 0) throw new Error(`${service} exited with ${state.ExitCode}.`);
    return true;
  }, 240_000);
}

async function waitForHealthy(service) {
  await waitFor(`${service} health`, () => {
    const state = containerState(service);
    if (!state?.Running) return false;
    if (state.Health?.Status === "unhealthy") {
      const output = state.Health.Log?.at(-1)?.Output?.trim() || "no healthcheck output";
      throw new Error(`${service} is unhealthy: ${output.slice(0, 500)}`);
    }
    return state.Health?.Status === "healthy";
  }, 300_000);
}

async function waitForHttp(url, label, timeoutMs = 180_000) {
  await waitFor(label, async () => {
    const response = await fetch(url, { signal: AbortSignal.timeout(4_000) });
    return response.ok;
  }, timeoutMs);
}

function prepareFixture() {
  const raw = compose([
    "exec",
    "-T",
    "api",
    "python",
    "scripts/e2e_evolution_fixture.py",
    "prepare",
    "--persona",
    personaSlug,
  ], { timeout: 60_000 });
  const line = raw.split(/\r?\n/).filter(Boolean).at(-1);
  const snapshot = JSON.parse(line);
  if (snapshot.persona_slug !== personaSlug || !snapshot.persona_id) {
    throw new Error("Fixture preparation returned an invalid restore snapshot.");
  }
  return snapshot;
}

function auditFixtureMessage(bindingId, externalMessageId) {
  const raw = compose([
    "exec",
    "-T",
    "api",
    "python",
    "scripts/e2e_evolution_fixture.py",
    "audit-message",
    "--binding-id",
    bindingId,
    "--external-message-id",
    externalMessageId,
  ], { timeout: 60_000 });
  return JSON.parse(raw.split(/\r?\n/).filter(Boolean).at(-1));
}

async function exerciseSyntheticWebhook(snapshot) {
  const externalMessageId = `e2e-${randomBytes(12).toString("hex")}`;
  const callbackToken = createHmac(
    "sha256",
    runtimeEnv.EVOLUTION_WEBHOOK_HMAC_SECRET,
  ).update(snapshot.fixture_binding_id).digest("base64url");
  const payload = {
    event: "messages.upsert",
    instance: "e2e-baita-connected",
    data: {
      key: {
        id: externalMessageId,
        remoteJid: "5511999999999@s.whatsapp.net",
        fromMe: false,
      },
      message: { conversation: "Mensagem sintetica de idempotencia" },
    },
  };
  const url = `http://127.0.0.1:${e2eApiPort}/webhooks/evolution/${snapshot.fixture_binding_id}`;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-brain-webhook-token": callbackToken,
      },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(10_000),
    });
    if (response.status !== 202) {
      throw new Error(`Synthetic Evolution webhook returned HTTP ${response.status}.`);
    }
  }
  const audit = auditFixtureMessage(
    snapshot.fixture_binding_id,
    externalMessageId,
  );
  if (audit.inbound_messages !== 1 || audit.inbound_buffers !== 1) {
    throw new Error(
      `Synthetic Evolution webhook was not idempotent: ${JSON.stringify(audit)}`,
    );
  }
  log("webhook sintetico aceito duas vezes com uma unica entrega persistida");
}

function dashboardEnvironment() {
  return {
    ...runtimeEnv,
    API_INTERNAL_BASE_URL: `http://127.0.0.1:${e2eApiPort}`,
    NEXT_PUBLIC_API_BASE_URL: "/api-brain",
    NEXT_DIST_DIR: ".next-e2e-evolution",
    NODE_ENV: "production",
  };
}

function buildDashboard() {
  const executable = path.join(dashboardDir, "node_modules", "next", "dist", "bin", "next");
  run(process.execPath, [executable, "build"], {
    cwd: dashboardDir,
    env: dashboardEnvironment(),
    stdio: "inherit",
    timeout: 10 * 60_000,
  });
}

function startDashboard() {
  const executable = path.join(dashboardDir, "node_modules", "next", "dist", "bin", "next");
  dashboardProcess = spawn(process.execPath, [
    executable,
    "start",
    "-p",
    String(e2eDashboardPort),
  ], {
    cwd: dashboardDir,
    env: dashboardEnvironment(),
    stdio: "inherit",
    windowsHide: true,
    detached: process.platform !== "win32",
  });
}

async function stopDashboard() {
  if (!dashboardProcess || dashboardProcess.exitCode !== null) return;
  const pid = dashboardProcess.pid;
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/pid", String(pid), "/T", "/F"], {
      stdio: "ignore",
      windowsHide: true,
      timeout: 15_000,
    });
  } else {
    try {
      process.kill(-pid, "SIGTERM");
    } catch {
      dashboardProcess.kill("SIGTERM");
    }
  }
}

function cleanupFixture() {
  if (!fixtureSnapshot || !composeStarted) return;
  const emails = [
    runtimeEnv.E2E_ADMIN_EMAIL,
    runtimeEnv.E2E_MANAGER_EMAIL,
    runtimeEnv.E2E_OPERATOR_EMAIL,
    runtimeEnv.E2E_VIEWER_EMAIL,
  ];
  const args = [
    "exec",
    "-T",
    "api",
    "python",
    "scripts/e2e_evolution_fixture.py",
    "cleanup",
    "--persona",
    personaSlug,
  ];
  for (const email of emails) args.push("--email", email);
  compose(args, {
    input: JSON.stringify(fixtureSnapshot),
    timeout: 90_000,
  });
}

async function cleanup() {
  if (cleanupPromise) return cleanupPromise;
  if (!dashboardProcess && !fixtureSnapshot && !composeStarted && !tempDir && !lockHeld) {
    return;
  }
  cleanupPromise = (async () => {
    log("restaurando fixtures e removendo a stack efêmera");
    await stopDashboard();
    try {
      // The E2E stack owns a fresh database volume that is destroyed below.
      // Restoring individual rows first adds no safety and can block docker
      // exec indefinitely on Windows during teardown.
    } catch (error) {
      process.stderr.write(`[e2e:evolution] limpeza lógica incompleta: ${error.message}\n`);
    }
    if (composeStarted) {
      try {
        compose(["down", "--volumes", "--remove-orphans", "--timeout", "10"], {
          stdio: "inherit",
          timeout: 120_000,
        });
      } catch (error) {
        process.stderr.write(`[e2e:evolution] falha ao remover stack efêmera: ${error.message}\n`);
        try {
          const containerIds = docker([
            "ps", "-aq", "--filter", `label=com.docker.compose.project=${projectName}`,
          ], { timeout: 15_000 }).split(/\r?\n/).filter(Boolean);
          if (containerIds.length) {
            docker(["rm", "-f", ...containerIds], { timeout: 60_000 });
          }
          const volumeNames = docker([
            "volume", "ls", "-q", "--filter", `label=com.docker.compose.project=${projectName}`,
          ], { timeout: 15_000 }).split(/\r?\n/).filter(Boolean);
          if (volumeNames.length) {
            docker(["volume", "rm", "-f", ...volumeNames], { timeout: 60_000 });
          }
        } catch (fallbackError) {
          process.stderr.write(
            `[e2e:evolution] cleanup fallback incomplete: ${fallbackError.message}\n`,
          );
        }
      }
    }
    if (tempDir) {
      const resolvedTemp = path.resolve(tempDir);
      const allowedPrefix = path.resolve(os.tmpdir(), tempPrefix);
      if (resolvedTemp.startsWith(allowedPrefix)) {
        fs.rmSync(resolvedTemp, { recursive: true, force: true });
      }
    }
    const resolvedNextDir = path.resolve(e2eNextDir);
    if (
      resolvedNextDir === path.join(path.resolve(dashboardDir), ".next-e2e-evolution")
      && fs.existsSync(resolvedNextDir)
    ) {
      fs.rmSync(resolvedNextDir, { recursive: true, force: true });
    }
    if (dashboardConfigSnapshots) {
      for (const [filePath, contents] of dashboardConfigSnapshots) {
        fs.writeFileSync(filePath, contents);
      }
    }
    if (lockHeld) {
      try {
        fs.unlinkSync(lockPath);
      } catch {
        // A process exit will not leave credentials behind; the lock has only a PID.
      }
      lockHeld = false;
    }
  })();
  return cleanupPromise;
}

async function main() {
  if (!fs.existsSync(envFile)) {
    throw new Error("Create .env.compose before running the local Evolution E2E.");
  }
  const baseEnv = parseEnvFile(fs.readFileSync(envFile, "utf8"));
  assertSafeBaseEnvironment(baseEnv);

  // Docker is checked before locks, containers, databases, or files are changed.
  try {
    docker(["info", "--format", "{{.ServerVersion}}"], {
      env: process.env,
      // Docker Desktop can take a little longer to answer immediately after
      // its engine has started, even though the daemon is already healthy.
      timeout: 60_000,
    });
  } catch (error) {
    throw new Error(`Docker is unavailable; no local state was changed. ${error.code || error.message}`);
  }

  acquireLock();
  e2eApiPort = await findFreePort();
  do {
    e2eDashboardPort = await findFreePort();
  } while (e2eDashboardPort === e2eApiPort);
  runtimeEnv = buildRuntimeEnv(baseEnv, e2eApiPort, e2eDashboardPort);
  tempDir = fs.mkdtempSync(path.join(os.tmpdir(), tempPrefix));
  dashboardConfigSnapshots = new Map(
    ["next-env.d.ts", "tsconfig.json"].map((name) => {
      const filePath = path.join(dashboardDir, name);
      return [filePath, fs.readFileSync(filePath)];
    }),
  );
  if (fs.existsSync(e2eNextDir)) {
    fs.rmSync(e2eNextDir, { recursive: true, force: true });
  }
  runtimeEnv.E2E_OUTPUT_DIR = path.join(tempDir, "playwright");
  configureEvolutionTrust();

  // A prior interrupted run can only own this fixed, E2E-specific project.
  try {
    compose(["down", "--volumes", "--remove-orphans", "--timeout", "10"], {
      timeout: 120_000,
    });
  } catch {
    removeEphemeralProjectResources();
  }
  log(
    `subindo Postgres, API :${e2eApiPort}, dashboard :${e2eDashboardPort}, workers, Redis e Evolution v2.3.7`,
  );
  composeStarted = true;
  compose(["build", "migrate", "api"], {
    stdio: "inherit",
    timeout: 30 * 60_000,
  });
  compose([
    "up",
    "-d",
    "--no-build",
    "db",
    "db-bootstrap",
    "storage",
    "migrate",
    "rest",
    "kong",
    "api",
    "workers",
    "evolution-redis",
    "evolution-api",
  ], {
    stdio: "inherit",
    timeout: 30 * 60_000,
  });

  await waitForOneShot("migrate");
  await waitForHttp(
    `http://127.0.0.1:${e2eApiPort}/health/ready`,
    "API readiness",
    300_000,
  );
  await waitForHealthy("evolution-redis");
  await waitForHealthy("evolution-api");
  compose(["up", "-d", "--no-build", "--no-deps", "seed-admin"], {
    stdio: "inherit",
    timeout: 120_000,
  });
  await waitForOneShot("seed-admin");

  fixtureSnapshot = prepareFixture();
  await exerciseSyntheticWebhook(fixtureSnapshot);
  buildDashboard();
  startDashboard();
  await waitForHttp(
    `http://127.0.0.1:${e2eDashboardPort}/login`,
    "dashboard proxy",
    240_000,
  );

  log("executando Playwright serial sem screenshot, vídeo, trace ou relatório HTML");
  const playwrightCli = path.join(dashboardDir, "node_modules", "playwright", "cli.js");
  run(process.execPath, [
    playwrightCli,
    "test",
    "--config",
    "playwright.evolution.config.ts",
  ], {
    cwd: dashboardDir,
    env: runtimeEnv,
    stdio: "inherit",
    timeout: 10 * 60_000,
  });
  log("cenário concluído sem alterar provider, instância ou QR");
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.once(signal, () => {
    cleanup().finally(() => process.exit(signal === "SIGINT" ? 130 : 143));
  });
}

let exitCode = 0;
try {
  await main();
} catch (error) {
  exitCode = 1;
  process.stderr.write(`[e2e:evolution] ${error.message}\n`);
} finally {
  await cleanup();
}
process.exitCode = exitCode;
