// Browser requests go through the Next.js rewrite proxy.
import { getPublicApiUrl } from "@/utils/env";

export const BASE = "/api-brain";
export const API_URL = BASE;
const API_ENV_ERROR = "Backend nao configurado. Defina NEXT_PUBLIC_API_URL na Vercel.";
const API_OFFLINE_ERROR =
  "Backend indisponivel agora. Verifique NEXT_PUBLIC_API_URL, confirme o endpoint /health e tente novamente.";

function assertApiConfigured() {
  if (process.env.NODE_ENV === "production") {
    try {
      getPublicApiUrl();
    } catch {
      throw new Error(API_ENV_ERROR);
    }
  }
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
    throw new Error(API_OFFLINE_ERROR);
  }

  if (!res.ok) {
    if (res.status === 503) {
      throw new Error(API_OFFLINE_ERROR);
    }
    let detail = "";
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail || body);
    } catch {
      detail = await res.text().catch(() => "");
    }
    throw new Error(`${res.status} ${path}${detail ? ` - ${detail}` : ""}`);
  }
  return res.json();
}

async function reqForm<T>(path: string, form: FormData): Promise<T> {
  assertApiConfigured();
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { method: "POST", body: form, credentials: "include" });
  } catch {
    throw new Error(API_OFFLINE_ERROR);
  }
  if (res.status === 503) throw new Error(API_OFFLINE_ERROR);
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

