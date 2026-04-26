"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { formatDistanceToNow } from "date-fns";
import { ptBR } from "date-fns/locale";

export default function MessageTimelinePage({ params }: { params: { leadId: string } }) {
  const [messages, setMessages] = useState<any[]>([]);
  const [logs, setLogs] = useState<any[]>([]);

  useEffect(() => {
    api.messages(params.leadId).then(setMessages).catch(console.error);
    api.agentLogs(params.leadId, 20).then(setLogs).catch(console.error);
  }, [params.leadId]);

  const logsByTime = Object.fromEntries(
    logs.map((l) => [l.created_at?.slice(0, 19), l])
  );

  return (
    <div className="max-w-2xl space-y-4">
      <h1 className="text-xl font-semibold">Timeline — {params.leadId}</h1>

      <div className="space-y-3">
        {messages.map((msg) => {
          const isLead = msg.sender_type === "lead" || msg.direction === "inbound";
          const log = logsByTime[msg.created_at?.slice(0, 19)];

          return (
            <div key={msg.id || msg.message_id} className={`flex flex-col gap-1 ${isLead ? "items-start" : "items-end"}`}>
              <div className={`max-w-[80%] rounded-xl px-4 py-2.5 text-sm ${
                isLead
                  ? "bg-brain-surface border border-brain-border text-white"
                  : "bg-brain-accent/20 border border-brain-accent/30 text-white"
              }`}>
                <p className="text-xs font-medium mb-1 text-brain-muted">
                  {isLead ? "Cliente" : `${msg.agent_name || msg.sender_type || "IA"}`}
                </p>
                {msg.texto}
              </div>

              {log && !isLead && (
                <div className="text-xs text-brain-muted space-y-0.5 px-1 text-right">
                  <p>Classificação: <span className="text-white">{log.input?.route_hint}</span></p>
                  <p>Agente: <span className="text-white">{log.agent_name}</span> · {log.latency_ms}ms</p>
                </div>
              )}

              <span className="text-xs text-brain-muted px-1">
                {msg.created_at
                  ? formatDistanceToNow(new Date(msg.created_at), { addSuffix: true, locale: ptBR })
                  : ""}
              </span>
            </div>
          );
        })}

        {messages.length === 0 && (
          <p className="text-brain-muted text-sm">Nenhuma mensagem encontrada.</p>
        )}
      </div>
    </div>
  );
}
