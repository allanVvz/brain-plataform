"use client";
import { useEffect, useState } from "react";
import { createClient } from "@/utils/supabase/client";
import { formatDistanceToNow } from "date-fns";
import { ptBR } from "date-fns/locale";

interface FeedItem {
  id: string;
  lead_id?: string;
  agent_name?: string;
  status: string;
  latency_ms?: number;
  created_at: string;
}

export function LiveFeed() {
  const [items, setItems] = useState<FeedItem[]>([]);

  useEffect(() => {
    const supabase = createClient();

    // initial load
    supabase
      .from("agent_logs")
      .select("id,lead_id,agent_name,status,latency_ms,created_at")
      .order("created_at", { ascending: false })
      .limit(20)
      .then(({ data }) => data && setItems(data));

    // realtime subscription
    const channel = supabase
      .channel("agent_logs_live")
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "agent_logs" },
        (payload) => {
          setItems((prev) => [payload.new as FeedItem, ...prev.slice(0, 19)]);
        }
      )
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, []);

  return (
    <div className="bg-brain-surface border border-brain-border rounded-xl overflow-hidden">
      <div className="px-4 py-2 border-b border-brain-border flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
        <span className="text-xs text-brain-muted">live</span>
      </div>
      <div className="divide-y divide-brain-border max-h-80 overflow-y-auto">
        {items.length === 0 && (
          <p className="text-brain-muted text-sm p-4">Aguardando eventos...</p>
        )}
        {items.map((item) => (
          <div key={item.id} className="px-4 py-2.5 flex items-center gap-3 text-xs">
            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${item.status === "success" ? "bg-green-400" : "bg-red-400"}`} />
            <span className="text-brain-muted font-mono">{item.lead_id?.slice(-8) || "—"}</span>
            <span className="text-white font-medium">{item.agent_name}</span>
            {item.latency_ms && (
              <span className="text-brain-muted ml-auto">{(item.latency_ms / 1000).toFixed(1)}s</span>
            )}
            <span className="text-brain-muted shrink-0">
              {formatDistanceToNow(new Date(item.created_at), { addSuffix: true, locale: ptBR })}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
