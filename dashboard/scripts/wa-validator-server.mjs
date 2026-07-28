import crypto from "node:crypto";
import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { spawn } from "node:child_process";

const port = Number(process.env.PORT || 3010);
const runtimeRoot = path.resolve(process.env.WA_VALIDATOR_RUNTIME || "/runtime");
const artifactRoot = path.resolve(process.env.WA_VALIDATOR_ARTIFACTS || "/artifacts");
const profile = path.resolve(process.env.WA_VALIDATOR_PROFILE || "/profile");
const executor = path.resolve(
  process.env.WA_VALIDATOR_EXECUTOR || "/app/scripts/wa-validator.mjs",
);
const secret = process.env.WA_VALIDATOR_RUNNER_TOKEN || "";
const processes = new Map();

function authorized(request) {
  if (!secret) return true;
  const presented = String(request.headers["x-webhook-token"] || "");
  const left = Buffer.from(presented);
  const right = Buffer.from(secret);
  return left.length === right.length && crypto.timingSafeEqual(left, right);
}

function send(response, status, payload) {
  response.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(payload));
}

async function body(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 2_000_000) throw new Error("request too large");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function safeSession(value) {
  const session = String(value || "");
  if (!/^[a-zA-Z0-9-]{8,80}$/.test(session)) {
    throw new Error("invalid session_id");
  }
  return session;
}

async function readOutput(session) {
  const outputPath = path.join(runtimeRoot, session, "output.json");
  try {
    return JSON.parse(await fs.readFile(outputPath, "utf8"));
  } catch {
    return {
      status: processes.has(session) ? "running" : "not_found",
      session_id: session,
    };
  }
}

const server = http.createServer(async (request, response) => {
  try {
    if (request.url === "/health") {
      send(response, 200, { ok: true });
      return;
    }
    if (!authorized(request)) {
      send(response, 401, { detail: "invalid token" });
      return;
    }
    if (request.method === "POST" && request.url === "/run") {
      const payload = await body(request);
      const session = safeSession(payload.session_id);
      if (processes.has(session)) {
        send(response, 409, { detail: "session already running" });
        return;
      }
      const runtimeDir = path.join(runtimeRoot, session);
      const artifacts = path.join(artifactRoot, session);
      await fs.mkdir(runtimeDir, { recursive: true });
      await fs.mkdir(artifacts, { recursive: true });
      await fs.mkdir(profile, { recursive: true });
      const scriptPath = path.join(runtimeDir, "script.json");
      const outputPath = path.join(runtimeDir, "output.json");
      const logPath = path.join(runtimeDir, "runner.log");
      await fs.writeFile(scriptPath, JSON.stringify(payload.script, null, 2), "utf8");
      const child = spawn(
        process.execPath,
        [
          executor,
          "--script",
          scriptPath,
          "--output",
          outputPath,
          "--profile",
          profile,
          "--artifacts",
          artifacts,
        ],
        { env: process.env, stdio: ["ignore", "pipe", "pipe"] },
      );
      processes.set(session, child);
      const logs = [];
      child.stdout.on("data", (chunk) => logs.push(chunk));
      child.stderr.on("data", (chunk) => logs.push(chunk));
      child.on("close", async () => {
        processes.delete(session);
        await fs.writeFile(logPath, Buffer.concat(logs));
      });
      send(response, 202, { ok: true, status: "starting", session_id: session });
      return;
    }
    const match = request.url?.match(/^\/sessions\/([a-zA-Z0-9-]+)$/);
    if (request.method === "GET" && match) {
      send(response, 200, await readOutput(safeSession(match[1])));
      return;
    }
    send(response, 404, { detail: "not found" });
  } catch (error) {
    send(response, 400, {
      detail: error instanceof Error ? error.message : String(error),
    });
  }
});

await fs.mkdir(runtimeRoot, { recursive: true });
server.listen(port, "0.0.0.0");
