"use client";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { formatDistanceToNow } from "date-fns";
import { ptBR } from "date-fns/locale";

type Tab = "n8n" | "agents" | "audit";

type AuditRow = {
  id?: string;
  event_type?: string;
  entity_type?: string;
  entity_id?: string;
  persona_id?: string;
  level?: string;
  source?: string;
  created_at?: string;
  payload?: any;
};

type Persona = { id: string; slug?: string; name?: string };

const ENTITY_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Todas as entidades" },
  { value: "asset", label: "Asset" },
  { value: "knowledge_node", label: "Knowledge node" },
  { value: "knowledge_edge", label: "Knowledge edge" },
  { value: "knowledge_item", label: "Knowledge item" },
  { value: "brand_profile", label: "Brand profile" },
  { value: "kb_entry", label: "KB entry" },
];

const SINCE_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Sempre" },
  { value: "24h", label: "Últimas 24h" },
  { value: "7d", label: "Últimos 7 dias" },
  { value: "30d", label: "Últimos 30 dias" },
];

function isoSinceFor(label: string): string | undefined {
  if (!label) return undefined;
  const now = new Date();
  if (label === "24h") now.setHours(now.getHours() - 24);
  else if (label === "7d") now.setDate(now.getDate() - 7);
  else if (label === "30d") now.setDate(now.getDate() - 30);
  else return undefined;
  return now.toISOString();
}

