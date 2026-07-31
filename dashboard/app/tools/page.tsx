"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bot,
  CheckCircle2,
  ExternalLink,
  Globe2,
  KeyRound,
  MessageCircle,
  Network,
  RefreshCw,
  ShieldAlert,
  Trash2,
} from "lucide-react";
import { api } from "@/lib/api";
import { useGlobalPersona } from "@/lib/useGlobalPersona";

const KEY_SERVICES = [
  { service: "meta", label: "Meta", description: "Catálogo e APIs da Meta", field: "access_token" },
  { service: "openai", label: "ChatGPT / OpenAI", description: "Chat, modelos e embeddings", field: "api_key" },
  { service: "anthropic", label: "Claude", description: "Modelos Claude da persona", field: "api_key" },
  { service: "deepseek", label: "DeepSeek", description: "Modelo usado nas automações n8n", field: "api_key" },
] as const;

function statusLabel(item: any) {
  if (!item?.configured) return "não configurada";
  if (!item?.enabled) return "desativada";
  if (["connected", "healthy"].includes(String(item?.status))) return "ativa";
  return String(item?.status || "pendente");
}

export default function ToolsPage() {
  const persona = useGlobalPersona();
  const [integrations, setIntegrations] = useState<any[]>([]);
  const [site, setSite] = useState<any>(null);
  const [channel, setChannel] = useState<any>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const byService = useMemo(
    () => Object.fromEntries(integrations.map((item) => [item.service, item])),
    [integrations],
  );

  const load = useCallback(async () => {
    if (!persona.slug) {
      setIntegrations([]);
      setSite(null);
      setChannel(null);
      return;
    }
    setError("");
    try {
      const [rows, siteState, channelState] = await Promise.all([
        api.personaIntegrations(persona.slug),
        api.personaPublicSite(persona.slug),
        api.whatsappChannel(persona.slug),
      ]);
      setIntegrations(rows || []);
      setSite(siteState);
      setChannel(channelState);
    } catch (reason: any) {
      setError(reason?.message || "Não foi possível carregar as integrações.");
    }
  }, [persona.slug]);

  useEffect(() => {
    setDrafts({});
    setMessage("");
    load();
  }, [load]);

  async function save(service: string, field: string) {
    const value = String(drafts[service] || "").trim();
    if (!value) {
      setError("Informe a chave antes de salvar.");
      return;
    }
    setBusy(service);
    setError("");
    setMessage("");
    try {
      await api.updatePersonaIntegration(persona.slug, service, {
        enabled: true,
        [field]: value,
        ...(service === "meta" ? { catalog_id: drafts.meta_catalog_id || "" } : {}),
      });
      setDrafts((current) => ({ ...current, [service]: "" }));
      setMessage(`Credencial ${service} salva no vault da persona.`);
      await load();
    } catch (reason: any) {
      setError(reason?.message || `Não foi possível salvar ${service}.`);
    } finally {
      setBusy("");
    }
  }

  async function revoke(service: string) {
    if (!window.confirm(`Revogar a credencial ${service} desta persona?`)) return;
    setBusy(service);
    setError("");
    setMessage("");
    try {
      await api.deletePersonaIntegrationCredentials(persona.slug, service);
      setMessage(`Credencial ${service} revogada.`);
      await load();
    } catch (reason: any) {
      setError(reason?.message || `Não foi possível revogar ${service}.`);
    } finally {
      setBusy("");
    }
  }

  if (!persona.slug) {
    return (
      <div className="rounded-2xl border border-amber-500/25 bg-amber-500/10 p-5 text-sm text-amber-200">
        Selecione uma persona no filtro do cabeçalho. Chaves, site e catálogo sempre pertencem a uma única persona.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">
            Persona selecionada · {persona.slug}
          </p>
          <h1 className="mt-1 text-xl font-semibold text-obs-text">Ferramentas e integrações</h1>
          <p className="mt-1 text-sm text-obs-subtle">
            Apenas integrações operacionais, com configuração isolada por persona.
          </p>
        </div>
        <button type="button" onClick={load} className="flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs text-obs-subtle">
          <RefreshCw size={14} /> Atualizar
        </button>
      </header>

      {error && <div role="alert" className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</div>}
      {message && <div role="status" className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-200">{message}</div>}

      <section>
        <h2 className="flex items-center gap-2 text-sm font-semibold text-obs-text">
          <KeyRound size={16} /> Chaves de API
        </h2>
        <div className="mt-3 grid gap-4 lg:grid-cols-2">
          {KEY_SERVICES.map((definition) => {
            const state = byService[definition.service];
            return (
              <article key={definition.service} className="rounded-2xl border border-white/10 bg-obs-surface p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-obs-text">{definition.label}</h3>
                    <p className="mt-1 text-xs text-obs-subtle">{definition.description}</p>
                  </div>
                  <span className={`rounded-full px-2 py-1 text-[10px] ${
                    state?.configured && state?.enabled
                      ? "bg-emerald-500/10 text-emerald-300"
                      : "bg-white/5 text-obs-faint"
                  }`}>{statusLabel(state)}</span>
                </div>
                {definition.service === "meta" && (
                  <input
                    value={drafts.meta_catalog_id || ""}
                    onChange={(event) => setDrafts((current) => ({ ...current, meta_catalog_id: event.target.value }))}
                    placeholder="Catalog ID"
                    className="mt-4 w-full rounded-xl border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text"
                  />
                )}
                <input
                  type="password"
                  autoComplete="new-password"
                  value={drafts[definition.service] || ""}
                  onChange={(event) => setDrafts((current) => ({ ...current, [definition.service]: event.target.value }))}
                  placeholder={state?.configured ? "Nova chave para rotacionar" : "Chave de API"}
                  className="mt-2 w-full rounded-xl border border-white/10 bg-obs-raised px-3 py-2 text-sm text-obs-text"
                />
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    disabled={busy === definition.service}
                    onClick={() => save(definition.service, definition.field)}
                    className="rounded-lg bg-obs-violet px-3 py-2 text-xs font-medium text-white disabled:opacity-40"
                  >
                    {state?.configured ? "Rotacionar chave" : "Salvar chave"}
                  </button>
                  {state?.configured && (
                    <button
                      type="button"
                      disabled={busy === definition.service}
                      onClick={() => revoke(definition.service)}
                      className="flex items-center gap-1 rounded-lg border border-rose-500/25 px-3 py-2 text-xs text-rose-300 disabled:opacity-40"
                    >
                      <Trash2 size={13} /> Revogar
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <OperationalCard icon={<MessageCircle size={17} />} title="WhatsApp" status={`${channel?.provider || "sem provider"} · ${channel?.status || "não configurado"}`} />
        <OperationalCard icon={<Network size={17} />} title="n8n" status={statusLabel(byService.n8n)} />
        <OperationalCard icon={<Bot size={17} />} title="Chat" status={statusLabel(byService.openai)} />
        <OperationalCard
          icon={<Globe2 size={17} />}
          title="Site e Catálogo API"
          status={site?.config?.site_slug
            ? `${site.config.site_name || site.config.site_slug} · ${site.config.format_key}`
            : "configuração pendente"}
          href={site?.config?.site_slug ? `/api/menu/${persona.slug}` : undefined}
        />
      </section>

      <div className="flex items-start gap-2 rounded-xl border border-sky-500/20 bg-sky-500/10 p-4 text-xs leading-5 text-sky-100">
        <ShieldAlert size={16} className="mt-0.5 shrink-0" />
        Segredos não são exibidos após o salvamento. Site, Catálogo API, Meta, Claude, ChatGPT e DeepSeek acompanham exclusivamente a persona selecionada no cabeçalho.
      </div>
    </div>
  );
}

function OperationalCard({
  icon,
  title,
  status,
  href,
}: {
  icon: React.ReactNode;
  title: string;
  status: string;
  href?: string;
}) {
  return (
    <article className="rounded-2xl border border-white/10 bg-obs-surface p-4">
      <div className="flex items-center gap-2 text-obs-text">{icon}<h3 className="text-sm font-semibold">{title}</h3></div>
      <p className="mt-3 text-xs text-obs-subtle">{status}</p>
      {href && (
        <a href={href} target="_blank" rel="noreferrer" className="mt-3 inline-flex items-center gap-1 text-xs text-obs-violet">
          Abrir endpoint <ExternalLink size={12} />
        </a>
      )}
      {!href && status.includes("ativa") && <CheckCircle2 size={15} className="mt-3 text-emerald-300" />}
    </article>
  );
}
