"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, Loader2, Megaphone, RefreshCw, Send, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { usePortal } from "../PortalContext";

const DEFAULT_POLICY = {
  max_unanswered_attempts_per_lead: 3,
  max_total_sends: 500,
  max_unique_leads: 400,
  daily_send_limit: 100,
  hourly_send_limit: 20,
};

const PROVIDER_LABEL: Record<string, string> = { meta_cloud: "Meta", evolution_baileys: "Evolution" };

export default function ClientDisparosPage() {
  const { personaSlug, capabilities } = usePortal();
  const [health, setHealth] = useState<any>(null);
  const [imports, setImports] = useState<any[]>([]);
  const [groups, setGroups] = useState<any[]>([]);
  const [campaigns, setCampaigns] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedImports, setSelectedImports] = useState<string[]>([]);
  const [audienceId, setAudienceId] = useState("");
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [purpose, setPurpose] = useState("ofertas_e_novidades");
  const [kind, setKind] = useState<"consent_request" | "promotional">("consent_request");
  const [provider, setProvider] = useState<"meta_cloud" | "evolution_baileys">("meta_cloud");
  const [templates, setTemplates] = useState<any[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [controlledTest, setControlledTest] = useState(false);
  const [message, setMessage] = useState("");
  const [reason, setReason] = useState("");
  const [policy, setPolicy] = useState(DEFAULT_POLICY);
  const [preview, setPreview] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [statusAction, setStatusAction] = useState<{ campaign: any; action: "pause" | "cancel" | "send" } | null>(null);
  const [statusReason, setStatusReason] = useState("");
  const [expandedId, setExpandedId] = useState("");
  const [detail, setDetail] = useState<any>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nextHealth, nextImports, nextGroups, nextCampaigns] = await Promise.all([
        api.portalCampaignProviderHealth(personaSlug),
        api.portalLeadImports(personaSlug),
        api.portalAudiences(personaSlug),
        api.portalCampaigns(personaSlug),
      ]);
      setHealth(nextHealth);
      setImports((nextImports || []).filter((row: any) => row.status === "completed"));
      setGroups(nextGroups || []);
      setCampaigns(nextCampaigns || []);
    } catch (reason: any) {
      setError(reason?.message || "Não foi possível carregar os disparos.");
    } finally {
      setLoading(false);
    }
  }, [personaSlug]);

  useEffect(() => {
    load();
    const timer = window.setInterval(() => load(), 10_000);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {
    setTemplateId("");
    if (!personaSlug) { setTemplates([]); return; }
    api.portalMessageTemplates(personaSlug, provider).then(setTemplates).catch(() => setTemplates([]));
  }, [personaSlug, provider]);

  const payload = useMemo(() => ({
    name, objective, purpose, campaign_kind: kind,
    import_batch_ids: selectedImports, audience_id: audienceId,
    provider, template_name: null,
    template_language: "pt_BR", template_id: templateId || null,
    send_mode: provider === "meta_cloud" && controlledTest ? "controlled_test" : "",
    message: message || null,
    variables: {}, assets: [], policy_overrides: policy,
  }), [name, objective, purpose, kind, selectedImports, audienceId, provider, templateId, controlledTest, message, policy]);

  async function runPreview() {
    setBusy(true); setError(""); setNotice("");
    try { setPreview(await api.portalCampaignPreview(personaSlug, payload)); }
    catch (reason: any) { setError(reason?.message || "Falha ao avaliar destinatários."); }
    finally { setBusy(false); }
  }

  async function createDraft() {
    setBusy(true); setError(""); setNotice("");
    try {
      await api.portalCreateCampaign(personaSlug, {
        ...payload,
        name: name || "Campanha",
        expected_revision: 0,
        expected_preview_checksum: preview.preview_checksum,
        idempotency_key: `campaign-draft:${crypto.randomUUID()}`,
        reason,
      });
      setNotice("Draft criado com revisão, política e destinatários congelados.");
      setPreview(null); setName(""); setObjective(""); setMessage(""); setReason(""); setTemplateId(""); setControlledTest(false);
      await load();
    } catch (reason: any) { setError(reason?.message || "Falha ao criar campanha."); }
    finally { setBusy(false); }
  }

  async function confirmStatusChange() {
    if (!statusAction) return;
    const { campaign, action } = statusAction;
    const needsReason = action !== "send" || campaign.provider === "meta_cloud";
    if (needsReason && !statusReason.trim()) return;
    setBusy(true); setError("");
    const body = {
      expected_revision: campaign.current_revision || 1,
      idempotency_key: `campaign-${action}:${campaign.id}:${crypto.randomUUID()}`,
      reason: needsReason ? statusReason.trim() : undefined,
    };
    try {
      if (action === "pause") await api.portalPauseCampaign(personaSlug, campaign.id, body);
      else if (action === "cancel") await api.portalCancelCampaign(personaSlug, campaign.id, body);
      else {
        await api.portalSendCampaign(personaSlug, campaign.id, body);
        setNotice("Envio iniciado. Acompanhe o status por destinatário abaixo.");
      }
      setStatusAction(null); setStatusReason("");
      await load();
    } catch (reason: any) { setError(reason?.message || "Falha ao alterar campanha."); }
    finally { setBusy(false); }
  }

  async function toggleDetail(campaign: any) {
    if (expandedId === campaign.id) { setExpandedId(""); setDetail(null); return; }
    setExpandedId(campaign.id);
    try { setDetail(await api.campaign(campaign.id)); }
    catch { setDetail(null); }
  }

  if (loading) {
    return <p className="p-8 text-center text-sm text-slate-500">Carregando disparos…</p>;
  }

  if (!health?.rollout_one_enabled) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-10 text-center shadow-sm">
        <Megaphone className="mx-auto text-slate-300" size={30} />
        <h2 className="mt-3 font-semibold text-slate-950">Disparos ainda não disponíveis</h2>
        <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">
          Essa operação ainda não teve o envio de campanhas liberado. Fale com o time responsável
          pela sua conta para habilitar.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-500">
          Provider {PROVIDER_LABEL[health?.provider] || "indisponível"} ·{" "}
          {health?.ready ? "pronto para elegibilidade" : "canal não conectado"}
        </p>
        <button
          type="button"
          onClick={() => load()}
          className="flex items-center gap-1.5 rounded-full border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
        >
          <RefreshCw size={13} /> Atualizar
        </button>
      </div>

      {error && (
        <div role="alert" className="flex items-center gap-2 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          <AlertCircle size={15} /> {error}
        </div>
      )}
      {notice && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-700">
          {notice}
        </div>
      )}

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-950">Nova campanha</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <Field label="Nome">
            <input value={name} onChange={(e) => setName(e.target.value)} disabled={!capabilities.edit}
              className="form-input w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm disabled:bg-slate-50" placeholder="Opt-in agosto" />
          </Field>
          <Field label="Objetivo">
            <input value={objective} onChange={(e) => setObjective(e.target.value)} disabled={!capabilities.edit}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm disabled:bg-slate-50" placeholder="Reativar clientes" />
          </Field>
          <Field label="Tipo">
            <select value={kind} onChange={(e) => setKind(e.target.value as any)} disabled={!capabilities.edit}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm disabled:bg-slate-50">
              <option value="consent_request">Solicitação de consentimento</option>
              <option value="promotional">Promocional (exige opt-in)</option>
            </select>
          </Field>
          <Field label="Grupo semântico">
            <select value={audienceId} onChange={(e) => setAudienceId(e.target.value)} disabled={!capabilities.edit}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm disabled:bg-slate-50">
              <option value="">Selecione</option>
              {groups.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
            </select>
          </Field>
          <Field label="Provider">
            <select value={provider} onChange={(e) => setProvider(e.target.value as any)} disabled={!capabilities.edit}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm disabled:bg-slate-50">
              <option value="meta_cloud">Meta</option>
              <option value="evolution_baileys">Evolution</option>
            </select>
          </Field>
          <Field label="Template">
            <select value={templateId} onChange={(e) => setTemplateId(e.target.value)} disabled={!capabilities.edit}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm disabled:bg-slate-50">
              <option value="">Nenhum (texto simples)</option>
              {templates.map((row) => <option key={row.id} value={row.id}>{row.meta_template_name || row.template_key}</option>)}
            </select>
          </Field>
        </div>
        {provider === "meta_cloud" && (
          <label className="mt-3 flex items-center gap-2 text-xs font-medium text-slate-500">
            <input type="checkbox" checked={controlledTest} onChange={(e) => setControlledTest(e.target.checked)} disabled={!capabilities.edit} />
            Modo texto controlado (teste) — só permitido com conversa ativa nas últimas 24h
          </label>
        )}
        <label className="mt-3 block text-xs font-medium text-slate-500">
          Mensagem de referência
          <textarea value={message} onChange={(e) => setMessage(e.target.value)} disabled={!capabilities.edit}
            className="mt-1 min-h-20 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm disabled:bg-slate-50" />
        </label>
        <label className="mt-3 block text-xs font-medium text-slate-500">
          Justificativa (motivo da campanha)
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} disabled={!capabilities.edit}
            placeholder="Por que esta campanha está sendo criada"
            className="mt-1 min-h-16 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm disabled:bg-slate-50" />
        </label>
        <div className="mt-4">
          <p className="mb-2 text-xs font-medium text-slate-500">Listas importadas</p>
          <div className="grid gap-2 md:grid-cols-2">
            {imports.map((row) => (
              <label key={row.id} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700">
                <input type="checkbox" disabled={!capabilities.edit} checked={selectedImports.includes(row.id)}
                  onChange={(e) => setSelectedImports((current) => e.target.checked ? [...current, row.id] : current.filter((id) => id !== row.id))} />
                <span className="truncate">{row.filename}</span>
                <span className="ml-auto text-slate-400">{row.valid_rows} leads</span>
              </label>
            ))}
            {!imports.length && <p className="text-xs text-slate-400">Nenhuma lista importada ainda.</p>}
          </div>
        </div>
        <div className="mt-4 flex justify-end">
          <button
            type="button"
            disabled={!capabilities.edit || busy || !name || !purpose || !audienceId || !selectedImports.length}
            onClick={runPreview}
            className="flex items-center gap-2 rounded-xl bg-slate-950 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />} Avaliar elegibilidade
          </button>
        </div>
      </section>

      {preview && (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap gap-2 text-xs">
            <Badge text={`${preview.counts.selected_unique} únicos`} />
            <Badge text={`${preview.counts.eligible} elegíveis`} tone="good" />
            <Badge text={`${preview.counts.blocked} bloqueados`} tone="bad" />
          </div>
          <div className="mt-4 flex justify-end">
            <button
              type="button"
              disabled={!capabilities.edit || busy || !preview.counts.selected_unique || !reason.trim()}
              onClick={createDraft}
              className="rounded-xl bg-slate-950 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50"
            >
              Confirmar draft congelado
            </button>
          </div>
        </section>
      )}

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 px-5 py-3">
          <h2 className="text-sm font-semibold text-slate-950">Campanhas</h2>
        </div>
        {campaigns.map((row) => (
          <div key={row.id} className="border-b border-slate-100 p-5 last:border-b-0">
            <div className="flex flex-wrap items-center gap-3">
              <div className="min-w-48 flex-1">
                <p className="text-sm font-medium text-slate-950">{row.name}</p>
                <p className="text-xs text-slate-500">rev. {row.current_revision} · {PROVIDER_LABEL[row.provider] || row.provider} · {row.status}</p>
              </div>
              {["draft", "validated", "running"].includes(row.status) && (
                <button type="button" disabled={!capabilities.edit}
                  onClick={() => { setStatusAction({ campaign: row, action: "send" }); setStatusReason(""); }}
                  className="flex items-center gap-1.5 rounded-lg bg-slate-950 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50">
                  <Send size={12} /> Enviar
                </button>
              )}
              <button type="button" onClick={() => toggleDetail(row)}
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50">
                {expandedId === row.id ? "Ocultar" : "Detalhes"}
              </button>
              <button type="button" disabled={!capabilities.edit}
                onClick={() => { setStatusAction({ campaign: row, action: "pause" }); setStatusReason(""); }}
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
                Pausar
              </button>
              <button type="button" disabled={!capabilities.edit}
                onClick={() => { setStatusAction({ campaign: row, action: "cancel" }); setStatusReason(""); }}
                className="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-50">
                Cancelar
              </button>
            </div>
            {statusAction && statusAction.campaign.id === row.id && (
              <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 p-3">
                {(statusAction.action !== "send" || row.provider === "meta_cloud") && (
                  <input value={statusReason} onChange={(e) => setStatusReason(e.target.value)}
                    placeholder={
                      statusAction.action === "pause" ? "Motivo da pausa"
                        : statusAction.action === "cancel" ? "Motivo do cancelamento"
                          : "Motivo do envio (obrigatório para Meta)"
                    }
                    className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs" />
                )}
                {statusAction.action === "send" && row.provider !== "meta_cloud" && (
                  <p className="text-xs text-slate-500">Evolution não exige justificativa para envio.</p>
                )}
                <button type="button" disabled={busy || (statusAction.action !== "send" && !statusReason.trim())
                  || (statusAction.action === "send" && row.provider === "meta_cloud" && !statusReason.trim())}
                  onClick={confirmStatusChange}
                  className="rounded-lg bg-slate-950 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50">
                  Confirmar
                </button>
                <button type="button" onClick={() => setStatusAction(null)}
                  className="rounded-lg px-3 py-1.5 text-xs font-medium text-slate-500 hover:bg-slate-100">
                  Voltar
                </button>
              </div>
            )}
            {expandedId === row.id && detail && (
              <div className="mt-3 space-y-2">
                {detail.delivery_confidence_caveat && (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
                    {detail.delivery_confidence_caveat}
                  </div>
                )}
                <div className="overflow-x-auto rounded-lg border border-slate-200">
                  <table className="w-full text-xs">
                    <thead className="bg-slate-50 text-slate-500">
                      <tr>
                        <th className="px-3 py-2 text-left">Lead</th>
                        <th className="px-3 py-2 text-left">Status seq.</th>
                        <th className="px-3 py-2 text-left">Provider</th>
                        <th className="px-3 py-2 text-left">Status envio</th>
                        <th className="px-3 py-2 text-left">Id externo</th>
                        <th className="px-3 py-2 text-left">Erro</th>
                        <th className="px-3 py-2 text-left">Horário</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(detail.recipients || []).map((recipient: any) => (
                        <tr key={recipient.id} className="border-t border-slate-100">
                          <td className="px-3 py-2 text-slate-800">{recipient.lead_id}</td>
                          <td className="px-3 py-2 text-slate-600">{recipient.sequence_status}{recipient.blocked_reason ? ` (${recipient.blocked_reason})` : ""}</td>
                          <td className="px-3 py-2 text-slate-600">{PROVIDER_LABEL[recipient.send?.provider] || recipient.send?.provider || "-"}</td>
                          <td className="px-3 py-2 text-slate-600">{recipient.send?.status || "-"}</td>
                          <td className="px-3 py-2 text-slate-400">{recipient.send?.external_message_id || "-"}</td>
                          <td className="px-3 py-2 text-red-600">{recipient.send?.error || "-"}</td>
                          <td className="px-3 py-2 text-slate-400">{recipient.send?.attempted_at || "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        ))}
        {!campaigns.length && <p className="p-10 text-center text-sm text-slate-500">Nenhuma campanha criada.</p>}
      </section>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="text-xs font-medium text-slate-500">{label}<div className="mt-1">{children}</div></label>;
}

function Badge({ text, tone }: { text: string; tone?: "good" | "bad" }) {
  const classes = tone === "good"
    ? "bg-emerald-50 text-emerald-700"
    : tone === "bad"
      ? "bg-red-50 text-red-700"
      : "bg-slate-100 text-slate-600";
  return <span className={`rounded-full px-2.5 py-1 font-medium ${classes}`}>{text}</span>;
}
