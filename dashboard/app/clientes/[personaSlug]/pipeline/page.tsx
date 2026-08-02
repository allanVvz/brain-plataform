"use client";

import { CalendarCheck2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { usePortal } from "../PortalContext";

export default function ClientPipelinePage() {
  const { personaSlug } = usePortal();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api.portalPipeline(personaSlug)
      .then((result) => active && setData(result))
      .catch((reason: any) => active && setError(reason?.message || "Não foi possível carregar o pipeline."));
    return () => {
      active = false;
    };
  }, [personaSlug]);

  return (
    <div className="space-y-5">
      {error && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}
      {!data && !error ? (
        <div className="rounded-2xl border border-slate-200 bg-white p-10 text-center text-sm text-slate-500 shadow-sm">
          Carregando pipeline…
        </div>
      ) : data && (
        <>
          <section className="grid gap-3 sm:grid-cols-3">
            {[
              ["Total de leads", data.summary?.total || 0],
              ["Em andamento", data.summary?.open || 0],
              [data.business_model === "appointment" ? "Agendados" : "Convertidos", data.summary?.converted || 0],
            ].map(([label, value]) => (
              <div key={String(label)} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
                <p className="mt-2 text-3xl font-semibold text-slate-950">{value}</p>
              </div>
            ))}
          </section>
          <section className="flex snap-x gap-4 overflow-x-auto pb-3">
            {(data.stages || []).map((stage: any) => (
              <div key={stage.id} className="w-[280px] shrink-0 snap-start rounded-2xl border border-slate-200 bg-slate-100/70 p-3">
                <div className="mb-3 flex items-center justify-between px-1">
                  <h2 className="text-sm font-semibold text-slate-800">{stage.label}</h2>
                  <span className="rounded-full bg-white px-2 py-0.5 text-xs text-slate-500 shadow-sm">{stage.leads.length}</span>
                </div>
                <div className="space-y-2">
                  {stage.leads.length === 0 ? (
                    <div className="rounded-xl border border-dashed border-slate-300 p-5 text-center text-xs text-slate-500">
                      Nenhum lead nesta etapa
                    </div>
                  ) : stage.leads.map((lead: any) => (
                    <article key={lead.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                      <p className="font-medium text-slate-900">{lead.nome || lead.telefone || `Lead #${lead.id}`}</p>
                      <p className="mt-1 text-xs text-slate-500">{lead.interesse_produto || "Interesse em qualificação"}</p>
                      {stage.id === data.summary?.conversion_stage && data.business_model === "appointment" && (
                        <p className="mt-3 flex items-center gap-1.5 text-xs font-medium text-emerald-700">
                          <CalendarCheck2 size={14} /> Agendamento confirmado
                        </p>
                      )}
                    </article>
                  ))}
                </div>
              </div>
            ))}
          </section>
        </>
      )}
    </div>
  );
}
