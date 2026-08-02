// Browser requests go through the Next.js rewrite proxy (same-origin).
// The relative prefix below is rewritten server-side to the real backend
// (API_INTERNAL_BASE_URL) by next.config.js, so the browser never needs the
// backend host and no secret is exposed. Override the prefix only if you mount
// the proxy under a different path.
export const BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api-brain";
export const API_URL = BASE;
export const API_OFFLINE_ERROR =
  "Backend indisponivel agora. Confirme o backend (API_INTERNAL_BASE_URL), o endpoint /health e tente novamente.";

export type ApiErrorKind =
  | "network"
  | "unauthenticated"
  | "forbidden"
  | "unavailable"
  | "client"
  | "server";

export class ApiError extends Error {
  readonly status: number;
  readonly path: string;
  readonly detail: string;
  readonly kind: ApiErrorKind;

  constructor(args: { status: number; path: string; detail?: string; kind: ApiErrorKind }) {
    const offline = args.kind === "network" || args.kind === "unavailable";
    super(
      offline
        ? API_OFFLINE_ERROR
        : `${args.status} ${args.path}${args.detail ? ` - ${args.detail}` : ""}`,
    );
    this.name = "ApiError";
    this.status = args.status;
    this.path = args.path;
    this.detail = args.detail || "";
    this.kind = args.kind;
  }
}

function assertApiConfigured() {
  // With the same-origin proxy the browser only needs a relative prefix, which
  // always has a default. Guard only against an explicitly blanked prefix.
  if (!BASE) {
    throw new Error("Proxy base ausente. Defina NEXT_PUBLIC_API_BASE_URL (padrao /api-brain).");
  }
}

function errorKind(status: number): ApiErrorKind {
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if ([502, 503, 504].includes(status)) return "unavailable";
  if (status >= 500) return "server";
  return "client";
}

async function responseDetail(res: Response): Promise<string> {
  const raw = await res.text().catch(() => "");
  if (!raw) return "";
  try {
    const body = JSON.parse(raw);
    return typeof body?.detail === "string"
      ? body.detail
      : JSON.stringify(body?.detail ?? body);
  } catch {
    return raw;
  }
}

async function assertResponse(path: string, res: Response): Promise<void> {
  if (res.ok) return;
  throw new ApiError({
    status: res.status,
    path,
    detail: await responseDetail(res),
    kind: errorKind(res.status),
  });
}

async function req<T>(path: string, opts?: RequestInit): Promise<T> {
  assertApiConfigured();
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      ...opts,
    });
  } catch {
    throw new ApiError({ status: 0, path, kind: "network" });
  }

  await assertResponse(path, res);
  return res.json();
}

async function reqForm<T>(path: string, form: FormData): Promise<T> {
  assertApiConfigured();
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { method: "POST", body: form, credentials: "include" });
  } catch {
    throw new ApiError({ status: 0, path, kind: "network" });
  }
  await assertResponse(path, res);
  return res.json();
}

function personaQuery(slug: string) {
  if (!slug) throw new Error("Persona do portal não informada.");
  return `persona_slug=${encodeURIComponent(slug)}`;
}

