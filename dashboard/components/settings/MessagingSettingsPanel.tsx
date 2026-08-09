"use client";

import Image from "next/image";
import dynamic from "next/dynamic";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  FlaskConical,
  LoaderCircle,
  MessageCircle,
  MessageSquareText,
  QrCode,
  RefreshCw,
  RotateCcw,
  Route,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useGlobalPersona } from "@/lib/useGlobalPersona";

type Provider = "meta_cloud" | "evolution_baileys";
type MessagingSubTab = "canal" | "agentes" | "validacoes";
type ConversationMode = "deterministic" | "n8n_agents" | "orquestrador";
type AutomationMode = "ai_with_handoff" | "human_only";

type RoutingConfig = {
  conversation_mode: ConversationMode;
  automation_mode?: AutomationMode;
  migration_applied?: boolean;
  model_required?: boolean;
  field_extractor?: string | null;
};

const CONNECTED = new Set(["connected", "open"]);
const STATUS_LABELS: Record<string, string> = {
  disabled: "não configurado",
  provisioning: "provisionando",
  connecting: "aguardando QR",
  qr_ready: "QR disponível",
  connected: "conectado",
  open: "conectado",
  disconnected: "desconectado",
  failed: "falha no provisionamento",
  safety_paused: "pausado por segurança",
};

const MessagesLayout = dynamic(
  () => import("@/app/messages/MessagesLayout").then((mod) => mod.MessagesLayout),
  {
    loading: () => (
      <p className="rounded-xl border border-white/10 bg-obs-surface p-4 text-sm text-obs-subtle">
        Carregando conversas de validação…
      </p>
    ),
  },
);
const ValidatorWorkspace = dynamic(
  () => import("@/app/wa-validator/page"),
  {
    loading: () => (
      <p className="rounded-xl border border-white/10 bg-obs-surface p-4 text-sm text-obs-subtle">
        Carregando testes do ChatBot…
      </p>
    ),
  },
);

const SUB_TABS: Array<{ key: MessagingSubTab; label: string; icon: typeof MessageCircle }> = [
  { key: "canal", label: "Canal", icon: MessageCircle },
  { key: "agentes", label: "Agentes", icon: Bot },
  { key: "validacoes", label: "Validações", icon: MessageSquareText },
];

function subTabFromLocation(): MessagingSubTab {
  if (typeof window === "undefined") return "canal";
  const candidate = new URLSearchParams(window.location.search).get("sub") || "";
  return SUB_TABS.some((tab) => tab.key === candidate) ? (candidate as MessagingSubTab) : "canal";
}

