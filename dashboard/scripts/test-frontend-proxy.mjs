#!/usr/bin/env node

const base = (process.env.FRONTEND_URL || "http://localhost:3000").replace(/\/+$/, "");

async function check(path, allowed) {
  const res = await fetch(`${base}${path}`, { method: "GET", redirect: "manual" });
  const server = res.headers.get("server") || "(none)";
  if (!allowed.includes(res.status)) {
    console.error(`FAIL ${path} -> ${res.status} (expected ${allowed.join("|")}) server=${server}`);
    return false;
  }
  console.log(`ok ${path} -> ${res.status} server=${server}`);
  return true;
}

try {
  const okHealth = await check("/api-brain/health", [200]);
  const okMe = await check("/api-brain/auth/me", [200, 401]);
  if (!okHealth || !okMe) process.exit(1);
  console.log("frontend proxy ok");
} catch (err) {
  console.error(`FAIL proxy test -> request error: ${err.message}`);
  process.exit(1);
}
