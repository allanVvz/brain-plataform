"use client";

import { useEffect, useState } from "react";
import { Loader2, Plug, Save, X } from "lucide-react";
import { api } from "@/lib/api";

type Service = { key: string; label: string; desc: string };

/**
 * Per-tool configuration modal opened by the gear icon. Currently Meta is the
 * only user-managed integration with editable credentials; other services show
 * a read-only status panel. The Meta access token is masked and never echoed
 * back by the backend.
 */
export function IntegrationConfigModal({
  service,
  data,
  onClose,
  onSaved,
}: {
  service: Service;
  data: any;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isMeta = service.key === "meta";
  const [businessId, setBusinessId] = useState("");
  const [catalogId, setCatalogId] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [status, setStatus] = useState<string>(data?.status || "unknown");
  const [busy, setBusy] = useState<null | "test" | "save">(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    setStatus(data?.status || "unknown");
    setBusinessId(data?.config_json?.business_id || data?.business_id || "");
    setCatalogId(data?.config_json?.catalog_id || data?.catalog_id || "");
    setAccessToken("");
    setError(null);
    setNotice(null);
  }, [service.key, data]);

  function credentialsBody() {
    return {
      business_id: businessId.trim(),
      catalog_id: catalogId.trim(),
      access_token: accessToken.trim(),
    };
  }

  async function testConnection() {
    setBusy("test");
    setError(null);
    setNotice(null);
    try {
      const res = await api.validateUserIntegration(service.key, credentialsBody());
      setStatus(res?.status || "healthy");
      setNotice("Conexao validada.");
    } catch (err: any) {
      setStatus("error");
      setError(err?.message || "Falha ao testar conexao.");
    } finally {
      setBusy(null);
    }
  }

  async function save() {
    setBusy("save");
    setError(null);
    setNotice(null);
    try {
      const res = await api.updateUserIntegration(service.key, { enabled: true, ...credentialsBody() });
      setStatus(res?.status || "healthy");
      setNotice("Configuracao salva.");
      onSaved();
    } catch (err: any) {
      setStatus("error");
      setError(err?.message || "Falha ao salvar.");
    } finally {
      setBusy(null);
    }
  }

  const statusColor =
    status === "healthy" ? "text-green-400" : status === "error" ? "text-red-400" : "text-obs-faint";

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/55 p-5 backdrop-blur-sm" role="dialog" aria-label={`Configurar ${service.label}`}>
      <div className="flex w-full max-w-md flex-col overflow-hidden rounded-xl glass-raised">
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
          <div className="flex items-center gap-2">
            <Plug size={15} className="text-obs-violet" />
            <div>
              <h2 className="text-sm font-semibold text-obs-text">Configurar {service.label}</h2>
              <p className={`text-[11px] font-medium ${statusColor}`}>status: {status}</p>
            </div>
          </div>
          <button type="button" onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 text-obs-subtle hover:text-obs-text" aria-label="Fechar">
            <X size={15} />
          </button>
        </div>

        <div className="space-y-3 p-5">
          {isMeta ? (
            <>
              <div>
                <label className="block text-[10px] uppercase tracking-wide text-obs-faint">Business ID</label>
                <input value={businessId} onChange={(e) => setBusinessId(e.target.value)} className="lg-input mt-1 w-full text-sm" aria-label="Business ID" />
              </div>
              <div>
                <label className="block text-[10px] uppercase tracking-wide text-obs-faint">Catalog ID</label>
                <input value={catalogId} onChange={(e) => setCatalogId(e.target.value)} className="lg-input mt-1 w-full text-sm" aria-label="Catalog ID" />
              </div>
              <div>
                <label className="block text-[10px] uppercase tracking-wide text-obs-faint">Access Token</label>
                <input
                  type="password"
                  value={accessToken}
                  onChange={(e) => setAccessToken(e.target.value)}
                  placeholder={data?.configured ? "•••••••• (mantém o token salvo)" : "Token de acesso"}
                  className="lg-input mt-1 w-full text-sm"
                  aria-label="Access Token"
                />
                <p className="mt-1 text-[11px] text-obs-faint">O token e mascarado e nunca retornado pelo backend.</p>
              </div>
            </>
          ) : (
            <p className="text-xs text-obs-subtle">
              {service.desc}. Esta integracao e gerenciada pelo sistema; nao ha credenciais editaveis aqui.
            </p>
          )}

          {error && <div className="rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">{error}</div>}
          {notice && <div className="rounded-lg border border-green-400/25 bg-green-400/05 px-3 py-2 text-xs text-green-300">{notice}</div>}
        </div>

        {isMeta && (
          <div className="flex items-center justify-end gap-2 border-t border-white/10 px-5 py-4">
            <button type="button" onClick={testConnection} disabled={busy !== null} className="lg-btn rounded-lg text-xs">
              {busy === "test" ? <Loader2 size={13} className="animate-spin" /> : <Plug size={13} />} Testar conexao
            </button>
            <button type="button" onClick={save} disabled={busy !== null} className="lg-btn lg-btn-primary rounded-lg">
              {busy === "save" ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />} Salvar
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