export const api = {
  // Auth
  login: (body: { identifier: string; password: string; remember?: boolean }) =>
    req<any>("/auth/login", { method: "POST", body: JSON.stringify(body) }),
  me: () => req<any>("/auth/me"),
  logout: () => req<any>("/auth/logout", { method: "POST", body: "{}" }),
  changePassword: (body: { current_password: string; new_password: string }) =>
    req<any>("/auth/change-password", { method: "POST", body: JSON.stringify(body) }),
  clientPages: () => req<Array<{
    slug: string;
    name: string;
    url: string;
    capabilities: { view: boolean; edit: boolean; manage: boolean; manage_members: boolean };
    channel: { configured: boolean; status: string; provider?: string | null };
  }>>("/portal/client-pages"),

  // Health & Insights
  health: () => req<any>("/health/score"),
  insights: (status?: string) => req<any[]>(`/insights${status ? `?status=${status}` : ""}`),
  updateInsight: (id: string, status: string) => req(`/insights/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  runValidator: () => req("/insights/run-validator", { method: "POST" }),
  healthHistory: (limit = 30) => req<any[]>(`/logs/health-history?limit=${limit}`),

  // Leads & Messages
  leads: (
    limit = 100,
    offset = 0,
    personaId?: string,
    validationScope: "exclude" | "only" | "all" = "exclude",
  ) =>
    req<any[]>(`/leads?limit=${limit}&offset=${offset}&validation_scope=${validationScope}${personaId ? `&persona_id=${personaId}` : ""}`),
  leadsScoped: (opts: {
    limit?: number;
    offset?: number;
    personaId?: string;
    personaSlug?: string;
    audienceId?: string;
    audienceSlug?: string;
    validationScope?: "exclude" | "only" | "all";
  }) => {
    const params = new URLSearchParams();
    params.set("limit", String(opts.limit ?? 100));
    params.set("offset", String(opts.offset ?? 0));
    if (opts.personaId) params.set("persona_id", opts.personaId);
    if (opts.personaSlug) params.set("persona_slug", opts.personaSlug);
    if (opts.audienceId) params.set("audience_id", opts.audienceId);
    if (opts.audienceSlug) params.set("audience_slug", opts.audienceSlug);
    params.set("validation_scope", opts.validationScope ?? "exclude");
    return req<any[]>(`/leads?${params.toString()}`);
  },
  lead: (id: string) => req<any>(`/leads/${id}`),
  leadMemberships: (leadId: string | number) => req<any>(`/leads/${leadId}/memberships`),
  moveLead: (leadRef: number, body: {
    target_persona_id: string;
    target_audience_id?: string;
    target_audience_slug?: string;
    source_audience_id?: string;
    source_audience_slug?: string;
  }) => req<any>(`/leads/${leadRef}/move`, { method: "POST", body: JSON.stringify(body) }),
  shareLead: (leadRef: number, body: {
    target_persona_id: string;
    target_audience_id?: string;
    target_audience_slug?: string;
    source_audience_id?: string;
    source_audience_slug?: string;
  }) => req<any>(`/leads/${leadRef}/share`, { method: "POST", body: JSON.stringify(body) }),
  leadImports: (personaId?: string) =>
    req<any[]>(`/leads/imports${personaId ? `?persona_id=${personaId}` : ""}`),
  leadImport: (batchId: string) => req<any>(`/leads/imports/${encodeURIComponent(batchId)}`),
  deleteLeadImport: (batchId: string) =>
    req<any>(`/leads/imports/${encodeURIComponent(batchId)}`, { method: "DELETE" }),
  uploadLeadImport: (file: File, personaId?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (personaId) form.append("persona_id", personaId);
    return reqForm<any>("/leads/imports", form);
  },
  updateLeadInfo: (leadRef: number, body: {
    nome?: string;
    interesse_produto?: string;
    commercial_note?: Record<string, string>;
  }) => req<any>(`/leads/${leadRef}`, { method: "PATCH", body: JSON.stringify(body) }),
  pauseAi: (leadRef: number) => req<{ ok: boolean; ai_paused: boolean }>(`/leads/${leadRef}/pause-ai`, { method: "POST" }),
  resumeAi: (leadRef: number) => req<{ ok: boolean; ai_paused: boolean }>(`/leads/${leadRef}/resume-ai`, { method: "POST" }),
  messages: (leadId: string) => req<any[]>(`/messages/${leadId}`),
  messagesByRef: (
    leadRef: number,
    limit = 200,
    validationScope: "exclude" | "only" | "all" = "exclude",
  ) =>
    req<any[]>(`/messages/by-ref/${leadRef}?limit=${limit}&validation_scope=${validationScope}`),
  messagesByRefScoped: (leadRef: number, opts: {
    limit?: number;
    personaId?: string;
    personaSlug?: string;
    audienceId?: string;
    audienceSlug?: string;
    validationScope?: "exclude" | "only" | "all";
  }) => {
    const params = new URLSearchParams();
    params.set("limit", String(opts.limit ?? 200));
    if (opts.personaId) params.set("persona_id", opts.personaId);
    if (opts.personaSlug) params.set("persona_slug", opts.personaSlug);
    if (opts.audienceId) params.set("audience_id", opts.audienceId);
    if (opts.audienceSlug) params.set("audience_slug", opts.audienceSlug);
    params.set("validation_scope", opts.validationScope ?? "exclude");
    return req<any[]>(`/messages/by-ref/${leadRef}?${params.toString()}`);
  },
  recentMessages: (hours = 24, personaId?: string) =>
    req<any[]>(`/messages?hours=${hours}${personaId ? `&persona_id=${personaId}` : ""}`),
  recentMessagesScoped: (opts: {
    hours?: number;
    personaId?: string;
    personaSlug?: string;
    audienceId?: string;
    audienceSlug?: string;
  }) => {
    const params = new URLSearchParams();
    params.set("hours", String(opts.hours ?? 24));
    if (opts.personaId) params.set("persona_id", opts.personaId);
    if (opts.personaSlug) params.set("persona_slug", opts.personaSlug);
    if (opts.audienceId) params.set("audience_id", opts.audienceId);
    if (opts.audienceSlug) params.set("audience_slug", opts.audienceSlug);
    return req<any[]>(`/messages?${params.toString()}`);
  },
  conversations: (
    hours = 168,
    personaId?: string,
    validationScope: "exclude" | "only" | "all" = "exclude",
  ) =>
    req<any[]>(`/messages/conversations?hours=${hours}&validation_scope=${validationScope}${personaId ? `&persona_id=${personaId}` : ""}`),
  conversationsScoped: (opts: {
    hours?: number;
    personaId?: string;
    personaSlug?: string;
    audienceId?: string;
    audienceSlug?: string;
    validationScope?: "exclude" | "only" | "all";
  }) => {
    const params = new URLSearchParams();
    params.set("hours", String(opts.hours ?? 168));
    if (opts.personaId) params.set("persona_id", opts.personaId);
    if (opts.personaSlug) params.set("persona_slug", opts.personaSlug);
    if (opts.audienceId) params.set("audience_id", opts.audienceId);
    if (opts.audienceSlug) params.set("audience_slug", opts.audienceSlug);
    params.set("validation_scope", opts.validationScope ?? "exclude");
    return req<any[]>(`/messages/conversations?${params.toString()}`);
  },
  sendMessage: (body: { lead_ref: number; client_message_id: string; texto: string; agent_id?: string; sender_id?: string; nome?: string }) =>
    req<{ ok: boolean; message_id: string; buffer_id: string; status: string; deduplicated: boolean }>(
      "/messages/send",
      { method: "POST", body: JSON.stringify(body) },
    ),
  portalConversations: (slug: string) =>
    req<any[]>(`/portal/conversations?${personaQuery(slug)}`),
  portalConversationMessages: (slug: string, leadRef: number) =>
    req<any[]>(`/portal/conversations/${leadRef}/messages?${personaQuery(slug)}`),
  portalKnowledgeChatContext: (slug: string, leadRef: number, q?: string, limit = 12) => {
    const params = new URLSearchParams();
    params.set("persona_slug", slug);
    params.set("lead_ref", String(leadRef));
    params.set("limit", String(limit));
    if (q) params.set("q", q);
    return req<any>(`/portal/knowledge/chat-context?${params.toString()}`);
  },
  portalLeads: (slug: string, limit = 500) =>
    req<any[]>(`/portal/leads?${personaQuery(slug)}&limit=${limit}`),
  portalLead: (slug: string, leadRef: number | string) =>
    req<any>(`/portal/leads/${leadRef}?${personaQuery(slug)}`),
  updatePortalLead: (slug: string, leadRef: number | string, body: Record<string, unknown>) =>
    req<any>(`/portal/leads/${leadRef}?${personaQuery(slug)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  portalPauseAi: (slug: string, leadRef: number) =>
    req<{ ok: boolean; ai_paused: boolean }>(
      `/portal/leads/${leadRef}/ai/pause?${personaQuery(slug)}`,
      { method: "POST" },
    ),
  portalResumeAi: (slug: string, leadRef: number) =>
    req<{ ok: boolean; ai_paused: boolean }>(
      `/portal/leads/${leadRef}/ai/resume?${personaQuery(slug)}`,
      { method: "POST" },
    ),
  portalSendMessage: (slug: string, body: { lead_id: number; client_message_id: string; text: string }) =>
    req<{ ok: boolean; message_id: string; buffer_id: string; status: string; deduplicated: boolean }>(
      `/portal/messages?${personaQuery(slug)}`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  portalPipeline: (slug: string) => req<any>(`/portal/pipeline?${personaQuery(slug)}`),
  personaAutomation: (slug: string) =>
    req<{ mode: "ai_with_handoff" | "human_only" }>(`/portal/personas/${encodeURIComponent(slug)}/automation`),
  updatePersonaAutomation: (slug: string, mode: "ai_with_handoff" | "human_only") =>
    req<{ ok: boolean; mode: string }>(`/portal/personas/${encodeURIComponent(slug)}/automation`, {
      method: "PATCH",
      body: JSON.stringify({ mode }),
    }),
  whatsappChannel: (slug: string) => req<any>(`/portal/personas/${encodeURIComponent(slug)}/channels/whatsapp`),
  whatsappMetaBinding: (slug: string) =>
    req<any>(`/integrations/meta/whatsapp/personas/${encodeURIComponent(slug)}`),
  updateWhatsAppMetaBinding: (slug: string, body: {
    phone_number_id: string;
    whatsapp_number?: string;
    workflow_name?: string;
    business_id?: string;
    waba_id?: string;
    verified_name?: string;
    mode?: "disabled" | "test_allowlist" | "active";
    allowlist?: string[];
    agent_id?: string;
    conversation_mode?: "deterministic";
  }) => req<any>(`/integrations/meta/whatsapp/personas/${encodeURIComponent(slug)}/binding`, {
    method: "PUT",
    body: JSON.stringify(body),
  }),
  provisionEvolution: (slug: string) => req<any>(`/portal/personas/${encodeURIComponent(slug)}/channels/whatsapp/evolution/provision`, { method: "POST", body: "{}" }),
  selectWhatsAppProvider: (slug: string, provider: "meta_cloud" | "evolution_baileys", confirmed: boolean) =>
    req<any>(`/portal/personas/${encodeURIComponent(slug)}/channels/whatsapp/provider`, { method: "POST", body: JSON.stringify({ provider, confirmed }) }),
  connectEvolution: (slug: string) => req<any>(`/portal/personas/${encodeURIComponent(slug)}/channels/whatsapp/evolution/connect`, { method: "POST", body: "{}" }),
  restartEvolution: (slug: string) => req<any>(`/portal/personas/${encodeURIComponent(slug)}/channels/whatsapp/evolution/restart`, { method: "POST", body: "{}" }),
  logoutEvolution: (slug: string) => req<any>(`/portal/personas/${encodeURIComponent(slug)}/channels/whatsapp/evolution/logout`, { method: "POST", body: "{}" }),
  revokeAndReconnectEvolution: (slug: string) => req<any>(`/portal/personas/${encodeURIComponent(slug)}/channels/whatsapp/evolution/revoke-and-reconnect`, { method: "POST", body: "{}" }),
  accessMembers: (slug: string) => req<any[]>(`/access/personas/${encodeURIComponent(slug)}/members`),
  createAccessMember: (slug: string, body: any) => req<any>(`/access/personas/${encodeURIComponent(slug)}/members`, { method: "POST", body: JSON.stringify(body) }),
  updateAccessMember: (slug: string, userId: string, body: any) => req<any>(`/access/personas/${encodeURIComponent(slug)}/members/${encodeURIComponent(userId)}`, { method: "PATCH", body: JSON.stringify(body) }),
  revokeAccessMember: (slug: string, userId: string) => req<any>(`/access/personas/${encodeURIComponent(slug)}/members/${encodeURIComponent(userId)}`, { method: "DELETE" }),

  // KB
  kb: (personaId?: string, status = "ATIVO") => req<any[]>(`/kb?status=${status}${personaId ? `&persona_id=${personaId}` : ""}`),
  syncKb: (personaId: string) => req(`/kb/sync?persona_id=${personaId}`, { method: "POST" }),

  // Personas
  personas: () => req<any[]>("/personas"),
  createPersona: (body: {
    slug: string;
    name: string;
    tone?: string | null;
    products?: string[];
    prompts?: Record<string, string>;
    config?: Record<string, any>;
    catalog_url?: string | null;
  }) => req<any>("/personas", { method: "POST", body: JSON.stringify(body) }),
  persona: (slug: string) => req<any>(`/personas/${slug}`),
  updatePersonaCatalogUrl: (slug: string, catalog_url: string | null) =>
    req<any>(`/personas/${slug}`, { method: "PATCH", body: JSON.stringify({ catalog_url }) }),
  publicSiteFormats: () => req<any[]>("/api/public-site-formats"),
  personaPublicSite: (slug: string) => req<any>(`/personas/${encodeURIComponent(slug)}/public-site`),
  updatePersonaPublicSite: (slug: string, body: {
    site_slug?: string;
    site_name?: string;
    format_key?: string;
    default_collection_slug?: string;
    whatsapp_phone?: string;
    whatsapp_message_template?: string;
    catalog_url?: string | null;
  }) => req<any>(`/personas/${encodeURIComponent(slug)}/public-site`, { method: "PATCH", body: JSON.stringify(body) }),
  audiences: (personaId: string) => req<any[]>(`/audiences?persona_id=${encodeURIComponent(personaId)}`),
  createAudience: (body: { persona_id: string; name: string; slug?: string; description?: string; source_type?: string }) =>
    req<any>("/audiences", { method: "POST", body: JSON.stringify(body) }),
  updateAudience: (audienceId: string, body: { name?: string; slug?: string; description?: string }) =>
    req<any>(`/audiences/${encodeURIComponent(audienceId)}`, { method: "PATCH", body: JSON.stringify(body) }),
  audienceLeads: (audienceId: string, limit = 1000, offset = 0) =>
    req<any>(`/audiences/${encodeURIComponent(audienceId)}/leads?limit=${limit}&offset=${offset}`),

  // Persona Routing
  personaRouting: (slug: string) =>
    req<any>(`/personas/${slug}/routing`),
  updatePersonaRouting: (slug: string, body: any) => 
    req<any>(`/personas/${slug}/routing`, { method: "PATCH", body: JSON.stringify(body) }),
  testPersonaRouting: (slug: string) =>
    req<any>(`/personas/${slug}/routing/test`,{ method: "POST", body: "{}" }),

  // Integrations & Logs
  integrations: () => req<any[]>("/integrations/user"),
  integrationCatalog: () => req<any[]>("/integrations/catalog"),
  updateUserIntegration: (
    service: string,
    body: {
      enabled: boolean;
      service_account_json?: string | Record<string, any>;
      spreadsheet_id?: string;
      api_key?: string;
      base_id?: string;
      access_token?: string;
      business_id?: string;
      catalog_id?: string;
    },
  ) => req<any>(`/integrations/user/${encodeURIComponent(service)}`, { method: "PUT", body: JSON.stringify(body) }),
  validateUserIntegration: (
    service: string,
    body?: {
      service_account_json?: string | Record<string, any>;
      spreadsheet_id?: string;
      api_key?: string;
      base_id?: string;
      access_token?: string;
      business_id?: string;
      catalog_id?: string;
    },
  ) => req<any>(`/integrations/user/${encodeURIComponent(service)}/validate`, { method: "POST", body: JSON.stringify(body || {}) }),
  deleteUserIntegrationCredentials: (service: string) =>
    req<any>(`/integrations/user/${encodeURIComponent(service)}/credentials`, { method: "DELETE" }),
  personaIntegrations: (slug: string) =>
    req<any[]>(`/integrations/personas/${encodeURIComponent(slug)}`),
  updatePersonaIntegration: (
    slug: string,
    service: string,
    body: {
      enabled: boolean;
      api_key?: string;
      access_token?: string;
      business_id?: string;
      catalog_id?: string;
      service_account_json?: string | Record<string, any>;
      spreadsheet_id?: string;
      base_id?: string;
    },
  ) => req<any>(
    `/integrations/personas/${encodeURIComponent(slug)}/${encodeURIComponent(service)}`,
    { method: "PUT", body: JSON.stringify(body) },
  ),
  validatePersonaIntegration: (slug: string, service: string) =>
    req<any>(
      `/integrations/personas/${encodeURIComponent(slug)}/${encodeURIComponent(service)}/validate`,
      { method: "POST", body: "{}" },
    ),
  deletePersonaIntegrationCredentials: (slug: string, service: string) =>
    req<any>(
      `/integrations/personas/${encodeURIComponent(slug)}/${encodeURIComponent(service)}/credentials`,
      { method: "DELETE" },
    ),
  n8nLogs: (limit = 100, status?: string) => req<any[]>(`/logs/n8n?limit=${limit}${status ? `&status=${status}` : ""}`),
  agentLogs: (leadId?: string, limit = 50, personaId?: string) =>
    req<any[]>(`/logs/agents?limit=${limit}${leadId ? `&lead_id=${leadId}` : ""}${personaId ? `&persona_id=${personaId}` : ""}`),
  auditLogs: (params: {
    entity_type?: string;
    event_type?: string;
    persona_id?: string;
    entity_id?: string;
    since?: string;
    search?: string;
    limit?: number;
  } = {}) => {
    const qs = new URLSearchParams();
    if (params.entity_type) qs.set("entity_type", params.entity_type);
    if (params.event_type) qs.set("event_type", params.event_type);
    if (params.persona_id) qs.set("persona_id", params.persona_id);
    if (params.entity_id) qs.set("entity_id", params.entity_id);
    if (params.since) qs.set("since", params.since);
    if (params.search) qs.set("search", params.search);
    qs.set("limit", String(params.limit ?? 200));
    return req<any[]>(`/logs/audit?${qs.toString()}`);
  },

  // Knowledge — Canonical taxonomy (single source of truth)
  knowledgeTaxonomy: (canonicalOnly = false) =>
    req<any>(`/knowledge/taxonomy${canonicalOnly ? "?canonical_only=true" : ""}`),

  // Knowledge — Vault Sync
  knowledgePreview: () => req<any>("/knowledge/import-vault/preview"),
  triggerSync: (persona?: string) => req<any>(`/knowledge/import-vault${persona ? `?persona=${persona}` : ""}`, { method: "POST" }),
  syncRuns: (limit = 20) => req<any[]>(`/knowledge/import-vault/runs?limit=${limit}`),
  syncRunLogs: (runId: string) => req<any[]>(`/knowledge/import-vault/runs/${runId}/logs`),

  // Knowledge — Single item fetch
  queueItem: (id: string) => req<any>(`/knowledge/queue/${id}`),
  kbEntry: (id: string) => req<any>(`/knowledge/kb/${id}`),
  updateKbEntry: (id: string, data: Record<string, any>) =>
    req<any>(`/knowledge/kb/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  validateKbEntry: (id: string) =>
    req<any>(`/knowledge/kb/${id}/validate`, { method: "POST" }),

  // Knowledge — Queue
  knowledgeQueue: (status = "pending", personaId?: string, contentType?: string) => {
    const params = new URLSearchParams({ status });
    if (personaId) params.set("persona_id", personaId);
    if (contentType) params.set("content_type", contentType);
    return req<any[]>(`/knowledge/queue?${params}`);
  },
  galleryAssets: (personaId?: string) =>
    req<any[]>(`/knowledge/gallery-assets${personaId ? `?persona_id=${personaId}` : ""}`),
  productCollections: (opts?: { persona_id?: string; persona_slug?: string }) => {
    const params = new URLSearchParams();
    if (opts?.persona_id) params.set("persona_id", opts.persona_id);
    if (opts?.persona_slug) params.set("persona_slug", opts.persona_slug);
    const qs = params.toString();
    return req<any[]>(`/knowledge/product-collections${qs ? `?${qs}` : ""}`);
  },
  productCategories: (opts?: { persona_id?: string; persona_slug?: string; collection_slug?: string }) => {
    const params = new URLSearchParams();
    if (opts?.persona_id) params.set("persona_id", opts.persona_id);
    if (opts?.persona_slug) params.set("persona_slug", opts.persona_slug);
    if (opts?.collection_slug) params.set("collection_slug", opts.collection_slug);
    const qs = params.toString();
    return req<any[]>(`/knowledge/categories${qs ? `?${qs}` : ""}`);
  },
  products: (opts?: { persona_id?: string; persona_slug?: string; collection_slug?: string; category_slug?: string; status?: string }) => {
    const params = new URLSearchParams();
    if (opts?.persona_id) params.set("persona_id", opts.persona_id);
    if (opts?.persona_slug) params.set("persona_slug", opts.persona_slug);
    if (opts?.collection_slug) params.set("collection_slug", opts.collection_slug);
    if (opts?.category_slug) params.set("category_slug", opts.category_slug);
    if (opts?.status) params.set("status", opts.status);
    const qs = params.toString();
    return req<any[]>(`/knowledge/products${qs ? `?${qs}` : ""}`);
  },
  menuPayload: (personaSlug: string, opts?: { collection_slug?: string }) => {
    const params = new URLSearchParams();
    if (opts?.collection_slug) params.set("collection_slug", opts.collection_slug);
    const qs = params.toString();
    return req<any>(`/api/menu/${encodeURIComponent(personaSlug)}${qs ? `?${qs}` : ""}`);
  },
  createProduct: (body: any) =>
    req<any>("/knowledge/products", { method: "POST", body: JSON.stringify(body) }),
  importProducts: (
    provider: "meta" | "shopify" | "scraper",
    opts: { persona_id?: string; persona_slug?: string; config?: Record<string, any>; items?: any[]; download_images?: boolean },
  ) =>
    req<any>("/knowledge/products/import", {
      method: "POST",
      body: JSON.stringify({
        provider,
        persona_id: opts.persona_id,
        persona_slug: opts.persona_slug,
        config: opts.config,
        items: opts.items,
        download_images: opts.download_images,
      }),
    }),
  previewImport: (
    provider: "meta" | "shopify" | "scraper",
    opts: { persona_id?: string; persona_slug?: string; config?: Record<string, any> },
  ) =>
    req<any>("/knowledge/products/import/preview", {
      method: "POST",
      body: JSON.stringify({ provider, persona_id: opts.persona_id, persona_slug: opts.persona_slug, config: opts.config }),
    }),
  importProductsCsv: (file: File, opts: { persona_id?: string; persona_slug?: string }) => {
    const form = new FormData();
    form.append("file", file);
    if (opts.persona_id) form.append("persona_id", opts.persona_id);
    if (opts.persona_slug) form.append("persona_slug", opts.persona_slug);
    return reqForm<any>("/knowledge/products/import/csv", form);
  },
  product: (slug: string, opts?: { persona_id?: string; persona_slug?: string }) => {
    const params = new URLSearchParams();
    if (opts?.persona_id) params.set("persona_id", opts.persona_id);
    if (opts?.persona_slug) params.set("persona_slug", opts.persona_slug);
    const qs = params.toString();
    return req<any>(`/knowledge/products/${encodeURIComponent(slug)}${qs ? `?${qs}` : ""}`);
  },
  updateProduct: (slug: string, body: any, opts?: { persona_id?: string; persona_slug?: string }) => {
    const params = new URLSearchParams();
    if (opts?.persona_id) params.set("persona_id", opts.persona_id);
    if (opts?.persona_slug) params.set("persona_slug", opts.persona_slug);
    const qs = params.toString();
    return req<any>(`/knowledge/products/${encodeURIComponent(slug)}${qs ? `?${qs}` : ""}`, { method: "PATCH", body: JSON.stringify(body) });
  },
  approveProduct: (slug: string, opts?: { persona_id?: string; persona_slug?: string }) => {
    const params = new URLSearchParams();
    if (opts?.persona_id) params.set("persona_id", opts.persona_id);
    if (opts?.persona_slug) params.set("persona_slug", opts.persona_slug);
    const qs = params.toString();
    return req<any>(`/knowledge/products/${encodeURIComponent(slug)}/approve${qs ? `?${qs}` : ""}`, { method: "POST", body: "{}" });
  },
  linkProductAsset: (slug: string, body: any, opts?: { persona_id?: string; persona_slug?: string }) => {
    const params = new URLSearchParams();
    if (opts?.persona_id) params.set("persona_id", opts.persona_id);
    if (opts?.persona_slug) params.set("persona_slug", opts.persona_slug);
    const qs = params.toString();
    return req<any>(`/knowledge/products/${encodeURIComponent(slug)}/link-asset${qs ? `?${qs}` : ""}`, { method: "POST", body: JSON.stringify(body) });
  },
  sofiaSuggestProductImages: (slug: string, body: any, opts?: { persona_id?: string; persona_slug?: string }) => {
    const params = new URLSearchParams();
    if (opts?.persona_id) params.set("persona_id", opts.persona_id);
    if (opts?.persona_slug) params.set("persona_slug", opts.persona_slug);
    const qs = params.toString();
    return req<any>(`/knowledge/products/${encodeURIComponent(slug)}/sofia-suggest-images${qs ? `?${qs}` : ""}`, { method: "POST", body: JSON.stringify(body || {}) });
  },

  // Assets (card upload pipeline)
  assetUpload: (
    file: File,
    body: { persona_id: string; branch_hint: string; asset_function?: string; persona_slug?: string },
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("persona_id", body.persona_id);
    form.append("branch_hint", body.branch_hint);
    if (body.asset_function) form.append("asset_function", body.asset_function);
    if (body.persona_slug) form.append("persona_slug", body.persona_slug);
    return reqForm<any>("/assets/upload", form);
  },
  assetList: (opts?: { persona_id?: string; upload_context?: string; status?: string; limit?: number; offset?: number }) => {
    const params = new URLSearchParams();
    if (opts?.persona_id) params.set("persona_id", opts.persona_id);
    if (opts?.upload_context) params.set("upload_context", opts.upload_context);
    if (opts?.status) params.set("status", opts.status);
    if (opts?.limit) params.set("limit", String(opts.limit));
    if (opts?.offset) params.set("offset", String(opts.offset));
    const qs = params.toString();
    return req<any[]>(`/assets${qs ? `?${qs}` : ""}`);
  },
  assetGet: (id: string) => req<any>(`/assets/${encodeURIComponent(id)}`),
  assetUpdate: (id: string, body: { asset_type?: string | null; asset_function?: string | null }) =>
    req<any>(`/assets/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) }),
  assetConnect: (id: string, body: { parent_node_id: string; relation_type?: string }) =>
    req<any>(`/assets/${encodeURIComponent(id)}/connect`, { method: "POST", body: JSON.stringify(body) }),
  assetEnsureGallery: (id: string) =>
    req<any>(`/assets/${encodeURIComponent(id)}/ensure-gallery`, { method: "POST", body: "{}" }),
  assetConnections: (id: string) =>
    req<{
      asset_id: string;
      knowledge_node_id: string | null;
      connections: Array<{
        edge_id: string;
        relation_type: string;
        slot_key: string | null;
        page_section: string | null;
        label: string | null;
        position: number | null;
        role: string | null;
        parent_node: {
          id: string;
          slug: string | null;
          node_type: string | null;
          title: string | null;
          collection_slug: string | null;
        };
        slot_options: Array<{ slot_key: string; label: string }>;
      }>;
    }>(`/assets/${encodeURIComponent(id)}/connections`),
  assetBindSlot: (
    id: string,
    body: {
      slot: string;
      persona_slug?: string;
      target_slug?: string | null;
      collection_slug?: string | null;
      position?: number;
      label?: string | null;
    },
  ) =>
    req<any>(`/assets/${encodeURIComponent(id)}/bind-slot`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  assetRebindPath: (
    id: string,
    body: {
      slot: string;
      persona_slug?: string;
      target_slug?: string | null;
      collection_slug?: string | null;
      position?: number;
      label?: string | null;
      remove_existing?: boolean;
    },
  ) =>
    req<any>(`/assets/${encodeURIComponent(id)}/rebind-path`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  assetLandingTargets: (id: string) =>
    req<{
      asset_id: string;
      targets: Array<{
        slot_key: string;
        slot_label: string;
        parent_node_type: string;
        target_slug: string | null;
        collection_slug: string | null;
        label: string;
        node_id: string;
      }>;
    }>(`/assets/${encodeURIComponent(id)}/landing-targets`),
  assetValidatePath: (id: string) =>
    req<{ asset_id: string; ok: boolean; errors: string[]; connections: any[] }>(
      `/assets/${encodeURIComponent(id)}/validate-path`,
      { method: "POST", body: "{}" },
    ),
  assetApprove: (id: string) =>
    req<any>(`/assets/${encodeURIComponent(id)}/approve`, { method: "POST", body: "{}" }),
  assetReject: (id: string) =>
    req<any>(`/assets/${encodeURIComponent(id)}/reject`, { method: "POST", body: "{}" }),
  assetUnbindSlot: (id: string, slotKey: string, targetSlug?: string | null) => {
    const qs = targetSlug ? `?target_slug=${encodeURIComponent(targetSlug)}` : "";
    return req<{ success: boolean; removed: number; edge_ids?: string[] }>(
      `/assets/${encodeURIComponent(id)}/bind-slot/${encodeURIComponent(slotKey)}${qs}`,
      { method: "DELETE" },
    );
  },
  assetDelete: (id: string) =>
    req<any>(`/assets/${encodeURIComponent(id)}`, { method: "DELETE" }),
  knowledgeCounts: (personaId?: string) =>
    req<any>(`/knowledge/queue/counts${personaId ? `?persona_id=${personaId}` : ""}`),
  updateQueueItem: (id: string, data: Record<string, any>) =>
    req<any>(`/knowledge/queue/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  approveItem: async (id: string, promoteToKb = false) => {
    const result = await req<any>(`/knowledge/queue/${id}/approve`, { method: "POST", body: JSON.stringify({ promote_to_kb: promoteToKb }) });
    if (result?.success === false) {
      throw new Error(result?.error || `Approval failed at ${result?.stage || "unknown_stage"}`);
    }
    return result;
  },
  rejectItem: (id: string, reason = "") =>
    req<any>(`/knowledge/queue/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) }),
  deleteKnowledgeItem: (id: string) =>
    req<any>(`/knowledge/queue/${id}`, { method: "DELETE" }),
  promoteToKb: (id: string) => req<any>(`/knowledge/queue/${id}/to-kb`, { method: "POST" }),

  // Knowledge — Upload
  uploadText: (body: { title: string; content: string; persona_id?: string; content_type?: string; metadata?: any }) =>
    req<any>("/knowledge/upload/text", { method: "POST", body: JSON.stringify(body) }),
  uploadFile: (file: File, personaId?: string, contentType = "other") => {
    const form = new FormData();
    form.append("file", file);
    if (personaId) form.append("persona_id", personaId);
    form.append("content_type", contentType);
    return reqForm<any>("/knowledge/upload/file", form);
  },

  // Knowledge — Bindings & Brand
  intakeKnowledge: (body: {
    raw_text: string;
    persona_id?: string;
    persona_slug?: string;
    source?: string;
    source_ref?: string;
    title?: string;
    content_type?: string;
    tags?: string[];
    metadata?: Record<string, any>;
    submitted_by?: string;
    validate?: boolean;
    parent_node_id?: string;
    parent_relation_type?: string;
  }) => req<any>("/knowledge/intake", { method: "POST", body: JSON.stringify(body) }),
  intakeKnowledgePlan: (body: {
    persona_id?: string;
    persona_slug?: string;
    run_token?: string;
    entries: any[];
    links?: any[];
    source?: string;
    source_ref?: string;
    submitted_by?: string;
    validate?: boolean;
  }) => req<any>("/knowledge/intake/plan", { method: "POST", body: JSON.stringify(body) }),
  workflowBindings: (personaId?: string) => req<any[]>(`/knowledge/bindings${personaId ? `?persona_id=${personaId}` : ""}`),
  brandProfile: (personaId: string) => req<any>(`/knowledge/brand/${personaId}`),

  // KB Intake (conversational classifier)
  kbIntakeModels: () => req<any[]>("/kb-intake/models"),
  kbIntakeStart: (model: string, initial_context = "", state?: Record<string, any>) =>
    req<any>("/kb-intake/start", { method: "POST", body: JSON.stringify({ model, initial_context, ...(state || {}) }) }),
  kbIntakeSession: (session_id: string) => req<any>(`/kb-intake/session/${encodeURIComponent(session_id)}`),
  kbIntakeUpdatePlan: (session_id: string, body: { knowledge_plan: any; status?: string; last_change?: string }) =>
    req<any>(`/kb-intake/session/${encodeURIComponent(session_id)}/plan`, { method: "PATCH", body: JSON.stringify(body) }),
  kbIntakeMessage: (session_id: string, message: string, file?: File) => {
    if (file) {
      const form = new FormData();
      form.append("session_id", session_id);
      form.append("message", message);
      form.append("file", file);
      return reqForm<any>("/kb-intake/upload", form);
    }
    return req<any>("/kb-intake/message", { method: "POST", body: JSON.stringify({ session_id, message }) });
  },
  kbIntakeSave: (session_id: string, content = "", plan_override?: any) =>
    req<any>("/kb-intake/save", { method: "POST", body: JSON.stringify({ session_id, content, plan_override }) }),
  kbIntakeCrawlPreview: (url: string, session_id?: string) =>
    req<any>("/kb-intake/crawl-preview", { method: "POST", body: JSON.stringify({ url, session_id }) }),

  // Knowledge Graph
  graphData: (personaSlug?: string, opts?: any) => {
    const params = new URLSearchParams();
    if (personaSlug) params.set("persona_slug", personaSlug);
    if (opts?.audienceSlug) params.set("audience_slug", opts.audienceSlug);
    if (opts?.focus) params.set("focus", opts.focus);
    if (typeof opts?.max_depth === "number") params.set("max_depth", String(opts.max_depth));
    if (opts?.include_tags) params.set("include_tags", "true");
    if (opts?.include_mentions) params.set("include_mentions", "true");
    if (opts?.include_technical) params.set("include_technical", "true");
    if (opts?.include_embedded === false) params.set("include_embedded", "false");
    if (opts?.mode) params.set("mode", opts.mode);
    const qs = params.toString();
    return req<any>(`/knowledge/graph-data${qs ? `?${qs}` : ""}`);
  },
  getGraphDocument: (personaSlug: string) => {
    const params = new URLSearchParams();
    params.set("persona_slug", personaSlug);
    return req<any>(`/graph-documents/current?${params.toString()}`);
  },
  // Canonical write path: publish the edited graph_json. The backend validates
  // the whole document and materializes the derived knowledge_nodes/edges (reindex).
  publishGraphDocument: (body: { persona_slug: string; brand_slug?: string | null; graph_json: any; source?: string; note?: string; expected_version?: number; idempotency_key?: string }) =>
    req<any>("/graph-documents/publish", { method: "POST", body: JSON.stringify({ source: "graph_ui", ...body }) }),
  applyGraphPatch: (body: { persona_slug: string; graph_json: any; source?: string; note?: string; expected_version?: number; idempotency_key?: string }) =>
    req<any>("/graph-documents/apply-patch", { method: "POST", body: JSON.stringify({ source: "graph_ui_patch", ...body }) }),
  syncGraphDocument: (body: { persona_slug: string; brand_slug?: string | null; idempotency_key?: string }) =>
    req<any>("/graph-documents/sync", { method: "POST", body: JSON.stringify(body) }),
  createGraphEdge: (body: { source_node_id: string; target_node_id: string; relation_type?: string; persona_id?: string; weight?: number; metadata?: any }) =>
    req<any>("/knowledge/graph-edges", { method: "POST", body: JSON.stringify(body) }),
  deleteGraphEdge: (edgeId: string) =>
    req<any>(`/knowledge/graph-edges/${encodeURIComponent(edgeId)}`, { method: "DELETE" }),
  deleteGraphNode: (nodeId: string) =>
    req<any>(`/knowledge/graph-nodes/${encodeURIComponent(nodeId)}`, { method: "DELETE" }),
  updateGraphNode: (
    nodeId: string,
    body: { title?: string; markdown?: string; summary?: string; tags?: string[]; status?: string },
  ) =>
    req<any>(`/knowledge/graph-nodes/${encodeURIComponent(nodeId)}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  sofiaGraphCommand: (body: {
    message?: string;
    action?: "command" | "confirm_pending" | "undo_pending";
    persona_slug?: string;
    tenant?: string;
    session_id?: string;
    plan_json?: Record<string, any> | null;
    pending_context?: Record<string, any>;
    active_persona_slug?: string;
    selected_node_id?: string | null;
    selected_node_ids?: string[];
  }) => {
    const action = body.action || "command";
    const explicit = String(body.message || "").trim();
    const command = explicit || (action === "command" ? "" : action);
    return req<any>("/sofia/graph-command", {
      method: "POST",
      body: JSON.stringify({
        persona_slug: body.persona_slug,
        command,
        context: {
          client_action: action === "command" ? "natural_language" : "ui_action",
          session_id: body.session_id || null,
          active_persona_slug: body.active_persona_slug || body.persona_slug || null,
          selected_node_id: body.selected_node_id || null,
          selected_node_ids: body.selected_node_ids || [],
          plan_json: body.plan_json || null,
          pending_context: body.pending_context || {},
        },
      }),
    });
  },

  // Sofia FAQ tool (adaptar_faqs_universais_ao_grafo)
  sofiaFaqGenerate: (body: {
    persona_slug?: string;
    session_id?: string | null;
    selected_node_id?: string | null;
    count?: number;
  }) => {
    const qty = body.count && body.count > 0 ? ` ${body.count}` : "";
    return req<any>("/sofia/graph-command", {
      method: "POST",
      body: JSON.stringify({
        persona_slug: body.persona_slug,
        command: `gere${qty} perguntas de FAQ para esse node`,
        context: {
          client_action: "natural_language",
          session_id: body.session_id || null,
          active_persona_slug: body.persona_slug || null,
          selected_node_id: body.selected_node_id || null,
          selected_node_ids: body.selected_node_id ? [body.selected_node_id] : [],
        },
      }),
    });
  },
  sofiaFaqAccept: (body: {
    persona_slug?: string;
    parent_node_id: string;
    parent_node_type?: string;
    faq_generation_count?: number;
    source_context?: Record<string, any>;
    generated_from_node_id?: string;
    generated_from_node_slug?: string;
    suggestions: Array<{ question: string; answer?: string }>;
  }) =>
    req<any>("/sofia/faq/accept", { method: "POST", body: JSON.stringify(body) }),
  // "Gerar" on a FAQ node appends accepted suggestions to that same FAQ's body.
  sofiaFaqAppend: (body: {
    persona_slug?: string;
    faq_node_id: string;
    suggestions: Array<{ question: string; answer?: string }>;
  }) =>
    req<any>("/sofia/faq/append", { method: "POST", body: JSON.stringify(body) }),

  // Knowledge — Chat sidebar context (semantic graph + KB fallback)
  knowledgeChatContext: (leadRef: number, q?: string, personaId?: string) => {
    const params = new URLSearchParams();
    params.set("lead_ref", String(leadRef));
    if (q) params.set("q", q);
    if (personaId) params.set("persona_id", personaId);
    return req<any>(`/knowledge/chat-context?${params.toString()}`);
  },
  knowledgeCatalog: (opts: { personaId?: string; personaSlug?: string } = {}) => {
    const params = new URLSearchParams();
    if (opts.personaId) params.set("persona_id", opts.personaId);
    if (opts.personaSlug) params.set("persona_slug", opts.personaSlug);
    const query = params.toString();
    return req<any>(`/knowledge/catalog${query ? `?${query}` : ""}`);
  },

  // Marketing
  marketingModes: () => req<any>("/marketing/modes"),
  marketingGenerate: (body: any) =>
    req<any>("/marketing/generate", { method: "POST", body: JSON.stringify(body) }),

  // WA Validator
  waBots: () => req<any[]>("/wa-validator/bots"),
  waFlows: () => req<any[]>("/wa-validator/flows"),
  waModels: () => req<any[]>("/wa-validator/models"),
  waSessions: () => req<any[]>("/wa-validator/sessions"),
  waSession: (id: string) => req<any>(`/wa-validator/sessions/${id}`),
  waGenerateScript: (body: any) =>
    req<any>("/wa-validator/generate-script", { method: "POST", body: JSON.stringify(body) }),
  waRun: (session_id: string) =>
    req<any>("/wa-validator/run", { method: "POST", body: JSON.stringify({ session_id }) }),
  waRunDirect: (session_id: string) =>
    req<any>("/wa-validator/run-direct", { method: "POST", body: JSON.stringify({ session_id }) }),
  waAnalyze: (session_id: string, model?: string) =>
    req<any>("/wa-validator/analyze", { method: "POST", body: JSON.stringify({ session_id, model }) }),

  // Pipeline
  pipelineStatus: () => req<any[]>("/pipeline/status"),
  pipelineMetrics: (personaId?: string) =>
    req<any>(`/pipeline/metrics${personaId ? `?persona_id=${personaId}` : ""}`),
  pipelineEvents: (limit = 50, eventType?: string, personaId?: string) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (eventType) params.set("event_type", eventType);
    if (personaId) params.set("persona_id", personaId);
    return req<any[]>(`/pipeline/events?${params.toString()}`);
  },
};
