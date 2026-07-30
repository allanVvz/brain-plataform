"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, MessageSquare, Plus, Search, Share2, Upload, Users } from "lucide-react";
import { api } from "@/lib/api";
import { AudiencePill } from "@/components/leads/AudiencePill";
import { CreateAudiencePrompt } from "@/components/leads/CreateAudiencePrompt";
import { MoveShareModal, MoveShareMode } from "@/components/leads/MoveShareModal";
import { ALL_AUDIENCE_KEY, buildLeadsFilters } from "@/lib/leads";

type Audience = {
  id: string;
  slug: string;
  name: string;
  persona_id: string;
  is_system?: boolean;
  source_type?: string;
};

type Membership = {
  id?: string;
  audience_id?: string;
  membership_type?: string;
  audience?: Audience;
};

type Lead = any;

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

const ALL_KEY = ALL_AUDIENCE_KEY;

function canStartConversation(lead: Lead): boolean {
  return Boolean(lead?.id) && Boolean(lead?.lead_id || lead?.telefone);
}

function leadAudiences(lead: Lead): Audience[] {
  const list = (lead?.memberships as Membership[] | undefined) || [];
  return list
    .map((m) => m.audience)
    .filter((a): a is Audience => Boolean(a));
}

function primaryAudienceLabel(lead: Lead, fallback: string): string {
  const list = (lead?.memberships as Membership[] | undefined) || [];
  const primary = list.find((m) => m.membership_type === "primary") || list[0];
  if (primary?.audience?.name) return primary.audience.name;
  const canal = String(lead?.canal || "").toLowerCase();
  const origem = String(lead?.origem || "").toLowerCase();
  if (canal === "bulk_import" || origem === "bulk_import") return "Import";
  return fallback;
}

