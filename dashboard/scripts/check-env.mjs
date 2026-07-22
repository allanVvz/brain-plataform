const required = ["API_INTERNAL_BASE_URL", "NEXT_PUBLIC_API_BASE_URL"];

const missing = required.filter((name) => !process.env[name]);
if (process.env.NEXT_PUBLIC_API_BASE_URL && process.env.NEXT_PUBLIC_API_BASE_URL !== "/api-brain") {
  missing.push("NEXT_PUBLIC_API_BASE_URL=/api-brain");
}

if (missing.length === 0) {
  console.log("[env-check] OK");
  process.exit(0);
}

const strict = process.env.CI === "true" || process.env.VERCEL === "1" || process.env.NODE_ENV === "production";
const message = `[env-check] Variaveis ausentes: ${missing.join(", ")}`;

if (strict) {
  console.error(message);
  process.exit(1);
}

console.warn(`${message} (modo local: apenas aviso)`);
process.exit(0);
