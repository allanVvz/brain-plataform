function missing(name: string): never {
  throw new Error(`Env ausente: ${name}. Configure nas variaveis do projeto (Vercel).`);
}

export function getPublicApiUrl(): string {
  const url = process.env.NEXT_PUBLIC_API_URL;
  if (!url) missing("NEXT_PUBLIC_API_URL");
  return url;
}

export function getSupabasePublicEnv(): { url: string; key: string } {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url) missing("NEXT_PUBLIC_SUPABASE_URL");
  if (!key) missing("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY (ou NEXT_PUBLIC_SUPABASE_ANON_KEY)");
  return { url, key };
}
