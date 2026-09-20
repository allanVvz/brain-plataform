"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, RefreshCw, RotateCcw, Send } from "lucide-react";
import { api } from "@/lib/api";
import { useGlobalPersona } from "@/lib/useGlobalPersona";

type QueueAction = "reprocess" | "send-preview" | "regenerate-preview";
type ContextMessage = { id?: string | number | null; content?: string | null; direction?: string | null; role?: string | null; sender_type?: string | null; created_at?: string | null };
type OutboundMessage = {
  buffer_id: string; sequence: number; kind: string; text?: string | null;
  proof_id?: string | null; status?: string | null; can_retry?: boolean;
  retry_reason?: string | null; can_send?: boolean; send_reason?: string | null;
};
type QueueItem = {
  id: string; demand_id?: string | null; lead_ref?: number | null; persona_id?: string | null;
  persona?: { name?: string; slug?: string } | null; lead?: { nome?: string | null; name?: string | null } | null;
  origin?: string | null; status?: string | null; queue_state?: string | null; available_at?: string | null;
  created_at?: string | null; customer_message?: string | null; customer_message_at?: string | null;
  last_agent_message?: string | null; last_agent_message_at?: string | null;
  recent_context?: ContextMessage[] | null; outbound_messages?: OutboundMessage[] | null; actions?: string[];
};

const ORIGINS: Record<string, string> = {
  conversation: "Resposta IA", campaign: "Campanha", manual: "Manual",
  proactive: "Aviso / reativação", system: "Operacional",
};
const STATES: Array<[string, string]> = [
  ["pending", "Aguardando envio"], ["preview_ready", "Prévia pronta"],
  ["technical_failure", "Falha técnica"], ["blocked", "Bloqueada"],
  ["pending_response", "Aguardando resposta da IA"], ["paused", "Pausada"],
  ["awaiting_customer", "Enviada — aguarda resposta"],
];

function formatDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(date);
}
function statusLabel(state?: string | null) { return STATES.find(([value]) => value === state)?.[1] || state || "—"; }
function messageStatusLabel(status?: string | null) {
  const labels: Record<string, string> = {
    preview_ready: "Pronta", pending_send: "Envio solicitado", buffered: "Agendada", processing: "Enviando",
    sent: "Enviada", delivered: "Entregue", read: "Lida", failed: "Falhou", dead_letter: "Falha técnica",
    retry: "Nova tentativa", technical_failure: "Sem prévia", blocked: "Bloqueada",
  };
  return labels[status || ""] || status || "—";
}
function contextLabel(message: ContextMessage) {
  return message.direction === "outbound" || ["assistant", "agent", "ai"].includes(message.role || "") ? "Agente" : "Cliente";
}
function ContextHistory({ messages }: { messages: ContextMessage[] }) {
  return <details className="mt-2 rounded-lg border border-white/10 bg-obs-panel/50 px-2 py-1 text-xs">
    <summary className="cursor-pointer text-obs-faint">Histórico recente ({messages.length})</summary>
    {messages.length ? <ol className="mt-2 space-y-2 pb-1">{messages.map((message, index) =>
      <li key={String(message.id ?? `${message.created_at || "message"}-${index}`)} className="border-t border-white/[0.06] pt-2 first:border-0 first:pt-0">
        <p className="text-obs-faint">{contextLabel(message)} · {formatDate(message.created_at)}</p>
        <p className="mt-0.5 whitespace-pre-wrap text-obs-subtle">{message.content || "[sem texto]"}</p>
      </li>)}</ol> : <p className="mt-2 pb-1 text-obs-faint">Histórico ainda não disponível.</p>}
  </details>;
}
function exactReason(enabled: boolean | undefined, reason?: string | null) { return enabled ? "" : (reason || "Ação indisponível no estado atual"); }

