"use client";
import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { api } from "@/lib/api";
import { RefreshCw, Filter } from "lucide-react";
import NodeDrawer from "@/components/graph/NodeDrawer";

const GraphView = dynamic(() => import("@/components/graph/GraphView"), { ssr: false });

export default function GraphPage() {
  const [personas, setPersonas] = useState<any[]>([]);
  const [selectedPersona, setSelectedPersona] = useState("");
  const [data, setData] = useState<{ nodes: any[]; edges: any[]; meta?: any } | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState<any>(null);

  async function load(slug = "") {
    setLoading(true);
    try {
      const d = await api.graphData(slug || undefined);
      setData(d);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    api.personas().then((p) => {
      setPersonas(p);
      load();
    });
  }, []);

  return (
    <div className="flex flex-col h-[calc(100vh-96px)] -mx-6 -mt-6 overflow-hidden">
      {/* Top bar */}
      <div className="flex items-center gap-3 px-6 py-3 border-b border-white/06 glass shrink-0">
        <span className="text-sm font-semibold text-obs-text">Grafo de Conhecimento</span>

        <div className="flex items-center gap-2 ml-auto">
          {data?.meta && (
            <span className="text-[11px] text-obs-subtle">
              {data.meta.total_personas} personas ·{" "}
              {data.meta.kb_entries ?? 0} KB ·{" "}
              {data.meta.ki_items ?? 0} queue
            </span>
          )}

          <div className="flex items-center gap-1.5 bg-obs-base border border-white/06 rounded-lg px-2 py-1">
            <Filter size={11} className="text-obs-subtle" />
            <select
              value={selectedPersona}
              onChange={(e) => { setSelectedPersona(e.target.value); load(e.target.value); }}
              className="bg-transparent text-xs text-obs-text focus:outline-none pr-1"
            >
              <option value="">Todos os clientes</option>
              {personas.map((p) => (
                <option key={p.slug} value={p.slug}>{p.name}</option>
              ))}
            </select>
          </div>

          <button
            onClick={() => load(selectedPersona)}
            disabled={loading}
            className="p-1.5 rounded-lg glass border border-white/06 text-obs-subtle hover:text-obs-text transition-colors disabled:opacity-40"
          >
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 px-6 py-2 border-b border-white/04 shrink-0">
        <LegendDot color="bg-obs-violet" label="Persona" />
        <LegendDot color="bg-obs-amber/60 rounded-sm" label="Galho (tipo)" shape="square" />
        <LegendDot color="bg-obs-slate" label="Validado" />
        <LegendDot color="bg-obs-amber" label="Pendente" />
        <LegendDot color="bg-obs-rose" label="Rejeitado" />
      </div>

      {/* Graph canvas */}
      <div className="flex-1 relative overflow-hidden">
        {loading && !data && (
          <div className="absolute inset-0 flex items-center justify-center text-obs-subtle text-sm">
            Carregando grafo...
          </div>
        )}

        {data && (
          <GraphView
            rawNodes={data.nodes}
            rawEdges={data.edges}
            onNodeClick={setSelectedNode}
          />
        )}

        {/* Drawer overlay */}
        <NodeDrawer
          node={selectedNode}
          onClose={() => setSelectedNode(null)}
          onUpdated={() => load(selectedPersona)}
        />
      </div>
    </div>
  );
}

function LegendDot({ color, label, shape }: { color: string; label: string; shape?: "square" }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className={`w-2 h-2 ${shape === "square" ? "rounded-sm" : "rounded-full"} ${color}`} />
      <span className="text-[10px] text-obs-subtle">{label}</span>
    </div>
  );
}
