"use client";

import Link from "next/link";
import { Search, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { LeadInfoModal } from "@/components/leads/LeadInfoModal";
import { usePortal } from "../PortalContext";

const stages = [
  ["novo", "Novo"],
  ["nao_qualificado", "Não qualificado"],
  ["contatado", "Contatado"],
  ["engajado", "Engajado"],
  ["qualificado", "Qualificado"],
  ["oportunidade", "Oportunidade"],
  ["fechado", "Fechado"],
  ["perdido", "Perdido"],
];

export default function ClientLeadsPage() {
  const { personaSlug, capabilities } = usePortal();
  const [rows, setRows] = useState<any[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [infoLead, setInfoLead] = useState<any | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setRows(await api.portalLeads(personaSlug));
    } catch (reason: any) {
      setError(reason?.message || "Não foi possível carregar os leads.");
    } finally {
      setLoading(false);
    }
  }, [personaSlug]);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return rows;
    return rows.filter((lead) =>
      [lead.nome, lead.telefone, lead.email, lead.cidade, lead.interesse_produto]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query)),
    );
  }, [rows, search]);

  async function updateLead(id: number, body: Record<string, unknown>) {
    try {
      const updated = await api.updatePortalLead(personaSlug, id, body);
      setRows((current) =>
        current.map((lead) => (lead.id === id ? { ...lead, ...updated } : lead)),
      );
    } catch (reason: any) {
      setError(reason?.message || "Não foi possível atualizar o lead.");
    }
  }

  return (
    <div className="space-y-5">
      <header>
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <Users size={23} /> Leads
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          Contatos e informações comerciais da sua persona.
        </p>
      </header>

      <label className="relative block max-w-xl">
        <Search className="absolute left-3 top-3 text-slate-400" size={17} />
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Buscar por nome, telefone, e-mail ou interesse"
          className="w-full rounded-xl border border-slate-200 bg-white py-2.5 pl-10 pr-4 text-sm shadow-sm outline-none focus:border-violet-400 focus:ring-2 focus:ring-violet-100"
        />
      </label>

      {error && (
        <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        {loading ? (
          <p className="p-8 text-center text-sm text-slate-500">Carregando leads…</p>
        ) : filtered.length === 0 ? (
          <div className="p-10 text-center">
            <Users className="mx-auto text-slate-300" size={30} />
            <h2 className="mt-3 font-semibold">Nenhum lead por aqui ainda</h2>
            <p className="mt-1 text-sm text-slate-500">
              Os contatos aparecerão quando chegarem pelo canal conectado.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {filtered.map((lead) => {
              const notes = lead.metadata?.portal?.notes || "";
              return (
                <article key={lead.id} className="grid gap-4 p-5 lg:grid-cols-[1.3fr_1fr_1.3fr_auto] lg:items-center">
                  <div className="min-w-0">
                    {capabilities.edit ? (
                      <button
                        type="button"
                        onClick={() => setInfoLead(lead)}
                        className="font-semibold text-slate-950 hover:text-violet-700"
                        title="Ver/editar informações do lead"
                      >
                        {lead.nome || lead.telefone || `Lead #${lead.id}`}
                      </button>
                    ) : (
                      <Link
                        href={`/clientes/${personaSlug}/mensagens/${lead.id}`}
                        className="font-semibold text-slate-950 hover:text-violet-700"
                      >
                        {lead.nome || lead.telefone || `Lead #${lead.id}`}
                      </Link>
                    )}
                    <p className="mt-1 truncate text-xs text-slate-500">
                      {[lead.telefone, lead.email, lead.cidade].filter(Boolean).join(" · ") || "Dados de contato pendentes"}
                    </p>
                  </div>
                  <label className="text-xs font-medium text-slate-500">
                    Estágio
                    <select
                      value={lead.stage || "novo"}
                      disabled={!capabilities.edit}
                      onChange={(event) => updateLead(lead.id, { stage: event.target.value })}
                      className="mt-1 block w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 disabled:bg-slate-50"
                    >
                      {stages.map(([value, label]) => (
                        <option key={value} value={value}>{label}</option>
                      ))}
                    </select>
                  </label>
                  <label className="text-xs font-medium text-slate-500">
                    Nota comercial
                    <input
                      defaultValue={notes}
                      disabled={!capabilities.edit}
                      onBlur={(event) => {
                        if (event.target.value !== notes) {
                          updateLead(lead.id, { notes: event.target.value });
                        }
                      }}
                      placeholder="Adicione um contexto"
                      className="mt-1 block w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 disabled:bg-slate-50"
                    />
                  </label>
                  <Link
                    href={`/clientes/${personaSlug}/mensagens/${lead.id}`}
                    className="rounded-lg border border-slate-200 px-3 py-2 text-center text-sm font-medium text-slate-700 hover:bg-slate-50"
                  >
                    Conversa
                  </Link>
                </article>
              );
            })}
          </div>
        )}
      </section>

      {infoLead && (
        <LeadInfoModal
          lead={infoLead}
          onClose={() => setInfoLead(null)}
          onSaved={async (updated) => {
            setRows((current) =>
              current.map((lead) => (lead.id === updated.id ? { ...lead, ...updated } : lead)),
            );
          }}
          onSubmit={(leadRef, body) => api.updatePortalLead(personaSlug, leadRef, body)}
        />
      )}
    </div>
  );
}
