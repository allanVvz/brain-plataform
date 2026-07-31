"use client";

import Image from "next/image";
import {
  AlertTriangle,
  CheckCircle2,
  LoaderCircle,
  MessageCircle,
  QrCode,
  RefreshCw,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";

type Provider = "meta_cloud" | "evolution_baileys";

const CONNECTED_STATES = new Set(["connected", "open"]);
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

export function MessagingSettingsPanel() {
  const [personas, setPersonas] = useState<any[]>([]);
  const [personaSlug, setPersonaSlug] = useState("");
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
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function load(slug = personaSlug) {
    if (!slug) return;
    const [nextChannel, nextMeta] = await Promise.all([
      api.whatsappChannel(slug),
      api.whatsappMetaBinding(slug).catch(() => null),
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
  }

  useEffect(() => {
    let active = true;
    setLoading(true);
    api.me()
      .then(async (session) => {
        if (!active) return;
        const list = session?.personas || [];
        setPersonas(list);
        const stored = window.localStorage.getItem("ai-brain-persona-slug") || "";
        const slug = list.some((item: any) => item.slug === stored)
          ? stored
          : list[0]?.slug || "";
        setPersonaSlug(slug);
        if (slug) await load(slug);
      })
      .catch((reason: any) => {
        if (active) setError(reason?.message || "Não foi possível carregar as personas.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (
      channel?.provider !== "evolution_baileys"
      || CONNECTED_STATES.has(String(channel?.status || "").toLowerCase())
    ) return;
    const timer = window.setInterval(() => {
      load().catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [channel?.provider, channel?.status, personaSlug]);

  const status = String(channel?.status || "disabled").toLowerCase();
  const connected = CONNECTED_STATES.has(status);
  const evolutionPending = channel?.provider === "evolution_baileys" && !connected;
  const providerLabel = channel?.provider === "meta_cloud"
    ? "Meta Cloud"
    : channel?.provider === "evolution_baileys"
      ? "Evolution"
      : "nenhum";
  const canConfigureMeta = Boolean(metaState?.meta_configured);
  const progress = useMemo(() => {
    if (connected) return 3;
    if (status === "qr_ready" || status === "connecting") return 2;
    if (status === "provisioning") return 1;
    return 0;
  }, [connected, status]);

  async function changePersona(slug: string) {
    setPersonaSlug(slug);
    setMessage("");
    setError("");
    setQr("");
    window.localStorage.setItem("ai-brain-persona-slug", slug);
    setLoading(true);
    try {
      await load(slug);
    } catch (reason: any) {
      setError(reason?.message || "Falha ao carregar a mensageria.");
    } finally {
      setLoading(false);
    }
  }

  async function activateProvider() {
    if (!personaSlug) return;
    const label = provider === "meta_cloud" ? "Meta Cloud" : "Evolution";
    if (!window.confirm(
      `Confirmar troca de ${providerLabel} para ${label}? Os leads atuais serão vinculados ao novo canal.`,
    )) return;
    setBusy(true);
    setMessage("");
    setError("");
    setQr("");
    try {
      const result = await api.selectWhatsAppProvider(personaSlug, provider, true);
      setMessage(
        `${label} ativado. ${Number(result?.rebound_leads || 0)} lead(s) rebindeado(s).`,
      );
      await load();
    } catch (reason: any) {
      setError(reason?.message || `Falha ao ativar ${label}. O canal anterior foi preservado.`);
    } finally {
      setBusy(false);
    }
  }

  async function saveMeta() {
    if (!canConfigureMeta) {
      setError("Configure primeiro a credencial Meta na aba Ferramentas.");
      return;
    }
    if (!metaDraft.phone_number_id.trim()) {
      setError("Informe o whatsapp_phone_number_id da Meta.");
      return;
    }
    if (!window.confirm("Confirmar configuração e ativação do canal Meta Cloud?")) return;
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const result = await api.updateWhatsAppMetaBinding(personaSlug, {
        phone_number_id: metaDraft.phone_number_id.trim(),
        whatsapp_number: metaDraft.whatsapp_number.trim() || undefined,
        workflow_name: metaDraft.workflow_name.trim() || "Meta Cloud WhatsApp",
        mode: "active",
        conversation_mode: "deterministic",
      });
      setMessage(
        `Meta Cloud configurado. ${Number(result?.rebound_leads || 0)} lead(s) rebindeado(s).`,
      );
      await load();
    } catch (reason: any) {
      setError(reason?.message || "Não foi possível configurar o binding Meta.");
    } finally {
      setBusy(false);
    }
  }

  async function requestQr() {
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const result = await api.connectEvolution(personaSlug);
      setQr(result?.qr?.base64 || "");
      setMessage(
        result?.status === "connected"
          ? "Evolution conectado."
          : "QR Code atualizado. Aguardando leitura pelo aparelho.",
      );
      await load();
    } catch (reason: any) {
      setError(reason?.message || "Não foi possível obter o QR Code da Evolution.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">
            Administração
          </p>
          <h2 className="mt-1 flex items-center gap-2 text-xl font-semibold text-obs-text">
            <MessageCircle size={19} className="text-obs-violet" /> Mensageria
          </h2>
          <p className="mt-1 text-sm text-obs-subtle">
            Um provider WhatsApp ativo por persona, com transporte direto e decisão determinística.
          </p>
        </div>
        <label className="text-xs text-obs-subtle">
          Persona
          <select
            aria-label="Persona da mensageria"
            value={personaSlug}
            onChange={(event) => changePersona(event.target.value)}
            className="mt-1 block min-w-64 rounded-xl border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text"
          >
            {personas.map((persona) => (
              <option key={persona.slug} value={persona.slug}>{persona.name}</option>
            ))}
          </select>
        </label>
      </header>

      {error && (
        <div role="alert" className="flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-200">
          <AlertTriangle className="mt-0.5 shrink-0" size={16} /> {error}
        </div>
      )}
      {message && (
        <div role="status" className="flex items-start gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm text-emerald-200">
          <CheckCircle2 className="mt-0.5 shrink-0" size={16} /> {message}
        </div>
      )}

      <section className="rounded-2xl border border-white/10 bg-obs-surface p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs text-obs-faint">Canal atual</p>
            <p className="mt-1 text-sm font-semibold text-obs-text">
              {providerLabel} · {STATUS_LABELS[status] || status}
            </p>
          </div>
          <button
            type="button"
            onClick={() => load().catch((reason: any) => setError(reason?.message || "Falha ao atualizar."))}
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
              <div
                key={label}
                className={`rounded-xl border p-3 ${
                  done
                    ? "border-emerald-500/25 bg-emerald-500/10"
                    : active
                      ? "border-obs-violet/30 bg-obs-violet/10"
                      : "border-white/10 bg-obs-base/50"
                }`}
              >
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
        <div className="rounded-2xl border border-white/10 bg-obs-surface p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-obs-text">Selecionar provider</h3>
          <p className="mt-1 text-xs leading-5 text-obs-subtle">
            A troca é confirmada antes de rebinder os leads. Mensagens e IDs externos permanecem no binding histórico.
          </p>
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

        <div className="rounded-2xl border border-white/10 bg-obs-surface p-5 shadow-sm">
          {provider === "meta_cloud" ? (
            <div>
              <h3 className="text-sm font-semibold text-obs-text">Configuração Meta Cloud</h3>
              <p className="mt-1 text-xs leading-5 text-obs-subtle">
                A credencial permanece no vault. Esta aba salva apenas a identidade pública do canal.
              </p>
              {!canConfigureMeta && (
                <p className="mt-3 rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                  Credencial Meta ausente. Configure-a em Ferramentas antes de ativar este binding.
                </p>
              )}
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <label className="text-xs text-obs-subtle">
                  whatsapp_phone_number_id
                  <input
                    value={metaDraft.phone_number_id}
                    onChange={(event) => setMetaDraft((draft) => ({
                      ...draft,
                      phone_number_id: event.target.value,
                    }))}
                    className="mt-1 block w-full rounded-xl border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text"
                  />
                </label>
                <label className="text-xs text-obs-subtle">
                  Número público (opcional)
                  <input
                    value={metaDraft.whatsapp_number}
                    onChange={(event) => setMetaDraft((draft) => ({
                      ...draft,
                      whatsapp_number: event.target.value,
                    }))}
                    className="mt-1 block w-full rounded-xl border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text"
                  />
                </label>
              </div>
              <button
                type="button"
                onClick={saveMeta}
                disabled={busy || !canConfigureMeta}
                className="mt-4 rounded-xl border border-obs-violet/30 bg-obs-violet/15 px-4 py-2.5 text-sm font-medium text-obs-violet disabled:opacity-40"
              >
                Configurar e ativar Meta
              </button>
            </div>
          ) : (
            <div>
              <h3 className="text-sm font-semibold text-obs-text">Onboarding Evolution</h3>
              <p className="mt-1 text-xs leading-5 text-obs-subtle">
                O provisionamento cria a instância sem expor credenciais. O QR é temporário e nunca é persistido.
              </p>
              {evolutionPending && (
                <button
                  type="button"
                  onClick={requestQr}
                  disabled={busy}
                  className="mt-4 flex items-center gap-2 rounded-xl border border-obs-violet/30 bg-obs-violet/15 px-4 py-2.5 text-sm font-medium text-obs-violet disabled:opacity-40"
                >
                  <QrCode size={16} /> Gerar ou atualizar QR Code
                </button>
              )}
              {qr && evolutionPending && (
                <div className="mt-4 rounded-xl border border-white/10 bg-white p-4 text-center">
                  <Image
                    unoptimized
                    width={240}
                    height={240}
                    src={qr}
                    alt="QR Code temporário da Evolution"
                    className="mx-auto rounded-lg"
                  />
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
