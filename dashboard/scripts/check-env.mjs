import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const localEnvPath = path.join(root, ".env.local");

function loadLocalEnv(filePath) {
  if (!fs.existsSync(filePath)) return;
  const text = fs.readFileSync(filePath, "utf8");
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const idx = trimmed.indexOf("=");
    if (idx <= 0) continue;
    const key = trimmed.slice(0, idx).trim();
    let value = trimmed.slice(idx + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (!process.env[key]) process.env[key] = value;
  }
}

loadLocalEnv(localEnvPath);

const required = [
  "API_INTERNAL_BASE_URL",
  "NEXT_PUBLIC_API_BASE_URL",
];

const missing = required.filter((name) => !process.env[name]);

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
