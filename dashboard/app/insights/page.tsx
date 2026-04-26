"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { InsightCard } from "@/components/InsightCard";
import { HealthScore } from "@/components/HealthScore";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

export default function InsightsPage() {
  const [insights, setInsights] = useState<any[]>([]);
  const [filter, setFilter] = useState("open");
  const [health, setHealth] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [running, setRunning] = useState(false);

  async function load() {
    const [ins, h, hist] = await Promise.all([
      api.insights(filter || undefined),
      api.health(),
      api.healthHistory(14),
    ]);
    setInsights(ins);
    setHealth(h);
    setHistory(hist.map((s: any) => ({ date: s.snapshot_at?.slice(5, 10), score: s.score_total })));
  }

  useEffect(() => { load(); }, [filter]);

  async function triggerValidator() {
    setRunning(true);
    await api.runValidator().catch(console.error);
    await load();
    setRunning(false);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Insights</h1>
        <button onClick={triggerValidator} disabled={running}
          className="text-sm bg-brain-accent hover:bg-brain-accent/80 disabled:opacity-50 px-4 py-1.5 rounded-md">
          {running ? "Analisando..." : "Analisar agora"}
        </button>
      </div>

      {health && <HealthScore data={health} />}

      {history.length > 1 && (
        <div className="bg-brain-surface border border-brain-border rounded-xl p-4">
          <p className="text-xs text-brain-muted mb-3 uppercase tracking-wide">Evolução do score</p>
          <ResponsiveContainer width="100%" height={120}>
            <LineChart data={history}>
              <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#6b7280" }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "#6b7280" }} />
              <Tooltip contentStyle={{ background: "#1a1d27", border: "1px solid #2a2d3a", borderRadius: 6 }} />
              <Line type="monotone" dataKey="score" stroke="#6366f1" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Filtros */}
      <div className="flex gap-2">
        {["open", "acknowledged", "resolved", ""].map((s) => (
          <button key={s} onClick={() => setFilter(s)}
            className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${filter === s ? "bg-brain-accent/20 border-brain-accent text-brain-accent" : "border-brain-border text-brain-muted hover:text-white"}`}>
            {s || "Todos"}
          </button>
        ))}
      </div>

      <div className="space-y-3">
        {insights.length === 0 && <p className="text-brain-muted text-sm">Nenhum insight neste filtro.</p>}
        {insights.map((i) => <InsightCard key={i.id} insight={i} onUpdate={load} />)}
      </div>
    </div>
  );
}
