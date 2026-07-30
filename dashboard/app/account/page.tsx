"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { KeyRound, UserCircle } from "lucide-react";
import { api } from "@/lib/api";

export default function AccountPage() {
  const [session, setSession] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.me().then(setSession).catch((e) => setError(e?.message || "Falha ao carregar conta."));
  }, []);

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <header>
        <h1 className="flex items-center gap-2 text-xl font-semibold"><UserCircle size={20} /> Minha conta</h1>
        <p className="mt-1 text-sm text-obs-subtle">Dados da sessão e acessos autorizados.</p>
      </header>
      {error && <div className="rounded-lg border border-red-400/30 p-3 text-sm text-red-500">{error}</div>}
      {session && (
        <section className="rounded-xl border border-black/10 bg-white/60 p-5">
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <div><dt className="text-obs-faint">Nome</dt><dd>{session.user?.name || "--"}</dd></div>
            <div><dt className="text-obs-faint">Email</dt><dd>{session.user?.email}</dd></div>
            <div><dt className="text-obs-faint">Perfil</dt><dd>{session.access_profile}</dd></div>
            <div><dt className="text-obs-faint">Personas</dt><dd>{session.personas?.length || 0}</dd></div>
          </dl>
          <Link href="/account/change-password" className="mt-5 inline-flex items-center gap-2 rounded-lg bg-obs-violet px-4 py-2 text-sm text-white">
            <KeyRound size={15} /> Alterar senha
          </Link>
        </section>
      )}
    </div>
  );
}