function renderDiff(diff: any) {
  if (!diff || typeof diff !== "object" || !diff.changed) return null;
  const entries = Object.entries(diff.changed as Record<string, { before: any; after: any }>);
  if (!entries.length) {
    return <div className="text-xs text-brain-muted">Nenhum campo mudou (apenas timestamps/metadados).</div>;
  }
  return (
    <div className="space-y-1.5">
      {entries.map(([key, change]) => (
        <div key={key} className="grid grid-cols-[140px_1fr] gap-2 text-xs">
          <div className="font-mono text-brain-muted truncate">{key}</div>
          <div className="space-y-0.5">
            <div className="text-red-700">
              <span className="text-brain-muted mr-1">antes:</span>
              <span className="font-mono break-all">{JSON.stringify(change.before)}</span>
            </div>
            <div className="text-emerald-700">
              <span className="text-brain-muted mr-1">depois:</span>
              <span className="font-mono break-all">{JSON.stringify(change.after)}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function actorLabel(payload: any): string {
  const actor = payload?.actor;
  if (!actor) return "—";
  return actor.email || actor.user_id || "—";
}

export default function LogsPage() {
  const [tab, setTab] = useState<Tab>("audit");
  const [n8nLogs, setN8nLogs] = useState<any[]>([]);
  const [agentLogs, setAgentLogs] = useState<any[]>([]);
  const [auditRows, setAuditRows] = useState<AuditRow[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Audit filters
  const [entityType, setEntityType] = useState<string>("");
  const [eventType, setEventType] = useState<string>("");
  const [personaId, setPersonaId] = useState<string>("");
  const [search, setSearch] = useState<string>("");
  const [sinceLabel, setSinceLabel] = useState<string>("7d");

  useEffect(() => {
    api.n8nLogs(100).then(setN8nLogs).catch(console.error);
    api.agentLogs(undefined, 100).then(setAgentLogs).catch(console.error);
    api.personas().then(setPersonas).catch(console.error);
  }, []);

  const loadAudit = () => {
    setAuditLoading(true);
    setAuditError(null);
    api
      .auditLogs({
        entity_type: entityType || undefined,
        event_type: eventType || undefined,
        persona_id: personaId || undefined,
        since: isoSinceFor(sinceLabel),
        search: search.trim() || undefined,
        limit: 200,
      })
      .then((rows) => setAuditRows(rows || []))
      .catch((err) => setAuditError(String(err?.message || err)))
      .finally(() => setAuditLoading(false));
  };

  useEffect(() => {
    if (tab !== "audit") return;
    loadAudit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const eventTypeOptions = useMemo(() => {
    const set = new Set<string>();
    auditRows.forEach((r) => r.event_type && set.add(r.event_type));
    return Array.from(set).sort();
  }, [auditRows]);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Logs</h1>

      <div className="flex gap-2">
        {(["audit", "agents", "n8n"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`text-sm px-4 py-1.5 rounded-md border transition-colors ${
              tab === t
                ? "bg-brain-accent/20 border-brain-accent text-brain-accent"
                : "border-brain-border text-brain-muted hover:text-white"
            }`}
          >
            {t === "audit" ? "Auditoria" : t === "n8n" ? "n8n Execuções" : "Agentes AI"}
          </button>
        ))}
      </div>

      {tab === "audit" && (
        <div className="space-y-3">
          <div className="bg-brain-surface border border-brain-border rounded-xl p-3 flex flex-wrap gap-2 items-center text-sm">
            <select
              value={entityType}
              onChange={(e) => setEntityType(e.target.value)}
              className="bg-transparent border border-brain-border rounded-md px-2 py-1"
            >
              {ENTITY_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>

            <select
              value={eventType}
              onChange={(e) => setEventType(e.target.value)}
              className="bg-transparent border border-brain-border rounded-md px-2 py-1"
            >
              <option value="">Todos os eventos</option>
              {eventTypeOptions.map((ev) => (
                <option key={ev} value={ev}>
                  {ev}
                </option>
              ))}
            </select>

            <select
              value={personaId}
              onChange={(e) => setPersonaId(e.target.value)}
              className="bg-transparent border border-brain-border rounded-md px-2 py-1"
            >
              <option value="">Todas as personas</option>
              {personas.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name || p.slug || p.id.slice(0, 8)}
                </option>
              ))}
            </select>

            <select
              value={sinceLabel}
              onChange={(e) => setSinceLabel(e.target.value)}
              className="bg-transparent border border-brain-border rounded-md px-2 py-1"
            >
              {SINCE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>

            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar no payload (slug, email, edge_id, ...)"
              className="bg-transparent border border-brain-border rounded-md px-2 py-1 flex-1 min-w-[220px]"
              onKeyDown={(e) => {
                if (e.key === "Enter") loadAudit();
              }}
            />

            <button
              onClick={loadAudit}
              className="text-sm px-3 py-1 rounded-md border border-brain-accent text-brain-accent hover:bg-brain-accent/10"
            >
              Aplicar
            </button>
            <span className="text-xs text-brain-muted ml-auto">
              {auditLoading ? "Carregando…" : `${auditRows.length} eventos`}
            </span>
          </div>

          {auditError && (
            <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-3 py-2 text-sm">
              {auditError}
            </div>
          )}

          <div className="bg-brain-surface border border-brain-border rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-brain-border text-brain-muted text-xs uppercase tracking-wide">
                  <th className="px-3 py-2 text-left w-32">Quando</th>
                  <th className="px-3 py-2 text-left">Evento</th>
                  <th className="px-3 py-2 text-left w-32">Entidade</th>
                  <th className="px-3 py-2 text-left">Ator</th>
                  <th className="px-3 py-2 text-left w-20">Nível</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-brain-border">
                {auditRows.map((row, idx) => {
                  const rowKey = row.id || `${row.event_type}-${row.created_at}-${idx}`;
                  const isExpanded = expandedId === rowKey;
                  const date = row.created_at ? new Date(row.created_at) : null;
                  const lvl = (row.level || "info").toLowerCase();
                  const lvlColor =
                    lvl === "error"
                      ? "text-red-700"
                      : lvl === "warn" || lvl === "warning"
                      ? "text-amber-700"
                      : "text-emerald-700";
                  return (
                    <>
                      <tr
                        key={rowKey}
                        className="hover:bg-white/5 cursor-pointer"
                        onClick={() => setExpandedId(isExpanded ? null : rowKey)}
                      >
                        <td className="px-3 py-2 text-brain-muted text-xs">
                          {date ? formatDistanceToNow(date, { addSuffix: true, locale: ptBR }) : "—"}
                        </td>
                        <td className="px-3 py-2 font-mono text-xs">{row.event_type || "—"}</td>
                        <td className="px-3 py-2 text-xs text-brain-muted">
                          <div>{row.entity_type || "—"}</div>
                          {row.entity_id && (
                            <div className="font-mono text-[10px] truncate" title={row.entity_id}>
                              {row.entity_id.slice(0, 8)}…
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-2 text-xs">{actorLabel(row.payload)}</td>
                        <td className={`px-3 py-2 text-xs ${lvlColor}`}>{lvl}</td>
                      </tr>
                      {isExpanded && (
                        <tr key={`${rowKey}-detail`} className="bg-white/40">
                          <td colSpan={5} className="px-3 py-3">
                            <div className="grid md:grid-cols-2 gap-4 text-xs">
                              <div>
                                <div className="text-brain-muted uppercase tracking-wide mb-1">Diff</div>
                                {renderDiff(row.payload?.diff) || (
                                  <div className="text-brain-muted">Sem diff registrado.</div>
                                )}
                              </div>
                              <div className="space-y-2">
                                <div>
                                  <div className="text-brain-muted uppercase tracking-wide mb-1">
                                    Contexto
                                  </div>
                                  <pre className="font-mono whitespace-pre-wrap break-all bg-white/60 border border-brain-border rounded-md p-2">
                                    {JSON.stringify(row.payload?.context ?? row.payload ?? {}, null, 2)}
                                  </pre>
                                </div>
                                <details>
                                  <summary className="text-brain-muted cursor-pointer">
                                    Payload completo
                                  </summary>
                                  <pre className="font-mono whitespace-pre-wrap break-all bg-white/60 border border-brain-border rounded-md p-2 mt-1">
                                    {JSON.stringify(row.payload ?? {}, null, 2)}
                                  </pre>
                                </details>
                                <div className="text-brain-muted">
                                  source: <span className="font-mono">{row.source || "—"}</span> ·
                                  persona:{" "}
                                  <span className="font-mono">{row.persona_id?.slice(0, 8) || "—"}</span>
                                </div>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
                {!auditLoading && !auditRows.length && (
                  <tr>
                    <td colSpan={5} className="px-3 py-6 text-center text-brain-muted text-sm">
                      Nenhum evento de auditoria encontrado com esses filtros.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab !== "audit" && (
        <div className="bg-brain-surface border border-brain-border rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-brain-border text-brain-muted text-xs uppercase tracking-wide">
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">{tab === "n8n" ? "Workflow" : "Agente"}</th>
                <th className="px-4 py-3 text-left">Lead</th>
                <th className="px-4 py-3 text-left">Duração</th>
                <th className="px-4 py-3 text-left">Quando</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-brain-border">
              {(tab === "n8n" ? n8nLogs : agentLogs).map((log) => {
                const isOk = log.status === "success" || log.status === "finished";
                const duration = tab === "n8n" ? log.duration_ms : log.latency_ms;
                const name = tab === "n8n" ? log.workflow_name : log.agent_name;
                const leadId = log.lead_id;
                const date = log.started_at || log.created_at;
                return (
                  <tr key={log.id} className="hover:bg-white/5">
                    <td className="px-4 py-2.5">
                      <span className={`text-xs font-medium ${isOk ? "text-green-400" : "text-red-400"}`}>
                        {isOk ? "✓" : "✗"} {log.status}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-white">{name || "—"}</td>
                    <td className="px-4 py-2.5 text-brain-muted font-mono text-xs">
                      {leadId?.slice(-8) || "—"}
                    </td>
                    <td className="px-4 py-2.5 text-brain-muted text-xs">
                      {duration ? `${(duration / 1000).toFixed(1)}s` : "—"}
                    </td>
                    <td className="px-4 py-2.5 text-brain-muted text-xs">
                      {date ? formatDistanceToNow(new Date(date), { addSuffix: true, locale: ptBR }) : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
