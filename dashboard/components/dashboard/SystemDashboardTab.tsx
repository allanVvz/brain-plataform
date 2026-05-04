"use client";

import { AlertTriangle, CheckCircle2, Gauge, RefreshCw } from "lucide-react";
import { HealthScore } from "@/components/HealthScore";
import { InsightCard } from "@/components/InsightCard";
import { LiveFeed } from "@/components/LiveFeed";

interface SystemDashboardTabProps {
  health: any;
  insights: any[];
  running: boolean;
  onRunValidator: () => void;
}

function MetricCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string | number;
  tone: "green" | "amber" | "rose" | "violet";
}) {
  const colors = {
    green: "text-emerald-300 bg-emerald-500/10 border-emerald-400/20",
    amber: "text-amber-300 bg-amber-500/10 border-amber-400/20",
    rose: "text-rose-300 bg-rose-500/10 border-rose-400/20",
    violet: "text-obs-violet bg-obs-violet/10 border-obs-violet/25",
  };

  return (
    <div className={`rounded-lg border px-4 py-3 ${colors[tone]}`}>
      <p className="text-[10px] uppercase tracking-[0.16em] opacity-70">{label}</p>
      <p className="mt-2 text-2xl font-semibold">{value}</p>
    </div>
  );
}

export function SystemDashboardTab({
  health,
  insights,
  running,
  onRunValidator,
}: SystemDashboardTabProps) {
  const critical = health?.open_critical ?? 0;
  const warnings = health?.open_warnings ?? 0;
  const score = health?.score_total ?? 0;

  return (
    <section className="space-y-6 animate-fade-in">
      <div className="grid gap-3 md:grid-cols-4">
        <MetricCard label="Score geral" value={score || "--"} tone="violet" />
        <MetricCard label="Criticos" value={critical} tone={critical > 0 ? "rose" : "green"} />
        <MetricCard label="Avisos" value={warnings} tone={warnings > 0 ? "amber" : "green"} />
        <MetricCard label="Insights abertos" value={insights.length} tone={insights.length ? "amber" : "green"} />
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]">
        <div className="space-y-6">
          <div className="flex flex-col gap-3 rounded-xl border border-white/06 bg-white/[0.03] p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-obs-violet/25 bg-obs-violet/10 text-obs-violet">
                <Gauge size={17} />
              </span>
              <div>
                <h2 className="text-sm font-semibold text-obs-text">Saude e qualidade</h2>
                <p className="text-xs text-obs-subtle">Performance, confiabilidade, arquitetura e impacto comercial.</p>
              </div>
            </div>
            <button
              type="button"
              onClick={onRunValidator}
              disabled={running}
              className="flex items-center justify-center gap-2 rounded-md border border-obs-violet/35 bg-obs-violet/15 px-3 py-2 text-xs font-medium text-obs-text transition hover:bg-obs-violet/25 disabled:opacity-50"
            >
              <RefreshCw size={13} className={running ? "animate-spin" : ""} />
              {running ? "Analisando" : "Analisar agora"}
            </button>
          </div>

          {health ? (
            <HealthScore data={health} />
          ) : (
            <div className="rounded-xl border border-white/06 bg-white/[0.03] p-8 text-sm text-obs-subtle">
              Carregando analise de saude...
            </div>
          )}

          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-xl border border-white/06 bg-white/[0.03] p-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-obs-text">
                <AlertTriangle size={15} className="text-amber-300" />
                Alertas criticos
              </div>
              <p className="mt-3 text-sm text-obs-subtle">
                {critical > 0
                  ? `${critical} alerta critico exige revisao operacional.`
                  : "Nenhum alerta critico aberto no momento."}
              </p>
            </div>
            <div className="rounded-xl border border-white/06 bg-white/[0.03] p-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-obs-text">
                <CheckCircle2 size={15} className="text-emerald-300" />
                Avisos
              </div>
              <p className="mt-3 text-sm text-obs-subtle">
                {warnings > 0
                  ? `${warnings} aviso em aberto para acompanhamento.`
                  : "Sem avisos pendentes."}
              </p>
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <div>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-xs font-semibold uppercase tracking-[0.18em] text-obs-faint">
                Insights recentes
              </h2>
              <a href="/insights" className="text-xs text-obs-violet hover:underline">
                Ver todos
              </a>
            </div>
            <div className="space-y-2">
              {insights.length === 0 && (
                <div className="rounded-xl border border-white/06 bg-white/[0.03] p-4 text-sm text-obs-subtle">
                  Nenhum insight aberto.
                </div>
              )}
              {insights.map((insight) => (
                <InsightCard key={insight.id} insight={insight} />
              ))}
            </div>
          </div>

          <div>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-[0.18em] text-obs-faint">
              Atividade em tempo real
            </h2>
            <LiveFeed />
          </div>
        </div>
      </div>
    </section>
  );
}
