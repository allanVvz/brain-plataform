"use client";

import { FormEvent, useEffect, useState } from "react";
import { KeyRound, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";

export function SecuritySettingsPanel() {
  const [user, setUser] = useState<any>(null);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.me().then((session) => setUser(session?.user || null)).catch(() => undefined);
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setMessage("");
    setError("");
    if (newPassword !== confirmation) {
      setError("As novas senhas não conferem.");
      return;
    }
    setBusy(true);
    try {
      await api.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmation("");
      setUser((value: any) => ({ ...value, must_change_password: false }));
      setMessage("Senha alterada com segurança.");
    } catch (reason: any) {
      setError(reason?.message || "Não foi possível alterar a senha.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <header>
        <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">
          Conta
        </p>
        <h2 className="mt-1 flex items-center gap-2 text-xl font-semibold text-obs-text">
          <ShieldCheck size={19} className="text-obs-violet" /> Segurança
        </h2>
        <p className="mt-1 text-sm text-obs-subtle">{user?.email}</p>
      </header>

      {user?.must_change_password && (
        <p className="rounded-xl border border-amber-500/25 bg-amber-500/10 p-4 text-sm text-amber-200">
          Sua conta ainda usa uma senha temporária. Este é um aviso; o acesso não é bloqueado.
        </p>
      )}
      {error && <p role="alert" className="rounded-xl border border-rose-500/25 bg-rose-500/10 p-4 text-sm text-rose-200">{error}</p>}
      {message && <p role="status" className="rounded-xl border border-emerald-500/25 bg-emerald-500/10 p-4 text-sm text-emerald-200">{message}</p>}

      <form onSubmit={submit} className="space-y-4 rounded-2xl border border-white/10 bg-obs-surface p-6 shadow-sm">
        <div className="flex items-center gap-2">
          <KeyRound size={16} className="text-obs-violet" />
          <h3 className="text-sm font-semibold text-obs-text">Alterar senha</h3>
        </div>
        <label className="block text-xs text-obs-subtle">
          Senha atual
          <input
            type="password"
            autoComplete="current-password"
            required
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            className="mt-1 block w-full rounded-xl border border-white/10 bg-obs-raised px-3 py-2.5 text-sm text-obs-text"
          />
        </label>
        <label className="block text-xs text-obs-subtle">
          Nova senha
          <input
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            className="mt-1 block w-full rounded-xl border border-white/10 bg-obs-raised px-3 py-2.5 text-sm text-obs-text"
          />
        </label>
        <label className="block text-xs text-obs-subtle">
          Confirmar nova senha
          <input
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            className="mt-1 block w-full rounded-xl border border-white/10 bg-obs-raised px-3 py-2.5 text-sm text-obs-text"
          />
        </label>
        <p className="text-xs text-obs-faint">
          Mínimo de 12 caracteres; a senha atual é obrigatória.
        </p>
        <button
          disabled={busy}
          className="rounded-xl bg-obs-violet px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50"
        >
          {busy ? "Salvando..." : "Salvar nova senha"}
        </button>
      </form>
    </div>
  );
}
