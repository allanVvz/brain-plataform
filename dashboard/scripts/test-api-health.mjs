#!/usr/bin/env node
// Test 1 — Docker backend health.
// Hits the API directly (default http://localhost:8080/health) and expects 200.
// Override with API_INTERNAL_BASE_URL or API_URL.
const base = (process.env.API_INTERNAL_BASE_URL || process.env.API_URL || "http://localhost:8080").replace(/\/+$/, "");
const url = `${base}/health`;

try {
  const res = await fetch(url, { method: "GET" });
  const body = await res.text();
  if (res.status !== 200) {
    console.error(`FAIL ${url} -> ${res.status}\n${body}`);
    process.exit(1);
  }
  console.log(`ok  ${url} -> ${res.status}  ${body.slice(0, 120)}`);
  console.log(`server header: ${res.headers.get("server") || "(none)"}`);
} catch (err) {
  console.error(`FAIL ${url} -> request error: ${err.message}`);
  console.error("Is the Docker stack up?  docker compose --env-file .env.compose ps");
  process.exit(1);
}
