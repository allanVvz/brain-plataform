"use client";

import Image from "next/image";
import { ChevronDown, KeyRound, QrCode, Settings, Smartphone } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { usePortal } from "../PortalContext";

const CONNECTED_STATES = new Set(["connected", "open"]);

export default function ClientSettingsPage() {
  const { personaSlug, capabilities, user } = usePortal();
  const [channel, setChannel] = useState<any>(null);
  const [qr, setQr] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [passwords, setPasswords] = useState({
    current_password: "",
    new_password: "",
  });

  async function loadChannel() {
    setChannel(await api.whatsappChannel(personaSlug));
  }

  useEffect(() => {
    loadChannel().catch((reason: any) => {
      setError(reason?.message || "Falha ao carregar o canal.");
    });
  }, [personaSlug]);

  async function requestEvolutionQr() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api.connectEvolution(personaSlug);
      setQr(result?.qr?.base64 || "");
      setMessage(
        result?.status === "connected"
          ? "Canal conectado."
          : "QR Code atualizado. Escaneie pelo WhatsApp para concluir.",
      );
      await loadChannel();
    } catch (reason: any) {
      setError(reason?.message || "Não foi possível gerar o QR Code.");
    } finally {
      setBusy(false);
    }
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

  const connected = CONNECTED_STATES.has(String(channel?.status || "").toLowerCase());
  const evolutionPending = (
    channel?.configured
    && channel?.provider === "evolution_baileys"
    && !connected
  );

  return (
    <div className="space-y-5">
      <header>
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <Settings size={23} /> Configurações
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          Estado do canal e segurança da sua conta.
        </p>
      </header>

      {user?.must_change_password && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          Recomendamos alterar a senha temporária. O portal continua disponível enquanto você conclui essa atualização.
        </div>
      )}
      {error && (
        <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}
      {message && (
        <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-700">
          {message}
        </div>
      )}

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-violet-50 text-violet-700">
            <Smartphone size={20} />
          </span>
          <div>
            <h2 className="font-semibold">Canal WhatsApp</h2>
            <p className="mt-1 text-sm text-slate-500">
              {connected
                ? "Canal conectado e disponível."
                : channel?.configured
                  ? "Canal aguardando conexão."
                  : "A configuração do canal ainda não foi concluída pelo administrador."}
            </p>
          </div>
        </div>

        {evolutionPending && (
          <div className="mt-5 rounded-xl border border-violet-200 bg-violet-50/60 p-4">
            <div className="flex items-start gap-3">
              <QrCode className="mt-0.5 text-violet-700" size={20} />
              <div>
                <h3 className="text-sm font-semibold text-slate-900">Concluir conexão do WhatsApp</h3>
                <p className="mt-1 text-xs leading-5 text-slate-600">
                  O administrador já preparou o canal Evolution. Gere o QR Code e escaneie em Aparelhos conectados.
                </p>
              </div>
            </div>
            {qr && (
              <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4 text-center">
                <Image
                  unoptimized
                  width={240}
                  height={240}
                  src={qr}
                  alt="QR Code temporário para conectar WhatsApp"
                  className="mx-auto rounded-lg bg-white p-2"
                />
                <p className="mt-2 text-xs text-slate-500">
                  Este código é temporário e não é armazenado pelo portal.
                </p>
              </div>
            )}
            {capabilities.manage && (
              <button
                type="button"
                disabled={busy}
                onClick={requestEvolutionQr}
                className="mt-4 flex items-center gap-2 rounded-xl bg-violet-700 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50"
              >
                <QrCode size={16} /> {busy ? "Atualizando..." : "Gerar ou atualizar QR Code"}
              </button>
            )}
          </div>
        )}
      </section>

      <details
        className="group rounded-2xl border border-slate-200 bg-white shadow-sm"
        open={user?.must_change_password || undefined}
      >
        <summary className="flex cursor-pointer list-none items-center gap-3 p-6">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-slate-100 text-slate-700">
            <KeyRound size={20} />
          </span>
          <div>
            <h2 className="font-semibold">Segurança</h2>
            <p className="mt-1 text-sm text-slate-500">{user?.email}</p>
          </div>
          <ChevronDown className="ml-auto text-slate-400 transition group-open:rotate-180" size={18} />
        </summary>
        <form onSubmit={changePassword} className="space-y-3 border-t border-slate-100 px-6 pb-6 pt-5">
          <label className="block text-xs font-medium text-slate-600">
            Senha atual
            <input
              type="password"
              required
              autoComplete="current-password"
              value={passwords.current_password}
              onChange={(event) => setPasswords((value) => ({
                ...value,
                current_password: event.target.value,
              }))}
              className="mt-1 block w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm"
            />
          </label>
          <label className="block text-xs font-medium text-slate-600">
            Nova senha
            <input
              type="password"
              required
              minLength={12}
              autoComplete="new-password"
              value={passwords.new_password}
              onChange={(event) => setPasswords((value) => ({
                ...value,
                new_password: event.target.value,
              }))}
              className="mt-1 block w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm"
            />
          </label>
          <p className="text-xs text-slate-500">
            Use pelo menos 12 caracteres e uma senha diferente da atual.
          </p>
          <button
            disabled={busy}
            className="rounded-xl bg-violet-700 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50"
          >
            Alterar senha
          </button>
        </form>
      </details>
    </div>
  );
}
