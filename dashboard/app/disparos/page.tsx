"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, Ban, Loader2, Megaphone, Pause, RefreshCw, Send, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";

const DEFAULT_POLICY = {
  max_unanswered_attempts_per_lead: 3,
  max_total_sends: 500,
  max_unique_leads: 400,
  daily_send_limit: 100,
  hourly_send_limit: 20,
};

const PROVIDER_LABEL: Record<string, string> = { meta_cloud: "Meta", evolution_baileys: "Evolution" };

export default function CampaignsPage() {
  const [personaId, setPersonaId] = useState("");
  const [imports, setImports] = useState<any[]>([]);
  const [groups, setGroups] = useState<any[]>([]);
  const [campaigns, setCampaigns] = useState<any[]>([]);
  const [health, setHealth] = useState<any>(null);
  const [selectedImports, setSelectedImports] = useState<string[]>([]);
  const [audienceId, setAudienceId] = useState("");
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [purpose, setPurpose] = useState("ofertas_e_novidades");
  const [kind, setKind] = useState<"consent_request" | "promotional">("consent_request");
  const [provider, setProvider] = useState<"meta_cloud" | "evolution_baileys">("meta_cloud");
  const [templates, setTemplates] = useState<any[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [showNewTemplate, setShowNewTemplate] = useState(false);
  const [newTemplateKey, setNewTemplateKey] = useState("");
  const [newTemplateBody, setNewTemplateBody] = useState("");
  const [newTemplateMetaName, setNewTemplateMetaName] = useState("");
  const [controlledTest, setControlledTest] = useState(false);
  const [message, setMessage] = useState("");
  const [reason, setReason] = useState("");
  const [policy, setPolicy] = useState(DEFAULT_POLICY);
  const [preview, setPreview] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [expandedId, setExpandedId] = useState("");
  const [detail, setDetail] = useState<any>(null);

  const load = useCallback(async () => {
    const scoped = window.localStorage.getItem("ai-brain-persona-id") || "";
    setPersonaId(scoped);
    if (!scoped) {
      setImports([]); setGroups([]); setCampaigns([]); setHealth(null);
      return;
    }
    const [nextImports, nextGroups, nextCampaigns, nextHealth] = await Promise.all([
      api.leadImports(scoped), api.audiences(scoped), api.campaigns(scoped),
      api.campaignProviderHealth(scoped),
    ]);
    setImports(nextImports.filter((row: any) => row.status === "completed"));
    setGroups(nextGroups);
    setCampaigns(nextCampaigns);
    setHealth(nextHealth);
  }, []);

  useEffect(() => {
    load().catch((reason) => setError(reason?.message || "Falha ao carregar disparos."));
    const timer = window.setInterval(() => load().catch(() => {}), 10_000);
    const onPersona = () => {
      setPreview(null); setSelectedImports([]); setAudienceId("");
      load().catch(() => {});
    };
    window.addEventListener("ai-brain-persona-change", onPersona);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("ai-brain-persona-change", onPersona);
    };
  }, [load]);

  const loadTemplates = useCallback(async () => {
    if (!personaId) { setTemplates([]); return; }
    try { setTemplates(await api.messageTemplates(personaId, provider)); }
    catch { setTemplates([]); }
  }, [personaId, provider]);

  useEffect(() => {
    setTemplateId("");
    loadTemplates().catch(() => {});
  }, [loadTemplates]);

  const payload = useMemo(() => ({
    persona_id: personaId,
    name,
    objective,
    purpose,
    campaign_kind: kind,
    import_batch_ids: selectedImports,
    audience_id: audienceId,
    provider,
    template_name: null,
    template_language: "pt_BR",
    template_id: templateId || null,
    send_mode: provider === "meta_cloud" && controlledTest ? "controlled_test" : "",
    message: message || null,
    variables: {},
    assets: [],
    policy_overrides: policy,
  }), [personaId, name, objective, purpose, kind, selectedImports, audienceId, provider, templateId, controlledTest, message, policy]);

  async function runPreview() {
    setBusy(true); setError(""); setNotice("");
    try { setPreview(await api.campaignPreview(payload)); }
    catch (reason: any) { setError(reason?.message || "Falha ao avaliar destinatarios."); }
    finally { setBusy(false); }
  }

  async function createDraft() {
    setBusy(true); setError(""); setNotice("");
    try {
      await api.createCampaign({
        ...payload,
        expected_revision: 0,
        expected_preview_checksum: preview.preview_checksum,
        idempotency_key: `campaign-draft:${crypto.randomUUID()}`,
        reason,
      });
      setNotice("Draft criado com revisao, politica e destinatarios congelados.");
      setPreview(null); setName(""); setObjective(""); setMessage(""); setReason(""); setTemplateId(""); setControlledTest(false);
      await load();
    } catch (reason: any) { setError(reason?.message || "Falha ao criar campanha."); }
    finally { setBusy(false); }
  }

  async function createTemplate() {
    if (!personaId || !newTemplateKey.trim() || !newTemplateBody.trim()) return;
    setBusy(true); setError("");
    try {
      await api.createMessageTemplate({
        persona_id: personaId,
        provider,
        template_key: newTemplateKey.trim(),
        body: newTemplateBody,
        meta_template_name: newTemplateMetaName || null,
      });
      setNewTemplateKey(""); setNewTemplateBody(""); setNewTemplateMetaName(""); setShowNewTemplate(false);
      await loadTemplates();
    } catch (reason: any) { setError(reason?.message || "Falha ao criar template."); }
    finally { setBusy(false); }
  }

  async function changeStatus(campaign: any, action: "pause" | "cancel") {
    const reason = window.prompt(action === "pause" ? "Motivo da pausa:" : "Motivo do cancelamento:");
    if (!reason?.trim()) return;
    const body = {
      expected_revision: campaign.current_revision || 1,
      idempotency_key: `campaign-${action}:${campaign.id}:${crypto.randomUUID()}`,
      reason,
    };
    try {
      if (action === "pause") await api.pauseCampaign(campaign.id, body);
      else await api.cancelCampaign(campaign.id, body);
      await load();
    } catch (reason: any) { setError(reason?.message || "Falha ao alterar campanha."); }
  }

  async function sendCampaign(campaign: any) {
    let sendReason: string | null | undefined = undefined;
    if (campaign.provider === "meta_cloud") {
      sendReason = window.prompt("Motivo do envio (obrigatorio para Meta):");
      if (!sendReason?.trim()) return;
    }
    const body = {
      expected_revision: campaign.current_revision || 1,
      idempotency_key: `campaign-send:${campaign.id}:${crypto.randomUUID()}`,
      reason: sendReason || undefined,
    };
    setBusy(true); setError("");
    try {
      await api.sendCampaign(campaign.id, body);
      setNotice("Envio iniciado. Acompanhe o status por destinatario abaixo.");
      await load();
      if (expandedId === campaign.id) await toggleDetail(campaign, true);
    } catch (reason: any) { setError(reason?.message || "Falha ao enviar campanha."); }
    finally { setBusy(false); }
  }

  async function toggleDetail(campaign: any, forceOpen = false) {
    if (!forceOpen && expandedId === campaign.id) { setExpandedId(""); setDetail(null); return; }
    setExpandedId(campaign.id);
    try { setDetail(await api.campaign(campaign.id)); }
    catch (reason: any) { setError(reason?.message || "Falha ao carregar detalhes."); }
  }

  return (
    <div className="lg-page-narrow flex flex-col gap-5 pb-16">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-obs-violet/10 text-obs-violet [border:1px_solid_var(--border-glass)]"><Megaphone size={16} /></span>
          <div><p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">Mensageria</p><h1 className="mt-1 text-xl font-semibold text-obs-text">Disparos</h1></div>
        </div>
        <button className="lg-btn lg-btn-secondary" onClick={() => load()}><RefreshCw size={13} /> Atualizar</button>
      </header>

      {!personaId && <Notice text="Selecione uma persona no topo para trabalhar com campanhas." />}
      {error && <Notice text={error} error />}
      {notice && <Notice text={notice} />}

      {personaId && (
        <>
          <section className="grid gap-3 md:grid-cols-4">
            <Metric label="Imports disponiveis" value={imports.length} />
            <Metric label="Campanhas" value={campaigns.length} />
            <Metric label="Provider" value={PROVIDER_LABEL[health?.provider] || "Indisponivel"} />
            <Metric label="Saude" value={health?.ready ? "Pronto" : "Bloqueado"} />
          </section>

          <section className="lg-card space-y-4">
            <div><p className="text-[10px] uppercase tracking-[0.16em] text-obs-faint">Nova campanha</p><h2 className="mt-1 text-base font-semibold text-obs-text">Conteudo e elegibilidade</h2></div>
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Nome"><input value={name} onChange={(e) => setName(e.target.value)} className="form-input" placeholder="Opt-in agosto" /></Field>
              <Field label="Objetivo"><input value={objective} onChange={(e) => setObjective(e.target.value)} className="form-input" placeholder="Reativar clientes" /></Field>
              <Field label="Tipo"><select value={kind} onChange={(e) => setKind(e.target.value as any)} className="form-input"><option value="consent_request">Solicitacao de consentimento</option><option value="promotional">Promocional (exige opt-in)</option></select></Field>
              <Field label="Finalidade"><input value={purpose} onChange={(e) => setPurpose(e.target.value)} className="form-input" /></Field>
              <Field label="Grupo semantico"><select value={audienceId} onChange={(e) => setAudienceId(e.target.value)} className="form-input"><option value="">Selecione</option>{groups.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></Field>
              <Field label="Provider"><select value={provider} onChange={(e) => setProvider(e.target.value as any)} className="form-input"><option value="meta_cloud">Meta</option><option value="evolution_baileys">Evolution</option></select></Field>
              <Field label="Template">
                <select value={templateId} onChange={(e) => setTemplateId(e.target.value)} className="form-input">
                  <option value="">Nenhum (texto simples)</option>
                  {templates.map((row) => <option key={row.id} value={row.id}>{row.meta_template_name || row.template_key}</option>)}
                </select>
              </Field>
              {provider === "meta_cloud" && (
                <Field label="Modo texto controlado (teste)">
                  <label className="flex items-center gap-2 text-xs text-obs-text">
                    <input type="checkbox" checked={controlledTest} onChange={(e) => setControlledTest(e.target.checked)} />
                    Permite texto simples sem template, apenas se houver conversa ativa nas ultimas 24h
                  </label>
                </Field>
              )}
            </div>
            <button type="button" onClick={() => setShowNewTemplate((v) => !v)} className="text-xs font-medium text-obs-violet underline">
              {showNewTemplate ? "Cancelar novo template" : "Criar novo template"}
            </button>
            {showNewTemplate && (
              <div className="grid gap-3 rounded-lg bg-white/[0.03] p-3 [border:1px_solid_var(--border-glass-soft)] md:grid-cols-2">
                <Field label="Chave do template"><input value={newTemplateKey} onChange={(e) => setNewTemplateKey(e.target.value)} className="form-input" placeholder="consentimento_ofertas_v1" /></Field>
                {provider === "meta_cloud" && (
                  <Field label="Nome aprovado na Meta"><input value={newTemplateMetaName} onChange={(e) => setNewTemplateMetaName(e.target.value)} className="form-input" placeholder="consentimento_ofertas_v1" /></Field>
                )}
                <div className="md:col-span-2">
                  <Field label="Corpo (use {{variavel}} para placeholders)">
                    <textarea value={newTemplateBody} onChange={(e) => setNewTemplateBody(e.target.value)} className="form-input min-h-20" placeholder="Ola {{nome}}, temos novidades para voce." />
                  </Field>
                </div>
                <div className="md:col-span-2 flex justify-end"><button disabled={busy || !newTemplateKey.trim() || !newTemplateBody.trim()} onClick={createTemplate} className="lg-btn lg-btn-secondary">Salvar template</button></div>
              </div>
            )}
            <Field label="Mensagem / snapshot de conteudo"><textarea value={message} onChange={(e) => setMessage(e.target.value)} className="form-input min-h-24" placeholder="Texto de referencia do template" /></Field>
            <Field label="Justificativa (motivo da campanha)"><textarea value={reason} onChange={(e) => setReason(e.target.value)} className="form-input min-h-16" placeholder="Por que esta campanha esta sendo criada" /></Field>
            <div>
              <p className="mb-2 text-xs font-medium text-obs-subtle">Imports (deduplicados por lead)</p>
              <div className="grid gap-2 md:grid-cols-2">
                {imports.map((row) => <label key={row.id} className="flex items-center gap-2 rounded-lg bg-white/[0.03] px-3 py-2 text-xs text-obs-text [border:1px_solid_var(--border-glass-soft)]"><input type="checkbox" checked={selectedImports.includes(row.id)} onChange={(e) => setSelectedImports((current) => e.target.checked ? [...current, row.id] : current.filter((id) => id !== row.id))} /> <span className="truncate">{row.filename}</span><span className="ml-auto text-obs-faint">{row.valid_rows} leads</span></label>)}
                {!imports.length && <p className="text-xs text-obs-faint">Importe uma lista antes de criar a campanha.</p>}
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-5">
              {Object.entries(policy).map(([key, value]) => <Field key={key} label={policyLabel(key)}><input type="number" min={1} value={value} onChange={(e) => setPolicy((current) => ({ ...current, [key]: Number(e.target.value) }))} className="form-input" /></Field>)}
            </div>
            <div className="flex justify-end"><button disabled={busy || !name || !purpose || !audienceId || !selectedImports.length} onClick={runPreview} className="lg-btn lg-btn-primary">{busy ? <Loader2 size={13} className="animate-spin" /> : <ShieldCheck size={13} />} Avaliar elegibilidade</button></div>
          </section>

          {preview && <section className="lg-card space-y-3">
            <div className="flex flex-wrap gap-2"><Badge text={`${preview.counts.selected_unique} unicos`} /><Badge text={`${preview.counts.eligible} elegiveis`} good /><Badge text={`${preview.counts.blocked} bloqueados`} bad /><Badge text={preview.provider_ready ? `${PROVIDER_LABEL[preview.provider]} pronto` : `${PROVIDER_LABEL[preview.provider]} indisponivel`} good={preview.provider_ready} bad={!preview.provider_ready} /></div>
            {!!Object.keys(preview.blocked_reasons || {}).length && <div className="text-xs text-obs-subtle">{Object.entries(preview.blocked_reasons).map(([key, value]) => <p key={key}>{key}: {String(value)}</p>)}</div>}
            <p className="break-all text-[10px] text-obs-faint">Policy: {preview.policy_checksum}</p>
            <div className="flex justify-end"><button disabled={busy || !preview.counts.selected_unique || !reason.trim()} onClick={createDraft} className="lg-btn lg-btn-primary">Confirmar draft congelado</button></div>
          </section>}

          <section className="lg-table-shell overflow-hidden">
            <div className="px-4 py-3 [border-bottom:1px_solid_var(--border-glass-soft)]"><h2 className="text-sm font-semibold text-obs-text">Campanhas</h2><p className="text-xs text-obs-faint">Polling a cada 10 segundos.</p></div>
            {campaigns.map((row) => (
              <div key={row.id} className="[border-bottom:1px_solid_var(--border-glass-soft)] last:[border-bottom:0]">
                <div className="flex flex-wrap items-center gap-3 px-4 py-3">
                  <div className="min-w-48 flex-1"><p className="text-sm font-medium text-obs-text">{row.name}</p><p className="text-xs text-obs-faint">rev. {row.current_revision} · {row.campaign_kind} · {PROVIDER_LABEL[row.provider] || row.provider} · {row.status}</p></div>
                  <Badge text={`${row.counts?.eligible || 0} elegiveis`} good />
                  <Badge text={`${row.counts?.blocked || 0} bloqueados`} bad />
                  {["draft", "validated", "running"].includes(row.status) && (
                    <button onClick={() => sendCampaign(row)} className="lg-btn lg-btn-primary"><Send size={12} /> Enviar</button>
                  )}
                  <button onClick={() => toggleDetail(row)} className="lg-btn lg-btn-secondary">{expandedId === row.id ? "Ocultar" : "Detalhes"}</button>
                  <button onClick={() => changeStatus(row, "pause")} className="lg-btn lg-btn-secondary"><Pause size={12} /> Pausar</button>
                  <button onClick={() => changeStatus(row, "cancel")} className="lg-btn lg-btn-danger"><Ban size={12} /> Cancelar</button>
                </div>
                {expandedId === row.id && detail && (
                  <div className="space-y-2 px-4 pb-4">
                    {detail.delivery_confidence_caveat && <Notice text={detail.delivery_confidence_caveat} />}
                    <div className="overflow-x-auto rounded-lg [border:1px_solid_var(--border-glass-soft)]">
                      <table className="w-full text-xs">
                        <thead className="bg-white/[0.03] text-obs-faint">
                          <tr><th className="px-3 py-2 text-left">Lead</th><th className="px-3 py-2 text-left">Status seq.</th><th className="px-3 py-2 text-left">Provider</th><th className="px-3 py-2 text-left">Status envio</th><th className="px-3 py-2 text-left">Id externo</th><th className="px-3 py-2 text-left">Erro</th><th className="px-3 py-2 text-left">Horario</th></tr>
                        </thead>
                        <tbody>
                          {(detail.recipients || []).map((recipient: any) => (
                            <tr key={recipient.id} className="[border-top:1px_solid_var(--border-glass-soft)]">
                              <td className="px-3 py-2 text-obs-text">{recipient.lead_id}</td>
                              <td className="px-3 py-2 text-obs-subtle">{recipient.sequence_status}{recipient.blocked_reason ? ` (${recipient.blocked_reason})` : ""}</td>
                              <td className="px-3 py-2 text-obs-subtle">{PROVIDER_LABEL[recipient.send?.provider] || recipient.send?.provider || "-"}</td>
                              <td className="px-3 py-2 text-obs-subtle">{recipient.send?.status || "-"}</td>
                              <td className="px-3 py-2 text-obs-faint">{recipient.send?.external_message_id || "-"}</td>
                              <td className="px-3 py-2 text-obs-rose">{recipient.send?.error || "-"}</td>
                              <td className="px-3 py-2 text-obs-faint">{recipient.send?.attempted_at || "-"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            ))}
            {!campaigns.length && <p className="p-8 text-center text-sm text-obs-faint">Nenhuma campanha criada.</p>}
          </section>
        </>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) { return <label className="text-xs text-obs-subtle"><span className="mb-1 block">{label}</span>{children}</label>; }
function Metric({ label, value }: { label: string; value: string | number }) { return <div className="lg-card"><p className="text-[10px] uppercase tracking-[0.16em] text-obs-faint">{label}</p><p className="mt-2 text-xl font-semibold text-obs-text">{value}</p></div>; }
function Badge({ text, good, bad }: { text: string; good?: boolean; bad?: boolean }) { return <span className={`lg-badge ${good ? "lg-badge-success" : bad ? "lg-badge-error" : "lg-badge-info"}`}>{text}</span>; }
function Notice({ text, error }: { text: string; error?: boolean }) { return <div className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm ${error ? "bg-obs-rose/10 text-obs-rose" : "bg-obs-amber/10 text-obs-amber"}`}><AlertCircle size={14} />{text}</div>; }
function policyLabel(key: string) { return ({ max_unanswered_attempts_per_lead: "Tentativas/lead", max_total_sends: "Total", max_unique_leads: "Leads unicos", daily_send_limit: "Por dia", hourly_send_limit: "Por hora" } as Record<string, string>)[key] || key; }