function LeadsPageInner() {
  const router = useRouter();
  const pathname = usePathname();
  const portalMatch = pathname.match(/^\/clientes\/([^/]+)/);
  const leadsBase = portalMatch ? `/clientes/${portalMatch[1]}/leads` : "/leads";
  const messagesBase = portalMatch ? `/clientes/${portalMatch[1]}/mensagens` : "/messages";
  const searchParams = useSearchParams();
  const audienceParam = searchParams.get("audience") || ALL_KEY;

  const [personaId, setPersonaId] = useState("");
  const [personaSlug, setPersonaSlug] = useState("");
  const [audiences, setAudiences] = useState<Audience[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [search, setSearch] = useState("");
  const [listMode, setListMode] = useState<"clients" | "validations">("clients");
  const [loading, setLoading] = useState(true);
  const [creatingAudience, setCreatingAudience] = useState(false);
  const [moveShare, setMoveShare] = useState<{ lead: Lead; mode: MoveShareMode } | null>(null);

  // Read persona from header global state
  useEffect(() => {
    const sync = () => {
      setPersonaId(window.localStorage.getItem("ai-brain-persona-id") || "");
      setPersonaSlug(window.localStorage.getItem("ai-brain-persona-slug") || "");
    };
    sync();
    window.addEventListener("ai-brain-persona-change", sync);
    return () => window.removeEventListener("ai-brain-persona-change", sync);
  }, []);

  const loadAudiences = useCallback(() => {
    if (!personaId) {
      setAudiences([]);
      return;
    }
    api.audiences(personaId)
      .then((rows) => setAudiences((rows || []) as Audience[]))
      .catch(() => setAudiences([]));
  }, [personaId]);

  useEffect(() => {
    loadAudiences();
  }, [loadAudiences]);

  const activeAudience = useMemo(() => {
    if (audienceParam === ALL_KEY) return null;
    return audiences.find((a) => a.slug === audienceParam) || null;
  }, [audiences, audienceParam]);

  const loadLeads = useCallback(async () => {
    setLoading(true);
    try {
      const baseRows = (await api.leadsScoped({
        personaId: personaId || undefined,
        personaSlug: personaSlug || undefined,
        audienceSlug: activeAudience?.slug,
        limit: 500,
      })) as Lead[];

      // Hydrate memberships in parallel (best effort)
      const enriched = await Promise.all(
        (baseRows || []).map(async (lead) => {
          if (!lead?.id) return lead;
          try {
            const m = await api.leadMemberships(lead.id);
            return { ...lead, memberships: m?.memberships || [] };
          } catch {
            return { ...lead, memberships: [] };
          }
        }),
      );
      setLeads(enriched);
    } catch (error) {
      console.error(error);
      setLeads([]);
    } finally {
      setLoading(false);
    }
  }, [personaId, personaSlug, activeAudience?.slug]);

  useEffect(() => {
    loadLeads();
  }, [loadLeads, personaId, personaSlug]);

  const filteredLeads = useMemo(() => {
    const q = search.trim().toLowerCase();
    return leads.filter((lead) => {
      const isValidation = Boolean(lead.validation?.is_validation);
      if (listMode === "validations" ? !isValidation : isValidation) return false;
      if (!q) return true;
      const hay = [lead.nome, lead.lead_id, lead.email, lead.telefone, lead.interesse_produto]
        .filter(Boolean)
        .map((v: string) => String(v).toLowerCase())
        .join(" ");
      return hay.includes(q);
    });
  }, [leads, listMode, search]);

  const audienceCounts = useMemo(() => {
    const counts: Record<string, number> = { [ALL_KEY]: leads.length };
    for (const lead of leads) {
      for (const audience of leadAudiences(lead)) {
        counts[audience.slug] = (counts[audience.slug] || 0) + 1;
      }
    }
    return counts;
  }, [leads]);

  const setAudienceParam = (slug: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (slug === ALL_KEY) params.delete("audience");
    else params.set("audience", slug);
    router.replace(`${leadsBase}${params.toString() ? `?${params}` : ""}`);
  };

  const renameAudience = async (audience: Audience, nextName: string) => {
    try {
      const result = await api.updateAudience(audience.id, { name: nextName });
      const updated = (result?.audience || result) as Audience;
      setAudiences((prev) => prev.map((a) => (a.id === audience.id ? { ...a, ...updated } : a)));
      if (activeAudience?.id === audience.id && updated.slug && updated.slug !== audience.slug) {
        setAudienceParam(updated.slug);
      }
    } catch (e: any) {
      console.error(e);
      alert(e?.message || "Falha ao renomear audiencia.");
    }
  };

  const onAudienceCreated = async (audience: Audience) => {
    setAudiences((prev) => {
      const without = prev.filter((a) => a.id !== audience.id);
      return [...without, audience].sort((a, b) => {
        if (a.is_system && !b.is_system) return -1;
        if (!a.is_system && b.is_system) return 1;
        return a.name.localeCompare(b.name);
      });
    });
    setAudienceParam(audience.slug);
  };

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
              Lead canonico por contato. Audiencias agrupam por persona; um mesmo lead pode estar em mais de uma audiencia via &quot;Compartilhar&quot;.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-obs-subtle">{filteredLeads.length} leads</span>
          <Link href="/leads/import" className="lg-btn lg-btn-secondary" title="Importar CSV">
            <Upload size={13} /> Importar CSV
          </Link>
        </div>
      </header>

      <>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex rounded-lg border border-white/06 bg-obs-base p-1">
              <button type="button" onClick={() => setListMode("clients")} className={`rounded-md px-3 py-1.5 text-xs ${listMode === "clients" ? "bg-white/10 text-obs-text" : "text-obs-faint"}`}>
                Clientes reais
              </button>
              <button type="button" onClick={() => setListMode("validations")} className={`rounded-md px-3 py-1.5 text-xs ${listMode === "validations" ? "bg-white/10 text-obs-text" : "text-obs-faint"}`}>
                Validações
              </button>
            </div>
            {personaId && buildLeadsFilters(audiences).map((f) => {
              const backing = f.isAll ? null : audiences.find((a) => a.slug === f.slug);
              const canRename = Boolean(backing && !(backing as any).from_graph_node);
              return (
                <AudiencePill
                  key={f.key}
                  data={{
                    id: backing?.id,
                    slug: f.slug,
                    name: f.name,
                    count: audienceCounts[f.slug] || 0,
                    isSystem: f.isSystem,
                  }}
                  active={audienceParam === f.slug}
                  onActivate={() => setAudienceParam(f.slug)}
                  onRename={canRename ? (next) => renameAudience(backing!, next) : undefined}
                />
              );
            })}
            {personaId && <button
              type="button"
              onClick={() => setCreatingAudience(true)}
              className="lg-btn lg-btn-secondary"
              title="Criar audiencia"
            >
              <Plus size={12} /> Nova
            </button>}

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
                  <th>Score</th>
                  <th>Produto</th>
                  <th>Origem</th>
                  <th>Ultima mensagem</th>
                  <th className="text-right">Acoes</th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr>
                    <td colSpan={7} className="text-center text-obs-faint">Carregando leads...</td>
                  </tr>
                )}
                {!loading && !filteredLeads.length && (
                  <tr>
                    <td colSpan={7} className="text-center text-obs-faint">
                      {search
                        ? "Nenhum lead corresponde a busca."
                        : activeAudience
                        ? `Nenhum lead na audiencia "${activeAudience.name}".`
                        : listMode === "validations"
                        ? "Nenhuma validação neste escopo."
                        : "Nenhum cliente real encontrado no escopo autorizado."}
                    </td>
                  </tr>
                )}
                {filteredLeads.map((lead) => {
                  const phone = lead.lead_id || lead.telefone || "";
                  const canStart = canStartConversation(lead);
                  const memberships = (lead.memberships || []) as Membership[];
                  const primaryName = primaryAudienceLabel(lead, "CRM");
                  const sharedNames = memberships
                    .filter((m) => m.membership_type === "shared")
                    .map((m) => m.audience?.name)
                    .filter(Boolean) as string[];
                  return (
                    <tr key={lead.id || phone}>
                      <td>
                        <div className="flex flex-col">
                          <Link
                            href={`${messagesBase}/${lead.id}`}
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
                      <td>
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-obs-text">{lead.qualification_score || 0}</span>
                          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-white/5">
                            <div className="h-full bg-obs-violet" style={{ width: `${Math.min(100, Number(lead.qualification_score || 0))}%` }} />
                          </div>
                        </div>
                        {lead.qualification_signals?.length > 0 && (
                          <p className="mt-1 max-w-40 truncate text-[9px] text-obs-faint">
                            {lead.qualification_signals.map((signal: any) => signal.label || signal.key).join(", ")}
                          </p>
                        )}
                      </td>
                      <td className="text-obs-subtle lg-cell-truncate">{lead.interesse_produto || "—"}</td>
                      <td>
                        <div className="flex flex-wrap items-center gap-1">
                          <span className="lg-badge">{primaryName}</span>
                          {sharedNames.map((n) => (
                            <span key={n} className="lg-badge lg-badge-info">+{n}</span>
                          ))}
                        </div>
                      </td>
                      <td className="lg-cell-truncate text-xs text-obs-subtle">
                        {lead.ultima_mensagem || "—"}
                      </td>
                      <td>
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            type="button"
                            onClick={() => setMoveShare({ lead, mode: "move" })}
                            className="lg-btn lg-btn-secondary"
                            title="Mover para outra audiencia"
                          >
                            <ArrowRight size={12} /> Mover
                          </button>
                          <button
                            type="button"
                            onClick={() => setMoveShare({ lead, mode: "share" })}
                            className="lg-btn lg-btn-secondary"
                            title="Compartilhar em outra audiencia"
                          >
                            <Share2 size={12} /> Compartilhar
                          </button>
                          {canStart ? (
                            <Link
                              href={`${messagesBase}/${lead.id}`}
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
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>

      {creatingAudience && personaId && (
        <CreateAudiencePrompt
          personaId={personaId}
          onClose={() => setCreatingAudience(false)}
          onCreated={onAudienceCreated}
        />
      )}

      {moveShare && (
        <MoveShareModal
          leadRef={Number(moveShare.lead.id)}
          leadName={moveShare.lead.nome || moveShare.lead.lead_id || `Lead #${moveShare.lead.id}`}
          initialMode={moveShare.mode}
          currentPersonaId={personaId || moveShare.lead.persona_id || null}
          currentMemberships={(moveShare.lead.memberships || []) as Membership[]}
          onClose={() => setMoveShare(null)}
          onDone={async () => {
            await Promise.all([loadAudiences(), loadLeads()]);
          }}
        />
      )}
    </div>
  );
}

export default function LeadsPage() {
  return (
    <Suspense fallback={<div className="lg-page-narrow text-sm text-obs-faint">Carregando leads...</div>}>
      <LeadsPageInner />
    </Suspense>
  );
}
