"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import {
  RefreshCw,
  Filter,
  Search,
  Network,
  GitBranch,
  Tag as TagIcon,
  AtSign,
  Database,
  Crosshair,
} from "lucide-react";
import NodeDrawer from "@/components/graph/NodeDrawer";

const GraphView = dynamic(() => import("@/components/graph/GraphView"), { ssr: false });

type ViewMode = "layered" | "semantic_tree" | "graph";

interface RegistryNodeType {
  node_type: string;
  label?: string;
  level?: number;
  importance?: number;
  color?: string;
  icon?: string;
  sort_order?: number;
}

interface RegistryRelation {
  relation_type: string;
  label?: string;
  inverse_label?: string;
  weight?: number;
  directional?: boolean;
  tier?: "strong" | "structural" | "auxiliary" | "curation";
  sort_order?: number;
}

interface FocusInfo {
  node_id: string;
  node_type?: string;
  slug?: string;
  title?: string;
}

interface FocusPathStep {
  node_id: string;
  slug?: string;
  title?: string;
  node_type?: string;
  relation_type?: string | null;
  direction?: string | null;
}

interface GraphPayload {
  nodes: any[];
  edges: any[];
  meta: {
    total_personas?: number;
    total_items?: number;
    ki_items?: number;
    kb_entries?: number;
    semantic_nodes?: number;
    semantic_edges?: number;
    focus?: FocusInfo | null;
    focus_path?: FocusPathStep[];
    applied_filters?: Record<string, unknown>;
    registry?: {
      node_types?: RegistryNodeType[];
      relations?: RegistryRelation[];
    };
  };
}

const MODES: { value: ViewMode; label: string; icon: React.ReactNode; help: string }[] = [
  { value: "semantic_tree", label: "Árvore",    icon: <GitBranch size={11} />, help: "Hierarquia automatica por aresta principal" },
  { value: "graph",         label: "Grafo",     icon: <Network size={11} />,   help: "Rede organica estilo Obsidian/neural" },
];

const DEPTHS = [1, 2, 3, 4, 5];