export function ReleaseQueuePanel() {
  const persona = useGlobalPersona();
  const [items, setItems] = useState<QueueItem[]>([]);
  const [origin, setOrigin] = useState("");
  const [status, setStatus] = useState("");
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [busyMessage, setBusyMessage] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async (offset = 0, append = false) => {
    if (!persona.id) { setItems([]); setNextOffset(null); return; }
    const result = await api.messagingQueue({ personaId: persona.id, origin: origin || undefined, status: status || undefined, offset, limit: 50 });
    const rows = (result.items || []) as QueueItem[];
    setItems((current) => append ? [...current, ...rows] : rows);
    setNextOffset(result.next_offset ?? null);
  }, [origin, persona.id, status]);

  useEffect(() => { load().catch((cause) => setError(cause?.message || "Falha ao carregar a fila.")); }, [load]);
  useEffect(() => {
    const timer = window.setInterval(() => load().catch((cause) => setError(cause?.message || "Falha ao atualizar a fila.")), 10000);
    return () => window.clearInterval(timer);
  }, [load]);
  const visibleItems = useMemo(() => items.filter((item) => item.persona_id === persona.id), [items, persona.id]);

  async function runMessageAction(action: "retry" | "send", item: QueueItem, message: OutboundMessage) {
    const capability = action === "retry" ? message.can_retry : message.can_send;
    const reason = action === "retry" ? message.retry_reason : message.send_reason;
    if (!capability || busyMessage) { if (!capability) setError(reason || "Ação indisponível no estado atual."); return; }
    const actionName: QueueAction = action === "send" ? "send-preview" : item.queue_state === "technical_failure" ? "reprocess" : "regenerate-preview";
    setBusyMessage(message.buffer_id); setError(""); setNotice("");
    try {
      const result = await api.controlMessagingQueue(actionName, { buffer_ids: [message.buffer_id] });
      const labels: Record<string, string> = {
        preview_gerado: "Prévia gerada", preview_individual_regenerado: "Mensagem regenerada",
        preview_reativacao_gerado: "Demanda de reativação criada", agendado: "Envio solicitado",
        bloqueado: "Ação bloqueada", superado: "Contexto mudou",
      };
      setNotice((result.items || []).map((row: { result?: string; reason?: string }) => `${labels[row.result || ""] || row.result || "Concluído"}${row.reason ? `: ${row.reason}` : ""}`).join(" · "));
      await load();
    } catch (cause: any) { setError(cause?.message || "Ação não concluída."); }
    finally { setBusyMessage(null); }
  }

  return <section className="flex flex-col gap-4">
    <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-obs-surface px-3 py-2 text-xs text-obs-subtle">
      <AlertCircle size={15} className="text-obs-violet" />Até três demandas reais por lead. Sessões do WA Validator permanecem disponíveis apenas em Logs.
    </div>
    <div className="flex flex-wrap items-end gap-2 rounded-xl border border-white/10 bg-obs-surface p-3">
      <label className="min-w-40 text-xs text-obs-faint">Origem<select aria-label="Origem" value={origin} onChange={(event) => setOrigin(event.target.value)} className="mt-1 block w-full rounded-lg border border-white/10 bg-obs-panel px-3 py-2 text-sm text-obs-text"><option value="">Todas as origens</option>{Object.entries(ORIGINS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label className="min-w-52 text-xs text-obs-faint">Estado<select aria-label="Estado" value={status} onChange={(event) => setStatus(event.target.value)} className="mt-1 block w-full rounded-lg border border-white/10 bg-obs-panel px-3 py-2 text-sm text-obs-text"><option value="">Todos os estados</option>{STATES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <button type="button" onClick={() => load().catch((cause) => setError(cause?.message || "Falha ao atualizar."))} className="flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm text-obs-subtle"><RefreshCw size={15} />Atualizar</button>
    </div>
    {notice && <p role="status" className="rounded-lg bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">{notice}</p>}
    {error && <p role="alert" className="rounded-lg bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{error}</p>}
    <div className="overflow-x-auto rounded-xl border border-white/10 bg-obs-surface">
      <table className="w-full min-w-[1120px] text-left text-sm">
        <thead className="bg-white/[0.03] text-xs text-obs-faint"><tr><th className="p-3">Contexto da conversa</th><th className="p-3">Prévia atual</th><th className="p-3">Lead</th><th className="p-3">Origem</th><th className="p-3">Horário</th><th className="p-3">Estado</th><th className="p-3 text-right">Ações</th></tr></thead>
        <tbody>{visibleItems.map((item) => {
          const sent = item.queue_state === "awaiting_customer";
          const messages = item.outbound_messages || [];
          return <tr key={item.demand_id || item.id} className={`border-t border-white/[0.06] align-top ${sent ? "bg-emerald-500/[0.04]" : "bg-rose-500/[0.04]"}`}>
            <td className="max-w-sm p-3"><p className="text-xs text-obs-faint">Demanda da cliente · {formatDate(item.customer_message_at || item.created_at)}</p><p className="mt-1 whitespace-pre-wrap text-obs-text">{item.customer_message || "Demanda sem texto disponível"}</p><p className="mt-3 text-xs text-obs-faint">Última resposta efetiva do agente</p><p className="mt-1 whitespace-pre-wrap text-obs-subtle">{item.last_agent_message || "Ainda sem resposta do agente"}</p><ContextHistory messages={item.recent_context || []} /></td>
            <td className="max-w-sm space-y-3 p-3">{messages.map((message, index) => <article key={message.buffer_id} className="rounded-lg border border-white/10 bg-obs-panel/40 p-2"><p className="text-xs font-medium text-obs-faint">Mensagem {index + 1} de {messages.length}</p><p className="mt-1 whitespace-pre-wrap text-obs-text">{message.text || "Nenhuma prévia gerada"}</p><p className="mt-2 text-xs text-obs-faint">{messageStatusLabel(message.status)}{message.proof_id ? ` · proof ${message.proof_id.slice(0, 8)}` : " · sem proof"}</p></article>)}</td>
            <td className="p-3"><p className="text-obs-text">{item.lead?.nome || item.lead?.name || "Lead"}</p><p className="text-xs text-obs-faint">{item.persona?.name || item.persona?.slug || ""}</p></td>
            <td className="p-3 text-obs-subtle">{ORIGINS[item.origin || ""] || item.origin || "—"}</td><td className="p-3 text-obs-subtle">{formatDate(item.available_at || item.created_at)}</td>
            <td className="p-3"><span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs ${sent ? "bg-emerald-500/15 text-emerald-200" : "bg-rose-500/15 text-rose-100"}`}>{sent ? <CheckCircle2 size={13} /> : <AlertCircle size={13} />}{statusLabel(item.queue_state)}</span><ul className="mt-2 space-y-1 text-xs text-obs-faint">{messages.map((message, index) => <li key={message.buffer_id}>Mensagem {index + 1}: {messageStatusLabel(message.status)}</li>)}</ul></td>
            <td className="p-3 text-right"><div className="space-y-3">{messages.map((message, index) => {
              const retryReason = exactReason(message.can_retry, message.retry_reason); const sendReason = exactReason(message.can_send, message.send_reason);
              return <div key={message.buffer_id} className="rounded-lg border border-white/[0.08] p-2"><p className="mb-2 text-xs text-obs-faint">Mensagem {index + 1}</p><div className="flex justify-end gap-1"><button type="button" disabled={Boolean(busyMessage) || !message.can_retry} title={retryReason} aria-label={`Retry mensagem ${index + 1}`} onClick={() => void runMessageAction("retry", item, message)} className="inline-flex items-center gap-1 rounded-lg border border-white/10 px-2 py-2 text-xs text-obs-text disabled:cursor-not-allowed disabled:opacity-40"><RotateCcw size={13} />Retry</button><button type="button" disabled={Boolean(busyMessage) || !message.can_send} title={sendReason} aria-label={`Enviar mensagem ${index + 1}`} onClick={() => void runMessageAction("send", item, message)} className="inline-flex items-center gap-1 rounded-lg bg-emerald-500/20 px-2 py-2 text-xs text-emerald-100 disabled:cursor-not-allowed disabled:opacity-40"><Send size={13} />Enviar</button></div>{retryReason && <p className="mt-1 max-w-52 text-xs text-obs-faint">Retry: {retryReason}</p>}{sendReason && <p className="mt-1 max-w-52 text-xs text-obs-faint">Enviar: {sendReason}</p>}</div>;
            })}</div></td>
          </tr>;
        })}</tbody>
      </table>
      {!visibleItems.length && <p className="p-10 text-center text-sm text-obs-subtle">Nenhuma demanda real aguarda ação.</p>}
    </div>
    {nextOffset !== null && <button type="button" onClick={() => load(nextOffset, true)} className="self-center rounded-lg border border-white/10 px-4 py-2 text-sm text-obs-text">Carregar mais</button>}
  </section>;
}
