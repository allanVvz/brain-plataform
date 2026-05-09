"use client";

import { startTransition, useEffect, useMemo, useState } from "react";
import { AlertCircle, Cable, DatabaseZap, KeyRound, RefreshCcw, ShieldCheck, Trash2 } from "lucide-react";
import { api } from "@/lib/api";

type IntegrationItem = {
  service: string;
  label: string;
  description: string;
  scope: "user" | "system";
  enabled: boolean;
  status: string;
  requires_credentials: boolean;
  configured: boolean;
  last_validated_at?: string | null;
  last_error?: string | null;
  response_ms?: number | null;
};

type ModalState = {
  service: string;
  label: string;
  configured: boolean;
};

const STATUS_META: Record<string, { tone: string; dot: string; label: string }> = {
  connected: { tone: "text-emerald-300", dot: "bg-emerald-400", label: "connected" },
  healthy: { tone: "text-emerald-300", dot: "bg-emerald-400", label: "healthy" },
  degraded: { tone: "text-amber-300", dot: "bg-amber-400", label: "degraded" },
  invalid_credentials: { tone: "text-rose-300", dot: "bg-rose-400", label: "invalid_credentials" },
  down: { tone: "text-rose-300", dot: "bg-rose-400", label: "down" },
  disabled: { tone: "text-zinc-400", dot: "bg-zinc-500", label: "disabled" },
  never_validated: { tone: "text-sky-300", dot: "bg-sky-400", label: "never_validated" },
  unknown: { tone: "text-zinc-400", dot: "bg-zinc-500", label: "unknown" },
};

function statusMeta(status: string) {
  return STATUS_META[status] || STATUS_META.unknown;
}

function Toggle({ checked, disabled, onChange }: { checked: boolean; disabled?: boolean; onChange: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={onChange}
      className={`relative inline-flex h-7 w-12 items-center rounded-full border transition ${
        checked ? "border-emerald-400/30 bg-emerald-400/20" : "border-white/10 bg-white/[0.05]"
      } ${disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"}`}
    >
      <span className={`inline-block h-5 w-5 rounded-full bg-white shadow transition ${checked ? "translate-x-6" : "translate-x-1"}`} />
    </button>
  );
}

