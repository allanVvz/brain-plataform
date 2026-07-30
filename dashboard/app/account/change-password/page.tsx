"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { KeyRound } from "lucide-react";
import { api } from "@/lib/api";
import { resolveSessionDestination } from "@/lib/session-routing";

export default function ChangePasswordPage() {
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (next !== confirm) {
      setError("As novas senhas nao conferem.");
      return;
    }
    setLoading(true);
    try {
      await api.changePassword({ current_password: current, new_password: next });
      const requested = new URLSearchParams(window.location.search).get("next") || "";
      const session = await api.me();
      router.replace(resolveSessionDestination(session, requested));
    } catch (e: any) {
      setError(e?.message || "Falha ao alterar senha.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto max-w-lg">
      <form onSubmit={submit} className="space-y-4 rounded-xl border border-black/10 bg-white/60 p-6">
        <h1 className="flex items-center gap-2 text-xl font-semibold"><KeyRound size={20} /> Alterar senha</h1>
        <p className="text-sm text-obs-subtle">Use pelo menos 12 caracteres.</p>
        <input className="w-full rounded-lg border border-black/10 bg-white px-3 py-2" type="password" autoComplete="current-password" placeholder="Senha atual" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        <input className="w-full rounded-lg border border-black/10 bg-white px-3 py-2" type="password" autoComplete="new-password" placeholder="Nova senha" minLength={12} value={next} onChange={(e) => setNext(e.target.value)} required />
        <input className="w-full rounded-lg border border-black/10 bg-white px-3 py-2" type="password" autoComplete="new-password" placeholder="Confirmar nova senha" minLength={12} value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
        {error && <div className="text-sm text-red-500">{error}</div>}
        <button disabled={loading} className="rounded-lg bg-obs-violet px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
          {loading ? "Salvando..." : "Salvar nova senha"}
        </button>
      </form>
    </div>
  );
}