export default function GraphPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [personas, setPersonas] = useState<any[]>([]);
  const [data, setData] = useState<GraphPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState<any>(null);
  const [searchQuery, setSearchQuery] = useState("");

  // ── URL-driven state ──────────────────────────────────────────
  const personaSlug = searchParams.get("persona") || "";
  const focus = searchParams.get("focus") || "";
  const maxDepth = Number(searchParams.get("depth") || 3);
  const mode = (searchParams.get("mode") as ViewMode) || "semantic_tree";
  const includeTags = searchParams.get("tags") === "1";
  const includeMentions = searchParams.get("mentions") === "1";
  const includeTechnical = searchParams.get("tech") === "1";
  const onlyPrimaryTreeEdges = searchParams.get("primary_edges") !== "0";

  const updateParam = useCallback(
    (patch: Record<string, string | number | boolean | null>) => {
      const next = new URLSearchParams(searchParams.toString());
      for (const [k, v] of Object.entries(patch)) {
        if (v === null || v === false || v === "") next.delete(k);
        else next.set(k, String(v));
      }
      router.replace(`/knowledge/graph${next.toString() ? `?${next}` : ""}`);
    },
    [router, searchParams],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api.graphData(personaSlug || undefined, {
        focus: focus || undefined,
        max_depth: maxDepth,
        include_tags: includeTags,
        include_mentions: includeMentions,
        include_technical: includeTechnical,
        mode,
      });
      setData(d as GraphPayload);
    } finally {
      setLoading(false);
    }
  }, [personaSlug, focus, maxDepth, includeTags, includeMentions, includeTechnical, mode]);

  useEffect(() => {
    api.personas().then((p) => setPersonas(p));
  }, []);

  useEffect(() => { load(); }, [load]);

  // Refresh node selection when payload changes (so drawer shows fresh data).
  useEffect(() => {
    if (!selectedNode || !data) return;
    const fresh = data.nodes.find((n) => n.id === selectedNode.id);
    if (fresh) setSelectedNode(fresh);
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  const focusNode = data?.meta?.focus || null;
  const focusPath = data?.meta?.focus_path || [];

  const onFocusNode = useCallback(
    (node: any) => {
      const data = node.data || {};
      const slug = data.slug;
      const ntype = data.node_type;
      if (slug && ntype) {
        updateParam({ focus: `${ntype}:${slug}` });
      } else if (node.id?.startsWith("gn:")) {
        updateParam({ focus: node.id.slice(3) });
      }
    },
    [updateParam],
  );

  const onClearFocus = useCallback(() => {
    updateParam({ focus: null });
  }, [updateParam]);

  return (
    <div className="flex flex-col h-[calc(100vh-96px)] -mx-6 -mt-6 overflow-hidden">
      {/* ── Top bar (3 rows) ──────────────────────────────────── */}
      <div className="px-6 py-2.5 border-b border-white/06 glass shrink-0 space-y-2">
        {/* Row 1: persona + mode + meta */}
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-obs-text">Grafo de Conhecimento</span>

          <div className="flex items-center gap-1.5 bg-obs-base border border-white/06 rounded-lg px-2 py-1">
            <Filter size={11} className="text-obs-subtle" />
            <select
              value={personaSlug}
              onChange={(e) => updateParam({ persona: e.target.value || null, focus: null })}
              className="bg-transparent text-xs text-obs-text focus:outline-none pr-1"
            >
              <option value="">Todos os clientes</option>
              {personas.map((p) => (
                <option key={p.slug} value={p.slug}>{p.name}</option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-1">
            {MODES.map((m) => (
              <button
                key={m.value}
                title={m.help}
                onClick={() => updateParam({ mode: m.value === "semantic_tree" ? null : m.value })}
                className={`flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border transition ${
                  mode === m.value
                    ? "bg-obs-violet/20 border-obs-violet text-obs-violet"
                    : "glass border-white/10 text-obs-subtle hover:text-obs-text"
                }`}
              >
                {m.icon}
                <span>{m.label}</span>
              </button>
            ))}
          </div>

          <div className="ml-auto flex items-center gap-3">
            {data?.meta && (
              <span className="text-[11px] text-obs-subtle">
                {data.nodes.length} nodes · {data.edges.length} edges
                {data.meta.semantic_nodes !== undefined && ` · ${data.meta.semantic_nodes} semânticos`}
              </span>
            )}
            <button
              onClick={load}
              disabled={loading}
              className="p-1.5 rounded-lg glass border border-white/06 text-obs-subtle hover:text-obs-text transition disabled:opacity-40"
            >
              <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
            </button>
          </div>
        </div>

        {/* Row 2: depth + visibility toggles */}
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] uppercase tracking-wider text-obs-faint">Profundidade</span>
            <div className="flex items-center gap-0.5">
              {DEPTHS.map((d) => (
                <button
                  key={d}
                  onClick={() => updateParam({ depth: d === 3 ? null : d })}
                  className={`w-6 h-6 text-[11px] rounded-md border transition ${
                    maxDepth === d
                      ? "bg-obs-violet/20 border-obs-violet text-obs-violet"
                      : "glass border-white/10 text-obs-subtle hover:text-obs-text"
                  }`}
                >
                  {d}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            <ToggleChip
              active={includeTags}
              onClick={() => updateParam({ tags: !includeTags ? "1" : null })}
              icon={<TagIcon size={10} />}
              label="Tags"
            />
            <ToggleChip
              active={includeMentions}
              onClick={() => updateParam({ mentions: !includeMentions ? "1" : null })}
              icon={<AtSign size={10} />}
              label="Mentions"
            />
            <ToggleChip
              active={includeTechnical}
              onClick={() => updateParam({ tech: !includeTechnical ? "1" : null })}
              icon={<Database size={10} />}
              label="Técnicos"
            />
          </div>

          {mode === "semantic_tree" && (
            <ToggleChip
              active={onlyPrimaryTreeEdges}
              onClick={() => updateParam({ primary_edges: onlyPrimaryTreeEdges ? "0" : null })}
              icon={<GitBranch size={10} />}
              label="Somente arestas principais"
            />
          )}

          {focusNode && (
            <div className="ml-auto flex items-center gap-2 px-2.5 py-1 rounded-md bg-obs-violet/10 border border-obs-violet/30">
              <Crosshair size={11} className="text-obs-violet" />
              <span className="text-[11px] text-obs-violet truncate max-w-[300px]">
                Foco: {focusNode.node_type}:{focusNode.slug}
              </span>
              <button
                onClick={onClearFocus}
                className="text-[11px] text-obs-subtle hover:text-white"
                title="Limpar foco"
              >
                ✕
              </button>
            </div>
          )}
        </div>

        {/* Row 3: search + focus path breadcrumb */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 bg-obs-base border border-white/06 rounded-lg px-2 py-1 w-72">
            <Search size={11} className="text-obs-faint" />
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Buscar slug/título..."
              className="flex-1 bg-transparent text-xs text-obs-text placeholder-obs-faint focus:outline-none"
            />
          </div>

          {focusPath.length > 0 && (
            <div className="flex items-center gap-1 text-[11px] text-obs-subtle min-w-0 overflow-x-auto">
              {focusPath.map((step, i) => (
                <span key={`${step.node_id}-${i}`} className="flex items-center gap-1 shrink-0">
                  {i > 0 && <span className="text-obs-faint">→</span>}
                  <span
                    className="px-1.5 py-0.5 rounded border truncate max-w-[140px]"
                    style={{
                      borderColor: i === focusPath.length - 1 ? "rgba(167,139,250,0.6)" : "rgba(255,255,255,0.10)",
                      color: i === focusPath.length - 1 ? "#a78bfa" : undefined,
                    }}
                    title={`${step.node_type}:${step.slug}`}
                  >
                    {step.title || step.slug || step.node_type}
                  </span>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Graph canvas ─────────────────────────────────────── */}
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
            mode={mode}
            searchQuery={searchQuery}
            focusNodeId={focusNode?.node_id || null}
            onlyPrimaryTreeEdges={onlyPrimaryTreeEdges}
          />
        )}

        {/* Legend */}
        {data?.meta?.registry?.node_types && data.meta.registry.node_types.length > 0 && (
          <div className="absolute bottom-3 left-3 max-w-[280px] rounded-lg glass border border-white/06 p-2 text-[10px]">
            <div className="text-[9px] uppercase tracking-wider text-obs-faint mb-1">Tipos</div>
            <div className="flex flex-wrap gap-1">
              {data.meta.registry.node_types
                .filter((t) => !["tag", "mention", "knowledge_item", "kb_entry"].includes(t.node_type) || includeTags || includeMentions || includeTechnical)
                .sort((a, b) => (a.level ?? 99) - (b.level ?? 99))
                .map((t) => (
                  <span
                    key={t.node_type}
                    className="flex items-center gap-1 px-1.5 py-0.5 rounded border"
                    style={{ borderColor: `${t.color}40`, background: `${t.color}10`, color: t.color }}
                  >
                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: t.color }} />
                    {t.label || t.node_type}
                  </span>
                ))}
            </div>
            <div className="text-[9px] uppercase tracking-wider text-obs-faint mt-1.5 mb-1">Relações</div>
            <div className="flex flex-col gap-0.5 text-[10px]">
              <LegendEdge label="Forte (about_product, answers_question, …)" color="rgba(255,255,255,0.55)" />
              <LegendEdge label="Estrutural (belongs_to_persona, …)" color="rgba(255,255,255,0.30)" />
              <LegendEdge label="Auxiliar (has_tag, mentions, …)" color="rgba(255,255,255,0.18)" dashed />
              <LegendEdge label="Curadoria (duplicate_of)" color="#f87171" />
            </div>
          </div>
        )}

        {/* Drawer overlay */}
        <NodeDrawer
          node={selectedNode}
          onClose={() => setSelectedNode(null)}
          onUpdated={load}
          focusPath={focusPath}
          onFocusHere={() => selectedNode && onFocusNode(selectedNode)}
        />
      </div>
    </div>
  );
}

function ToggleChip({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1 text-[10px] px-2 py-1 rounded-md border transition ${
        active
          ? "bg-obs-violet/15 border-obs-violet/50 text-obs-violet"
          : "glass border-white/10 text-obs-subtle hover:text-obs-text"
      }`}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

function LegendEdge({ label, color, dashed }: { label: string; color: string; dashed?: boolean }) {
  return (
    <div className="flex items-center gap-1.5 text-obs-subtle">
      <svg width="20" height="6" viewBox="0 0 20 6">
        <line
          x1="0" y1="3" x2="20" y2="3"
          stroke={color}
          strokeWidth={2}
          strokeDasharray={dashed ? "3 3" : undefined}
        />
      </svg>
      <span>{label}</span>
    </div>
  );
}
