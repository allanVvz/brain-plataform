"use client";

import { useCallback, useEffect, useState } from "react";
import { LogOut, QrCode, RefreshCw, Smartphone } from "lucide-react";
import Image from "next/image";
import { api } from "@/lib/api";

export default function WhatsAppPage() {
  const [slug, setSlug] = useState("");
  const [channel, setChannel] = useState<any>(null);
  const [qr, setQr] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [provider, setProvider] = useState<"meta_cloud" | "evolution_baileys">("evolution_baileys");

  const load = useCallback(async (value?: string) => {
    const active = value || window.localStorage.getItem("ai-brain-persona-slug") || "";
    setSlug(active);
    if (!active) return;
    try {
      const result = await api.whatsappChannel(active);
      setChannel(result);
      if (result.provider) setProvider(result.provider);
      if (result.status === "connected") setQr("");
    } catch (e: any) {
      setError(e?.message || "Falha ao carregar canal.");
    }
  }, []);

  useEffect(() => {
    load();
    const change = (event: Event) => load((event as CustomEvent<{ slug?: string }>).detail?.slug);
    window.addEventListener("ai-brain-persona-change", change);
    return () => window.removeEventListener("ai-brain-persona-change", change);
  }, [load]);

  async function action(fn: () => Promise<any>) {
    setBusy(true); setError("");
    try {
      const result = await fn();
      setQr(result?.qr?.base64 || "");
      await load(slug);
    } catch (e: any) {
      setError(e?.message || "Operacao indisponivel.");
    } finally {
      setBusy(false);
    }
  }

  async function switchProvider() {
    const label = provider === "meta_cloud" ? "Meta API" : "Evolution API";
    if (!window.confirm(`Confirmar troca do canal WhatsApp para ${label}? O canal anterior será preservado inativo.`)) return;
    await action(() => api.selectWhatsAppProvider(slug, provider, true));
  }

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <header>
        <h1 className="flex items-center gap-2 text-xl font-semibold"><Smartphone size={20} /> WhatsApp</h1>
        <p className="mt-1 text-sm text-obs-subtle">Conecte o numero da persona selecionada.</p>
      </header>
      {!slug && <div className="rounded-xl border border-amber-400/30 p-4 text-sm">Selecione uma persona.</div>}
      {slug && (
        <section className="space-y-4 rounded-xl border border-black/10 bg-white/60 p-5">
          <div className="flex items-center justify-between">
            <div><p className="text-sm text-obs-faint">Estado</p><p className="font-medium">{channel?.status || "carregando"}</p></div>
            <div className={`h-3 w-3 rounded-full ${channel?.status === "connected" ? "bg-green-500" : "bg-amber-400"}`} />
          </div>
          {error && <div className="text-sm text-red-500">{error}</div>}
          {qr && <Image unoptimized width={256} height={256} src={qr} alt="QR Code para conectar WhatsApp" className="mx-auto h-64 w-64 rounded-lg bg-white p-2" />}
          {channel?.can_manage && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-end gap-2">
                <label className="text-xs text-obs-subtle">Provider
                  <select aria-label="Provider WhatsApp" value={provider} onChange={(event) => setProvider(event.target.value as typeof provider)} className="mt-1 block rounded-lg border border-black/10 bg-white px-3 py-2 text-sm text-obs-text">
                    <option value="meta_cloud">Meta API</option>
                    <option value="evolution_baileys">Evolution API</option>
                  </select>
                </label>
                <button disabled={busy || provider === channel?.provider} onClick={switchProvider} className="rounded-lg bg-obs-violet px-4 py-2 text-sm text-white disabled:opacity-40">Trocar canal</button>
              </div>
              <div className="flex flex-wrap gap-2">
              {channel?.configured && channel?.provider === "evolution_baileys" && (
                <>
                  <button disabled={busy} onClick={() => action(() => api.connectEvolution(slug))} className="flex items-center gap-2 rounded-lg bg-obs-violet px-4 py-2 text-sm text-white"><QrCode size={14} /> QR Code</button>
                  <button disabled={busy} onClick={() => action(() => api.restartEvolution(slug))} className="flex items-center gap-2 rounded-lg border border-black/10 px-4 py-2 text-sm"><RefreshCw size={14} /> Reiniciar</button>
                  <button disabled={busy} onClick={() => action(() => api.logoutEvolution(slug))} className="flex items-center gap-2 rounded-lg border border-red-400/30 px-4 py-2 text-sm text-red-500"><LogOut size={14} /> Desconectar</button>
                </>
              )}
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
