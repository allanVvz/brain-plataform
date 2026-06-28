#!/usr/bin/env node

const base = (process.env.API_HEALTH_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");

try {
  const res = await fetch(`${base}/health`, { method: "GET" });
  if (res.status !== 200) {
    console.error(`FAIL api health -> ${res.status}`);
    process.exit(1);
  }
  console.log(`ok api health -> ${res.status}`);
} catch (err) {
  console.error(`FAIL api health -> request error: ${err.message}`);
  process.exit(1);
}
