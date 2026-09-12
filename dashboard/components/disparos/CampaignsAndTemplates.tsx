"use client";

/**
 * Shared campaigns + templates screen. Rendered identically by the internal
 * dashboard (`components/disparos/CampaignsPanel.tsx`) and the client portal
 * (`app/clientes/[personaSlug]/disparos/page.tsx`) -- same fields, same
 * actions, same template lifecycle (create -> submit -> edit resubmits ->
 * sync). Callers differ only in which api.ts functions they bind (admin vs
 * portal-prefixed) and which persona scope they resolve; both are passed in
 * as props so this component never needs to know which caller it is.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, Ban, Loader2, Megaphone, Pause, RefreshCw, Send, ShieldCheck } from "lucide-react";

const DEFAULT_POLICY = {
  max_unanswered_attempts_per_lead: 3,
  max_total_sends: 500,
  max_unique_leads: 400,
  daily_send_limit: 100,
  hourly_send_limit: 20,
};

const PROVIDER_LABEL: Record<string, string> = { meta_cloud: "Meta", evolution_baileys: "Evolution" };

const APPROVAL_LABEL: Record<string, string> = {
  draft: "Rascunho", pending: "Em análise na Meta", approved: "Aprovado",
  rejected: "Rejeitado", paused: "Pausado", disabled: "Desativado",
};

const APPROVAL_TONE: Record<string, "neutral" | "good" | "bad" | "warn"> = {
  draft: "neutral", pending: "warn", approved: "good", rejected: "bad",
  paused: "neutral", disabled: "neutral",
};

export type CampaignsApi = {
  leadImports: () => Promise<any[]>;
  audiences: () => Promise<any[]>;
  campaigns: () => Promise<any[]>;
  campaignProviderHealth: () => Promise<any>;
  campaignPreview: (body: Record<string, unknown>) => Promise<any>;
  createCampaign: (body: Record<string, unknown>) => Promise<any>;
  pauseCampaign: (campaignId: string, body: Record<string, unknown>) => Promise<any>;
  cancelCampaign: (campaignId: string, body: Record<string, unknown>) => Promise<any>;
  sendCampaign: (campaignId: string, body: Record<string, unknown>) => Promise<any>;
  campaign: (campaignId: string) => Promise<any>;
  messageTemplates: (provider: string) => Promise<any[]>;
  createMessageTemplate: (body: Record<string, unknown>) => Promise<any>;
  editMessageTemplate: (templateId: string, body: Record<string, unknown>) => Promise<any>;
  submitMessageTemplate: (templateId: string, body: Record<string, unknown>) => Promise<any>;
  syncMessageTemplateStatus: (templateId: string) => Promise<any>;
};

export type Capabilities = { view: boolean; edit: boolean; manage?: boolean };

type Variant = "internal" | "portal";

const CLASSES: Record<Variant, Record<string, string>> = {
  internal: {
    card: "lg-card space-y-4",
    tableShell: "lg-table-shell overflow-hidden",
    input: "form-input",
    btnPrimary: "lg-btn lg-btn-primary",
    btnSecondary: "lg-btn lg-btn-secondary",
    btnDanger: "lg-btn lg-btn-danger",
    row: "[border-bottom:1px_solid_var(--border-glass-soft)] last:[border-bottom:0]",
    inlineBox: "rounded-lg bg-white/[0.03] p-3 [border:1px_solid_var(--border-glass-soft)]",
    faint: "text-obs-faint",
    subtle: "text-obs-subtle",
    text: "text-obs-text",
    label: "text-xs text-obs-subtle",
  },
  portal: {
    card: "rounded-2xl border border-slate-200 bg-white p-5 shadow-sm space-y-4",
    tableShell: "overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm",
    input: "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm disabled:bg-slate-50",
    btnPrimary: "flex items-center gap-2 rounded-xl bg-slate-950 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50",
    btnSecondary: "rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50",
    btnDanger: "rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-50",
    row: "border-b border-slate-100 p-5 last:border-b-0",
    inlineBox: "rounded-lg border border-slate-200 bg-slate-50 p-3",
    faint: "text-slate-400",
    subtle: "text-slate-500",
    text: "text-slate-950",
    label: "text-xs font-medium text-slate-500",
  },
};

function extractPlaceholders(text: string): string[] {
  const seen: string[] = [];
  for (const match of text.matchAll(/\{\{\s*(\w+)\s*\}\}/g)) {
    if (!seen.includes(match[1])) seen.push(match[1]);
  }
  return seen;
}

function componentsFromSchema(schema: any[]): {
  header: string; body: string; footer: string; buttons: string[];
} {
  const byType = (type: string) => (schema || []).find((c) => String(c?.type || "").toUpperCase() === type);
  return {
    header: byType("HEADER")?.text || "",
    body: byType("BODY")?.text || "",
    footer: byType("FOOTER")?.text || "",
    buttons: ((byType("BUTTONS")?.buttons || []) as any[]).map((b) => b?.text || ""),
  };
}

export function CampaignsAndTemplates({
  variant, personaKey, capabilities, api,
}: {
  variant: Variant;
  /** Empty string means "no persona selected yet" (internal dashboard only). */
  personaKey: string;
  capabilities: Capabilities;
  api: CampaignsApi;
}) {
  const cx = CLASSES[variant];
  const [imports, setImports] = useState<any[]>([]);
  const [groups, setGroups] = useState<any[]>([]);
  const [campaigns, setCampaigns] = useState<any[]>([]);
  const [health, setHealth] = useState<any>(null);
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

  // -- template authoring form --
  const [showTemplateForm, setShowTemplateForm] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<any>(null);
  const [templateKey, setTemplateKey] = useState("");
  const [templateMetaName, setTemplateMetaName] = useState("");
  const [templateCategory, setTemplateCategory] = useState<"MARKETING" | "UTILITY" | "AUTHENTICATION">("MARKETING");
  const [headerText, setHeaderText] = useState("");
  const [bodyText, setBodyText] = useState("");
  const [footerText, setFooterText] = useState("");
  const [showButtons, setShowButtons] = useState(false);
  const [buttonTexts, setButtonTexts] = useState<string[]>([""]);
  const [exampleValues, setExampleValues] = useState<Record<string, string>>({});
  const [templateBusy, setTemplateBusy] = useState(false);
  const [templateReasonAction, setTemplateReasonAction] = useState<{ template: any; action: "submit" | "edit" } | null>(null);
  const [templateActionReason, setTemplateActionReason] = useState("");

  const headerPlaceholders = useMemo(() => extractPlaceholders(headerText), [headerText]);
  const bodyPlaceholders = useMemo(() => extractPlaceholders(bodyText), [bodyText]);
  const allPlaceholders = useMemo(
    () => Array.from(new Set([...headerPlaceholders, ...bodyPlaceholders])),
    [headerPlaceholders, bodyPlaceholders],
  );

  const load = useCallback(async () => {
    if (!personaKey) {
      setImports([]); setGroups([]); setCampaigns([]); setHealth(null); setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const [nextImports, nextGroups, nextCampaigns, nextHealth] = await Promise.all([
        api.leadImports(), api.audiences(), api.campaigns(), api.campaignProviderHealth(),
      ]);
      setImports((nextImports || []).filter((row: any) => row.status === "completed"));
      setGroups(nextGroups || []);
      setCampaigns(nextCampaigns || []);
      setHealth(nextHealth);
    } catch (reason: any) {
      setError(reason?.message || "Falha ao carregar disparos.");
    } finally {
      setLoading(false);
    }
  }, [personaKey, api]);

  useEffect(() => {
    load();
    const timer = window.setInterval(() => load(), 10_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const loadTemplates = useCallback(async () => {
    if (!personaKey) { setTemplates([]); return; }
    try { setTemplates(await api.messageTemplates(provider)); }
    catch { setTemplates([]); }
  }, [personaKey, provider, api]);

  useEffect(() => {
    setTemplateId("");
    loadTemplates();
  }, [loadTemplates]);

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
    try { setPreview(await api.campaignPreview(payload)); }
    catch (reason: any) { setError(reason?.message || "Falha ao avaliar destinatarios."); }
    finally { setBusy(false); }
  }

  async function createDraft() {
    setBusy(true); setError(""); setNotice("");
    try {
      await api.createCampaign({
        ...payload,
        name: name || "Campanha",
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
      if (action === "pause") await api.pauseCampaign(campaign.id, body);
      else if (action === "cancel") await api.cancelCampaign(campaign.id, body);
      else {
        await api.sendCampaign(campaign.id, body);
        setNotice("Envio iniciado. Acompanhe o status por destinatario abaixo.");
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
    catch (reason: any) { setError(reason?.message || "Falha ao carregar detalhes."); }
  }

  function resetTemplateForm() {
    setEditingTemplate(null);
    setTemplateKey(""); setTemplateMetaName(""); setTemplateCategory("MARKETING");
    setHeaderText(""); setBodyText(""); setFooterText("");
    setShowButtons(false); setButtonTexts([""]); setExampleValues({});
  }

  function openCreateTemplateForm() {
    resetTemplateForm();
    setShowTemplateForm(true);
  }

  function openEditTemplateForm(template: any) {
    const parsed = componentsFromSchema(template.meta_component_schema || []);
    setEditingTemplate(template);
    setTemplateKey(template.template_key || "");
    setTemplateMetaName(template.meta_template_name || "");
    setTemplateCategory(template.meta_template_category || "MARKETING");
    setHeaderText(parsed.header);
    setBodyText(parsed.body);
    setFooterText(parsed.footer);
    setShowButtons(parsed.buttons.length > 0);
    setButtonTexts(parsed.buttons.length ? parsed.buttons : [""]);
    setExampleValues({});
    setShowTemplateForm(true);
  }

  function buildComponents(): Record<string, unknown>[] {
    const components: Record<string, unknown>[] = [];
    if (headerText.trim()) {
      components.push({
        type: "HEADER", text: headerText.trim(),
        ...(headerPlaceholders.length ? { example_values: pick(exampleValues, headerPlaceholders) } : {}),
      });
    }
    components.push({
      type: "BODY", text: bodyText.trim(),
      ...(bodyPlaceholders.length ? { example_values: pick(exampleValues, bodyPlaceholders) } : {}),
    });
    if (footerText.trim()) components.push({ type: "FOOTER", text: footerText.trim() });
    const buttons = buttonTexts.map((text) => text.trim()).filter(Boolean);
    if (showButtons && buttons.length) {
      components.push({ type: "BUTTONS", buttons: buttons.map((text) => ({ type: "QUICK_REPLY", text })) });
    }
    return components;
  }

  async function saveTemplate() {
    if (!personaKey || !templateKey.trim() || !bodyText.trim()) return;
    if (provider === "meta_cloud" && !templateMetaName.trim()) return;
    setTemplateBusy(true); setError("");
    try {
      const components = buildComponents();
      if (editingTemplate) {
        setTemplateReasonAction({ template: editingTemplate, action: "edit" });
        setTemplateBusy(false);
        return;
      }
      await api.createMessageTemplate({
        provider, template_key: templateKey.trim(), components,
        meta_template_name: templateMetaName || null, meta_template_category: templateCategory,
      });
      setShowTemplateForm(false);
      resetTemplateForm();
      await loadTemplates();
    } catch (reason: any) { setError(reason?.message || "Falha ao salvar template."); }
    finally { setTemplateBusy(false); }
  }

  async function confirmTemplateReasonAction() {
    if (!templateReasonAction || !templateActionReason.trim()) return;
    const { template, action } = templateReasonAction;
    setTemplateBusy(true); setError("");
    try {
      if (action === "edit") {
        await api.editMessageTemplate(template.id, {
          expected_revision: template.revision || 1,
          idempotency_key: `template-edit:${template.id}:${crypto.randomUUID()}`,
          reason: templateActionReason.trim(),
          components: buildComponents(),
          meta_template_category: templateCategory,
        });
        setShowTemplateForm(false);
        resetTemplateForm();
      } else {
        await api.submitMessageTemplate(template.id, {
          expected_revision: template.revision || 1,
          idempotency_key: `template-submit:${template.id}:${crypto.randomUUID()}`,
          reason: templateActionReason.trim(),
        });
      }
      setTemplateReasonAction(null); setTemplateActionReason("");
      await loadTemplates();
    } catch (reason: any) { setError(reason?.message || "Falha ao atualizar template."); }
    finally { setTemplateBusy(false); }
  }

  async function syncTemplate(template: any) {
    setTemplateBusy(true); setError("");
    try {
      await api.syncMessageTemplateStatus(template.id);
      await loadTemplates();
    } catch (reason: any) { setError(reason?.message || "Falha ao sincronizar status."); }
    finally { setTemplateBusy(false); }
  }

  if (!personaKey) {
    return <Notice cx={cx} text="Selecione uma persona para trabalhar com campanhas e templates." />;
  }

  if (loading) {
    return <p className={`p-8 text-center text-sm ${cx.faint}`}>Carregando disparos…</p>;
  }

  if (!health?.rollout_one_enabled) {
    return (
      <div className={`${cx.card} text-center`}>
        <Megaphone className={`mx-auto ${cx.faint}`} size={30} />
        <h2 className={`mt-3 font-semibold ${cx.text}`}>Disparos ainda não disponíveis</h2>
        <p className={`mx-auto mt-1 max-w-md text-sm ${cx.subtle}`}>
          Essa operação ainda não teve o envio de campanhas liberado para esta persona.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      {error && <Notice cx={cx} text={error} error />}
      {notice && <Notice cx={cx} text={notice} />}

      <section className="flex items-center justify-between text-xs">
        <p className={cx.subtle}>
          Provider {PROVIDER_LABEL[health?.provider] || "indisponível"} ·{" "}
          {health?.ready ? "pronto para elegibilidade" : "canal não conectado"}
        </p>
        <button type="button" onClick={() => load()} className={cx.btnSecondary}>
          <RefreshCw size={13} className="mr-1 inline" /> Atualizar
        </button>
      </section>

      <section className={cx.card}>
        <div>
          <p className={`text-[10px] uppercase tracking-[0.16em] ${cx.faint}`}>Nova campanha</p>
          <h2 className={`mt-1 text-base font-semibold ${cx.text}`}>Conteudo e elegibilidade</h2>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          <Field cx={cx} label="Nome"><input value={name} onChange={(e) => setName(e.target.value)} disabled={!capabilities.edit} className={cx.input} placeholder="Opt-in agosto" /></Field>
          <Field cx={cx} label="Objetivo"><input value={objective} onChange={(e) => setObjective(e.target.value)} disabled={!capabilities.edit} className={cx.input} placeholder="Reativar clientes" /></Field>
          <Field cx={cx} label="Tipo">
            <select value={kind} onChange={(e) => setKind(e.target.value as any)} disabled={!capabilities.edit} className={cx.input}>
              <option value="consent_request">Solicitação de consentimento</option>
              <option value="promotional">Promocional (exige opt-in)</option>
            </select>
          </Field>
          <Field cx={cx} label="Finalidade"><input value={purpose} onChange={(e) => setPurpose(e.target.value)} disabled={!capabilities.edit} className={cx.input} /></Field>
          <Field cx={cx} label="Grupo semântico">
            <select value={audienceId} onChange={(e) => setAudienceId(e.target.value)} disabled={!capabilities.edit} className={cx.input}>
              <option value="">Selecione</option>
              {groups.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
            </select>
          </Field>
          <Field cx={cx} label="Provider">
            <select value={provider} onChange={(e) => setProvider(e.target.value as any)} disabled={!capabilities.edit} className={cx.input}>
              <option value="meta_cloud">Meta</option>
              <option value="evolution_baileys">Evolution</option>
            </select>
          </Field>
          <Field cx={cx} label="Template">
            <select value={templateId} onChange={(e) => setTemplateId(e.target.value)} disabled={!capabilities.edit} className={cx.input}>
              <option value="">Nenhum (texto simples)</option>
              {templates.map((row) => <option key={row.id} value={row.id}>{row.meta_template_name || row.template_key}</option>)}
            </select>
          </Field>
          {provider === "meta_cloud" && (
            <Field cx={cx} label="Modo texto controlado (teste)">
              <label className={`flex items-center gap-2 text-xs ${cx.text}`}>
                <input type="checkbox" checked={controlledTest} onChange={(e) => setControlledTest(e.target.checked)} disabled={!capabilities.edit} />
                Permite texto simples sem template, so com conversa ativa nas ultimas 24h
              </label>
            </Field>
          )}
        </div>
        <Field cx={cx} label="Mensagem / snapshot de conteudo"><textarea value={message} onChange={(e) => setMessage(e.target.value)} disabled={!capabilities.edit} className={`${cx.input} min-h-24`} placeholder="Texto de referencia do template" /></Field>
        <Field cx={cx} label="Justificativa (motivo da campanha)"><textarea value={reason} onChange={(e) => setReason(e.target.value)} disabled={!capabilities.edit} className={`${cx.input} min-h-16`} placeholder="Por que esta campanha está sendo criada" /></Field>
        <div>
          <p className={`mb-2 text-xs font-medium ${cx.subtle}`}>Imports (deduplicados por lead)</p>
          <div className="grid gap-2 md:grid-cols-2">
            {imports.map((row) => (
              <label key={row.id} className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs ${cx.text} ${cx.inlineBox}`}>
                <input type="checkbox" disabled={!capabilities.edit} checked={selectedImports.includes(row.id)}
                  onChange={(e) => setSelectedImports((current) => e.target.checked ? [...current, row.id] : current.filter((id) => id !== row.id))} />
                <span className="truncate">{row.filename}</span>
                <span className={`ml-auto ${cx.faint}`}>{row.valid_rows} leads</span>
              </label>
            ))}
            {!imports.length && <p className={`text-xs ${cx.faint}`}>Importe uma lista antes de criar a campanha.</p>}
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-5">
          {Object.entries(policy).map(([key, value]) => (
            <Field cx={cx} key={key} label={policyLabel(key)}>
              <input type="number" min={1} value={value} disabled={!capabilities.edit}
                onChange={(e) => setPolicy((current) => ({ ...current, [key]: Number(e.target.value) }))} className={cx.input} />
            </Field>
          ))}
        </div>
        <div className="flex justify-end">
          <button disabled={!capabilities.edit || busy || !name || !purpose || !audienceId || !selectedImports.length} onClick={runPreview} className={cx.btnPrimary}>
            {busy ? <Loader2 size={13} className="animate-spin" /> : <ShieldCheck size={13} />} Avaliar elegibilidade
          </button>
        </div>
      </section>

      {preview && (
        <section className={cx.card}>
          <div className="flex flex-wrap gap-2 text-xs">
            <Badge cx={cx} text={`${preview.counts.selected_unique} únicos`} />
            <Badge cx={cx} text={`${preview.counts.eligible} elegíveis`} tone="good" />
            <Badge cx={cx} text={`${preview.counts.blocked} bloqueados`} tone="bad" />
            <Badge cx={cx} text={preview.provider_ready ? `${PROVIDER_LABEL[preview.provider]} pronto` : `${PROVIDER_LABEL[preview.provider]} indisponível`} tone={preview.provider_ready ? "good" : "bad"} />
          </div>
          {!!Object.keys(preview.blocked_reasons || {}).length && (
            <div className={`text-xs ${cx.subtle}`}>{Object.entries(preview.blocked_reasons).map(([key, value]) => <p key={key}>{key}: {String(value)}</p>)}</div>
          )}
          <p className={`break-all text-[10px] ${cx.faint}`}>Policy: {preview.policy_checksum}</p>
          <div className="flex justify-end">
            <button disabled={!capabilities.edit || busy || !preview.counts.selected_unique || !reason.trim()} onClick={createDraft} className={cx.btnPrimary}>
              Confirmar draft congelado
            </button>
          </div>
        </section>
      )}

      <section className={cx.card}>
        <div className="flex items-center justify-between">
          <div>
            <p className={`text-[10px] uppercase tracking-[0.16em] ${cx.faint}`}>Templates ({PROVIDER_LABEL[provider]})</p>
            <h2 className={`mt-1 text-base font-semibold ${cx.text}`}>Ciclo de vida do template</h2>
          </div>
          {capabilities.edit && (
            <button type="button" onClick={() => (showTemplateForm ? setShowTemplateForm(false) : openCreateTemplateForm())} className={cx.btnSecondary}>
              {showTemplateForm ? "Cancelar" : "Criar novo template"}
            </button>
          )}
        </div>

        {showTemplateForm && (
          <div className={`grid gap-3 ${cx.inlineBox} md:grid-cols-2`}>
            <Field cx={cx} label="Chave do template">
              <input value={templateKey} onChange={(e) => setTemplateKey(e.target.value)} disabled={!!editingTemplate} className={cx.input} placeholder="vz_lupas_boas_vindas" />
            </Field>
            {provider === "meta_cloud" && (
              <>
                <Field cx={cx} label="Nome aprovado na Meta">
                  <input value={templateMetaName} onChange={(e) => setTemplateMetaName(e.target.value)} disabled={!!editingTemplate} className={cx.input} placeholder="vz_lupas_boas_vindas" />
                </Field>
                <Field cx={cx} label="Categoria">
                  <select value={templateCategory} onChange={(e) => setTemplateCategory(e.target.value as any)} className={cx.input}>
                    <option value="MARKETING">Marketing</option>
                    <option value="UTILITY">Utilidade</option>
                    <option value="AUTHENTICATION">Autenticação</option>
                  </select>
                </Field>
              </>
            )}
            <div className="md:col-span-2">
              <Field cx={cx} label="Cabeçalho (opcional)"><input value={headerText} onChange={(e) => setHeaderText(e.target.value)} className={cx.input} placeholder="Bem-vindo à VZ Lupas" /></Field>
            </div>
            <div className="md:col-span-2">
              <Field cx={cx} label="Corpo (use {{1}}, {{2}}... para variáveis)">
                <textarea value={bodyText} onChange={(e) => setBodyText(e.target.value)} className={`${cx.input} min-h-24`} placeholder="Ola! Seja bem-vindo..." />
              </Field>
            </div>
            <div className="md:col-span-2">
              <Field cx={cx} label="Rodapé (opcional)"><input value={footerText} onChange={(e) => setFooterText(e.target.value)} className={cx.input} placeholder="VZ Lupas - Visão de verdade" /></Field>
            </div>
            {allPlaceholders.length > 0 && (
              <div className={`md:col-span-2 grid gap-2 ${cx.inlineBox} md:grid-cols-2`}>
                <p className={`md:col-span-2 text-xs ${cx.subtle}`}>A Meta exige um valor de exemplo para cada variavel antes de aprovar.</p>
                {allPlaceholders.map((token) => (
                  <Field cx={cx} key={token} label={`Exemplo para {{${token}}}`}>
                    <input value={exampleValues[token] || ""} onChange={(e) => setExampleValues((current) => ({ ...current, [token]: e.target.value }))} className={cx.input} />
                  </Field>
                ))}
              </div>
            )}
            <div className="md:col-span-2">
              <button type="button" onClick={() => setShowButtons((v) => !v)} className={`text-xs font-medium underline ${cx.subtle}`}>
                {showButtons ? "Remover botoes" : "Adicionar botoes de resposta rapida"}
              </button>
            </div>
            {showButtons && (
              <div className="md:col-span-2 flex flex-col gap-2">
                {buttonTexts.map((text, index) => (
                  <input key={index} value={text} className={cx.input} placeholder={`Botao ${index + 1}`}
                    onChange={(e) => setButtonTexts((current) => current.map((v, i) => i === index ? e.target.value : v))} />
                ))}
                {buttonTexts.length < 3 && (
                  <button type="button" onClick={() => setButtonTexts((current) => [...current, ""])} className={`text-xs underline ${cx.subtle}`}>+ botao</button>
                )}
              </div>
            )}
            <div className="md:col-span-2 flex justify-end gap-2">
              <button disabled={templateBusy || !templateKey.trim() || !bodyText.trim()} onClick={saveTemplate} className={cx.btnPrimary}>
                {editingTemplate ? "Salvar edição" : "Salvar rascunho"}
              </button>
            </div>
            {templateReasonAction?.action === "edit" && (
              <div className={`md:col-span-2 flex flex-wrap items-center gap-2 ${cx.inlineBox}`}>
                <input value={templateActionReason} onChange={(e) => setTemplateActionReason(e.target.value)}
                  placeholder="Motivo da edição" className={`min-w-0 flex-1 ${cx.input}`} />
                <button disabled={templateBusy || !templateActionReason.trim()} onClick={confirmTemplateReasonAction} className={cx.btnPrimary}>Confirmar</button>
                <button onClick={() => { setTemplateReasonAction(null); setTemplateActionReason(""); }} className={cx.btnSecondary}>Voltar</button>
              </div>
            )}
          </div>
        )}

        <div className="flex flex-col gap-2">
          {templates.map((row) => (
            <div key={row.id} className={`flex flex-wrap items-center gap-2 rounded-lg px-3 py-2 text-xs ${cx.inlineBox}`}>
              <div className="min-w-40 flex-1">
                <p className={`font-medium ${cx.text}`}>{row.meta_template_name || row.template_key}</p>
                <p className={cx.faint}>{row.template_key} · {row.meta_template_language}</p>
              </div>
              <StatusBadge status={row.meta_approval_status || "draft"} />
              {row.meta_rejection_reason && <span className="text-obs-rose text-[11px]">{row.meta_rejection_reason}</span>}
              {capabilities.edit && (
                <>
                  <button onClick={() => openEditTemplateForm(row)} className={cx.btnSecondary}>Editar</button>
                  {!row.meta_template_id && row.provider === "meta_cloud" && (
                    <button
                      onClick={() => { setTemplateReasonAction({ template: row, action: "submit" }); setTemplateActionReason(""); }}
                      className={cx.btnPrimary}
                    >
                      Submeter
                    </button>
                  )}
                  {row.meta_template_id && (
                    <button disabled={templateBusy} onClick={() => syncTemplate(row)} className={cx.btnSecondary}>Sincronizar status</button>
                  )}
                </>
              )}
              {templateReasonAction?.action === "submit" && templateReasonAction.template.id === row.id && (
                <div className={`mt-2 flex w-full flex-wrap items-center gap-2 ${cx.inlineBox}`}>
                  <input value={templateActionReason} onChange={(e) => setTemplateActionReason(e.target.value)}
                    placeholder="Motivo da submissao" className={`min-w-0 flex-1 ${cx.input}`} />
                  <button disabled={templateBusy || !templateActionReason.trim()} onClick={confirmTemplateReasonAction} className={cx.btnPrimary}>Confirmar</button>
                  <button onClick={() => { setTemplateReasonAction(null); setTemplateActionReason(""); }} className={cx.btnSecondary}>Voltar</button>
                </div>
              )}
            </div>
          ))}
          {!templates.length && <p className={`text-xs ${cx.faint}`}>Nenhum template criado para {PROVIDER_LABEL[provider]}.</p>}
        </div>
      </section>

      <section className={cx.tableShell}>
        <div className="px-4 py-3">
          <h2 className={`text-sm font-semibold ${cx.text}`}>Campanhas</h2>
          <p className={`text-xs ${cx.faint}`}>Polling a cada 10 segundos.</p>
        </div>
        {campaigns.map((row) => (
          <div key={row.id} className={cx.row}>
            <div className="flex flex-wrap items-center gap-3 px-4 py-3">
              <div className="min-w-48 flex-1">
                <p className={`text-sm font-medium ${cx.text}`}>{row.name}</p>
                <p className={`text-xs ${cx.faint}`}>rev. {row.current_revision} · {row.campaign_kind} · {PROVIDER_LABEL[row.provider] || row.provider} · {row.status}</p>
              </div>
              <Badge cx={cx} text={`${row.counts?.eligible || 0} elegíveis`} tone="good" />
              <Badge cx={cx} text={`${row.counts?.blocked || 0} bloqueados`} tone="bad" />
              {["draft", "validated", "running"].includes(row.status) && (
                <button disabled={!capabilities.edit} onClick={() => { setStatusAction({ campaign: row, action: "send" }); setStatusReason(""); }} className={cx.btnPrimary}>
                  <Send size={12} className="mr-1 inline" /> Enviar
                </button>
              )}
              <button onClick={() => toggleDetail(row)} className={cx.btnSecondary}>{expandedId === row.id ? "Ocultar" : "Detalhes"}</button>
              <button disabled={!capabilities.edit} onClick={() => { setStatusAction({ campaign: row, action: "pause" }); setStatusReason(""); }} className={cx.btnSecondary}>
                <Pause size={12} className="mr-1 inline" /> Pausar
              </button>
              <button disabled={!capabilities.edit} onClick={() => { setStatusAction({ campaign: row, action: "cancel" }); setStatusReason(""); }} className={cx.btnDanger}>
                <Ban size={12} className="mr-1 inline" /> Cancelar
              </button>
            </div>
            {statusAction && statusAction.campaign.id === row.id && (
              <div className={`mx-4 mb-3 flex flex-wrap items-center gap-2 ${cx.inlineBox}`}>
                {(statusAction.action !== "send" || row.provider === "meta_cloud") && (
                  <input value={statusReason} onChange={(e) => setStatusReason(e.target.value)}
                    placeholder={statusAction.action === "pause" ? "Motivo da pausa" : statusAction.action === "cancel" ? "Motivo do cancelamento" : "Motivo do envio (obrigatorio para Meta)"}
                    className={`min-w-0 flex-1 ${cx.input}`} />
                )}
                {statusAction.action === "send" && row.provider !== "meta_cloud" && (
                  <p className={`text-xs ${cx.subtle}`}>Evolution não exige justificativa para envio.</p>
                )}
                <button disabled={busy || (statusAction.action !== "send" && !statusReason.trim()) || (statusAction.action === "send" && row.provider === "meta_cloud" && !statusReason.trim())}
                  onClick={confirmStatusChange} className={cx.btnPrimary}>Confirmar</button>
                <button onClick={() => setStatusAction(null)} className={cx.btnSecondary}>Voltar</button>
              </div>
            )}
            {expandedId === row.id && detail && (
              <div className="space-y-2 px-4 pb-4">
                {detail.delivery_confidence_caveat && <Notice cx={cx} text={detail.delivery_confidence_caveat} />}
                <div className="overflow-x-auto rounded-lg">
                  <table className="w-full text-xs">
                    <thead className={cx.faint}>
                      <tr>
                        <th className="px-3 py-2 text-left">Lead</th>
                        <th className="px-3 py-2 text-left">Status seq.</th>
                        <th className="px-3 py-2 text-left">Provider</th>
                        <th className="px-3 py-2 text-left">Status envio</th>
                        <th className="px-3 py-2 text-left">Id externo</th>
                        <th className="px-3 py-2 text-left">Erro</th>
                        <th className="px-3 py-2 text-left">Horario</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(detail.recipients || []).map((recipient: any) => (
                        <tr key={recipient.id}>
                          <td className={`px-3 py-2 ${cx.text}`}>{recipient.lead_id}</td>
                          <td className={`px-3 py-2 ${cx.subtle}`}>{recipient.sequence_status}{recipient.blocked_reason ? ` (${recipient.blocked_reason})` : ""}</td>
                          <td className={`px-3 py-2 ${cx.subtle}`}>{PROVIDER_LABEL[recipient.send?.provider] || recipient.send?.provider || "-"}</td>
                          <td className={`px-3 py-2 ${cx.subtle}`}>{recipient.send?.status || "-"}</td>
                          <td className={`px-3 py-2 ${cx.faint}`}>{recipient.send?.external_message_id || "-"}</td>
                          <td className="px-3 py-2 text-obs-rose">{recipient.send?.error || "-"}</td>
                          <td className={`px-3 py-2 ${cx.faint}`}>{recipient.send?.attempted_at || "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        ))}
        {!campaigns.length && <p className={`p-8 text-center text-sm ${cx.faint}`}>Nenhuma campanha criada.</p>}
      </section>
    </div>
  );
}

function pick(source: Record<string, string>, keys: string[]): Record<string, string> {
  const result: Record<string, string> = {};
  for (const key of keys) result[key] = source[key] || "";
  return result;
}

function Field({ cx, label, children }: { cx: Record<string, string>; label: string; children: React.ReactNode }) {
  return <label className={cx.label}><span className="mb-1 block">{label}</span>{children}</label>;
}

function Badge({ cx, text, tone }: { cx: Record<string, string>; text: string; tone?: "good" | "bad" }) {
  const tones: Record<string, string> = {
    good: "bg-emerald-500/10 text-emerald-500",
    bad: "bg-rose-500/10 text-rose-500",
    neutral: "bg-slate-500/10 text-slate-400",
  };
  return <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${tones[tone || "neutral"]}`}>{text}</span>;
}

function StatusBadge({ status }: { status: string }) {
  const tone = APPROVAL_TONE[status] || "neutral";
  const tones: Record<string, string> = {
    good: "bg-emerald-500/10 text-emerald-500",
    bad: "bg-rose-500/10 text-rose-500",
    warn: "bg-amber-500/10 text-amber-500",
    neutral: "bg-slate-500/10 text-slate-400",
  };
  return <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${tones[tone]}`}>{APPROVAL_LABEL[status] || status}</span>;
}

function Notice({ cx, text, error }: { cx: Record<string, string>; text: string; error?: boolean }) {
  return (
    <div className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm ${error ? "bg-rose-500/10 text-rose-500" : "bg-amber-500/10 text-amber-500"}`}>
      <AlertCircle size={14} />{text}
    </div>
  );
}

function policyLabel(key: string) {
  return ({
    max_unanswered_attempts_per_lead: "Tentativas/lead", max_total_sends: "Total",
    max_unique_leads: "Leads únicos", daily_send_limit: "Por dia", hourly_send_limit: "Por hora",
  } as Record<string, string>)[key] || key;
}
