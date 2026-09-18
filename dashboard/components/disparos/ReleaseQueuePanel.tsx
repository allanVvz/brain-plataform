"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, ChevronDown, ChevronUp, Pause, Play, RefreshCw, RotateCcw, X } from "lucide-react";
import { api } from "@/lib/api";

type QueueAction = "pause" | "resume" | "reprocess";
type QueueItem = {
  id: string; preview?: string | null; content?: string | null; lead_ref?: number | null; persona_id?: string | null;
  persona?: { id?: string; name?: string; slug?: string } | null; lead?: { nome?: string | null; name?: string | null } | null;
  origin?: string | null; status?: string | null; available_at?: string | null; created_at?: string | null;
  attempt_count?: number | null; max_attempts?: number | null; last_error?: string | null;
  graph_publication?: string | null; graph_rule?: string | null; publication?: string | null; rule?: string | null;
  action_history?: Array<Record<string, unknown>>; history?: Array<Record<string, unknown>>; [key: string]: unknown;
};
type Persona = { id?: string; name?: string | null; slug?: string | null };

const ORIGINS: Record<string, string> = { conversation: "Resposta IA", campaign: "Campanha", manual: "Manual", proactive: "Aviso / reativação", system: "Operacional" };
const STATES = ["buffered", "pending", "retry", "processing", "waiting_human", "paused", "sent", "delivered", "read", "dead_letter", "ignored", "reprocessed"];
const formatDate = (value?: string | null) => {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const now = new Date();
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  const clock = new Intl.DateTimeFormat("pt-BR", { timeStyle: "short" }).format(date);
  if (date.toDateString() === now.toDateString()) return `Hoje às ${clock}`;
  if (date.toDateString() === tomorrow.toDateString()) return `Amanhã às ${clock}`;
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(date);
};
const previewOf = (item: QueueItem) => item.preview || item.content || String(item.payload_preview || "Sem conteúdo disponível");
const personaLabel = (persona?: Persona | null, fallback?: string | null) => persona?.name || persona?.slug || fallback || "Sem persona";
const historyOf = (item: QueueItem) => item.action_history || item.history || (Array.isArray(item.actions) ? item.actions as Array<Record<string, unknown>> : []);

