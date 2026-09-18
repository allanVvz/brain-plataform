"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, RefreshCw, Send } from "lucide-react";
import { api } from "@/lib/api";
import { useGlobalPersona } from "@/lib/useGlobalPersona";

type QueueAction = "pause" | "resume" | "reprocess" | "send-preview" | "reactivate";
type QueueItem = {
  id: string;
  preview?: string | null;
  lead_ref?: number | null;
  persona?: { name?: string; slug?: string } | null;
  lead?: { nome?: string | null; name?: string | null } | null;
  origin?: string | null;
  status?: string | null;
  queue_state?: string | null;
  available_at?: string | null;
  created_at?: string | null;
  last_error?: string | null;
  actions?: string[];
};

const ORIGINS: Record<string, string> = {
  conversation: "Resposta IA", campaign: "Campanha", manual: "Manual", proactive: "Aviso / reativação", system: "Operacional",
};
const STATES: Array<[string, string]> = [
  ["pending", "Aguardando envio"],
  ["preview_ready", "Preview pronto"],
  ["technical_failure", "Falha técnica"],
  ["paused", "Pausada"],
  ["awaiting_customer", "Enviada — aguarda resposta"],
];
const ACTIONS: Array<{ value: QueueAction; label: string }> = [
  { value: "reprocess", label: "Gerar preview" },
  { value: "reactivate", label: "Reativar cliente" },
  { value: "send-preview", label: "Enviar preview" },
  { value: "pause", label: "Pausar" },
  { value: "resume", label: "Retomar" },
];

function formatDate(value?: string | null) {
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
}

function statusLabel(state?: string | null) {
  return STATES.find(([value]) => value === state)?.[1] || state || "—";
}

function primaryAction(item: QueueItem): { action: QueueAction; label: string } | null {
  if (item.actions?.includes("reprocess")) return { action: "reprocess", label: "Corrigir e gerar resposta" };
  if (item.actions?.includes("reactivate")) return { action: "reactivate", label: "Reativar cliente" };
  if (item.actions?.includes("send_preview")) return { action: "send-preview", label: "Enviar" };
  if (item.actions?.includes("resume")) return { action: "resume", label: "Retomar" };
  if (item.actions?.includes("pause")) return { action: "pause", label: "Pausar" };
  return null;
}