function formatDate(value?: string | null) {
  if (!value) return "Nunca validado";
  return new Date(value).toLocaleString("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

export default function McpIntegrationsWorkspace({
  readOnly = false,
  title = "MCP",
  subtitle = "Gerencie conectores por usuario e acompanhe os servicos centrais do runtime.",
}: {
  readOnly?: boolean;
  title?: string;
  subtitle?: string;
}) {
  const [items, setItems] = useState<IntegrationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyService, setBusyService] = useState<string | null>(null);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [modal, setModal] = useState<ModalState | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [googleJson, setGoogleJson] = useState("");
  const [spreadsheetId, setSpreadsheetId] = useState("");
  const [airtableKey, setAirtableKey] = useState("");
  const [airtableBaseId, setAirtableBaseId] = useState("");

  const grouped = useMemo(
    () => ({
      user: items.filter((item) => item.scope === "user"),
      system: items.filter((item) => item.scope === "system"),
    }),
    [items],
  );

  async function refresh() {
    setLoading(true);
    setGlobalError(null);
    try {
      setItems(await api.integrations());
    } catch (error: any) {
      setGlobalError(error?.message || "Falha ao carregar integracoes.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh().catch(console.error);
  }, []);

  function resetModalState() {
    setGoogleJson("");
    setSpreadsheetId("");
    setAirtableKey("");
    setAirtableBaseId("");
    setFormError(null);
  }

  function openModal(item: IntegrationItem) {
    resetModalState();
    setModal({ service: item.service, label: item.label, configured: item.configured });
  }

  function closeModal() {
    resetModalState();
    setModal(null);
  }

  async function handleToggle(item: IntegrationItem) {
    if (readOnly || item.scope !== "user") return;
    setGlobalError(null);
    if (!item.enabled && !item.configured) {
      openModal(item);
      return;
    }
    setBusyService(item.service);
    try {
      await api.updateUserIntegration(item.service, { enabled: !item.enabled });
      startTransition(() => {
        refresh().catch(console.error);
      });
    } catch (error: any) {
      const message = error?.message || "Falha ao atualizar integracao.";
      if (!item.enabled) {
        openModal(item);
        setFormError(message);
      } else {
        setGlobalError(message);
      }
    } finally {
      setBusyService(null);
    }
  }

  async function saveCredentials() {
    if (!modal) return;
    setBusyService(modal.service);
    setFormError(null);
    try {
      if (modal.service === "google_sheets") {
        await api.updateUserIntegration(modal.service, {
          enabled: true,
          service_account_json: googleJson,
          spreadsheet_id: spreadsheetId || undefined,
        });
      } else {
        await api.updateUserIntegration(modal.service, {
          enabled: true,
          api_key: airtableKey,
          base_id: airtableBaseId,
        });
      }
      closeModal();
      startTransition(() => {
        refresh().catch(console.error);
      });
    } catch (error: any) {
      setFormError(error?.message || "Falha ao validar credenciais.");
    } finally {
      setBusyService(null);
    }
  }

  async function removeCredentials() {
    if (!modal) return;
    setBusyService(modal.service);
    setFormError(null);
    try {
      await api.deleteUserIntegrationCredentials(modal.service);
      closeModal();
      startTransition(() => {
        refresh().catch(console.error);
      });
    } catch (error: any) {
      setFormError(error?.message || "Falha ao remover credenciais.");
    } finally {
      setBusyService(null);
    }
  }

  return (
    <div className="space-y-6">
      <header className="rounded-[28px] border border-white/8 bg-[radial-gradient(circle_at_top_left,rgba(16,185,129,0.18),transparent_40%),radial-gradient(circle_at_top_right,rgba(59,130,246,0.16),transparent_38%),rgba(9,10,14,0.92)] p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-zinc-400">Model Context Protocol</p>
            <div className="flex items-center gap-3">
              <span className="flex h-11 w-11 items-center justify-center rounded-2xl border border-emerald-400/20 bg-emerald-400/10 text-emerald-300">
                <DatabaseZap size={18} />
              </span>
              <div>
                <h1 className="text-2xl font-semibold text-white">{title}</h1>
                <p className="max-w-2xl text-sm text-zinc-300">{subtitle}</p>
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={() => refresh().catch(console.error)}
            className="inline-flex items-center gap-2 self-start rounded-full border border-white/10 bg-white/[0.04] px-4 py-2 text-sm text-zinc-200 transition hover:border-white/20 hover:bg-white/[0.07]"
          >
            <RefreshCcw size={14} />
            Atualizar
          </button>
        </div>
      </header>

      {globalError && (
        <div className="flex items-start gap-3 rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-100">
          <AlertCircle size={16} className="mt-0.5 shrink-0" />
          <p>{globalError}</p>
        </div>
      )}

      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <KeyRound size={15} className="text-emerald-300" />
          <div>
            <h2 className="text-sm font-semibold text-white">Conectores do usuario</h2>
            <p className="text-xs text-zinc-400">Cada usuario controla suas proprias credenciais para Google Sheets e Airtable.</p>
          </div>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {grouped.user.map((item) => {
            const meta = statusMeta(item.status);
            const busy = busyService === item.service;
            return (
              <article key={item.service} className="rounded-[24px] border border-white/8 bg-white/[0.03] p-5">
                <div className="flex items-start justify-between gap-4">
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <span className={`h-2.5 w-2.5 rounded-full ${meta.dot}`} />
                      <p className="text-lg font-medium text-white">{item.label}</p>
                    </div>
                    <p className="text-sm leading-6 text-zinc-300">{item.description}</p>
                  </div>
                  {!readOnly && <Toggle checked={item.enabled} disabled={busy} onChange={() => handleToggle(item)} />}
                </div>

                <div className="mt-5 grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-2xl border border-white/6 bg-black/20 p-3">
                    <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-500">Status</p>
                    <p className={`mt-2 font-medium ${meta.tone}`}>{meta.label}</p>
                  </div>
                  <div className="rounded-2xl border border-white/6 bg-black/20 p-3">
                    <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-500">Credenciais</p>
                    <p className="mt-2 font-medium text-white">{item.configured ? "Configuradas" : "Nao configuradas"}</p>
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-xs text-zinc-400">
                  <span>Ultima validacao: {formatDate(item.last_validated_at)}</span>
                  {!readOnly && (
                    <button
                      type="button"
                      onClick={() => openModal(item)}
                      className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-zinc-200 transition hover:border-white/20 hover:bg-white/[0.07]"
                    >
                      <Cable size={13} />
                      Configurar credenciais
                    </button>
                  )}
                </div>

                {item.last_error && (
                  <p className="mt-4 rounded-2xl border border-rose-400/15 bg-rose-400/10 px-3 py-2 text-xs text-rose-200">
                    {item.last_error}
                  </p>
                )}
              </article>
            );
          })}
        </div>
      </section>

      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <ShieldCheck size={15} className="text-sky-300" />
          <div>
            <h2 className="text-sm font-semibold text-white">Servicos do sistema</h2>
            <p className="text-xs text-zinc-400">Esses conectores ficam visiveis no MCP, mas sao gerenciados pelo runtime da plataforma.</p>
          </div>
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {grouped.system.map((item) => {
            const meta = statusMeta(item.status);
            return (
              <article key={item.service} className="rounded-[22px] border border-white/8 bg-white/[0.03] p-4">
                <div className="flex items-center gap-2">
                  <span className={`h-2.5 w-2.5 rounded-full ${meta.dot}`} />
                  <p className="font-medium text-white">{item.label}</p>
                </div>
                <p className="mt-2 text-sm leading-6 text-zinc-300">{item.description}</p>
                <div className="mt-4 flex items-center justify-between text-xs">
                  <span className={meta.tone}>{meta.label}</span>
                  <span className="text-zinc-500">{item.response_ms ? `${item.response_ms}ms` : formatDate(item.last_validated_at)}</span>
                </div>
                {item.last_error && (
                  <p className="mt-3 rounded-2xl border border-rose-400/15 bg-rose-400/10 px-3 py-2 text-xs text-rose-200">
                    {item.last_error}
                  </p>
                )}
              </article>
            );
          })}
        </div>
      </section>

      {loading && (
        <div className="rounded-2xl border border-white/8 bg-white/[0.03] p-4 text-sm text-zinc-400">
          Carregando integrações...
        </div>
      )}

      {modal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4">
          <div className="w-full max-w-xl rounded-[28px] border border-white/10 bg-[#0f1117] p-6 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-zinc-500">Credenciais</p>
                <h3 className="mt-2 text-xl font-semibold text-white">{modal.label}</h3>
                <p className="mt-2 text-sm text-zinc-300">Ao habilitar, a credencial e validada antes de liberar o conector.</p>
              </div>
              <button
                type="button"
                onClick={closeModal}
                className="rounded-full border border-white/10 px-3 py-1 text-sm text-zinc-300 transition hover:border-white/20 hover:bg-white/[0.05]"
              >
                Fechar
              </button>
            </div>

            <div className="mt-6 space-y-4">
              {modal.service === "google_sheets" ? (
                <>
                  <label className="block space-y-2">
                    <span className="text-sm text-zinc-200">JSON da service account</span>
                    <input
                      type="file"
                      accept="application/json"
                      onChange={async (event) => {
                        const file = event.target.files?.[0];
                        setGoogleJson(file ? await file.text() : "");
                      }}
                      className="block w-full rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-zinc-200"
                    />
                  </label>
                  <label className="block space-y-2">
                    <span className="text-sm text-zinc-200">Spreadsheet ID opcional</span>
                    <input
                      value={spreadsheetId}
                      onChange={(event) => setSpreadsheetId(event.target.value)}
                      className="w-full rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-zinc-100 outline-none transition focus:border-emerald-400/40"
                      placeholder="1AbCdEfGh..."
                    />
                  </label>
                </>
              ) : (
                <>
                  <label className="block space-y-2">
                    <span className="text-sm text-zinc-200">API key / token</span>
                    <input
                      value={airtableKey}
                      onChange={(event) => setAirtableKey(event.target.value)}
                      className="w-full rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-zinc-100 outline-none transition focus:border-emerald-400/40"
                      placeholder="pat..."
                    />
                  </label>
                  <label className="block space-y-2">
                    <span className="text-sm text-zinc-200">Base ID</span>
                    <input
                      value={airtableBaseId}
                      onChange={(event) => setAirtableBaseId(event.target.value)}
                      className="w-full rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-zinc-100 outline-none transition focus:border-emerald-400/40"
                      placeholder="app..."
                    />
                  </label>
                </>
              )}

              {formError && (
                <div className="rounded-2xl border border-rose-400/15 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">
                  {formError}
                </div>
              )}
            </div>

            <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
              <div>
                {modal.configured && (
                  <button
                    type="button"
                    onClick={removeCredentials}
                    disabled={busyService === modal.service}
                    className="inline-flex items-center gap-2 rounded-full border border-rose-400/20 bg-rose-400/10 px-4 py-2 text-sm text-rose-200 transition hover:bg-rose-400/15 disabled:opacity-50"
                  >
                    <Trash2 size={14} />
                    Remover credenciais
                  </button>
                )}
              </div>
              <button
                type="button"
                onClick={saveCredentials}
                disabled={busyService === modal.service}
                className="inline-flex items-center gap-2 rounded-full border border-emerald-400/25 bg-emerald-400/15 px-4 py-2 text-sm font-medium text-emerald-100 transition hover:bg-emerald-400/20 disabled:opacity-50"
              >
                <ShieldCheck size={14} />
                {busyService === modal.service ? "Salvando..." : "Salvar e testar"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
