"use client";

import Image from "next/image";
import { KeyRound, QrCode, Settings, Smartphone } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { usePortal } from "../PortalContext";

export default function ClientSettingsPage() {
  const { personaSlug, capabilities, user } = usePortal();
  const [channel, setChannel] = useState<any>(null);
  const [provider, setProvider] = useState<"meta_cloud" | "evolution_baileys">("evolution_baileys");
  const [qr, setQr] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [passwords, setPasswords] = useState({ current_password: "", new_password: "" });

  async function loadChannel() {
    const result = await api.whatsappChannel(personaSlug);
    setChannel(result);
    if (result.provider) setProvider(result.provider);
  }

  useEffect(() => {
    loadChannel().catch((reason: any) => setError(reason?.message || "Falha ao carregar o canal."));
  }, [personaSlug]);

  async function channelAction(action: () => Promise<any>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await action();
      setQr(result?.qr?.base64 || "");
      setMessage("Configuração atualizada.");
      await loadChannel();
    } catch (reason: any) {
      setError(reason?.message || "Operação indisponível.");
    } finally {
      setBusy(false);
    }
  }

  async function switchProvider() {
    const label = provider === "meta_cloud" ? "Meta Cloud" : "Evolution";
    if (!window.confirm(`Confirmar troca do canal para ${label}?`)) return;
    await channelAction(() => api.selectWhatsAppProvider(personaSlug, provider, true));
  }

  async function changePassword(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api.changePassword(passwords);
      setPasswords({ current_password: "", new_password: "" });
      setMessage("Senha alterada com segurança.");
    } catch (reason: any) {
      setError(reason?.message || "Não foi possível alterar a senha.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <header>
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <Settings size={23} /> Configurações
        </h1>
        <p className="mt-1 text-sm text-slate-600">Canal WhatsApp, conta e segurança.</p>
      </header>
      {error && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}
      {message && <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-700">{message}</div>}

      <div className="grid gap-5 xl:grid-cols-2">
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-violet-50 text-violet-700"><Smartphone size={20} /></span>
            <div>
              <h2 className="font-semibold">Canal WhatsApp</h2>
              <p className="mt-1 text-sm text-slate-500">
                {channel?.configured ? `Estado atual: ${channel.status}` : "Nenhum canal conectado. O portal permanece disponível em modo onboarding."}
              </p>
            </div>
          </div>
          {qr && (
            <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4 text-center">
              <Image unoptimized width={240} height={240} src={qr} alt="QR Code temporário para conectar WhatsApp" className="mx-auto rounded-lg bg-white p-2" />
              <p className="mt-2 text-xs text-slate-500">Este código é temporário e não é armazenado pelo portal.</p>
            </div>
          )}
          <div className="mt-5 space-y-3">
            <label className="block text-xs font-medium text-slate-600">
              Provider
              <select
                value={provider}
                disabled={!capabilities.manage || busy}
                onChange={(event) => setProvider(event.target.value as typeof provider)}
                className="mt-1 block w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm disabled:bg-slate-50"
              >
                <option value="meta_cloud">Meta Cloud</option>
                <option value="evolution_baileys">Evolution</option>
              </select>
            </label>
            {capabilities.manage ? (
              <div className="flex flex-wrap gap-2">
                <button disabled={busy || provider === channel?.provider} onClick={switchProvider} className="rounded-xl bg-slate-950 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-40">Trocar provider</button>
                {channel?.configured && channel?.provider === "evolution_baileys" ? (
                  <button disabled={busy} onClick={() => channelAction(() => api.connectEvolution(personaSlug))} className="flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-medium"><QrCode size={16} /> Solicitar QR</button>
                ) : !channel?.configured && provider === "evolution_baileys" ? (
                  <button disabled={busy} onClick={() => channelAction(() => api.provisionEvolution(personaSlug))} className="rounded-xl border border-slate-200 px-4 py-2.5 text-sm font-medium">Preparar Evolution</button>
                ) : null}
              </div>
            ) : (
              <p className="rounded-xl bg-slate-50 p-3 text-xs text-slate-500">Seu perfil possui acesso somente leitura às configurações do canal.</p>
            )}
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-slate-100 text-slate-700"><KeyRound size={20} /></span>
            <div>
              <h2 className="font-semibold">Conta e segurança</h2>
              <p className="mt-1 text-sm text-slate-500">{user?.email}</p>
            </div>
          </div>
          <form onSubmit={changePassword} className="mt-5 space-y-3">
            <label className="block text-xs font-medium text-slate-600">
              Senha atual
              <input type="password" required autoComplete="current-password" value={passwords.current_password} onChange={(event) => setPasswords((value) => ({ ...value, current_password: event.target.value }))} className="mt-1 block w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm" />
            </label>
            <label className="block text-xs font-medium text-slate-600">
              Nova senha
              <input type="password" required minLength={12} autoComplete="new-password" value={passwords.new_password} onChange={(event) => setPasswords((value) => ({ ...value, new_password: event.target.value }))} className="mt-1 block w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm" />
            </label>
            <p className="text-xs text-slate-500">Use pelo menos 12 caracteres e uma senha diferente da atual.</p>
            <button disabled={busy} className="rounded-xl bg-violet-700 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50">Alterar senha</button>
          </form>
        </section>
      </div>
    </div>
  );
}
