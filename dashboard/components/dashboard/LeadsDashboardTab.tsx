"use client";

import { ArrowRight, TrendingUp, Users } from "lucide-react";

interface LeadsDashboardTabProps {
  leads: any[];
}

const funnelStages = [
  { key: "novo", label: "Novo", aliases: ["novo", "new", "nao qualificado"] },
  { key: "qualificado", label: "Qualificado", aliases: ["qualificado", "qualified", "interested"] },
  { key: "em_conversa", label: "Em Conversa", aliases: ["em conversa", "contatado", "engajado", "conversation", "conversando"] },
  { key: "proposta", label: "Proposta", aliases: ["proposta", "oportunidade", "proposal", "opportunity"] },
  { key: "fechado", label: "Fechado", aliases: ["fechado", "won", "closed"] },
  { key: "perdido", label: "Perdido", aliases: ["perdido", "lost"] },
];

function normalizeStage(stage: string | null | undefined) {
  const clean = (stage || "novo").toLowerCase().trim();
  return funnelStages.find((item) => item.aliases.includes(clean))?.key || "novo";
}

function pct(value: number, total: number) {
  if (!total) return 0;
  return Math.round((value / total) * 100);
}

export function LeadsDashboardTab({ leads }: LeadsDashboardTabProps) {
  const totalLeads = leads.length;
  const stageCounts = funnelStages.map((stage) => ({
    ...stage,
    count: leads.filter((lead) => normalizeStage(lead.stage) === stage.key).length,
  }));
  const won = stageCounts.find((stage) => stage.key === "fechado")?.count || 0;
  const open = totalLeads - (stageCounts.find((stage) => stage.key === "perdido")?.count || 0);

  return (
    <section className="space-y-6 animate-fade-in">
      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-xl border border-white/06 bg-white/[0.035] p-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.16em] text-obs-faint">
            <Users size={14} />
            Leads totais
          </div>
          <p className="mt-3 text-3xl font-semibold text-white">{totalLeads}</p>
        </div>
        <div className="rounded-xl border border-white/06 bg-white/[0.035] p-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.16em] text-obs-faint">
            <TrendingUp size={14} />
            Conversao final
          </div>
          <p className="mt-3 text-3xl font-semibold text-emerald-300">{pct(won, totalLeads)}%</p>
        </div>
        <div className="rounded-xl border border-white/06 bg-white/[0.035] p-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.16em] text-obs-faint">
            <ArrowRight size={14} />
            Em fluxo
          </div>
          <p className="mt-3 text-3xl font-semibold text-obs-violet">{open}</p>
        </div>
      </div>

      <div className="rounded-xl border border-white/06 bg-white/[0.025] p-5 lg:p-6">
        <div className="mb-6 flex flex-col gap-1">
          <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">
            Funil de conversao
          </p>
          <h2 className="text-lg font-semibold text-obs-text">Pipeline comercial</h2>
        </div>

        <div className="mx-auto flex max-w-5xl flex-col items-center gap-3">
          {stageCounts.map((stage, index) => {
            const width = Math.max(48, 100 - index * 9);
            const next = stageCounts[index + 1];
            const conversion = next && stage.count > 0 ? pct(next.count, stage.count) : null;
            const share = pct(stage.count, totalLeads);
            return (
              <div key={stage.key} className="w-full">
                <div
                  className="mx-auto rounded-lg border border-white/08 bg-gradient-to-r from-white/[0.04] via-white/[0.07] to-white/[0.04] px-4 py-4 shadow-obs-node"
                  style={{ width: `${width}%` }}
                >
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <p className="text-sm font-semibold text-white">{stage.label}</p>
                      <p className="mt-1 text-xs text-obs-subtle">{share}% do total</p>
                    </div>
                    <div className="flex items-center gap-4">
                      <div className="text-right">
                        <p className="text-2xl font-semibold text-white">{stage.count}</p>
                        <p className="text-[10px] uppercase tracking-[0.14em] text-obs-faint">leads</p>
                      </div>
                      {conversion !== null && (
                        <div className="hidden min-w-24 rounded-md border border-obs-violet/20 bg-obs-violet/10 px-3 py-2 text-right sm:block">
                          <p className="text-sm font-semibold text-obs-violet">{conversion}%</p>
                          <p className="text-[10px] text-obs-faint">para o proximo</p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
