"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, Ban, Loader2, Megaphone, Pause, RefreshCw, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";

const DEFAULT_POLICY = {
  max_unanswered_attempts_per_lead: 3,
  max_total_sends: 500,
  max_unique_leads: 400,
  daily_send_limit: 100,
  hourly_send_limit: 20,
};

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
  const [templateName, setTemplateName] = useState("");
  const [message, setMessage] = useState("");
  const [policy, setPolicy] = useState(DEFAULT_POLICY);
  const [preview, setPreview] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

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

  const payload = useMemo(() => ({
    persona_id: personaId,
    name,
    objective,
    purpose,
    campaign_kind: kind,
    import_batch_ids: selectedImports,
    audience_id: audienceId,
    provider: "meta_cloud",
    template_name: templateName || null,
    template_language: "pt_BR",
    message: message || null,
    variables: {},
    assets: [],
    policy_overrides: policy,
  }), [personaId, name, objective, purpose, kind, selectedImports, audienceId, templateName, message, policy]);

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
        reason: "Criacao confirmada na interface de disparos",
      });
      setNotice("Draft criado com revisao, politica e destinatarios congelados.");
      setPreview(null); setName(""); setObjective(""); setTemplateName(""); setMessage("");
      await load();
    } catch (reason: any) { setError(reason?.message || "Falha ao criar campanha."); }
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
            <Metric label="Provider" value={health?.provider === "meta_cloud" ? "Meta" : "Indisponivel"} />
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
              <Field label="Template Meta"><input value={templateName} onChange={(e) => setTemplateName(e.target.value)} className="form-input" placeholder="consentimento_ofertas_v1" /></Field>
            </div>
            <Field label="Mensagem / snapshot de conteudo"><textarea value={message} onChange={(e) => setMessage(e.target.value)} className="form-input min-h-24" placeholder="Texto de referencia do template" /></Field>
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
            <div className="flex flex-wrap gap-2"><Badge text={`${preview.counts.selected_unique} unicos`} /><Badge text={`${preview.counts.eligible} elegiveis`} good /><Badge text={`${preview.counts.blocked} bloqueados`} bad /><Badge text={preview.provider_ready ? "Meta pronto" : "Meta indisponivel"} good={preview.provider_ready} bad={!preview.provider_ready} /></div>
            {!!Object.keys(preview.blocked_reasons || {}).length && <div className="text-xs text-obs-subtle">{Object.entries(preview.blocked_reasons).map(([key, value]) => <p key={key}>{key}: {String(value)}</p>)}</div>}
            <p className="break-all text-[10px] text-obs-faint">Policy: {preview.policy_checksum}</p>
            <div className="flex justify-end"><button disabled={busy || !preview.counts.selected_unique} onClick={createDraft} className="lg-btn lg-btn-primary">Confirmar draft congelado</button></div>
          </section>}

          <section className="lg-table-shell overflow-hidden">
            <div className="px-4 py-3 [border-bottom:1px_solid_var(--border-glass-soft)]"><h2 className="text-sm font-semibold text-obs-text">Campanhas</h2><p className="text-xs text-obs-faint">Polling a cada 10 segundos. O envio permanece desabilitado nesta entrega.</p></div>
            {campaigns.map((row) => <div key={row.id} className="flex flex-wrap items-center gap-3 px-4 py-3 [border-bottom:1px_solid_var(--border-glass-soft)] last:[border-bottom:0]"><div className="min-w-48 flex-1"><p className="text-sm font-medium text-obs-text">{row.name}</p><p className="text-xs text-obs-faint">rev. {row.current_revision} · {row.campaign_kind} · {row.status}</p></div><Badge text={`${row.counts?.eligible || 0} elegiveis`} good /><Badge text={`${row.counts?.blocked || 0} bloqueados`} bad /><button onClick={() => changeStatus(row, "pause")} className="lg-btn lg-btn-secondary"><Pause size={12} /> Pausar</button><button onClick={() => changeStatus(row, "cancel")} className="lg-btn lg-btn-danger"><Ban size={12} /> Cancelar</button></div>)}
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
