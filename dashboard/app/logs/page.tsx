"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Bot, History, Network, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { useGlobalPersona } from "@/lib/useGlobalPersona";

type Tab = "audit" | "agents" | "n8n";

function dateLabel(value?: string) {
  if (!value) return "sem data";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "sem data" : parsed.toLocaleString("pt-BR");
}

function belongsToPersona(row: any, personaId: string) {
  if (!personaId) return false;
  const rowPersona = row?.persona_id
    || row?.payload?.persona_id
    || row?.metadata?.persona_id
    || row?.data?.persona_id;
  return !rowPersona || String(rowPersona) === String(personaId);
}

export default function LogsPage() {
  const persona = useGlobalPersona();
  const [tab, setTab] = useState<Tab>("audit");
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");

  const load = useCallback(async () => {
    if (!persona.id) {
      setRows([]);
      return;
    }
    setLoading(true);
    setError("");
    try {
      if (tab === "audit") {
        setRows(await api.auditLogs({ persona_id: persona.id, limit: 200 }));
      } else if (tab === "agents") {
        setRows(await api.agentLogs(undefined, 150, persona.id));
      } else {
        const all = await api.n8nLogs(200);
        setRows(all.filter((row) => belongsToPersona(row, persona.id)));
      }
    } catch (reason: any) {
      setError(reason?.message || "Não foi possível carregar os logs.");
    } finally {
      setLoading(false);
    }
  }, [persona.id, tab]);

  useEffect(() => {
    load();
  }, [load]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((row) => JSON.stringify(row).toLowerCase().includes(needle));
  }, [query, rows]);

  if (!persona.id) {
    return (
      <div className="rounded-2xl border border-amber-500/25 bg-amber-500/10 p-5 text-sm text-amber-200">
        Selecione uma persona no cabeçalho para consultar os registros.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">
            Persona selecionada · {persona.slug}
          </p>
          <h1 className="mt-1 text-xl font-semibold text-obs-text">Logs operacionais</h1>
          <p className="mt-1 text-sm text-obs-subtle">
            Auditoria, decisões do chatbot e execuções úteis para diagnóstico.
          </p>
        </div>
        <button type="button" onClick={load} disabled={loading} className="flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs text-obs-subtle disabled:opacity-40">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} /> Atualizar
        </button>
      </header>

      <nav className="flex flex-wrap gap-2" aria-label="Tipos de log">
        {([
          ["audit", "Auditoria", <History key="audit" size={14} />],
          ["agents", "Chat e agentes", <Bot key="agents" size={14} />],
          ["n8n", "Automações n8n", <Network key="n8n" size={14} />],
        ] as const).map(([value, label, icon]) => (
          <button
            key={value}
            type="button"
            onClick={() => setTab(value)}
            className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${
              tab === value
                ? "border-obs-violet/40 bg-obs-violet/15 text-obs-violet"
                : "border-white/10 text-obs-subtle"
            }`}
          >
            {icon}{label}
          </button>
        ))}
      </nav>

      <input
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Buscar evento, lead, componente ou status"
        className="w-full rounded-xl border border-white/10 bg-obs-raised px-4 py-2.5 text-sm text-obs-text"
      />

      {error && (
        <div role="alert" className="flex gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">
          <AlertTriangle size={16} /> {error}
        </div>
      )}

      <section className="space-y-2">
        {!loading && !visible.length && (
          <div className="rounded-2xl border border-white/10 bg-obs-surface p-8 text-center text-sm text-obs-faint">
            Nenhum registro deste tipo para a persona selecionada.
          </div>
        )}
        {visible.map((row, index) => (
          <details key={row.id || row.n8n_id || `${tab}-${index}`} className="group rounded-xl border border-white/10 bg-obs-surface p-4">
            <summary className="cursor-pointer list-none">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-obs-text">
                    {row.event_type || row.action || row.workflow_name || row.component || "Registro"}
                  </p>
                  <p className="mt-1 text-xs text-obs-faint">
                    {row.entity_type || row.agent_type || row.status || "informação operacional"}
                  </p>
                </div>
                <span className="text-xs text-obs-faint">
                  {dateLabel(row.created_at || row.started_at || row.ts)}
                </span>
              </div>
            </summary>
            <pre className="mt-4 max-h-72 overflow-auto rounded-lg border border-white/10 bg-obs-base/70 p-3 text-[11px] leading-5 text-obs-subtle">
              {JSON.stringify(row.payload || row.metadata || row, null, 2)}
            </pre>
          </details>
        ))}
      </section>
    </div>
  );
}
