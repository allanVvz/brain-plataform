export type SessionPersona = {
  slug?: string | null;
};

export type SessionLike = {
  account_type?: string | null;
  user?: {
    account_type?: string | null;
    must_change_password?: boolean | null;
  } | null;
  personas?: SessionPersona[] | null;
  navigation?: {
    surface?: string | null;
    home_url?: string | null;
  } | null;
};

const CLIENT_SECTIONS = new Set(["mensagens", "leads", "pipeline", "configuracoes"]);

export function safeLocalTarget(value?: string | null): string {
  const target = (value || "").trim();
  if (!target.startsWith("/") || target.startsWith("//") || target.includes("\\")) {
    return "";
  }
  return target;
}

function accountType(session: SessionLike): string {
  return session.account_type || session.user?.account_type || "internal";
}

function authorizedClientTarget(session: SessionLike, target: string): boolean {
  const pathname = target.split(/[?#]/, 1)[0];
  const parts = pathname.split("/").filter(Boolean);
  if (parts[0] !== "clientes" || parts.length < 2) return false;

  let slug = "";
  try {
    slug = decodeURIComponent(parts[1]);
  } catch {
    return false;
  }
  const authorized = (session.personas || []).some((persona) => persona?.slug === slug);
  if (!authorized) return false;
  if (parts.length === 2) return true;
  return CLIENT_SECTIONS.has(parts[2]);
}

export function defaultSessionHome(session: SessionLike): string {
  const declaredHome = safeLocalTarget(session.navigation?.home_url);
  if (accountType(session) !== "client") {
    return declaredHome && declaredHome !== "/login" ? declaredHome : "/";
  }

  if (declaredHome && authorizedClientTarget(session, declaredHome)) {
    return declaredHome;
  }
  const slug = (session.personas || []).find((persona) => persona?.slug)?.slug;
  return slug ? `/clientes/${encodeURIComponent(slug)}/mensagens` : "/login";
}

export function resolveSessionDestination(
  session: SessionLike,
  requestedTarget?: string | null,
): string {
  const target = safeLocalTarget(requestedTarget);
  const fallback = defaultSessionHome(session);

  if (accountType(session) === "client") {
    return target && authorizedClientTarget(session, target) ? target : fallback;
  }
  return target && target !== "/login" ? target : fallback;
}
