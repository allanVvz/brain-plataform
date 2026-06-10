function missing(name: string): never {
  throw new Error(`Env ausente: ${name}. Configure nas variaveis do projeto (Vercel).`);
}

export function getPublicApiUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL || "/api-brain";
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