export function MessagingSettingsPanel() {
  const persona = useGlobalPersona();
  const personaSlug = persona.slug;
  const [subTab, setSubTab] = useState<MessagingSubTab>("canal");
  // Bumped after a WA Validator run finishes so the leads/conversations list
  // below it (a sibling component with no other link to it) refetches --
  // confirmed live 2026-08-09: without this, a just-created validation lead
  // was invisible until a manual refresh click.
  const [validationRunNonce, setValidationRunNonce] = useState(0);

  useEffect(() => {
    setSubTab(subTabFromLocation());
  }, []);

  function selectSubTab(next: MessagingSubTab) {
    setSubTab(next);
    const url = new URL(window.location.href);
    if (next === "canal") url.searchParams.delete("sub");
    else url.searchParams.set("sub", next);
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
  }

  if (!personaSlug) {
    return (
      <div className="rounded-2xl border border-amber-500/25 bg-amber-500/10 p-5 text-sm text-amber-200">
        Selecione uma persona no filtro do cabeçalho para configurar a mensageria.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">
            Persona selecionada no cabeçalho · {personaSlug}
          </p>
          <h2 className="mt-1 flex items-center gap-2 text-xl font-semibold text-obs-text">
            <MessageCircle size={19} className="text-obs-violet" /> Mensageria
          </h2>
          <p className="mt-1 text-sm text-obs-subtle">
            Canal, agente de IA e conversas de validação, tudo em um único lugar.
          </p>
        </div>
        <nav aria-label="Sub-seções de mensageria" className="grid grid-cols-3 rounded-xl border border-white/10 bg-obs-base p-1">
          {SUB_TABS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => selectSubTab(key)}
              aria-selected={subTab === key}
              className={`inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition ${
                subTab === key ? "bg-obs-violet/15 text-obs-violet" : "text-obs-subtle hover:text-obs-text"
              }`}
            >
              <Icon size={13} /> {label}
            </button>
          ))}
        </nav>
      </header>

      {subTab === "canal" && <CanalSubPanel personaSlug={personaSlug} />}
      {subTab === "agentes" && <AgentesSubPanel personaSlug={personaSlug} />}
      {subTab === "validacoes" && (
        <div className="space-y-5">
          <div className="overflow-hidden rounded-2xl border border-white/10 bg-obs-surface p-4">
            <ValidatorWorkspace onRunComplete={() => setValidationRunNonce((n) => n + 1)} />
          </div>
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.22em] text-obs-faint">
              Conversas de validação registradas
            </h3>
            <div className="overflow-hidden rounded-2xl border border-white/10 bg-obs-surface">
              <MessagesLayout validationMode refreshSignal={validationRunNonce} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function CanalSubPanel({ personaSlug }: { personaSlug: string }) {
  const [channel, setChannel] = useState<any>(null);
  const [metaState, setMetaState] = useState<any>(null);
  const [provider, setProvider] = useState<Provider>("evolution_baileys");
  const [metaDraft, setMetaDraft] = useState({
    phone_number_id: "",
    whatsapp_number: "",
    workflow_name: "Meta Cloud WhatsApp",
  });
  const [qr, setQr] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!personaSlug) {
      setChannel(null);
      setMetaState(null);
      return;
    }
    setLoading(true);
    try {
      const [nextChannel, nextMeta] = await Promise.all([
        api.whatsappChannel(personaSlug),
        api.whatsappMetaBinding(personaSlug).catch(() => null),
      ]);
      setChannel(nextChannel);
      setMetaState(nextMeta);
      setProvider((nextChannel?.provider as Provider) || "evolution_baileys");
      const binding = nextMeta?.binding;
      if (binding) {
        setMetaDraft((draft) => ({
          phone_number_id: binding.whatsapp_phone_number_id || draft.phone_number_id,
          whatsapp_number: binding.whatsapp_number || draft.whatsapp_number,
          workflow_name: binding.workflow_name || draft.workflow_name,
        }));
      }
    } catch (reason: any) {
      setError(reason?.message || "Não foi possível carregar a mensageria.");
    } finally {
      setLoading(false);
    }
  }, [personaSlug]);

  useEffect(() => {
    setQr("");
    setMessage("");
    setError("");
    load();
  }, [load]);

  useEffect(() => {
    if (
      channel?.provider !== "evolution_baileys"
      || CONNECTED.has(String(channel?.status || "").toLowerCase())
    ) return;
    const timer = window.setInterval(() => load(), 5000);
    return () => window.clearInterval(timer);
  }, [channel?.provider, channel?.status, load]);

  const status = String(channel?.status || "disabled").toLowerCase();
  const connected = CONNECTED.has(status);
  const evolutionPending = channel?.provider === "evolution_baileys" && !connected;
  const providerLabel = channel?.provider === "meta_cloud"
    ? "Meta Cloud"
    : channel?.provider === "evolution_baileys" ? "Evolution" : "nenhum";
  const progress = useMemo(() => {
    if (connected) return 3;
    if (status === "qr_ready" || status === "connecting") return 2;
    if (status === "provisioning") return 1;
    return 0;
  }, [connected, status]);

  async function perform(action: () => Promise<any>, success: (result: any) => string) {
    if (!personaSlug) return;
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const result = await action();
      setQr(result?.qr?.base64 || "");
      setMessage(success(result));
      await load();
    } catch (reason: any) {
      setError(reason?.message || "A operação não pôde ser concluída.");
    } finally {
      setBusy(false);
    }
  }

  async function activateProvider() {
    const label = provider === "meta_cloud" ? "Meta Cloud" : "Evolution";
    if (!window.confirm(
      `Confirmar troca de ${providerLabel} para ${label}? Os leads atuais serão vinculados ao novo canal.`,
    )) return;
    await perform(
      () => api.selectWhatsAppProvider(personaSlug, provider, true),
      (result) => `${label} ativado. ${Number(result?.rebound_leads || 0)} lead(s) rebindeado(s).`,
    );
  }

  async function saveMeta() {
    if (!metaState?.meta_configured) {
      setError("Configure primeiro a credencial Meta em Ferramentas.");
      return;
    }
    if (!metaDraft.phone_number_id.trim()) {
      setError("Informe o whatsapp_phone_number_id da Meta.");
      return;
    }
    if (!window.confirm("Confirmar configuração e ativação do canal Meta Cloud?")) return;
    await perform(
      () => api.updateWhatsAppMetaBinding(personaSlug, {
        phone_number_id: metaDraft.phone_number_id.trim(),
        whatsapp_number: metaDraft.whatsapp_number.trim() || undefined,
        workflow_name: metaDraft.workflow_name.trim() || "Meta Cloud WhatsApp",
        mode: "active",
        conversation_mode: "deterministic",
      }),
      (result) => `Meta Cloud configurado. ${Number(result?.rebound_leads || 0)} lead(s) rebindeado(s).`,
    );
  }

  async function requestQr() {
    await perform(
      () => api.connectEvolution(personaSlug),
      (result) => result?.status === "connected"
        ? "Evolution conectado."
        : "QR Code atualizado. Aguardando leitura pelo aparelho.",
    );
  }

  async function revokeSession() {
    if (!window.confirm(
      "Revogar a sessão Evolution atual? O WhatsApp será desconectado e um novo QR Code será emitido.",
    )) return;
    await perform(
      () => api.revokeAndReconnectEvolution(personaSlug),
      () => "Sessão revogada. Leia o novo QR Code para reconectar.",
    );
  }

  return (
    <div className="space-y-5">
      {error && (
        <div role="alert" className="flex gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200">
          <AlertTriangle size={16} /> {error}
        </div>
      )}
      {message && (
        <div role="status" className="flex gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm text-emerald-200">
          <CheckCircle2 size={16} /> {message}
        </div>
      )}

      <section className="rounded-2xl border border-white/10 bg-obs-surface p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs text-obs-faint">Canal atual</p>
            <p className="mt-1 text-sm font-semibold text-obs-text">
              {providerLabel} · {STATUS_LABELS[status] || status}
            </p>
          </div>
          <button
            type="button"
            onClick={load}
            disabled={loading || busy}
            className="flex items-center gap-2 rounded-lg border border-white/10 bg-obs-raised px-3 py-2 text-xs text-obs-subtle disabled:opacity-50"
          >
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Atualizar
          </button>
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          {["Provisionamento", "QR Code", "Conectado"].map((label, index) => {
            const done = progress > index;
            const active = progress === index && !connected;
            return (
              <div key={label} className={`rounded-xl border p-3 ${
                done ? "border-emerald-500/25 bg-emerald-500/10"
                  : active ? "border-obs-violet/30 bg-obs-violet/10"
                    : "border-white/10 bg-obs-base/50"
              }`}>
                <p className="flex items-center gap-2 text-xs font-medium text-obs-text">
                  {active
                    ? <LoaderCircle size={13} className="animate-spin text-obs-violet" />
                    : <CheckCircle2 size={13} className={done ? "text-emerald-300" : "text-obs-faint"} />}
                  {label}
                </p>
              </div>
            );
          })}
        </div>
      </section>

      <section className="grid gap-5 xl:grid-cols-[0.8fr_1.2fr]">
        <div className="rounded-2xl border border-white/10 bg-obs-surface p-5">
          <h3 className="text-sm font-semibold text-obs-text">Provider da persona</h3>
          <select
            aria-label="Provider WhatsApp administrativo"
            value={provider}
            onChange={(event) => setProvider(event.target.value as Provider)}
            disabled={busy || loading}
            className="mt-4 block w-full rounded-xl border border-white/10 bg-obs-raised px-3 py-2.5 text-sm text-obs-text"
          >
            <option value="meta_cloud">Meta Cloud</option>
            <option value="evolution_baileys">Evolution</option>
          </select>
          <button
            type="button"
            onClick={activateProvider}
            disabled={busy || loading || provider === channel?.provider}
            className="mt-3 w-full rounded-xl bg-obs-violet px-4 py-2.5 text-sm font-medium text-white disabled:opacity-40"
          >
            {busy ? "Aplicando..." : "Confirmar troca"}
          </button>
        </div>

        <div className="rounded-2xl border border-white/10 bg-obs-surface p-5">
          {provider === "meta_cloud" ? (
            <div>
              <h3 className="text-sm font-semibold text-obs-text">Configuração Meta Cloud</h3>
              {!metaState?.meta_configured && (
                <p className="mt-3 rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                  Credencial Meta ausente nesta persona. Configure-a em Ferramentas.
                </p>
              )}
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <label className="text-xs text-obs-subtle">
                  whatsapp_phone_number_id
                  <input
                    value={metaDraft.phone_number_id}
                    onChange={(event) => setMetaDraft((draft) => ({ ...draft, phone_number_id: event.target.value }))}
                    className="mt-1 block w-full rounded-xl border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text"
                  />
                </label>
                <label className="text-xs text-obs-subtle">
                  Número público (opcional)
                  <input
                    value={metaDraft.whatsapp_number}
                    onChange={(event) => setMetaDraft((draft) => ({ ...draft, whatsapp_number: event.target.value }))}
                    className="mt-1 block w-full rounded-xl border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text"
                  />
                </label>
              </div>
              <button
                type="button"
                onClick={saveMeta}
                disabled={busy || !metaState?.meta_configured}
                className="mt-4 rounded-xl border border-obs-violet/30 bg-obs-violet/15 px-4 py-2.5 text-sm font-medium text-obs-violet disabled:opacity-40"
              >
                Configurar e ativar Meta
              </button>
            </div>
          ) : (
            <div>
              <h3 className="text-sm font-semibold text-obs-text">Sessão Evolution</h3>
              <p className="mt-1 text-xs leading-5 text-obs-subtle">
                O QR é temporário e nunca é persistido. Revogar remove a sessão do aparelho e abre um novo onboarding.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                {evolutionPending && (
                  <button type="button" onClick={requestQr} disabled={busy} className="flex items-center gap-2 rounded-xl bg-obs-violet px-4 py-2.5 text-sm text-white disabled:opacity-40">
                    <QrCode size={16} /> Gerar ou atualizar QR
                  </button>
                )}
                {connected && channel?.provider === "evolution_baileys" && (
                  <button type="button" onClick={revokeSession} disabled={busy} className="flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-2.5 text-sm text-rose-200 disabled:opacity-40">
                    <RotateCcw size={16} /> Revogar sessão e gerar novo QR
                  </button>
                )}
              </div>
              {qr && (
                <div className="mt-4 rounded-xl border border-white/10 bg-white p-4 text-center">
                  <Image unoptimized width={240} height={240} src={qr} alt="QR Code temporário da Evolution" className="mx-auto rounded-lg" />
                </div>
              )}
              {connected && channel?.provider === "evolution_baileys" && (
                <p className="mt-4 flex items-center gap-2 text-sm text-emerald-300">
                  <CheckCircle2 size={16} /> Instância conectada.
                </p>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function AgentesSubPanel({ personaSlug }: { personaSlug: string }) {
  const [routing, setRouting] = useState<RoutingConfig | null>(null);
  const [routingBusy, setRoutingBusy] = useState(false);
  const [routingMessage, setRoutingMessage] = useState("");
  const [routingError, setRoutingError] = useState("");
  const [integrations, setIntegrations] = useState<any[]>([]);

  useEffect(() => {
    let active = true;
    setRouting(null);
    setRoutingMessage("");
    setRoutingError("");
    if (!personaSlug) return () => { active = false; };

    Promise.all([
      api.personaRouting(personaSlug),
      api.personaIntegrations(personaSlug).catch(() => []),
    ])
      .then(([nextRouting, nextIntegrations]) => {
        if (!active) return;
        setRouting(nextRouting);
        setIntegrations((nextIntegrations || []).filter((item: any) => ["deepseek", "openai", "anthropic"].includes(item.service)));
      })
      .catch((error) => {
        if (active) setRoutingError(error?.message || "Não foi possível carregar o agente.");
      });

    return () => { active = false; };
  }, [personaSlug]);

  async function updateConversationMode(mode: ConversationMode) {
    if (!personaSlug || routingBusy || routing?.conversation_mode === mode) return;
    setRoutingBusy(true);
    setRoutingMessage("");
    setRoutingError("");
    try {
      const updated = await api.updatePersonaRouting(personaSlug, { conversation_mode: mode });
      setRouting(updated);
      setRoutingMessage(
        mode === "deterministic"
          ? "Fluxo determinístico ativado."
          : mode === "n8n_agents"
          ? "Orquestração n8n com IA ativada e workflow ressincronizado."
          : "Orquestrador interno selecionado.",
      );
    } catch (error: any) {
      setRoutingError(error?.message || "Falha ao atualizar o motor de atendimento.");
    } finally {
      setRoutingBusy(false);
    }
  }

  async function toggleAutomation() {
    if (!personaSlug || routingBusy || !routing) return;
    const next: AutomationMode = routing.automation_mode === "human_only" ? "ai_with_handoff" : "human_only";
    setRoutingBusy(true);
    setRoutingMessage("");
    setRoutingError("");
    try {
      const updated = await api.updatePersonaRouting(personaSlug, { automation_mode: next });
      setRouting(updated);
      setRoutingMessage(next === "human_only" ? "IA desligada para esta persona." : "IA ligada para esta persona.");
    } catch (error: any) {
      setRoutingError(error?.message || "Falha ao atualizar o estado da IA.");
    } finally {
      setRoutingBusy(false);
    }
  }

  const aiOff = routing?.automation_mode === "human_only";
  const needsAgent = routing?.conversation_mode === "n8n_agents" || routing?.conversation_mode === "orquestrador";

  return (
    <div className="space-y-4">
      <section className="rounded-2xl border border-white/10 bg-obs-surface p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-obs-violet/25 bg-obs-violet/10 text-obs-violet">
              <Bot size={16} />
            </span>
            <div>
              <h3 className="text-sm font-semibold text-obs-text">Estado da IA</h3>
              <p className="mt-1 text-xs leading-5 text-obs-subtle">
                Liga/desliga a automação para toda a persona — quando desligada, toda
                mensagem que chega fica aguardando um humano, mesmo com o motor configurado.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={toggleAutomation}
            disabled={routingBusy || !routing}
            title={aiOff ? "IA desligada — clique para ligar" : "IA ligada — clique para desligar"}
            className={`inline-flex shrink-0 items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition disabled:opacity-50 ${
              aiOff
                ? "border-amber-400/40 bg-amber-500/10 text-amber-200 hover:bg-amber-500/20"
                : "border-emerald-400/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
            }`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${aiOff ? "bg-amber-400" : "bg-emerald-400"}`} />
            {aiOff ? "IA desligada" : "IA ligada"}
          </button>
        </div>
      </section>

      <section className="rounded-2xl border border-white/10 bg-obs-surface p-4">
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-obs-violet/25 bg-obs-violet/10 text-obs-violet">
            <Route size={16} />
          </span>
          <div>
            <h3 className="text-sm font-semibold text-obs-text">Motor de atendimento</h3>
            <p className="mt-1 text-xs leading-5 text-obs-subtle">
              Configuração única da persona. O envio permanece direto pelo provider de WhatsApp.
            </p>
          </div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-3">
          {([
            {
              value: "deterministic",
              title: "Determinístico",
              description: "Usa o grafo e as regras publicadas, sem consumir um agente de IA.",
            },
            {
              value: "n8n_agents",
              title: "n8n",
              description: "O n8n compõe a resposta com um agente de IA, com decisões comerciais determinísticas.",
            },
            {
              value: "orquestrador",
              title: "Orquestrador",
              description: "Motor interno futuro, dentro do próprio backend. Hoje o executor real é o n8n.",
              badge: "em breve",
            },
          ] as const).map((option) => {
            const selected = routing?.conversation_mode === option.value;
            const disabled = routingBusy || !routing?.migration_applied || option.value === "orquestrador";
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => updateConversationMode(option.value)}
                disabled={disabled}
                className={`rounded-xl border p-4 text-left transition disabled:cursor-not-allowed disabled:opacity-50 ${
                  selected
                    ? "border-obs-violet/40 bg-obs-violet/10"
                    : "border-white/10 bg-obs-base/60 hover:border-white/20"
                }`}
              >
                <span className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium text-obs-text">{option.title}</span>
                  {selected && <CheckCircle2 size={15} className="text-obs-violet" />}
                  {"badge" in option && (
                    <span className="rounded-full border border-white/10 bg-obs-base px-2 py-0.5 text-[10px] uppercase tracking-wide text-obs-faint">
                      {option.badge}
                    </span>
                  )}
                </span>
                <span className="mt-2 block text-xs leading-5 text-obs-subtle">
                  {option.description}
                </span>
              </button>
            );
          })}
        </div>

        {routingMessage && <p className="mt-3 text-xs text-green-300">{routingMessage}</p>}
        {routingError && (
          <p className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
            {routingError}
          </p>
        )}
      </section>

      <section className={`rounded-2xl border border-white/10 bg-obs-surface p-4 ${!needsAgent ? "opacity-60" : ""}`}>
        <h3 className="text-sm font-semibold text-obs-text">Agente de IA</h3>
        <p className="mt-1 text-xs leading-5 text-obs-subtle">
          {needsAgent
            ? "Provedor de modelo que compõe as respostas quando o motor não é determinístico."
            : "Só é usado pelos motores n8n/Orquestrador — o motor atual (Determinístico) não precisa de um agente de IA."}
        </p>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          {integrations.length === 0 && (
            <p className="text-xs text-obs-faint">Nenhum provedor de IA configurado em Ferramentas ainda.</p>
          )}
          {integrations.map((item) => {
            const ready = item.service === "deepseek" && item.enabled && item.configured;
            return (
              <div
                key={item.service}
                className={`rounded-xl border p-3 text-xs ${
                  ready ? "border-obs-violet/40 bg-obs-violet/10" : "border-white/10 bg-obs-base/60"
                }`}
              >
                <p className="font-medium text-obs-text">{item.label || item.service}</p>
                <p className="mt-1 text-obs-faint">
                  {ready ? "Ativo — usado pelo n8n" : item.configured ? "Requer provisionamento n8n" : "Não configurado"}
                </p>
              </div>
            );
          })}
        </div>
        {routing?.field_extractor && (
          <p className="mt-3 text-xs text-obs-subtle">Modelo ativo: {routing.field_extractor}.</p>
        )}
      </section>
    </div>
  );
}
