"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Settings, X, RefreshCw, Send } from "lucide-react";

interface Persona { id: string; slug: string; name: string; tone: string; products: string[]; config: any; active: boolean; created_at: string; }

interface RoutingConfig {
  slug: string;
  id: string;
  process_mode: "internal" | "n8n";
  outbound_webhook_url: string | null;
  has_outbound_webhook_secret: boolean;
  has_inbound_webhook_token: boolean;
  inbound_webhook_token?: string;
  migration_applied?: boolean;
  routing_source?: string;
}

export default function PersonaPage() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selected, setSelected] = useState<Persona | null>(null);
  const [brand, setBrand] = useState<any>(null);
  const [bindings, setBindings] = useState<any[]>([]);
  const [kbCount, setKbCount] = useState<number | null>(null);
  const [routing, setRouting] = useState<RoutingConfig | null>(null);
  const [routingBusy, setRoutingBusy] = useState(false);
  const [showWebhookDrawer, setShowWebhookDrawer] = useState(false);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [inboundToken, setInboundToken] = useState("");
  const [routingMessage, setRoutingMessage] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const processEndpoint = typeof window !== "undefined" ? `${window.location.origin}/api-brain/process` : "/api-brain/process";

  useEffect(() => {
    api.personas().then((list) => {
      setPersonas(list);
      if (list.length > 0) selectPersona(list[0]);
    }).finally(() => setLoading(false));
  }, []);

  async function selectPersona(p: Persona) {
    setSelected(p);
    setBrand(null);
    setBindings([]);
    setKbCount(null);
    setRouting(null);
    setShowWebhookDrawer(false);
    setWebhookUrl("");
    setWebhookSecret("");
    setInboundToken("");
    setRoutingMessage(null);
    setTestResult(null);
    const [brandData, bindingsData, kbData, routingData] = await Promise.all([
      api.brandProfile(p.id).catch(() => null),
      api.workflowBindings(p.id).catch(() => []),
      api.kb(p.id).catch(() => []),
      api.personaRouting(p.slug).catch(() => null),
    ]);
    setBrand(brandData);
    setBindings(bindingsData);
    setKbCount(Array.isArray(kbData) ? kbData.length : 0);
    setRouting(routingData);
  }

  async function setProcessMode(mode: "internal" | "n8n") {
    if (!selected || routingBusy) return;
    if (routing && !routing.migration_applied) {
      setRoutingMessage("A migration 011 ainda não foi aplicada. O modo exibido vem do fluxo n8n legado e está somente leitura.");
      return;
    }
    setRoutingBusy(true);
    try {
      const updated = await api.updatePersonaRouting(selected.slug, {
        process_mode: mode,
        // When switching to n8n the operator needs a token; auto-generate if missing.
        ...(mode === "n8n" && routing && !routing.has_inbound_webhook_token
          ? { rotate_inbound_token: true }
          : {}),
      });
      setRouting(updated);
    } catch (e) {
      console.error(e);
    } finally {
      setRoutingBusy(false);
    }
  }

  useEffect(() => {
    if (!routing) return;
    setWebhookUrl(routing.outbound_webhook_url || "");
    setWebhookSecret("");
    setInboundToken(routing.inbound_webhook_token || "");
    setRoutingMessage(null);
    setTestResult(null);
  }, [routing?.slug]);

  async function saveRoutingConfig(extra: Record<string, any> = {}) {
    if (!selected || routingBusy) return;
    if (routing && !routing.migration_applied) {
      setRoutingMessage("Aplique supabase/migrations/011_persona_routing.sql antes de editar o roteamento.");
      return;
    }
    setRoutingBusy(true);
    setRoutingMessage(null);
    try {
      const updated = await api.updatePersonaRouting(selected.slug, {
        outbound_webhook_url: webhookUrl.trim() || null,
        ...(webhookSecret.trim() ? { outbound_webhook_secret: webhookSecret.trim() } : {}),
        ...(inboundToken.trim() ? { inbound_webhook_token: inboundToken.trim() } : {}),
        ...extra,
      });
      setRouting(updated);
      if (updated?.inbound_webhook_token) {
        setInboundToken(updated.inbound_webhook_token);
      }
      setWebhookSecret("");
      setRoutingMessage("Configuração salva.");
    } catch (e: any) {
      setRoutingMessage(e?.message || "Falha ao salvar configuração.");
    } finally {
      setRoutingBusy(false);
    }
  }

  async function rotateInboundToken() {
    if (!selected || routingBusy) return;
    await saveRoutingConfig({ rotate_inbound_token: true });
  }

  async function testRoutingWebhook() {
    if (!selected || routingBusy) return;
    setRoutingBusy(true);
    setTestResult(null);
    try {
      const result = await api.testPersonaRouting(selected.slug);
      setTestResult(result.ok ? `Webhook respondeu ${result.status}.` : `Falha: ${result.error || result.status || "sem status"}`);
    } catch (e: any) {
      setTestResult(e?.message || "Falha ao testar webhook.");
    } finally {
      setRoutingBusy(false);
    }
  }

  if (loading) return <p className="text-brain-muted text-sm">Carregando...</p>;

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Personas / Clientes</h1>

      {/* Client tabs */}
      <div className="flex gap-2 flex-wrap">
        {personas.map((p) => (
          <button key={p.id} onClick={() => selectPersona(p)}
            className={`text-sm px-4 py-1.5 rounded-md border transition-colors ${
              selected?.id === p.id
                ? "bg-brain-accent/20 border-brain-accent text-brain-accent font-medium"
                : "border-brain-border text-brain-muted hover:text-white"
            }`}>
            {p.name}
          </button>
        ))}
      </div>

      {selected && (
        <div className="grid grid-cols-3 gap-4">
          {/* Main info */}
          <div className="col-span-2 space-y-4">
            <div className="bg-brain-surface border border-brain-border rounded-xl p-5 space-y-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-brain-accent/20 flex items-center justify-center text-brain-accent font-bold text-lg">
                  {selected.name[0]}
                </div>
                <div>
                  <p className="font-semibold text-lg">{selected.name}</p>
                  <p className="text-xs text-brain-muted font-mono">{selected.slug}</p>
                </div>
                <span className={`ml-auto text-xs px-2 py-0.5 rounded-full border ${selected.active ? "border-green-500/40 text-green-400" : "border-red-500/40 text-red-400"}`}>
                  {selected.active ? "ativo" : "inativo"}
                </span>
              </div>

              <div>
                <p className="text-xs text-brain-muted uppercase tracking-wide mb-1">Tom de voz</p>
                <p className="text-sm">{selected.tone || "—"}</p>
              </div>

              <div>
                <p className="text-xs text-brain-muted uppercase tracking-wide mb-1">Produtos</p>
                <div className="flex flex-wrap gap-1.5">
                  {(selected.products || []).map((p) => (
                    <span key={p} className="text-xs bg-brain-bg border border-brain-border rounded px-2 py-0.5">{p}</span>
                  ))}
                </div>
              </div>

              {selected.config && Object.keys(selected.config).length > 0 && (
                <div>
                  <p className="text-xs text-brain-muted uppercase tracking-wide mb-1">Config</p>
                  <pre className="text-xs bg-brain-bg border border-brain-border rounded p-3 overflow-x-auto">
                    {JSON.stringify(selected.config, null, 2)}
                  </pre>
                </div>
              )}
            </div>

            {/* Brand Profile */}
            {brand && Object.keys(brand).length > 0 && (
              <div className="bg-brain-surface border border-brain-border rounded-xl p-5 space-y-3">
                <p className="text-sm font-semibold">Brand Profile</p>
                {brand.tagline && (
                  <div>
                    <p className="text-xs text-brain-muted mb-0.5">Tagline</p>
                    <p className="text-sm italic">"{brand.tagline}"</p>
                  </div>
                )}
                {brand.positioning && (
                  <div>
                    <p className="text-xs text-brain-muted mb-0.5">Posicionamento</p>
                    <p className="text-sm">{brand.positioning}</p>
                  </div>
                )}
                {brand.tone_pillars?.length > 0 && (
                  <div>
                    <p className="text-xs text-brain-muted mb-1">Pilares de tom</p>
                    <div className="flex gap-2 flex-wrap">
                      {brand.tone_pillars.map((t: string) => (
                        <span key={t} className="text-xs bg-brain-accent/10 border border-brain-accent/30 text-brain-accent rounded px-2 py-0.5">{t}</span>
                      ))}
                    </div>
                  </div>
                )}
                {brand.differentials?.length > 0 && (
                  <div>
                    <p className="text-xs text-brain-muted mb-1">Diferenciais</p>
                    <ul className="text-sm space-y-0.5">
                      {brand.differentials.map((d: string, i: number) => (
                        <li key={i} className="flex gap-2"><span className="text-brain-accent">·</span>{d}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {brand.palette?.length > 0 && (
                  <div>
                    <p className="text-xs text-brain-muted mb-1">Paleta</p>
                    <div className="flex gap-2">
                      {brand.palette.map((c: string) => (
                        <div key={c} className="flex items-center gap-1.5">
                          <div className="w-5 h-5 rounded border border-brain-border" style={{ backgroundColor: c }} />
                          <span className="text-xs font-mono text-brain-muted">{c}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
            {!brand && (
              <div className="bg-brain-surface border border-dashed border-brain-border rounded-xl p-4 text-center text-sm text-brain-muted">
                Sem brand profile. Sincronize o vault ou adicione via{" "}
                <a href="/knowledge/upload" className="text-brain-accent hover:underline">Upload</a>.
              </div>
            )}

            {/* Roteamento de mensagens */}
            <div className="bg-brain-surface border border-brain-border rounded-xl p-5 space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold">Roteamento de mensagens</p>
                <button
                  onClick={() => setShowWebhookDrawer(true)}
                  title="Configurar webhooks"
                  className="p-1.5 rounded-md border border-brain-border text-brain-muted hover:text-white hover:border-brain-accent transition-colors"
                >
                  <Settings size={14} />
                </button>
              </div>
              <p className="text-xs text-brain-muted">
                Define quem responde mensagens dessa persona. Em ambos os modos as respostas do
                operador saem pelo <code className="text-brain-accent">outbound webhook</code>.
              </p>
              <div className="space-y-2">
                <label className="flex items-start gap-2.5 cursor-pointer p-2 rounded-md hover:bg-white/3 border border-transparent hover:border-brain-border transition">
                  <input
                    type="radio"
                    name="process_mode"
                    value="internal"
                    checked={routing?.process_mode === "internal"}
                    onChange={() => setProcessMode("internal")}
                    disabled={routingBusy || !routing}
                    className="mt-0.5 accent-brain-accent"
                  />
                  <div>
                    <p className="text-sm">Processar internamente <span className="text-xs text-brain-muted">(AI Brain)</span></p>
                    <p className="text-xs text-brain-muted">
                      Classifica, decide rota, gera resposta e envia via outbound webhook.
                    </p>
                  </div>
                </label>
                <label className="flex items-start gap-2.5 cursor-pointer p-2 rounded-md hover:bg-white/3 border border-transparent hover:border-brain-border transition">
                  <input
                    type="radio"
                    name="process_mode"
                    value="n8n"
                    checked={routing?.process_mode === "n8n"}
                    onChange={() => setProcessMode("n8n")}
                    disabled={routingBusy || !routing}
                    className="mt-0.5 accent-brain-accent"
                  />
                  <div>
                    <p className="text-sm">Processar via n8n</p>
                    <p className="text-xs text-brain-muted">
                      AI Brain só persiste a inbound. n8n é responsável pela resposta. Operador continua usando outbound webhook.
                    </p>
                  </div>
                </label>
              </div>
              {routing && !routing.outbound_webhook_url && (
                <p className="text-xs text-amber-300/80 border border-amber-400/30 bg-amber-500/10 rounded px-2 py-1.5">
                  Outbound webhook não configurado — abra a engrenagem para definir.
                </p>
              )}
              {routing?.process_mode === "n8n" && !routing.has_inbound_webhook_token && (
                <p className="text-xs text-amber-300/80 border border-amber-400/30 bg-amber-500/10 rounded px-2 py-1.5">
                  Sem inbound token — n8n pode chamar /process sem autenticação. Rotacione o token na engrenagem.
                </p>
              )}
            </div>
          </div>

          {/* Right column: stats + bindings */}
          <div className="space-y-4">
            {/* Quick stats */}
            <div className="bg-brain-surface border border-brain-border rounded-xl p-4 space-y-3">
              <p className="text-xs text-brain-muted uppercase tracking-wide">Resumo</p>
              <Stat label="Entradas na KB" value={kbCount ?? "—"} />
              <Stat label="Fluxos n8n" value={bindings.length} />
            </div>

            {/* n8n bindings */}
            <div className="bg-brain-surface border border-brain-border rounded-xl p-4 space-y-2">
              <p className="text-xs text-brain-muted uppercase tracking-wide mb-2">Fluxos n8n</p>
              {bindings.length === 0 && (
                <p className="text-xs text-brain-muted">Nenhum fluxo vinculado.</p>
              )}
              {bindings.map((b) => (
                <div key={b.id} className="flex items-center gap-2 text-xs">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${b.active ? "bg-green-400" : "bg-brain-muted"}`} />
                  <span className="text-white truncate">{b.workflow_name}</span>
                  {b.whatsapp_number && <span className="text-brain-muted shrink-0">{b.whatsapp_number}</span>}
                </div>
              ))}
            </div>

            {/* Quick links */}
            <div className="bg-brain-surface border border-brain-border rounded-xl p-4 space-y-1">
              <p className="text-xs text-brain-muted uppercase tracking-wide mb-2">Ações rápidas</p>
              <a href={`/kb?persona_id=${selected.id}`} className="block text-xs text-brain-accent hover:underline py-0.5">→ Ver KB</a>
              <a href="/knowledge/sync" className="block text-xs text-brain-accent hover:underline py-0.5">→ Sincronizar Vault</a>
              <a href={`/knowledge/validate?persona=${selected.id}`} className="block text-xs text-brain-accent hover:underline py-0.5">→ Validar itens pendentes</a>
              <a href="/knowledge/upload" className="block text-xs text-brain-accent hover:underline py-0.5">→ Upload de conhecimento</a>
            </div>
          </div>
        </div>
      )}

      {selected && showWebhookDrawer && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/40">
          <button
            aria-label="Fechar configurações"
            className="flex-1 cursor-default"
            onClick={() => setShowWebhookDrawer(false)}
          />
          <aside className="w-full max-w-md h-full bg-brain-surface border-l border-brain-border shadow-2xl p-5 overflow-y-auto space-y-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold">Webhooks de {selected.name}</p>
                <p className="text-xs text-brain-muted font-mono">{selected.slug}</p>
              </div>
              <button
                onClick={() => setShowWebhookDrawer(false)}
                className="p-1.5 rounded-md border border-brain-border text-brain-muted hover:text-white"
                title="Fechar"
              >
                <X size={14} />
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-xs text-brain-muted block mb-1">Webhook de saída</label>
                <input
                  value={webhookUrl}
                  onChange={(e) => setWebhookUrl(e.target.value)}
                  placeholder="https://n8n.../webhook/cliente-out"
                  className="w-full bg-brain-bg border border-brain-border rounded-md px-3 py-2 text-sm text-white placeholder-brain-muted focus:outline-none focus:border-brain-accent"
                />
                <p className="text-[11px] text-brain-muted mt-1">
                  Usado para mensagens enviadas pelo operador em modo internal ou n8n.
                </p>
              </div>

              <div>
                <label className="text-xs text-brain-muted block mb-1">Secret de saída</label>
                <input
                  value={webhookSecret}
                  onChange={(e) => setWebhookSecret(e.target.value)}
                  placeholder={routing?.has_outbound_webhook_secret ? "Secret já configurado; preencha para substituir" : "Opcional"}
                  type="password"
                  className="w-full bg-brain-bg border border-brain-border rounded-md px-3 py-2 text-sm text-white placeholder-brain-muted focus:outline-none focus:border-brain-accent"
                />
              </div>

              <div className="border border-brain-border rounded-lg p-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="text-xs text-brain-muted">Token de entrada n8n</p>
                    <p className="text-[11px] text-brain-muted">
                      Envie em <code className="text-brain-accent">X-Webhook-Token</code> quando o n8n chamar o AI Brain.
                    </p>
                  </div>
                  <button
                    onClick={rotateInboundToken}
                    disabled={routingBusy}
                    className="inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded-md border border-brain-border text-brain-muted hover:text-white disabled:opacity-50"
                  >
                    <RefreshCw size={12} />
                    Rotacionar
                  </button>
                </div>
                <input
                  value={inboundToken}
                  onChange={(e) => setInboundToken(e.target.value)}
                  placeholder={routing?.has_inbound_webhook_token ? "Token já configurado; rotacione para visualizar novo" : "Sem token configurado"}
                  className="w-full bg-brain-bg border border-brain-border rounded-md px-3 py-2 text-xs font-mono text-white placeholder-brain-muted focus:outline-none focus:border-brain-accent"
                />
              </div>

              <div className="border border-brain-border rounded-lg p-3 space-y-2">
                <p className="text-xs text-brain-muted">Endpoint para o n8n chamar</p>
                <code className="block text-xs bg-brain-bg border border-brain-border rounded px-2 py-2 break-all text-brain-accent">
                  POST {processEndpoint}
                </code>
                <p className="text-[11px] text-brain-muted">
                  Body esperado: lead_id, persona_slug, mensagem, nome, stage e demais campos do lead.
                </p>
              </div>

              {routingMessage && (
                <p className="text-xs text-brain-muted border border-brain-border rounded px-2 py-1.5">{routingMessage}</p>
              )}
              {testResult && (
                <p className="text-xs text-brain-muted border border-brain-border rounded px-2 py-1.5">{testResult}</p>
              )}
            </div>

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                onClick={testRoutingWebhook}
                disabled={routingBusy || !routing?.outbound_webhook_url}
                className="inline-flex items-center gap-1.5 text-xs px-3 py-2 rounded-md border border-brain-border text-brain-muted hover:text-white disabled:opacity-50"
              >
                <Send size={12} />
                Testar
              </button>
              <button
                onClick={() => saveRoutingConfig()}
                disabled={routingBusy}
                className="text-xs px-3 py-2 rounded-md bg-brain-accent text-black font-medium disabled:opacity-50"
              >
                Salvar
              </button>
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-brain-muted">{label}</span>
      <span className="text-sm font-semibold text-white">{value}</span>
    </div>
  );
}
