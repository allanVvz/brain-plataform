"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { formatDistanceToNow } from "date-fns";
import { ptBR } from "date-fns/locale";

export default function LogsPage() {
  const [n8nLogs, setN8nLogs] = useState<any[]>([]);
  const [agentLogs, setAgentLogs] = useState<any[]>([]);
  const [tab, setTab] = useState<"n8n" | "agents">("n8n");

  useEffect(() => {
    api.n8nLogs(100).then(setN8nLogs).catch(console.error);
    api.agentLogs(undefined, 100).then(setAgentLogs).catch(console.error);
  }, []);

  const logs = tab === "n8n" ? n8nLogs : agentLogs;

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Logs</h1>

      <div className="flex gap-2">
        {(["n8n", "agents"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`text-sm px-4 py-1.5 rounded-md border transition-colors ${tab === t ? "bg-brain-accent/20 border-brain-accent text-brain-accent" : "border-brain-border text-brain-muted hover:text-white"}`}>
            {t === "n8n" ? "n8n Execuções" : "Agentes AI"}
          </button>
        ))}
      </div>

      <div className="bg-brain-surface border border-brain-border rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-brain-border text-brain-muted text-xs uppercase tracking-wide">
              <th className="px-4 py-3 text-left">Status</th>
              <th className="px-4 py-3 text-left">{tab === "n8n" ? "Workflow" : "Agente"}</th>
              <th className="px-4 py-3 text-left">Lead</th>
              <th className="px-4 py-3 text-left">Duração</th>
              <th className="px-4 py-3 text-left">Quando</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-brain-border">
            {logs.map((log) => {
              const isOk = log.status === "success" || log.status === "finished";
              const duration = tab === "n8n" ? log.duration_ms : log.latency_ms;
              const name = tab === "n8n" ? log.workflow_name : log.agent_name;
              const leadId = log.lead_id;
              const date = log.started_at || log.created_at;

              return (
                <tr key={log.id} className="hover:bg-white/5">
                  <td className="px-4 py-2.5">
                    <span className={`text-xs font-medium ${isOk ? "text-green-400" : "text-red-400"}`}>
                      {isOk ? "✓" : "✗"} {log.status}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-white">{name || "—"}</td>
                  <td className="px-4 py-2.5 text-brain-muted font-mono text-xs">{leadId?.slice(-8) || "—"}</td>
                  <td className="px-4 py-2.5 text-brain-muted text-xs">{duration ? `${(duration / 1000).toFixed(1)}s` : "—"}</td>
                  <td className="px-4 py-2.5 text-brain-muted text-xs">
                    {date ? formatDistanceToNow(new Date(date), { addSuffix: true, locale: ptBR }) : "—"}
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