export const api = {
  // Auth
  login: (body: { identifier: string; password: string; remember?: boolean }) =>
    req<any>("/auth/login", { method: "POST", body: JSON.stringify(body) }),
  me: () => req<any>("/auth/me"),
  logout: () => req<any>("/auth/logout", { method: "POST", body: "{}" }),

  // Health & Insights
  health: () => req<any>("/health/score"),
  insights: (status?: string) => req<any[]>(`/insights${status ? `?status=${status}` : ""}`),
  updateInsight: (id: string, status: string) => req(`/insights/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  runValidator: () => req("/insights/run-validator", { method: "POST" }),
  healthHistory: (limit = 30) => req<any[]>(`/logs/health-history?limit=${limit}`),

  // Leads & Messages
  leads: (limit = 100, offset = 0, personaId?: string) =>
    req<any[]>(`/leads?limit=${limit}&offset=${offset}${personaId ? `&persona_id=${personaId}` : ""}`),
  leadsScoped: (opts: {
    limit?: number;
    offset?: number;
    personaId?: string;
    personaSlug?: string;
    audienceId?: string;
    audienceSlug?: string;
  }) => {
    const params = new URLSearchParams();
    params.set("limit", String(opts.limit ?? 100));
    params.set("offset", String(opts.offset ?? 0));
    if (opts.personaId) params.set("persona_id", opts.personaId);
    if (opts.personaSlug) params.set("persona_slug", opts.personaSlug);
    if (opts.audienceId) params.set("audience_id", opts.audienceId);
    if (opts.audienceSlug) params.set("audience_slug", opts.audienceSlug);
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
  pauseAi: (leadRef: number) => req<{ ok: boolean; ai_paused: boolean }>(`/leads/${leadRef}/pause-ai`, { method: "POST" }),
  resumeAi: (leadRef: number) => req<{ ok: boolean; ai_paused: boolean }>(`/leads/${leadRef}/resume-ai`, { method: "POST" }),
  messages: (leadId: string) => req<any[]>(`/messages/${leadId}`),
  messagesByRef: (leadRef: number, limit = 200) => req<any[]>(`/messages/by-ref/${leadRef}?limit=${limit}`),
  messagesByRefScoped: (leadRef: number, opts: {
    limit?: number;
    personaId?: string;
    personaSlug?: string;
    audienceId?: string;
    audienceSlug?: string;
  }) => {
    const params = new URLSearchParams();
    params.set("limit", String(opts.limit ?? 200));
    if (opts.personaId) params.set("persona_id", opts.personaId);
    if (opts.personaSlug) params.set("persona_slug", opts.personaSlug);
    if (opts.audienceId) params.set("audience_id", opts.audienceId);
    if (opts.audienceSlug) params.set("audience_slug", opts.audienceSlug);
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
  conversations: (hours = 168, personaId?: string) =>
    req<any[]>(`/messages/conversations?hours=${hours}${personaId ? `&persona_id=${personaId}` : ""}`),
  conversationsScoped: (opts: {
    hours?: number;
    personaId?: string;
    personaSlug?: string;
    audienceId?: string;
    audienceSlug?: string;
  }) => {
    const params = new URLSearchParams();
    params.set("hours", String(opts.hours ?? 168));
    if (opts.personaId) params.set("persona_id", opts.personaId);
    if (opts.personaSlug) params.set("persona_slug", opts.personaSlug);
    if (opts.audienceId) params.set("audience_id", opts.audienceId);
    if (opts.audienceSlug) params.set("audience_slug", opts.audienceSlug);
    return req<any[]>(`/messages/conversations?${params.toString()}`);
  },
  sendMessage: (body: { lead_ref: number; texto: string; agent_id?: string; sender_id?: string; nome?: string }) =>
    req<{ ok: boolean; message_id: string; status: string; webhook_status?: number; webhook_error?: string }>(
      "/messages/send",
      { method: "POST", body: JSON.stringify(body) },
    ),

  // KB
  kb: (personaId?: string, status = "ATIVO") => req<any[]>(`/kb?status=${status}${personaId ? `&persona_id=${personaId}` : ""}`),
  syncKb: (personaId: string) => req(`/kb/sync?persona_id=${personaId}`, { method: "POST" }),

  // Personas
  personas: () => req<any[]>("/personas"),
  persona: (slug: string) => req<any>(`/personas/${slug}`),
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
    },
  ) => req<any>(`/integrations/user/${encodeURIComponent(service)}`, { method: "PUT", body: JSON.stringify(body) }),
  validateUserIntegration: (
    service: string,
    body?: {
      service_account_json?: string | Record<string, any>;
      spreadsheet_id?: string;
      api_key?: string;
      base_id?: string;
    },
  ) => req<any>(`/integrations/user/${encodeURIComponent(service)}/validate`, { method: "POST", body: JSON.stringify(body || {}) }),
  deleteUserIntegrationCredentials: (service: string) =>
    req<any>(`/integrations/user/${encodeURIComponent(service)}/credentials`, { method: "DELETE" }),
  n8nLogs: (limit = 100, status?: string) => req<any[]>(`/logs/n8n?limit=${limit}${status ? `&status=${status}` : ""}`),
  agentLogs: (leadId?: string, limit = 50) => req<any[]>(`/logs/agents?limit=${limit}${leadId ? `&lead_id=${leadId}` : ""}`),

  // Knowledge — Vault Sync
  knowledgePreview: () => req<any>("/knowledge/sync/preview"),
  triggerSync: (persona?: string) => req<any>(`/knowledge/sync${persona ? `?persona=${persona}` : ""}`, { method: "POST" }),
  syncRuns: (limit = 20) => req<any[]>(`/knowledge/sync/runs?limit=${limit}`),
  syncRunLogs: (runId: string) => req<any[]>(`/knowledge/sync/runs/${runId}/logs`),

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
  knowledgeCounts: (personaId?: string) =>
    req<any>(`/knowledge/queue/counts${personaId ? `?persona_id=${personaId}` : ""}`),
  updateQueueItem: (id: string, data: Record<string, any>) =>
    req<any>(`/knowledge/queue/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  approveItem: (id: string, promoteToKb = false) =>
    req<any>(`/knowledge/queue/${id}/approve`, { method: "POST", body: JSON.stringify({ promote_to_kb: promoteToKb }) }),
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
  kbIntakeStart: (model: string, initial_context = "") =>
    req<any>("/kb-intake/start", { method: "POST", body: JSON.stringify({ model, initial_context }) }),
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
  createGraphEdge: (body: { source_node_id: string; target_node_id: string; relation_type?: string; persona_id?: string; weight?: number; metadata?: any }) =>
    req<any>("/knowledge/graph-edges", { method: "POST", body: JSON.stringify(body) }),
  deleteGraphEdge: (edgeId: string) =>
    req<any>(`/knowledge/graph-edges/${encodeURIComponent(edgeId)}`, { method: "DELETE" }),
  deleteGraphNode: (nodeId: string) =>
    req<any>(`/knowledge/graph-nodes/${encodeURIComponent(nodeId)}`, { method: "DELETE" }),

  // Knowledge — Chat sidebar context (semantic graph + KB fallback)
  knowledgeChatContext: (leadRef: number, q?: string, personaId?: string) => {
    const params = new URLSearchParams();
    params.set("lead_ref", String(leadRef));
    if (q) params.set("q", q);
    if (personaId) params.set("persona_id", personaId);
    return req<any>(`/knowledge/chat-context?${params.toString()}`);
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
