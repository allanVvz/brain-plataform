const BASE = process.env.NEXT_PUBLIC_AI_BRAIN_URL || "http://localhost:8000";

async function req<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
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
  leads: (limit = 100, offset = 0) => req<any[]>(`/leads?limit=${limit}&offset=${offset}`),
  lead: (id: string) => req<any>(`/leads/${id}`),
  messages: (leadId: string) => req<any[]>(`/messages/${leadId}`),
  recentMessages: (hours = 24) => req<any[]>(`/messages?hours=${hours}`),

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

  // WA Validator
  waFlows: () => req<any[]>("/wa-validator/flows"),
  waModels: () => req<any[]>("/wa-validator/models"),
  waSessions: () => req<any[]>("/wa-validator/sessions"),
  waSession: (id: string) => req<any>(`/wa-validator/sessions/${id}`),
  waGenerateScript: (body: { persona_slug: string; flow_id: string; target_contact: string; model?: string }) =>
    req<any>("/wa-validator/generate-script", { method: "POST", body: JSON.stringify(body) }),
  waRun: (session_id: string) =>
    req<any>("/wa-validator/run", { method: "POST", body: JSON.stringify({ session_id }) }),
  waAnalyze: (session_id: string, model?: string) =>
    req<any>("/wa-validator/analyze", { method: "POST", body: JSON.stringify({ session_id, model }) }),

  // Pipeline
  pipelineStatus: () => req<any[]>("/pipeline/status"),
  pipelineMetrics: () => req<any>("/pipeline/metrics"),
  pipelineEvents: (limit = 50, eventType?: string) =>
    req<any[]>(`/pipeline/events?limit=${limit}${eventType ? `&event_type=${eventType}` : ""}`),
};
