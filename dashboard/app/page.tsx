"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { HealthScore } from "@/components/HealthScore";
import { InsightCard } from "@/components/InsightCard";
import { LiveFeed } from "@/components/LiveFeed";

export default function DashboardPage() {
  const [health, setHealth] = useState<any>(null);
  const [insights, setInsights] = useState<any[]>([]);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    api.health().then(setHealth).catch(console.error);
    api.insights("open").then((d) => setInsights(d.slice(0, 5))).catch(console.error);
  }, []);

  async function triggerValidator() {
    setRunning(true);
    try {
      const result = await api.runValidator();
      setHealth(result);
      const fresh = await api.insights("open");
      setInsights(fresh.slice(0, 5));
    } catch (e) {
      console.error(e);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Dashboard</h1>
        <button
          onClick={triggerValidator}
          disabled={running}
          className="text-sm bg-brain-accent hover:bg-brain-accent/80 disabled:opacity-50 px-4 py-1.5 rounded-md transition-colors"
        >
          {running ? "Analisando..." : "Analisar agora"}
        </button>
      </div>

      {/* Health Score */}
      {health && <HealthScore data={health} />}

      <div className="grid grid-cols-2 gap-6">
        {/* Insights críticos */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium text-brain-muted uppercase tracking-wide">Insights recentes</h2>
            <a href="/insights" className="text-xs text-brain-accent hover:underline">Ver todos</a>
          </div>
          <div className="space-y-2">
            {insights.length === 0 && (
              <p className="text-brain-muted text-sm">Nenhum insight aberto.</p>
            )}
            {insights.map((i) => <InsightCard key={i.id} insight={i} />)}
          </div>
        </div>

        {/* Live feed */}
        <div>
          <h2 className="text-sm font-medium text-brain-muted uppercase tracking-wide mb-3">Atividade em tempo real</h2>
          <LiveFeed />
        </div>
      </div>
    </div>
  );
}
