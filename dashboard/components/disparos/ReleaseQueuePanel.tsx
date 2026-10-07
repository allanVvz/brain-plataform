"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Pause, Play, RefreshCw, Send, Sparkles } from "lucide-react";
import { ApiError, api } from "@/lib/api";
import { useGlobalPersona } from "@/lib/useGlobalPersona";
import {
  ACTION_LABEL, STATE_LABEL, simplifyMessage,
  type SimpleAction, type SimpleActionKey, type SimpleState,
} from "./queueSimple";

type ContextMessage = { id?: string | number | null; content?: string | null; direction?: string | null; role?: string | null; created_at?: string | null };
type OutboundMessage = {
  buffer_id: string; sequence: number; kind: string; text?: string | null; status?: string | null;
  can_send?: boolean; send_reason?: string | null;
};
type QueueItem = {
  id: string; demand_id?: string | null; lead_ref?: number | null; persona_id?: string | null;
  persona?: { name?: string; slug?: string } | null; lead?: { nome?: string | null; name?: string | null } | null;
  queue_state?: string | null; available_at?: string | null; created_at?: string | null;
  customer_message?: string | null; customer_message_at?: string | null;
  last_agent_message?: string | null; recent_context?: ContextMessage[] | null;
  outbound_messages?: OutboundMessage[] | null;
};

const FILTERS: Array<[SimpleState | "", string]> = [
  ["", "Todas"], ["pausada", "Pausadas"], ["agendada", "Agendadas"],
  ["preview", "Preview pronto"], ["sem_preview", "Sem preview"], ["enviada", "Enviadas"],
];
const STATE_STYLE: Record<SimpleState, string> = {
  pausada: "bg-rose-500/15 text-rose-200",
  agendada: "bg-sky-500/15 text-sky-100",
  preview: "bg-violet-500/15 text-violet-100",
  sem_preview: "bg-amber-500/15 text-amber-100",
  enviada: "bg-emerald-500/15 text-emerald-200",
};
const ICON: Record<SimpleActionKey, typeof Pause> = { pausar: Pause, retomar: Play, gerar_preview: Sparkles, enviar: Send };
const RESULT_LABEL: Record<string, string> = {
  pausado: "Pausada", retomado: "Retomada", agendado: "Agendada para envio",
  preview_gerado: "Preview gerado", operator_preview_gerado: "Preview gerado",
  preview_individual_regenerado: "Preview gerado", preview_reativacao_gerado: "Preview gerado",
  recuperando_tentativa_antiga: "Preview gerado", bloqueado: "Não foi possível", superado: "A conversa mudou",
};

function formatDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `queue-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

// Never lets a 401/403/409/422 read as "backend fora do ar", and keeps the
// request_id for support.
function describeQueueError(cause: unknown): string {
  if (!(cause instanceof ApiError)) return cause instanceof Error ? cause.message : "Ação não concluída.";
  const suffix = cause.requestId ? ` (request_id ${cause.requestId})` : "";
  if (cause.status === 0) return `Sem conexão com o backend. Tente novamente.${suffix}`;
  if (cause.kind === "unauthenticated") return `Sessão expirada — faça login novamente.${suffix}`;
  if (cause.kind === "forbidden") return `Sem permissão para esta ação nesta persona.${suffix}`;
  if (cause.status === 409) return `A conversa mudou enquanto você agia — atualize a fila.${suffix}`;
  if (cause.status === 422) return `Dados inválidos: ${cause.detail || "confira os campos"}.${suffix}`;
  return `${cause.detail || "Ação não concluída"} (HTTP ${cause.status}).${suffix}`;
}

export function ReleaseQueuePanel() {
  const persona = useGlobalPersona();
  const [items, setItems] = useState<QueueItem[]>([]);
  const [filter, setFilter] = useState<SimpleState | "">("");
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async (offset = 0, append = false) => {
    if (!persona.id) { setItems([]); setNextOffset(null); return; }
    const result = await api.messagingQueue({ personaId: persona.id, offset, limit: 50 });
    const rows = (result.items || []) as QueueItem[];
    setItems((current) => append ? [...current, ...rows] : rows);
    setNextOffset(result.next_offset ?? null);
  }, [persona.id]);

  useEffect(() => { load().catch((cause) => setError(describeQueueError(cause))); }, [load]);
  useEffect(() => {
    const timer = window.setInterval(() => load().catch((cause) => setError(describeQueueError(cause))), 10000);
    return () => window.clearInterval(timer);
  }, [load]);

  const rows = useMemo(() => items
    .filter((item) => item.persona_id === persona.id)
    .map((item) => ({
      item,
      messages: (item.outbound_messages || []).map((message) => ({ message, view: simplifyMessage(item.queue_state, message) })),
    }))
    .filter(({ messages }) => !filter || messages.some(({ view }) => view.state === filter)),
  [items, persona.id, filter]);

  async function run(message: OutboundMessage, action: SimpleAction) {
    if (!action.enabled || busy) { if (!action.enabled) setError(action.reason || "Ação indisponível agora."); return; }
    if (action.key === "gerar_preview" && action.endpoint !== "regenerate-preview"
      && !window.confirm("Vou gerar um preview para esta lead. Nada é enviado até você clicar em Enviar. Continuar?")) return;
    setBusy(message.buffer_id); setError(""); setNotice("");
    try {
      // One key per click: a network retry of the same POST replays it and gets
      // the recorded result back instead of running the action twice.
      const result = await api.controlMessagingQueue(action.endpoint, { buffer_ids: [message.buffer_id], idempotency_key: newIdempotencyKey() });
      setNotice((result.items || []).map((row: { result?: string; reason?: string }) =>
        `${RESULT_LABEL[row.result || ""] || "Concluído"}${row.reason ? `: ${row.reason}` : ""}`).join(" · "));
      await load();
    } catch (cause) { setError(describeQueueError(cause)); }
    finally { setBusy(null); }
  }

  return <section className="flex flex-col gap-4">
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-white/10 bg-obs-surface p-3">
      {FILTERS.map(([value, label]) => <button key={label} type="button" aria-pressed={filter === value}
        onClick={() => setFilter(value)}
        className={`rounded-full px-3 py-1.5 text-xs ${filter === value ? "bg-obs-violet/20 text-obs-text" : "text-obs-subtle hover:text-obs-text"}`}>{label}</button>)}
      <button type="button" onClick={() => load().catch((cause) => setError(describeQueueError(cause)))}
        className="ml-auto flex items-center gap-2 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-obs-subtle"><RefreshCw size={13} />Atualizar</button>
    </div>
    {notice && <p role="status" className="rounded-lg bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">{notice}</p>}
    {error && <p role="alert" className="rounded-lg bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{error}</p>}
    <div className="overflow-x-auto rounded-xl border border-white/10 bg-obs-surface">
      <table className="w-full min-w-[900px] text-left text-sm">
        <thead className="bg-white/[0.03] text-xs text-obs-faint"><tr><th className="p-3">Lead</th><th className="p-3">Conversa</th><th className="p-3">Mensagem</th><th className="p-3">Estado</th><th className="p-3 text-right">Ações</th></tr></thead>
        <tbody>{rows.map(({ item, messages }) => messages.map(({ message, view }, index) =>
          <tr key={message.buffer_id} className="border-t border-white/[0.06] align-top">
            {index === 0 && <>
              <td rowSpan={messages.length} className="p-3"><p className="text-obs-text">{item.lead?.nome || item.lead?.name || "Lead"}</p><p className="text-xs text-obs-faint">{item.persona?.name || item.persona?.slug || ""}</p></td>
              <td rowSpan={messages.length} className="max-w-xs p-3"><p className="text-xs text-obs-faint">Cliente · {formatDate(item.customer_message_at || item.created_at)}</p><p className="mt-1 whitespace-pre-wrap text-obs-text">{item.customer_message || "—"}</p>{item.last_agent_message && <><p className="mt-2 text-xs text-obs-faint">Última resposta do agente</p><p className="mt-1 whitespace-pre-wrap text-obs-subtle">{item.last_agent_message}</p></>}</td>
            </>}
            <td className="max-w-sm p-3 whitespace-pre-wrap text-obs-text">{message.text || <span className="text-obs-faint">Sem preview</span>}</td>
            <td className="p-3"><span className={`inline-flex rounded-full px-2 py-1 text-xs ${STATE_STYLE[view.state]}`}>{STATE_LABEL[view.state]}</span>{view.state === "agendada" && item.available_at && <p className="mt-1 text-xs text-obs-faint">{formatDate(item.available_at)}</p>}</td>
            <td className="p-3"><div className="flex justify-end gap-1">{view.actions.map((action) => {
              const Icon = ICON[action.key];
              return <button key={action.key} type="button" disabled={Boolean(busy) || !action.enabled}
                title={action.enabled ? undefined : action.reason || undefined}
                aria-label={`${ACTION_LABEL[action.key]} mensagem ${index + 1}`}
                onClick={() => void run(message, action)}
                className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-40 ${action.key === "enviar" ? "bg-emerald-500/20 text-emerald-100" : "border border-white/10 text-obs-text"}`}>
                <Icon size={13} />{ACTION_LABEL[action.key]}</button>;
            })}</div>{view.actions.some((action) => !action.enabled && action.reason) && <p className="mt-1 text-right text-xs text-obs-faint">{view.actions.find((action) => !action.enabled)?.reason}</p>}</td>
          </tr>))}</tbody>
      </table>
      {!rows.length && <p className="p-10 text-center text-sm text-obs-subtle">Nada na fila.</p>}
    </div>
    {nextOffset !== null && <button type="button" onClick={() => load(nextOffset, true)} className="self-center rounded-lg border border-white/10 px-4 py-2 text-sm text-obs-text">Carregar mais</button>}
  </section>;
}
