"use client";

import { Database, Network, Sparkles } from "lucide-react";
import { KnowledgeFlow } from "@/components/dashboard/KnowledgeFlow";

interface KnowledgeDashboardTabProps {
  leads: any[];
  knowledgeCounts: any;
  pipelineMetrics: any;
}

function getKnowledgeStats(knowledgeCounts: any, leads: any[], pipelineMetrics: any) {
  const byStatus = knowledgeCounts?.by_status || {};
  const byType = knowledgeCounts?.by_type || {};
  const total = Number(knowledgeCounts?.total || 0);
  const validated =
    Number(byStatus.validated || 0) +
    Number(byStatus.approved || 0) +
    Number(byStatus.embedded || 0) +
    Number(byStatus.ATIVO || 0);

  return {
    totalKnowledgeItems: total,
    validatedKnowledgeItems: validated,
    crmInferencesCount: Number(pipelineMetrics?.crm_inferences_count || leads.length || 0),
    makerInferencesCount: Number(
      pipelineMetrics?.maker_inferences_count ||
        byType.asset ||
        byType.maker_material ||
        0,
    ),
  };
}

export function KnowledgeDashboardTab({
  leads,
  knowledgeCounts,
  pipelineMetrics,
}: KnowledgeDashboardTabProps) {
  const stats = getKnowledgeStats(knowledgeCounts, leads, pipelineMetrics);
  const validationRate = stats.totalKnowledgeItems
    ? Math.round((stats.validatedKnowledgeItems / stats.totalKnowledgeItems) * 100)
    : 0;

  return (
    <section className="space-y-6 animate-fade-in">
      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-xl border border-white/06 bg-white/[0.035] p-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.16em] text-obs-faint">
            <Database size={14} />
            Knowledge Items
          </div>
          <p className="mt-3 text-3xl font-semibold text-white">{stats.totalKnowledgeItems}</p>
        </div>
        <div className="rounded-xl border border-white/06 bg-white/[0.035] p-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.16em] text-obs-faint">
            <Network size={14} />
            Validados
          </div>
          <p className="mt-3 text-3xl font-semibold text-emerald-300">{validationRate}%</p>
        </div>
        <div className="rounded-xl border border-white/06 bg-white/[0.035] p-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.16em] text-obs-faint">
            <Sparkles size={14} />
            Inferencias
          </div>
          <p className="mt-3 text-3xl font-semibold text-obs-violet">
            {stats.crmInferencesCount + stats.makerInferencesCount}
          </p>
        </div>
      </div>

      <KnowledgeFlow {...stats} />
    </section>
  );
}
