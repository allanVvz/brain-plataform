"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { MessageSquare, Search, Upload, Users } from "lucide-react";
import { api } from "@/lib/api";

type LeadOrigin = "crm" | "csv_bulk";
type FilterKey = "all" | "crm" | "csv_bulk";

const STAGE_LABEL: Record<string, string> = {
  novo: "Novo",
  "nao qualificado": "Nao qualificado",
  contatado: "Contatado",
  engajado: "Engajado",
  qualificado: "Qualificado",
  oportunidade: "Oportunidade",
  fechado: "Fechado",
  perdido: "Perdido",
};

const STAGE_COLOR: Record<string, string> = {
  novo: "text-obs-subtle",
  "nao qualificado": "text-obs-faint",
  contatado: "text-blue-400",
  engajado: "text-amber-400",
  qualificado: "text-orange-400",
  oportunidade: "text-emerald-400",
  fechado: "text-emerald-500 font-semibold",
  perdido: "text-rose-400",
};

function originOf(lead: any): LeadOrigin {
  return lead?.canal === "bulk_import" ? "csv_bulk" : "crm";
}

function canStartConversation(lead: any): boolean {
  return Boolean(lead?.id) && Boolean(lead?.lead_id || lead?.canal);
}

export default function LeadsPage() {
  const [leads, setLeads] = useState<any[]>([]);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<FilterKey>("all");
  const [personaFilterId, setPersonaFilterId] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setPersonaFilterId(window.localStorage.getItem("ai-brain-persona-id") || "");
    const onPersonaChange = (event: Event) => {
      const detail = (event as CustomEvent<{ id?: string }>).detail;
      setPersonaFilterId(detail?.id || window.localStorage.getItem("ai-brain-persona-id") || "");
    };
    window.addEventListener("ai-brain-persona-change", onPersonaChange);
    return () => window.removeEventListener("ai-brain-persona-change", onPersonaChange);
  }, []);

  useEffect(() => {
    setLoading(true);
    api.leads(200, 0, personaFilterId || undefined)
      .then((list) => setLeads(Array.isArray(list) ? list : []))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [personaFilterId]);

  const counts = useMemo(() => {
    const c = { all: leads.length, crm: 0, csv_bulk: 0 };
    for (const lead of leads) {
      const o = originOf(lead);
      c[o] += 1;
    }
    return c;
  }, [leads]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return leads.filter((lead) => {
      if (filter !== "all" && originOf(lead) !== filter) return false;
      if (!q) return true;
      const hay = [lead.nome, lead.lead_id, lead.email, lead.interesse_produto]
        .filter(Boolean)
        .map((v: string) => String(v).toLowerCase())
        .join(" ");
      return hay.includes(q);
    });
  }, [leads, search, filter]);

  return (
    <div className="lg-page-narrow flex flex-col gap-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-obs-violet/10 text-obs-violet [border:1px_solid_var(--border-glass)]">
            <Users size={16} />
          </span>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">CRM</p>
            <h1 className="mt-1 text-xl font-semibold text-obs-text">Leads</h1>
            <p className="mt-0.5 text-xs text-obs-subtle">
              Todos os contatos consolidados do CRM e importacoes CSV.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-obs-subtle">{filtered.length} leads</span>
          <Link
            href="/leads/import"
            className="lg-btn lg-btn-secondary"
            title="Importar CSV"
          >
            <Upload size={13} /> Importar CSV
          </Link>
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        <FilterPill active={filter === "all"} onClick={() => setFilter("all")} count={counts.all}>
          Todos
        </FilterPill>
        <FilterPill active={filter === "crm"} onClick={() => setFilter("crm")} count={counts.crm}>
          CRM
        </FilterPill>
        <FilterPill active={filter === "csv_bulk"} onClick={() => setFilter("csv_bulk")} count={counts.csv_bulk}>
          CSV/Bulk
        </FilterPill>

        <div className="relative ml-auto w-full max-w-xs">
          <Search size={13} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-obs-faint" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar por nome, telefone, email..."
            className="lg-search w-full pl-8 text-sm"
          />
        </div>
      </div>

      <div className="lg-table-shell">
        <table className="lg-table">
          <thead>
            <tr>
              <th>Lead</th>
              <th>Stage</th>
              <th>Produto</th>
              <th>Canal</th>
              <th>Origem</th>
              <th>Ultima mensagem</th>
              <th className="text-right">Acao</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={7} className="text-center text-obs-faint">Carregando leads...</td>
              </tr>
            )}
            {!loading && !filtered.length && (
              <tr>
                <td colSpan={7} className="text-center text-obs-faint">
                  {search || filter !== "all"
                    ? "Nenhum lead corresponde aos filtros."
                    : "Nenhum lead encontrado para esta persona."}
                </td>
              </tr>
            )}
            {filtered.map((lead) => {
              const origin = originOf(lead);
              const phone = lead.lead_id || "";
              const canStart = canStartConversation(lead);
              return (
                <tr key={lead.id || phone}>
                  <td>
                    <div className="flex flex-col">
                      <Link
                        href={`/messages/${lead.id}`}
                        className="font-medium text-obs-text hover:text-obs-violet"
                      >
                        {lead.nome || phone || "—"}
                      </Link>
                      {phone && (
                        <span className="font-mono text-[11px] text-obs-faint">{phone}</span>
                      )}
                    </div>
                  </td>
                  <td className={STAGE_COLOR[lead.stage] || "text-obs-text"}>
                    {STAGE_LABEL[lead.stage] || lead.stage || "Novo"}
                  </td>
                  <td className="text-obs-subtle lg-cell-truncate">{lead.interesse_produto || "—"}</td>
                  <td className="text-obs-subtle">{lead.canal || "whatsapp"}</td>
                  <td>
                    <OriginBadge origin={origin} />
                  </td>
                  <td className="lg-cell-truncate text-xs text-obs-subtle">
                    {lead.ultima_mensagem || "—"}
                  </td>
                  <td className="text-right">
                    {canStart ? (
                      <Link
                        href={`/messages/${lead.id}`}
                        className="lg-btn lg-btn-primary"
                        title="Iniciar conversa"
                      >
                        <MessageSquare size={12} /> Iniciar conversa
                      </Link>
                    ) : (
                      <span
                        aria-disabled
                        className="lg-btn lg-btn-secondary opacity-50"
                        title="Sem canal valido"
                      >
                        <MessageSquare size={12} /> Sem canal
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FilterPill({
  active,
  count,
  onClick,
  children,
}: {
  active: boolean;
  count?: number;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`lg-btn ${active ? "lg-btn-primary" : "lg-btn-secondary"}`}
    >
      {children}
      {typeof count === "number" && (
        <span className={`ml-1 text-[10px] ${active ? "opacity-80" : "text-obs-faint"}`}>
          {count}
        </span>
      )}
    </button>
  );
}

function OriginBadge({ origin }: { origin: LeadOrigin }) {
  if (origin === "csv_bulk") {
    return <span className="lg-badge lg-badge-info">Import</span>;
  }
  return <span className="lg-badge">CRM</span>;
}