export function ReleaseQueuePanel() {
  const persona = useGlobalPersona();
  const [items, setItems] = useState<QueueItem[]>([]);
  const [origin, setOrigin] = useState("");
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async (offset = 0, append = false) => {
    if (!persona.id) {
      setItems([]);
      setNextOffset(null);
      return;
    }
    const result = await api.messagingQueue({ personaId: persona.id, origin: origin || undefined, status: status || undefined, offset, limit: 50 });
    const rows = (result.items || []) as QueueItem[];
    setItems((current) => append ? [...current, ...rows] : rows);
    setNextOffset(result.next_offset ?? null);
    if (!append) setSelected([]);
  }, [origin, persona.id, status]);

  useEffect(() => {
    load().catch((cause) => setError(cause?.message || "Falha ao carregar a fila."));
  }, [load]);

  const selectedItems = useMemo(() => items.filter((item) => selected.includes(item.id)), [items, selected]);
  const allSelected = items.length > 0 && selected.length === items.length;
  const selectedActions = useMemo(() => ACTIONS.filter(({ value }) =>
    selectedItems.length > 0 && selectedItems.every((item) => item.actions?.includes(value === "send-preview" ? "send_preview" : value)),
  ), [selectedItems]);

  async function runAction(action: QueueAction, targets = selectedItems) {
    if (!targets.length) return;
    const unsupported = targets.filter((item) => !item.actions?.includes(action));
    if (unsupported.length) {
      setError(`${unsupported.length} mensagem(ns) não aceitam esta ação no estado atual.`);
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api.controlMessagingQueue(action, { buffer_ids: targets.map((item) => item.id) });
      const results = result.items || [];
      const labels: Record<string, string> = {
        preview_gerado: "Preview gerado",
        preview_reativacao_gerado: "Preview de reativação criado. Revise a nova linha e clique em Enviar.",
        agendado: "Agendado",
        pausado: "Pausado",
        retomado: "Retomado",
        bloqueado: "Bloqueado",
        superado: "Contexto mudou",
      };
      setNotice(results.map((row: { result?: string; reason?: string }) => {
        const label = labels[row.result || ""] || row.result || "Concluído";
        return row.reason ? `${label}: ${row.reason}` : label;
      }).join(" · "));
      await load();
    } catch (cause: any) {
      setError(cause?.message || "Ação não concluída.");
    } finally {
      setBusy(false);
    }
  }

  return <section className="flex flex-col gap-4">
    <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-obs-surface px-3 py-2 text-xs text-obs-subtle">
      <AlertCircle size={15} className="text-obs-violet" />
      Mensagens ativas. Histórico e conversas já respondidas não aparecem aqui.
    </div>

    <div className="flex flex-wrap items-end gap-2 rounded-xl border border-white/10 bg-obs-surface p-3">
      <label className="min-w-40 text-xs text-obs-faint">Origem
        <select aria-label="Origem" value={origin} onChange={(event) => setOrigin(event.target.value)} className="mt-1 block w-full rounded-lg border border-white/10 bg-obs-panel px-3 py-2 text-sm text-obs-text">
          <option value="">Todas as origens</option>{Object.entries(ORIGINS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
      </label>
      <label className="min-w-52 text-xs text-obs-faint">Estado
        <select aria-label="Estado" value={status} onChange={(event) => setStatus(event.target.value)} className="mt-1 block w-full rounded-lg border border-white/10 bg-obs-panel px-3 py-2 text-sm text-obs-text">
          <option value="">Todos os estados</option>{STATES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      {selectedActions.map(({ value, label }) => <button key={value} type="button" disabled={busy} onClick={() => void runAction(value)} className="rounded-lg border border-obs-violet/30 px-3 py-2 text-sm text-obs-text disabled:opacity-40">{label}</button>)}
      <button type="button" onClick={() => load().catch((cause) => setError(cause?.message || "Falha ao atualizar."))} className="flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-sm text-obs-subtle"><RefreshCw size={15} />Atualizar</button>
    </div>

    {notice && <p role="status" className="rounded-lg bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">{notice}</p>}
    {error && <p role="alert" className="rounded-lg bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{error}</p>}

    <div className="overflow-x-auto rounded-xl border border-white/10 bg-obs-surface">
      <table className="w-full min-w-[960px] text-left text-sm">
        <thead className="bg-white/[0.03] text-xs text-obs-faint"><tr>
          <th className="w-12 p-3"><input aria-label="Selecionar todas" type="checkbox" checked={allSelected} onChange={(event) => setSelected(event.target.checked ? items.map((item) => item.id) : [])} /></th>
          <th className="p-3">Mensagem</th><th className="p-3">Lead</th><th className="p-3">Origem</th><th className="p-3">Previsão</th><th className="p-3">Estado</th><th className="p-3 text-right">Ação</th>
        </tr></thead>
        <tbody>{items.map((item) => {
          const sent = item.queue_state === "awaiting_customer";
          const action = primaryAction(item);
          return <tr key={item.id} className={`border-t border-white/[0.06] ${sent ? "bg-emerald-500/[0.06]" : "bg-rose-500/[0.06]"}`}>
            <td className="p-3"><input aria-label="Selecionar mensagem" type="checkbox" checked={selected.includes(item.id)} onChange={() => setSelected((current) => current.includes(item.id) ? current.filter((id) => id !== item.id) : [...current, item.id])} /></td>
            <td className="max-w-xl p-3"><p className="line-clamp-2 text-obs-text">{item.preview || "Sem conteúdo disponível"}</p>{item.last_error && <p className="mt-1 text-xs text-rose-200">{item.last_error}</p>}</td>
            <td className="p-3"><p className="text-obs-text">{item.lead?.nome || item.lead?.name || "Lead"}</p><p className="text-xs text-obs-faint">{item.persona?.name || item.persona?.slug || ""}</p></td>
            <td className="p-3 text-obs-subtle">{ORIGINS[item.origin || ""] || item.origin || "—"}</td>
            <td className="p-3 text-obs-subtle">{formatDate(item.available_at || item.created_at)}</td>
            <td className="p-3"><span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs ${sent ? "bg-emerald-500/15 text-emerald-200" : "bg-rose-500/15 text-rose-100"}`}>{sent ? <CheckCircle2 size={13} /> : <AlertCircle size={13} />}{statusLabel(item.queue_state)}</span></td>
            <td className="p-3 text-right">{action && <button type="button" disabled={busy} onClick={() => void runAction(action.action, [item])} className={`inline-flex items-center gap-1 rounded-lg px-3 py-2 text-xs font-medium disabled:opacity-40 ${action.action === "reactivate" ? "bg-obs-violet text-white" : action.action === "send-preview" ? "bg-emerald-500/20 text-emerald-100" : "border border-white/10 text-obs-text"}`}><Send size={13} />{action.label}</button>}</td>
          </tr>;
        })}</tbody>
      </table>
      {!items.length && <p className="p-10 text-center text-sm text-obs-subtle">Nenhuma mensagem ativa aguarda envio ou resposta da lead.</p>}
    </div>
    {nextOffset !== null && <button type="button" onClick={() => load(nextOffset, true)} className="self-center rounded-lg border border-white/10 px-4 py-2 text-sm text-obs-text">Carregar mais</button>}
  </section>;
}
