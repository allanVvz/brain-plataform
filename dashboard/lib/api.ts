// Requests go through the Next.js rewrite proxy (/api-brain → backend).
// This avoids cross-origin CORS issues entirely, regardless of environment.
export const BASE = "/api-brain";

async function req<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
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
  const res = await fetch(`${BASE}${path}`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

export const api = {
  // Health & Insights
  health: () => req<any>("/health/score"),
  insights: (status?: string) => req<any[]>(`/insights${status ? `?status=${status}` : ""}`),
  updateInsight: (id: string, status: string) => req(`/insights/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  runValidator: () => req("/insights/run-validator", { method: "POST" }),
  healthHistory: (limit = 30) => req<any[]>(`/logs/health-history?limit=${limit}`),

  // Leads & Messages
  leads: (limit = 100, offset = 0, personaId?: string) =>
    req<any[]>(`/leads?limit=${limit}&offset=${offset}${personaId ? `&persona_id=${personaId}` : ""}`),
  lead: (id: string) => req<any>(`/leads/${id}`),
  pauseAi: (leadRef: number) => req<{ ok: boolean; ai_paused: boolean }>(`/leads/${leadRef}/pause-ai`, { method: "POST" }),
  resumeAi: (leadRef: number) => req<{ ok: boolean; ai_paused: boolean }>(`/leads/${leadRef}/resume-ai`, { method: "POST" }),
  messages: (leadId: string) => req<any[]>(`/messages/${leadId}`),
  messagesByRef: (leadRef: number, limit = 200) => req<any[]>(`/messages/by-ref/${leadRef}?limit=${limit}`),
  recentMessages: (hours = 24) => req<any[]>(`/messages?hours=${hours}`),
  conversations: (hours = 168, personaId?: string) =>
    req<any[]>(`/messages/conversations?hours=${hours}${personaId ? `&persona_id=${personaId}` : ""}`),
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

  // Integrations & Logs
  integrations: (personaId?: string) => req<any[]>(`/integrations${personaId ? `?persona_id=${personaId}` : ""}`),
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
  knowledgeCounts: () => req<any>("/knowledge/queue/counts"),
  updateQueueItem: (id: string, data: Record<string, any>) =>
    req<any>(`/knowledge/queue/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  approveItem: (id: string, promoteToKb = false) =>
    req<any>(`/knowledge/queue/${id}/approve`, { method: "POST", body: JSON.stringify({ promote_to_kb: promoteToKb }) }),
  rejectItem: (id: string, reason = "") =>
    req<any>(`/knowledge/queue/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) }),
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
  workflowBindings: (personaId?: string) => req<any[]>(`/knowledge/bindings${personaId ? `?persona_id=${personaId}` : ""}`),
  brandProfile: (personaId: string) => req<any>(`/knowledge/brand/${personaId}`),

  // KB Intake (conversational classifier)
  kbIntakeModels: () => req<any[]>("/kb-intake/models"),
  kbIntakeStart: (model: string) =>
    req<any>("/kb-intake/start", { method: "POST", body: JSON.stringify({ model }) }),
  kbIntakeMessage: (session_id: string, message: string) =>
    req<any>("/kb-intake/message", { method: "POST", body: JSON.stringify({ session_id, message }) }),
  kbIntakeSave: (session_id: string, content = "") =>
    req<any>("/kb-intake/save", { method: "POST", body: JSON.stringify({ session_id, content }) }),

  // Knowledge Graph
  graphData: (personaSlug?: string) =>
    req<any>(`/knowledge/graph-data${personaSlug ? `?persona_slug=${personaSlug}` : ""}`),

  // Knowledge — Chat sidebar context (semantic graph + KB fallback)
  knowledgeChatContext: (leadRef: number, q?: string, personaId?: string) => {
    const params = new URLSearchParams();
    params.set("lead_ref", String(leadRef));
    if (q) params.set("q", q);
    if (personaId) params.set("persona_id", personaId);
    return req<{
      query_terms: string[];
      nodes: any[];
      edges: any[];
      kb_entries: any[];
      assets: any[];
      summary: string;
    }>(`/knowledge/chat-context?${params.toString()}`);
  },

  // WA Validator
  waBots: () => req<any[]>("/wa-validator/bots"),
  waFlows: () => req<any[]>("/wa-validator/flows"),
  waModels: () => req<any[]>("/wa-validator/models"),
  waSessions: () => req<any[]>("/wa-validator/sessions"),
  waSession: (id: string) => req<any>(`/wa-validator/sessions/${id}`),
  waGenerateScript: (body: { persona_slug: string; flow_id: string; target_contact: string; model?: string }) =>
    req<any>("/wa-validator/generate-script", { method: "POST", body: JSON.stringify(body) }),
  waRun: (session_id: string) =>
    req<any>("/wa-validator/run", { method: "POST", body: JSON.stringify({ session_id }) }),
  waRunDirect: (session_id: string) =>
    req<any>("/wa-validator/run-direct", { method: "POST", body: JSON.stringify({ session_id }) }),
  waAnalyze: (session_id: string, model?: string) =>
    req<any>("/wa-validator/analyze", { method: "POST", body: JSON.stringify({ session_id, model }) }),

  // Pipeline
  pipelineStatus: () => req<any[]>("/pipeline/status"),
  pipelineMetrics: () => req<any>("/pipeline/metrics"),
  pipelineEvents: (limit = 50, eventType?: string) =>
    req<any[]>(`/pipeline/events?limit=${limit}${eventType ? `&event_type=${eventType}` : ""}`),
};
