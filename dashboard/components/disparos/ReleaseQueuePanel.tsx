"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, Clock, Pause, Play, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";

const SCOPE_LABEL: Record<string, string> = {
  safety_paused_binding: "Canal pausado por seguranca",
  deploy_pause: "Retomada de deploy",
};

const BATCH_STATUS_LABEL: Record<string, string> = {
  releasing: "Registrando",
  registered: "Agendado",
  completed: "Concluido",
  cancelled: "Cancelado",
};

function MetricCard({ label, value, tone }: { label: string; value: string | number; tone: "green" | "amber" | "rose" | "violet" }) {
  const colors = {
    green: "text-emerald-300 bg-emerald-500/10 border-emerald-400/20",
    amber: "text-amber-300 bg-amber-500/10 border-amber-400/20",
    rose: "text-rose-300 bg-rose-500/10 border-rose-400/20",
    violet: "text-obs-violet bg-obs-violet/10 border-obs-violet/25",
  };
  return (
    <div className={`rounded-lg border px-4 py-3 ${colors[tone]}`}>
      <p className="text-[10px] uppercase tracking-[0.16em] opacity-70">{label}</p>
      <p className="mt-2 text-2xl font-semibold">{value}</p>
    </div>
  );
}

function Notice({ text, error }: { text: string; error?: boolean }) {
  return (
    <div className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm ${error ? "bg-obs-rose/10 text-obs-rose" : "bg-obs-amber/10 text-obs-amber"}`}>
      <AlertCircle size={14} />{text}
    </div>
  );
}

function toLocalInputValue(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function ReleaseQueuePanel() {
  const [personaId, setPersonaId] = useState("");
  const [bindings, setBindings] = useState<any[]>([]);
  const [batches, setBatches] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedBindingId, setSelectedBindingId] = useState("");
  const [reason, setReason] = useState("");
  const [expandedId, setExpandedId] = useState("");
  const [detail, setDetail] = useState<any>(null);
  const [rescheduleDrafts, setRescheduleDrafts] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    const scoped = window.localStorage.getItem("ai-brain-persona-id") || "";
    setPersonaId(scoped);
    if (!scoped) { setBindings([]); setBatches([]); return; }
    const [nextBindings, nextBatches] = await Promise.all([
      api.workflowBindings(scoped),
      api.releaseBatches(scoped),
    ]);
    setBindings(nextBindings || []);
    setBatches(nextBatches || []);
  }, []);

  useEffect(() => {
    load().catch((reason) => setError(reason?.message || "Falha ao carregar fila de liberacao."));
    const timer = window.setInterval(() => load().catch(() => {}), 15_000);
    const onPersona = () => { setSelectedBindingId(""); setReason(""); load().catch(() => {}); };
    window.addEventListener("ai-brain-persona-change", onPersona);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("ai-brain-persona-change", onPersona);
    };
  }, [load]);

  const pausedBindings = useMemo(
    () => bindings.filter((row) => row.connection_status === "safety_paused"),
    [bindings]
  );

  const kpis = useMemo(() => {
    const registered = batches.filter((row) => row.status === "registered");
    const pendingItems = registered.reduce((sum, row) => sum + (row.item_count || 0), 0);
    return {
      pausedBindings: pausedBindings.length,
      registeredBatches: registered.length,
      pendingItems,
      totalBatches: batches.length,
    };
  }, [pausedBindings, batches]);

  async function registerBatch() {
    if (!selectedBindingId || !reason.trim()) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await api.registerReleaseBatch({
        scope: "safety_paused_binding",
        persona_id: personaId,
        binding_id: selectedBindingId,
        reason,
        idempotency_key: `release-batch:${crypto.randomUUID()}`,
      });
      setNotice(
        result?.deduplicated
          ? "Essa acao ja tinha sido registrada."
          : `Canal restaurado e ${result?.item_count ?? 0} mensagem(ns) agendada(s) dentro do horario comercial.`
      );
      setSelectedBindingId(""); setReason("");
      await load();
    } catch (reason: any) {
      setError(reason?.message || "Falha ao registrar liberacao.");
    } finally {
      setBusy(false);
    }
  }

  async function toggleDetail(batch: any) {
    if (expandedId === batch.id) { setExpandedId(""); setDetail(null); return; }
    setExpandedId(batch.id);
    try { setDetail(await api.releaseBatch(batch.id)); }
    catch (reason: any) { setError(reason?.message || "Falha ao carregar detalhes do lote."); }
  }

  async function refreshDetail(batchId: string) {
    try { setDetail(await api.releaseBatch(batchId)); } catch { /* keep last known detail */ }
  }

  async function pauseItem(item: any) {
    const itemReason = window.prompt("Motivo da pausa deste item:");
    if (!itemReason?.trim()) return;
    try {
      await api.pauseReleaseItem(item.id, {
        reason: itemReason,
        idempotency_key: `release-item-pause:${item.id}:${crypto.randomUUID()}`,
      });
      await refreshDetail(item.batch_id);
    } catch (reason: any) { setError(reason?.message || "Falha ao pausar item."); }
  }

  async function resumeItem(item: any) {
    try {
      await api.resumeReleaseItem(item.id, {
        reason: "Retomado pelo operador",
        idempotency_key: `release-item-resume:${item.id}:${crypto.randomUUID()}`,
      });
      await refreshDetail(item.batch_id);
    } catch (reason: any) { setError(reason?.message || "Falha ao retomar item."); }
  }

  async function rescheduleItem(item: any) {
    const draft = rescheduleDrafts[item.id];
    if (!draft) return;
    const iso = new Date(draft).toISOString();
    try {
      await api.rescheduleReleaseItem(item.id, {
        reason: "Reagendado pelo operador",
        idempotency_key: `release-item-reschedule:${item.id}:${crypto.randomUUID()}`,
        new_available_at: iso,
      });
      await refreshDetail(item.batch_id);
    } catch (reason: any) { setError(reason?.message || "Falha ao reagendar item."); }
  }

  return (
    <div className="flex flex-col gap-5">
      {!personaId && <Notice text="Selecione uma persona no topo para ver a fila de liberacao." />}
      {error && <Notice text={error} error />}
      {notice && <Notice text={notice} />}

      {personaId && (
        <>
          <section className="grid gap-3 md:grid-cols-4">
            <MetricCard label="Canais pausados" value={kpis.pausedBindings} tone={kpis.pausedBindings ? "rose" : "green"} />
            <MetricCard label="Lotes agendados" value={kpis.registeredBatches} tone={kpis.registeredBatches ? "amber" : "green"} />
            <MetricCard label="Itens pendentes" value={kpis.pendingItems} tone={kpis.pendingItems ? "amber" : "green"} />
            <MetricCard label="Lotes no total" value={kpis.totalBatches} tone="violet" />
          </section>

          <section className="lg-card space-y-4">
            <div>
              <p className="text-[10px] uppercase tracking-[0.16em] text-obs-faint">Cadastrar acao</p>
              <h2 className="mt-1 text-base font-semibold text-obs-text">Liberar canal pausado por seguranca</h2>
              <p className="mt-1 text-xs text-obs-faint">
                Restaura o canal e agenda todo o backlog represado dentro do horario comercial (08:00-20:00, America/Sao_Paulo) na mesma acao.
              </p>
            </div>
            {!pausedBindings.length && <p className="text-xs text-obs-faint">Nenhum canal desta persona esta pausado por seguranca agora.</p>}
            {!!pausedBindings.length && (
              <div className="grid gap-3 md:grid-cols-2">
                <label className="text-xs text-obs-subtle">
                  <span className="mb-1 block">Canal pausado</span>
                  <select value={selectedBindingId} onChange={(e) => setSelectedBindingId(e.target.value)} className="form-input">
                    <option value="">Selecione</option>
                    {pausedBindings.map((row) => (
                      <option key={row.id} value={row.id}>
                        {row.workflow_name || row.whatsapp_number} ({row.provider})
                      </option>
                    ))}
                  </select>
                </label>
                <label className="text-xs text-obs-subtle">
                  <span className="mb-1 block">Motivo</span>
                  <input value={reason} onChange={(e) => setReason(e.target.value)} className="form-input" placeholder="Fim do teste, retomando atendimento normal" />
                </label>
              </div>
            )}
            <div className="flex justify-end">
              <button
                disabled={busy || !selectedBindingId || !reason.trim()}
                onClick={registerBatch}
                className="lg-btn lg-btn-primary"
              >
                <Play size={13} /> Cadastrar acao de liberacao
              </button>
            </div>
          </section>

          <section className="lg-table-shell overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 [border-bottom:1px_solid_var(--border-glass-soft)]">
              <div>
                <h2 className="text-sm font-semibold text-obs-text">Lotes de liberacao</h2>
                <p className="text-xs text-obs-faint">Polling a cada 15 segundos.</p>
              </div>
              <button className="lg-btn lg-btn-secondary" onClick={() => load()}><RefreshCw size={13} /> Atualizar</button>
            </div>
            {batches.map((row) => (
              <div key={row.id} className="[border-bottom:1px_solid_var(--border-glass-soft)] last:[border-bottom:0]">
                <div className="flex flex-wrap items-center gap-3 px-4 py-3">
                  <div className="min-w-48 flex-1">
                    <p className="text-sm font-medium text-obs-text">{SCOPE_LABEL[row.scope] || row.scope}</p>
                    <p className="text-xs text-obs-faint">
                      {row.item_count} item(ns) · {BATCH_STATUS_LABEL[row.status] || row.status} · {row.window_start_local}-{row.window_end_local} {row.timezone}
                    </p>
                  </div>
                  <button onClick={() => toggleDetail(row)} className="lg-btn lg-btn-secondary">
                    {expandedId === row.id ? "Ocultar" : "Detalhes"}
                  </button>
                </div>
                {expandedId === row.id && detail && (
                  <div className="space-y-2 px-4 pb-4">
                    <div className="overflow-x-auto rounded-lg [border:1px_solid_var(--border-glass-soft)]">
                      <table className="w-full text-xs">
                        <thead className="bg-white/[0.03] text-obs-faint">
                          <tr>
                            <th className="px-3 py-2 text-left">Lead</th>
                            <th className="px-3 py-2 text-left">Status atual</th>
                            <th className="px-3 py-2 text-left">Horario agendado</th>
                            <th className="px-3 py-2 text-left">Pausado</th>
                            <th className="px-3 py-2 text-left">Acoes</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(detail.items || []).map((item: any) => (
                            <tr key={item.id} className="[border-top:1px_solid_var(--border-glass-soft)]">
                              <td className="px-3 py-2 text-obs-text">{item.lead_ref}</td>
                              <td className="px-3 py-2 text-obs-subtle">{item.lead_buffer?.status || "-"}</td>
                              <td className="px-3 py-2 text-obs-faint">
                                {item.override_available_at || item.computed_available_at}
                              </td>
                              <td className="px-3 py-2 text-obs-subtle">{item.paused ? "Sim" : "Nao"}</td>
                              <td className="px-3 py-2">
                                <div className="flex flex-wrap items-center gap-2">
                                  {!item.paused && (
                                    <button onClick={() => pauseItem(item)} className="lg-btn lg-btn-secondary"><Pause size={12} /> Pausar</button>
                                  )}
                                  {item.paused && (
                                    <button onClick={() => resumeItem(item)} className="lg-btn lg-btn-secondary"><Play size={12} /> Retomar</button>
                                  )}
                                  <input
                                    type="datetime-local"
                                    className="form-input w-auto"
                                    value={rescheduleDrafts[item.id] ?? toLocalInputValue(item.override_available_at || item.computed_available_at)}
                                    onChange={(e) => setRescheduleDrafts((current) => ({ ...current, [item.id]: e.target.value }))}
                                  />
                                  <button onClick={() => rescheduleItem(item)} className="lg-btn lg-btn-secondary"><Clock size={12} /> Reagendar</button>
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            ))}
            {!batches.length && <p className="p-8 text-center text-sm text-obs-faint">Nenhum lote de liberacao registrado.</p>}
          </section>
        </>
      )}
    </div>
  );
}
