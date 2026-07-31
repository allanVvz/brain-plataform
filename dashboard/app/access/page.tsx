"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Copy, UserPlus, Users } from "lucide-react";
import { api } from "@/lib/api";

type AccessProfile = "manager" | "operator" | "viewer";

const ACCESS_PROFILES: Record<AccessProfile, {
  role: "user" | "operator" | "viewer";
  can_view: boolean;
  can_edit: boolean;
  can_manage: boolean;
}> = {
  manager: { role: "user", can_view: true, can_edit: true, can_manage: true },
  operator: { role: "operator", can_view: true, can_edit: true, can_manage: false },
  viewer: { role: "viewer", can_view: true, can_edit: false, can_manage: false },
};

function profileFor(row: any): AccessProfile {
  if (row?.can_manage) return "manager";
  if (row?.can_edit) return "operator";
  return "viewer";
}

export default function AccessPage() {
  const [slug, setSlug] = useState("");
  const [members, setMembers] = useState<any[]>([]);
  const [email, setEmail] = useState("");
  const [profile, setProfile] = useState<AccessProfile>("manager");
  const [temporary, setTemporary] = useState("");
  const [portalUrl, setPortalUrl] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async (next?: string) => {
    const active = next || window.localStorage.getItem("ai-brain-persona-slug") || "";
    setSlug(active);
    if (!active) return setMembers([]);
    try { setMembers(await api.accessMembers(active)); }
    catch (e: any) { setError(e?.message || "Falha ao carregar acessos."); }
  }, []);

  useEffect(() => {
    load();
    const change = (event: Event) => load((event as CustomEvent<{ slug?: string }>).detail?.slug);
    window.addEventListener("ai-brain-persona-change", change);
    return () => window.removeEventListener("ai-brain-persona-change", change);
  }, [load]);

  async function create(event: FormEvent) {
    event.preventDefault(); setError(""); setTemporary(""); setPortalUrl("");
    try {
      const result = await api.createAccessMember(slug, {
        email,
        ...ACCESS_PROFILES[profile],
      });
      setTemporary(result?.temporary_password || "");
      setPortalUrl(result?.portal_url || `/clientes/${slug}/mensagens`);
      setEmail("");
      await load(slug);
    } catch (e: any) { setError(e?.message || "Falha ao criar acesso."); }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <header><h1 className="flex items-center gap-2 text-xl font-semibold"><Users size={20} /> Acessos</h1><p className="mt-1 text-sm text-obs-subtle">Clientes vinculados à persona selecionada.</p></header>
      <form onSubmit={create} className="grid gap-3 rounded-xl border border-black/10 bg-white/60 p-4 sm:grid-cols-[1fr_12rem_auto] sm:items-end">
        <label className="text-xs font-medium text-obs-subtle">
          Email
          <input className="mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm text-obs-text" type="email" placeholder="cliente@empresa.com" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label className="text-xs font-medium text-obs-subtle">
          Tipo de acesso
          <select
            aria-label="Tipo de acesso"
            className="mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm text-obs-text"
            value={profile}
            onChange={(event) => setProfile(event.target.value as AccessProfile)}
          >
            <option value="manager">Gestor do Cliente</option>
            <option value="operator">Operador</option>
            <option value="viewer">Visualizador</option>
          </select>
        </label>
        <button disabled={!slug} className="flex items-center gap-2 rounded-lg bg-obs-violet px-4 py-2 text-sm text-white disabled:opacity-40"><UserPlus size={14} /> Criar</button>
      </form>
      {(temporary || portalUrl) && <div data-testid="temporary-password-panel" className="space-y-3 rounded-xl border border-amber-400/30 bg-amber-50 p-4 text-sm"><p className="font-medium">Convite de acesso — entregue manualmente por canal seguro</p>{temporary && <div><p className="text-xs">Senha temporária, exibida somente agora</p><div className="mt-1 flex items-center gap-2"><code data-testid="temporary-password" className="rounded bg-white px-2 py-1">{temporary}</code><button type="button" onClick={() => navigator.clipboard.writeText(temporary)} aria-label="Copiar senha"><Copy size={14} /></button></div></div>}<div><p className="text-xs">Link do portal</p><div className="mt-1 flex items-center gap-2"><code data-testid="portal-url" className="rounded bg-white px-2 py-1">{portalUrl}</code><button type="button" onClick={() => navigator.clipboard.writeText(`${window.location.origin}${portalUrl}`)} aria-label="Copiar link do portal"><Copy size={14} /></button></div></div></div>}
      {error && <div className="text-sm text-red-500">{error}</div>}
      <div className="space-y-2">
        {members.map((row) => {
          const user = row.app_users || {};
          return (
            <div key={row.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-black/10 bg-white/60 p-4">
              <div><p className="font-medium">{user.name || user.email}</p><p className="text-xs text-obs-faint">{user.email}</p></div>
              <div className="flex items-center gap-2">
                <select
                  aria-label={`Permissão de ${user.email}`}
                  value={profileFor(row)}
                  onChange={async (event) => {
                    const next = event.target.value as AccessProfile;
                    setError("");
                    try {
                      await api.updateAccessMember(slug, row.user_id, ACCESS_PROFILES[next]);
                      await load(slug);
                    } catch (reason: any) {
                      setError(reason?.message || "Falha ao atualizar o acesso.");
                    }
                  }}
                  className="rounded-lg border border-black/10 bg-white px-2 py-1.5 text-xs text-obs-text"
                >
                  <option value="manager">Gestor</option>
                  <option value="operator">Operador</option>
                  <option value="viewer">Visualizador</option>
                </select>
                <button
                  onClick={async () => {
                    if (!window.confirm(`Revogar o acesso de ${user.email}?`)) return;
                    await api.revokeAccessMember(slug, row.user_id);
                    await load(slug);
                  }}
                  className="text-xs text-red-500"
                >
                  Revogar
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
