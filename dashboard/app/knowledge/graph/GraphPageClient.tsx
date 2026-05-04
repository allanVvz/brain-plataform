"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import {
  RefreshCw,
  Search,
  Network,
  GitBranch,
  Tag as TagIcon,
  AtSign,
  Database,
  Crosshair,
  Layers3,
  Plus,
  X,
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
    };
  };
}

interface GraphFilterOption {
  value: string;
  label: string;
  nodeType: string;
  level: number;
  confidence: number;
}

const MODES: { value: ViewMode; label: string; icon: React.ReactNode; help: string }[] = [
  { value: "semantic_tree", label: "Árvore",    icon: <GitBranch size={11} />, help: "Hierarquia automatica por aresta principal" },
  { value: "graph",         label: "Grafo",     icon: <Network size={11} />,   help: "Rede organica estilo Obsidian/neural" },
];

export default function GraphPageClient() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [personas, setPersonas] = useState<any[]>([]);
  const [data, setData] = useState<GraphPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState<any>(null);
  const [addPanelOpen, setAddPanelOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [headerPersonaSlug, setHeaderPersonaSlug] = useState("");
  const [graphNotice, setGraphNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  // ── URL-driven state ──────────────────────────────────────────
  const focus = searchParams.get("focus") || "";
  const mode = (searchParams.get("mode") as ViewMode) || "graph";
  const includeTags = searchParams.get("tags") === "1";
  const includeMentions = searchParams.get("mentions") === "1";
  const includeTechnical = searchParams.get("tech") === "1";
  const showAllEdges = searchParams.get("all_edges") === "1" || searchParams.get("primary_edges") === "0";
  const branchDistance = Number(searchParams.get("distance") || 48);

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

  useEffect(() => {
    const syncFromHeader = () => {
      const stored = window.localStorage.getItem("ai-brain-persona-slug") || "";
      setHeaderPersonaSlug(stored);
    };
    syncFromHeader();
    window.addEventListener("ai-brain-persona-change", syncFromHeader as EventListener);
    return () => window.removeEventListener("ai-brain-persona-change", syncFromHeader as EventListener);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api.graphData(headerPersonaSlug || undefined, {
        focus: focus || undefined,
        max_depth: 5,
        include_tags: includeTags,
        include_mentions: includeMentions,
        include_technical: includeTechnical,
        mode,
      });
      setData(d as GraphPayload);
    } finally {
      setLoading(false);
    }
  }, [headerPersonaSlug, focus, includeTags, includeMentions, includeTechnical, mode]);

  useEffect(() => {
    api.personas().then((p: any) => setPersonas(p));
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
  const effectivePersonaSlug = headerPersonaSlug;
  const effectivePersona = useMemo(
    () => personas.find((p) => p.slug === effectivePersonaSlug) || null,
    [personas, effectivePersonaSlug],
  );

  const graphFilterOptions = useMemo<GraphFilterOption[]>(() => {
    if (!data) return [];
    const unique = new Map<string, GraphFilterOption>();
    for (const node of data.nodes || []) {
      const d = node?.data || {};
      const nodeType = String(d.node_type || "").toLowerCase();
      if (!nodeType || ["persona", "tag", "mention", "knowledge_item", "kb_entry"].includes(nodeType)) continue;
      const slug = String(d.slug || "");
      if (!slug) continue;
      const key = `${nodeType}:${slug}`;
      if (unique.has(key)) continue;
      unique.set(key, {
        value: key,
        label: String(d.label || slug),
        nodeType,
        level: Number(d.level ?? 99),
        confidence: typeof d.confidence === "number" ? d.confidence : 0,
      });
    }
    return Array.from(unique.values()).sort((a, b) => {
      if (a.level !== b.level) return a.level - b.level;
      if (b.confidence !== a.confidence) return b.confidence - a.confidence;
      if (a.nodeType !== b.nodeType) return a.nodeType.localeCompare(b.nodeType);
      return a.label.localeCompare(b.label);
    });
  }, [data]);

  const selectedDirectLinks = useMemo(() => {
    if (!data || !selectedNode) return [];
    const byId = new Map((data.nodes || []).map((node) => [node.id, node]));
    const hierarchyRank: Record<string, number> = {
      persona: 0,
      brand: 20,
      campaign: 30,
      briefing: 40,
      audience: 50,
      product: 60,
      entity: 70,
      tone: 80,
      rule: 85,
      copy: 90,
      faq: 95,
      asset: 100,
      knowledge_item: 120,
      kb_entry: 120,
      tag: 130,
      mention: 130,
    };
    return (data.edges || [])
      .filter((edge) => edge.source === selectedNode.id || edge.target === selectedNode.id)
      .map((edge) => {
        const outbound = edge.source === selectedNode.id;
        const otherId = outbound ? edge.target : edge.source;
        const other = byId.get(otherId);
        return {
          id: edge.id,
          direction: (outbound ? "out" : "in") as "out" | "in",
          other_id: otherId,
          other_label: other?.data?.label || otherId,
          other_type: other?.data?.node_type || other?.data?.content_type || "node",
          other_summary: other?.data?.content_preview || other?.data?.description || "",
          other_level: Number(other?.data?.level ?? hierarchyRank[String(other?.data?.node_type || other?.data?.content_type || "node")] ?? 999),
        };
      })
      .sort((a, b) => {
        if (a.other_level !== b.other_level) return a.other_level - b.other_level;
        if (a.other_type !== b.other_type) return String(a.other_type).localeCompare(String(b.other_type));
        return String(a.other_label).localeCompare(String(b.other_label));
      });
  }, [data, selectedNode]);

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

  const handleConnectNodes = useCallback(
    async (sourceId: string, targetId: string) => {
      if (!sourceId.startsWith("gn:") || !targetId.startsWith("gn:")) {
        setGraphNotice({ tone: "error", text: "Conexao permitida apenas entre blocos de conhecimento." });
        return;
      }
      try {
        setGraphNotice(null);
        await api.createGraphEdge({
          source_node_id: sourceId,
          target_node_id: targetId,
          relation_type: "manual",
          persona_id: effectivePersona?.id,
          weight: 1,
          metadata: { direction: "source_to_target", created_from: "graph_ui" },
        });
        await load();
        setGraphNotice({ tone: "success", text: "Conexao criada." });
        window.setTimeout(() => setGraphNotice(null), 2200);
      } catch (error) {
        setGraphNotice({
          tone: "error",
          text: error instanceof Error ? error.message : "Nao foi possivel criar a conexao.",
        });
      }
    },
    [effectivePersona?.id, load],
  );

  const handleDeleteEdge = useCallback(
    async (edgeId: string) => {
      if (!edgeId.startsWith("ge:")) {
        setGraphNotice({ tone: "error", text: "Esta conexao nao pode ser apagada pela UI." });
        return;
      }
      try {
        await api.deleteGraphEdge(edgeId);
        await load();
        setGraphNotice({ tone: "success", text: "Conexao apagada." });
        window.setTimeout(() => setGraphNotice(null), 2200);
      } catch (error) {
        setGraphNotice({
          tone: "error",
          text: error instanceof Error ? error.message : "Nao foi possivel apagar a conexao.",
        });
      }
    },
    [load],
  );

  return (
    <div className="flex flex-col h-[calc(100vh-96px)] -mx-6 -mt-6 overflow-hidden">
      {/* ── Top bar (3 rows) ──────────────────────────────────── */}
      <div className="px-6 py-2.5 border-b border-white/06 glass shrink-0 space-y-2">
        {/* Row 1: persona + mode + meta */}
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-obs-text">Grafo de Conhecimento</span>

          <div className="flex min-w-[320px] items-center gap-2 rounded-lg border border-white/08 bg-white/[0.04] px-2.5 py-1.5 shadow-sm">
            <Layers3 size={11} className="text-obs-subtle" />
            <select
              value={focus}
              onChange={(e) => updateParam({ focus: e.target.value || null })}
              aria-label="filtro-semantico-grafo"
              className="w-full bg-transparent text-xs font-medium text-obs-text outline-none [color-scheme:dark]"
              disabled={!effectivePersonaSlug || graphFilterOptions.length === 0}
            >
              <option className="bg-[#11151f] text-obs-text" value="">
                {effectivePersona?.name ? `${effectivePersona.name} no centro` : "Centro: persona"}
              </option>
              {graphFilterOptions.map((option) => (
                <option className="bg-[#11151f] text-obs-text" key={option.value} value={option.value}>
                  {`L${option.level} · ${option.nodeType} · ${option.label}${option.confidence > 0 ? ` · conf ${option.confidence.toFixed(2)}` : ""}`}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-1">
            {MODES.map((m) => (
              <button
                key={m.value}
                title={m.help}
                onClick={() => updateParam({ mode: m.value === "graph" ? null : m.value })}
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

        {/* Row 2: visual spacing + visibility toggles */}
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex min-w-[320px] items-center gap-3 rounded-lg border border-white/06 bg-obs-base/80 px-3 py-2">
            <span className="whitespace-nowrap text-[10px] uppercase tracking-wider text-obs-faint">Forca gravitacional</span>
            <input
              type="range"
              min={0}
              max={100}
              value={branchDistance}
              onChange={(e) => updateParam({ distance: Number(e.target.value) === 48 ? null : e.target.value })}
              className="h-1 flex-1 accent-obs-violet"
              aria-label="forca-gravitacional"
            />
            <span className="w-8 text-right text-[10px] text-obs-subtle">{branchDistance}</span>
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

          <ToggleChip
            active={showAllEdges}
            onClick={() => updateParam({ all_edges: !showAllEdges ? "1" : null, primary_edges: null })}
            icon={<GitBranch size={10} />}
            label="Mostrar todas"
          />

          {focusNode && (
            <div className="ml-auto flex items-center gap-2 px-2.5 py-1 rounded-md bg-obs-violet/10 border border-obs-violet/30">
              <Crosshair size={11} className="text-obs-violet" />
              <span className="text-[11px] text-obs-violet truncate max-w-[300px]">
                Foco: {focusNode.title || focusNode.slug || focusNode.node_type}
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

        {effectivePersona && (
          <div className="flex items-center gap-2 text-[11px] text-obs-subtle">
            <span className="rounded border border-obs-violet/30 bg-obs-violet/10 px-2 py-0.5 text-obs-violet">
              Persona central: {effectivePersona.name}
            </span>
            <span>Filtro semantico por nivel, tipo e confianca dentro da persona ativa.</span>
          </div>
        )}
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
            onConnectNodes={handleConnectNodes}
            onDeleteEdge={handleDeleteEdge}
            mode={mode}
            searchQuery={searchQuery}
            focusNodeId={focusNode?.node_id || null}
            showAllEdges={showAllEdges}
            branchDistance={branchDistance}
          />
        )}

        {graphNotice && (
          <div
            className={`absolute right-4 top-4 z-50 rounded-lg border px-3 py-2 text-xs shadow-lg ${
              graphNotice.tone === "success"
                ? "border-emerald-400/30 bg-emerald-500/12 text-emerald-200"
                : "border-red-400/35 bg-red-500/15 text-red-100"
            }`}
          >
            {graphNotice.text}
          </div>
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
          </div>
        )}

        {/* Drawer overlay */}
        <NodeDrawer
          node={selectedNode}
          onClose={() => setSelectedNode(null)}
          onUpdated={load}
          focusPath={focusPath}
          directLinks={selectedDirectLinks}
          onFocusHere={() => selectedNode && onFocusNode(selectedNode)}
        />

        <button
          type="button"
          onClick={() => setAddPanelOpen(true)}
          className="absolute bottom-5 left-1/2 z-40 flex h-12 w-12 -translate-x-1/2 items-center justify-center rounded-full border border-obs-violet/45 bg-obs-violet/20 text-obs-violet shadow-obs-node transition hover:bg-obs-violet/30 hover:text-white"
          title="Adicionar bloco"
        >
          <Plus size={22} />
        </button>

        {addPanelOpen && (
          <AddBlockPanel onClose={() => setAddPanelOpen(false)} />
        )}
      </div>
    </div>
  );
}

function AddBlockPanel({ onClose }: { onClose: () => void }) {
  const nodeTypes = [
    "Persona",
    "Entidade",
    "Brand",
    "Campanha",
    "Produto",
    "Briefing",
    "Audiência",
    "Tom",
    "Regra",
    "Copy",
    "FAQ",
    "Asset",
  ];
  return (
    <div className="absolute inset-0 z-50 flex items-end justify-center bg-black/35 p-5">
      <div className="w-full max-w-2xl rounded-2xl border border-white/08 bg-[#0e1118] shadow-2xl">
        <div className="flex items-center justify-between border-b border-white/06 px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-obs-text">Adicionar bloco ao grafo</h2>
            <p className="mt-0.5 text-xs text-obs-subtle">Escolha o tipo de card para criar o próximo bloco.</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-obs-subtle transition hover:bg-white/5 hover:text-white"
          >
            <X size={16} />
          </button>
        </div>

        <div className="p-5">
          <section>
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-obs-faint">Tipos</p>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
              {nodeTypes.map((type) => (
                <button
                  key={type}
                  type="button"
                  className="rounded-lg border border-white/06 bg-white/[0.03] px-3 py-2 text-left text-xs text-obs-subtle transition hover:border-obs-violet/35 hover:text-white"
                >
                  {type}
                </button>
              ))}
            </div>
          </section>
        </div>
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
