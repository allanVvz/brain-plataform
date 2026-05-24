function missing(name: string): never {
  throw new Error(`Env ausente: ${name}. Configure nas variaveis do projeto (Vercel).`);
}

export function getPublicApiUrl(): string {
  const url = process.env.NEXT_PUBLIC_API_URL || process.env.NEXT_PUBLIC_AI_BRAIN_URL;
  if (!url) missing("NEXT_PUBLIC_API_URL (ou legado NEXT_PUBLIC_AI_BRAIN_URL)");
  return url;
}

export function getSupabasePublicEnv(): { url: string; key: string } {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url) missing("NEXT_PUBLIC_SUPABASE_URL");
  if (!key) missing("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY (ou NEXT_PUBLIC_SUPABASE_ANON_KEY)");
  return { url, key };
}

// Build the public catalog URL for a given persona slug.
// Returns null when NEXT_PUBLIC_CARDAPIO_BASE_URL is not configured, so the
// /persona screen can render a setup hint instead of a broken link.
export function getCatalogUrlForPersona(personaSlug: string | null | undefined): string | null {
  const base = (process.env.NEXT_PUBLIC_CARDAPIO_BASE_URL || "").trim();
  const slug = (personaSlug || "").trim();
  if (!base || !slug) return null;
  const cleanBase = base.replace(/\/+$/, "");
  const cleanSlug = slug.replace(/^\/+/, "");
  return `${cleanBase}/${cleanSlug}`;
}
