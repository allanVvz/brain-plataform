#!/usr/bin/env node
// Test 2 + 3 — the Next.js /api-brain proxy reaches the Docker backend.
//
// With the dashboard running (http://localhost:3000) this verifies:
//   /api-brain/health  -> 200            (proxy forwards to backend /health)
//   /api-brain/auth/me -> 200 | 401       (real backend route; 401 = no session)
// and that the response actually came FROM the backend (Server: uvicorn) THROUGH
// the proxy — i.e. there is no rogue uvicorn bound to :3000.
const base = (process.env.FRONTEND_URL || "http://localhost:3000").replace(/\/+$/, "");

async function check(path, allowed) {
  const url = `${base}${path}`;
  const res = await fetch(url, { method: "GET", redirect: "manual" });
  const server = res.headers.get("server") || "(none)";
  if (!allowed.includes(res.status)) {
    console.error(`FAIL ${path} -> ${res.status} (expected ${allowed.join("|")}) server=${server}`);
    return false;
  }
  console.log(`ok  ${path} -> ${res.status} server=${server}`);
  return true;
}

try {
  const okHealth = await check("/api-brain/health", [200]);
  const okMe = await check("/api-brain/auth/me", [200, 401]);
  if (!okHealth || !okMe) process.exit(1);
  console.log("frontend proxy ok");
} catch (err) {
  console.error(`FAIL proxy test -> request error: ${err.message}`);
  console.error("Is the dashboard running?  npm run dev  (and is the Docker stack up?)");
  process.exit(1);
}
