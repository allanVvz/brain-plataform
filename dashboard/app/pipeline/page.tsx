"use client";
import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";

const STATUS_DOT: Record<string, string> = {
  online:     "bg-green-400",
  offline:    "bg-red-500",
  degraded:   "bg-yellow-400",
  error:      "bg-red-500",
  pending:    "bg-yellow-400",
  processing: "bg-blue-400 animate-pulse",
  unknown:    "bg-brain-muted",
};

const SERVICE_LABELS: Record<string, string> = {
  vault_sync:           "Vault Sync",
  knowledge_intake:     "Knowledge Intake",
  knowledge_validation: "Knowledge Validation",
  embedding_service:    "Embedding Service",
  flow_validator:       "Flow Validator",
  n8n_crm_vitoria:      "n8n CRM Vitória",
  supabase:             "Supabase",
  whatsapp_webhook:     "WhatsApp Webhook",
  mcp_figma:            "MCP Figma",
};

const COLUMNS: { label: string; services: string[] }[] = [
  {
    label: "Entradas",
    services: ["vault_sync", "knowledge_intake", "whatsapp_webhook", "mcp_figma"],
  },
  {
    label: "Processamento",
    services: ["knowledge_validation", "embedding_service", "flow_validator"],
  },
  {
    label: "Saídas",
    services: ["n8n_crm_vitoria", "supabase"],
  },
];

function fmt(ts: string | null) {
  if (!ts) return "—";
  const d = new Date(ts);
  return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function relTime(ts: string | null) {
  if (!ts) return "nunca";
  const diff = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
  if (diff < 60) return `${diff}s atrás`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m atrás`;
  return `${Math.floor(diff / 3600)}h atrás`;
}

export default function PipelinePage() {
  const [statuses, setStatuses] = useState<any[]>([]);
  const [metrics, setMetrics] = useState<any>({});
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [s, m, e] = await Promise.all([
        api.pipelineStatus(),
        api.pipelineMetrics(),
        api.pipelineEvents(30),
      ]);
      setStatuses(s);
      setMetrics(m);
      setEvents(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, [load]);

  const byService = Object.fromEntries(statuses.map((s) => [s.service, s]));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Pipeline em Tempo Real</h1>
          <p className="text-sm text-brain-muted mt-0.5">Status ao vivo de todos os serviços da plataforma</p>
        </div>
        <button
          onClick={load}
          className="text-xs text-brain-muted hover:text-white border border-brain-border px-3 py-1.5 rounded-md transition-colors">
          Atualizar
        </button>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {[
          { label: "Atenção necessária", value: metrics.pending_attention ?? "—", color: "text-yellow-400" },
          { label: "Aprovados hoje", value: metrics.approved_today ?? "—", color: "text-green-400" },
          { label: "Entradas na KB", value: metrics.kb_entries ?? "—", color: "text-blue-400" },
          { label: "Assets pendentes", value: metrics.assets_pending ?? "—", color: "text-orange-400" },
          { label: "Erros (24h)", value: metrics.errors_24h ?? "—", color: "text-red-400" },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-brain-surface border border-brain-border rounded-xl p-4 text-center">
            <div className={`text-2xl font-bold ${color}`}>{value}</div>
            <div className="text-[11px] text-brain-muted mt-1">{label}</div>
          </div>
        ))}
      </div>

      {/* Architecture flow */}
      <div className="grid grid-cols-3 gap-4">
        {COLUMNS.map(({ label, services }, ci) => (
          <div key={label} className="space-y-2">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xs font-semibold text-brain-muted uppercase tracking-widest">{label}</span>
              {ci < COLUMNS.length - 1 && (
                <span className="ml-auto text-brain-muted text-xs">→</span>
              )}
            </div>
            {services.map((svc) => {
              const row = byService[svc];
              const status = row?.status ?? "unknown";
              return (
                <div
                  key={svc}
                  className="bg-brain-surface border border-brain-border rounded-xl px-4 py-3 flex items-center gap-3">
                  <span className={`w-2 h-2 rounded-full shrink-0 ${STATUS_DOT[status] ?? "bg-brain-muted"}`} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-white truncate">
                      {SERVICE_LABELS[svc] ?? svc}
                    </div>
                    <div className="text-[11px] text-brain-muted mt-0.5">
                      {status} · {relTime(row?.last_activity ?? null)}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>

      {/* Live events feed */}
      <div>
        <h2 className="text-sm font-semibold text-brain-muted mb-3 uppercase tracking-widest">Eventos Recentes</h2>
        {loading && <p className="text-brain-muted text-sm">Carregando...</p>}
        <div className="bg-brain-surface border border-brain-border rounded-xl overflow-hidden">
          {events.length === 0 && !loading && (
            <div className="px-4 py-6 text-center text-brain-muted text-sm">Nenhum evento registrado.</div>
          )}
          {events.map((ev, i) => (
            <div
              key={ev.id ?? i}
              className={`px-4 py-2.5 flex items-center gap-3 text-sm ${
                i < events.length - 1 ? "border-b border-brain-border" : ""
              }`}>
              <span className="text-brain-muted font-mono text-xs shrink-0 w-20">
                {fmt(ev.created_at)}
              </span>
              <span className={`text-xs px-2 py-0.5 rounded-full font-medium shrink-0 ${
                ev.event_type?.includes("fail") || ev.event_type?.includes("error")
                  ? "bg-red-500/10 text-red-400"
                  : ev.event_type?.includes("approved") || ev.event_type?.includes("completed")
                  ? "bg-green-500/10 text-green-400"
                  : "bg-brain-border/50 text-brain-muted"
              }`}>
                {ev.event_type}
              </span>
              <span className="text-white flex-1 truncate">
                {ev.entity_type && (
                  <span className="text-brain-muted mr-1">{ev.entity_type}</span>
                )}
                {ev.payload && Object.keys(ev.payload).length > 0 && (
                  <span className="text-brain-muted">
                    {Object.entries(ev.payload)
                      .slice(0, 3)
                      .map(([k, v]) => `${k}: ${String(v).slice(0, 40)}`)
                      .join(" · ")}
                  </span>
                )}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
