const required = ["NEXT_PUBLIC_SUPABASE_URL"];

const oneOf = [["NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "NEXT_PUBLIC_SUPABASE_ANON_KEY"]];
const apiOneOf = ["NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_AI_BRAIN_URL"];

const missing = required.filter((name) => !process.env[name]);
if (!apiOneOf.some((name) => process.env[name])) {
  missing.push(`${apiOneOf[0]} (ou legado ${apiOneOf[1]})`);
}
for (const pair of oneOf) {
  if (!pair.some((name) => process.env[name])) {
    missing.push(`${pair[0]} (ou ${pair[1]})`);
  }
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