export function ReleaseQueuePanel() {
  const [items, setItems] = useState<QueueItem[]>([]); const [personas, setPersonas] = useState<Persona[]>([]);
  const [personaId, setPersonaId] = useState(""); const [leadRef, setLeadRef] = useState("");
  const [origin, setOrigin] = useState(""); const [status, setStatus] = useState(""); const [selected, setSelected] = useState<string[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null); const [notice, setNotice] = useState("");
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false); const [detail, setDetail] = useState<QueueItem | null>(null);
  const [detailItems, setDetailItems] = useState<QueueItem[]>([]); const [detailLoading, setDetailLoading] = useState(false);
  const queryLeadRef = useMemo(() => typeof window === "undefined" ? "" : new URLSearchParams(window.location.search).get("lead_ref") || "", []);

  const load = useCallback(async (offset = 0, append = false) => {
    const reprocessedHistory = status === "reprocessed";
    const result = await api.messagingQueue({ persona_id: personaId || undefined, lead_ref: leadRef ? Number(leadRef) : undefined, origin: origin || undefined, status: reprocessedHistory ? undefined : status || undefined, history: reprocessedHistory ? "reprocessed" : undefined, offset, limit: 50 });
    const rows = (reprocessedHistory
      ? (result.history || []).map((event: any) => ({
          id: `${event.entity_id}:${event.created_at}`, lead_ref: event.payload?.lead_ref,
          persona_id: event.persona_id, preview: event.payload?.operator_reason || "Reprocessamento registrado",
          origin: "system", status: event.payload?.result || "reprocessado", created_at: event.created_at,
          attempt_count: 0, max_attempts: 0, actions: [event],
        }))
      : result.items || []) as QueueItem[];
    setItems((previous) => append ? [...previous, ...rows] : rows); setNextOffset(result.next_offset ?? null);
    if (!append) setSelected([]);
  }, [leadRef, origin, personaId, status]);

  useEffect(() => {
    // The default must be the authorized global queue.  A persona scope is a
    // deliberate filter, not an implicit side-effect of the navigation menu.
    setLeadRef(queryLeadRef);
    Promise.resolve(api.personas?.() ?? []).then((rows) => setPersonas((rows || []) as Persona[])).catch(() => setPersonas([]));
  }, [queryLeadRef]);
  useEffect(() => { load().catch((cause) => setError(cause?.message || "Falha ao carregar a fila.")); }, [load]);

  async function openLead(item: QueueItem) {
    if (!item.lead_ref) return;
    setDetail(item); setDetailItems([]); setDetailLoading(true);
    try {
      const result = await api.messagingQueue({ lead_ref: item.lead_ref, offset: 0, limit: 100 });
      const buffered = (result.items || []) as QueueItem[];
      const bufferedIds = new Set(buffered.map((row) => String(row.correlation_id || row.id)));
      const timeline = ((result.timeline || []) as QueueItem[])
        .filter((row) => !bufferedIds.has(String(row.correlation_id || row.id)))
        .map((row) => ({ ...row, id: `message:${row.id}`, status: row.status || "registrada", origin: row.origin || "conversation" }));
      setDetailItems([...buffered, ...timeline].sort((a, b) => String(b.created_at || b.available_at || "").localeCompare(String(a.created_at || a.available_at || ""))));
    }
    catch (cause: any) { setError(cause?.message || "Falha ao carregar o contexto da lead."); }
    finally { setDetailLoading(false); }
  }
  async function action(kind: QueueAction, ids = selected) {
    if (!ids.length) return;
    const verb = kind === "pause" ? "pausar" : kind === "resume" ? "retomar" : "reprocessar";
    const reason = window.prompt(`Motivo para ${verb} ${ids.length} item(ns):`); if (!reason?.trim()) return;
    setBusy(true); setError("");
    try {
      const result = await api.controlMessagingQueue(kind, { buffer_ids: ids, reason, idempotency_key: `queue:${kind}:${crypto.randomUUID()}` });
      setNotice((result.items || []).map((row: { result?: string; reason?: string }) => `${row.result || "processado"}${row.reason ? ` (${row.reason})` : ""}`).join(" · ") || "Ação registrada.");
      await load(); if (detail?.lead_ref) await openLead(detail);
    } catch (cause: any) { setError(cause?.message || "Ação não concluída."); } finally { setBusy(false); }
  }
  const toggle = (id: string) => setSelected((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]);
  const allSelected = items.length > 0 && items.every((item) => selected.includes(item.id));
  const detailLeadName = detail?.lead?.nome || detail?.lead?.name || detail?.lead_ref;

  return <div className="flex flex-col gap-4">
    <div className="flex gap-2 rounded-xl border border-obs-amber/25 bg-obs-amber/10 px-3 py-2 text-xs text-obs-amber"><AlertCircle className="shrink-0" size={15} />Bloqueios técnicos são somente leitura. Pausa, retomada e reprocessamento são sempre por mensagem.</div>
    <div className="grid gap-2 rounded-xl border border-white/10 bg-obs-surface p-3 sm:grid-cols-2 xl:grid-cols-5">
      <label className="text-xs text-obs-faint">Persona<select value={personaId} onChange={(event) => setPersonaId(event.target.value)} className="mt-1 block w-full rounded-lg border border-white/10 bg-obs-panel px-3 py-2 text-sm text-obs-text"><option value="">Todas autorizadas</option>{personas.filter((persona) => Boolean(persona.id)).map((persona) => <option key={persona.id} value={persona.id}>{personaLabel(persona)}</option>)}</select></label>
      <label className="text-xs text-obs-faint">Lead<input aria-label="Lead" value={leadRef} inputMode="numeric" onChange={(event) => setLeadRef(event.target.value.replace(/\D/g, ""))} placeholder="ID da lead" className="mt-1 block w-full rounded-lg border border-white/10 bg-obs-panel px-3 py-2 text-sm text-obs-text" /></label>
      <label className="text-xs text-obs-faint">Origem<select aria-label="Origem" value={origin} onChange={(event) => setOrigin(event.target.value)} className="mt-1 block w-full rounded-lg border border-white/10 bg-obs-panel px-3 py-2 text-sm text-obs-text"><option value="">Todas</option>{Object.entries(ORIGINS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label className="text-xs text-obs-faint">Estado<select aria-label="Estado" value={status} onChange={(event) => setStatus(event.target.value)} className="mt-1 block w-full rounded-lg border border-white/10 bg-obs-panel px-3 py-2 text-sm text-obs-text"><option value="">Todos</option>{STATES.map((state) => <option key={state} value={state}>{state === "reprocessed" ? "Reprocessadas (histórico)" : state}</option>)}</select></label>
      <div className="flex items-end gap-2"><button onClick={() => load()} className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-obs-violet/15 px-3 py-2 text-sm text-obs-violet ring-1 ring-obs-violet/25"><RefreshCw size={15} />Atualizar</button>{leadRef && <button onClick={() => setLeadRef("")} className="rounded-lg border border-white/10 p-2 text-obs-subtle" title="Limpar filtro da lead"><X size={16} /></button>}</div>
    </div>
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-white/10 bg-obs-surface p-3"><span className="mr-2 text-xs text-obs-subtle">{selected.length} selecionado(s)</span><button disabled={!selected.length || busy} onClick={() => action("pause")} className="flex items-center gap-1 rounded-lg bg-obs-amber/15 px-3 py-2 text-xs text-obs-amber disabled:opacity-40"><Pause size={14} />Pausar</button><button disabled={!selected.length || busy} onClick={() => action("resume")} className="flex items-center gap-1 rounded-lg bg-emerald-500/15 px-3 py-2 text-xs text-emerald-300 disabled:opacity-40"><Play size={14} />Retomar</button><button disabled={!selected.length || busy} onClick={() => action("reprocess")} className="flex items-center gap-1 rounded-lg bg-obs-violet/15 px-3 py-2 text-xs text-obs-violet disabled:opacity-40"><RotateCcw size={14} />Reprocessar</button></div>
    {notice && <p role="status" className="rounded-lg bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">{notice}</p>}{error && <p role="alert" className="rounded-lg bg-obs-rose/10 px-3 py-2 text-xs text-obs-rose">{error}</p>}
    <div className="overflow-x-auto rounded-xl border border-white/10"><table className="w-full min-w-[1050px] text-left text-xs"><thead className="bg-white/[0.03] text-obs-faint"><tr><th className="p-3"><input type="checkbox" aria-label="Selecionar todos" checked={allSelected} onChange={(event) => setSelected(event.target.checked ? items.map((item) => item.id) : [])} /></th><th className="p-3">Mensagem</th><th className="p-3">Lead / persona</th><th className="p-3">Origem</th><th className="p-3">Previsto</th><th className="p-3">Estado</th><th className="p-3">Tentativas</th><th className="p-3">Regra / publicação</th><th className="p-3">Ação</th></tr></thead><tbody>{items.map((item) => <tr key={item.id} className="border-t border-white/[0.06] align-top"><td className="p-3"><input aria-label={`Selecionar ${item.id}`} type="checkbox" checked={selected.includes(item.id)} onChange={() => toggle(item.id)} /></td><td className="max-w-sm p-3 text-obs-text"><p className="line-clamp-2">{previewOf(item)}</p>{item.last_error && <p className="mt-1 line-clamp-2 text-obs-rose">{item.last_error}</p>}<p className="mt-1 font-mono text-[10px] text-obs-faint">{item.id}</p></td><td className="p-3"><button onClick={() => openLead(item)} disabled={!item.lead_ref} className="text-left text-obs-text hover:text-obs-violet disabled:cursor-default"><p>{item.lead?.nome || item.lead?.name || item.lead_ref || "Sem lead"}</p><p className="text-obs-faint">{personaLabel(item.persona, item.persona_id)}</p></button></td><td className="p-3">{ORIGINS[item.origin || ""] || item.origin || "—"}</td><td className="p-3">{formatDate(item.available_at || item.created_at)}</td><td className="p-3">{item.status || "—"}</td><td className="p-3">{item.attempt_count || 0}/{item.max_attempts || 0}</td><td className="max-w-40 p-3 text-obs-faint"><p className="truncate">{item.graph_rule || item.rule || "—"}</p><p className="truncate">{item.graph_publication || item.publication || ""}</p></td><td className="p-3 whitespace-nowrap"><button onClick={() => action("pause", [item.id])} className="mr-2 text-obs-amber">Pausar</button><button onClick={() => action("resume", [item.id])} className="mr-2 text-emerald-300">Retomar</button><button onClick={() => action("reprocess", [item.id])} className="text-obs-violet">Reprocessar</button></td></tr>)}</tbody></table>{!items.length && <p className="p-8 text-center text-sm text-obs-subtle">Nenhuma mensagem nesta fila com estes filtros.</p>}</div>
    {nextOffset !== null && <button onClick={() => load(nextOffset, true)} className="self-center rounded-lg border border-white/10 px-4 py-2 text-sm">Carregar mais</button>}
    {detail && <aside aria-label="Contexto da lead" className="rounded-xl border border-obs-violet/25 bg-obs-surface p-4"><div className="flex items-start justify-between gap-3"><div><p className="text-xs uppercase tracking-wide text-obs-faint">Linha do tempo e buffer</p><h2 className="mt-1 font-semibold text-obs-text">Lead {detailLeadName}</h2><p className="text-xs text-obs-subtle">{personaLabel(detail.persona, detail.persona_id)} · {detail.lead_ref}</p></div><button onClick={() => setDetail(null)} className="rounded-lg p-1 text-obs-subtle" aria-label="Fechar contexto"><X size={18} /></button></div><div className="mt-3 space-y-2">{detailLoading && <p className="text-sm text-obs-subtle">Carregando histórico da fila…</p>}{!detailLoading && detailItems.map((item) => <details key={item.id} className="rounded-lg border border-white/10 p-3"><summary className="flex cursor-pointer list-none items-center gap-2 text-sm text-obs-text"><span className="flex-1 line-clamp-1">{previewOf(item)}</span><span className="text-xs text-obs-faint">{item.status} · {formatDate(item.available_at || item.created_at)}</span><ChevronDown className="details-open:hidden" size={15} /><ChevronUp className="hidden details-open:block" size={15} /></summary><div className="mt-3 space-y-2 border-t border-white/[0.06] pt-3 text-xs"><p><span className="text-obs-faint">Origem:</span> {ORIGINS[item.origin || ""] || item.origin || "—"}</p><p><span className="text-obs-faint">Erro seguro:</span> {item.last_error || "—"}</p><p><span className="text-obs-faint">Regra/publicação:</span> {item.graph_rule || item.rule || "—"} {item.graph_publication || item.publication || ""}</p>{historyOf(item).map((entry, index) => <p key={index} className="rounded bg-white/[0.03] p-2 text-obs-subtle">{String(entry.action || entry.event_type || entry.result || "ação")} · {String(entry.reason || entry.created_at || "sem detalhe")}</p>)}</div></details>)}{!detailLoading && !detailItems.length && <p className="text-sm text-obs-subtle">Não há itens de buffer visíveis para esta lead.</p>}</div></aside>}
  </div>;
}
