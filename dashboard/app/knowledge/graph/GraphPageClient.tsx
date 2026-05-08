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
import { getVisualHierarchyRank } from "@/components/graph/knowledgeGraphLayout";

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
  const [selectedNodes, setSelectedNodes] = useState<any[]>([]);
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
  const includeEmbedded = searchParams.get("embedded") !== "0";
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
        include_embedded: includeEmbedded,
        mode,
      });
      setData(d as GraphPayload);
      return d as GraphPayload;
    } finally {
      setLoading(false);
    }
  }, [headerPersonaSlug, focus, includeTags, includeMentions, includeTechnical, includeEmbedded, mode]);

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
        level: getVisualHierarchyRank(nodeType),
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
          other_level: getVisualHierarchyRank(String(other?.data?.node_type || other?.data?.content_type || "node")),
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
      const byId = new Map((data?.nodes || []).map((node) => [node.id, node]));
      const sourceNode = byId.get(sourceId);
      const targetNode = byId.get(targetId);
      const sourceType = String(sourceNode?.data?.node_type || sourceNode?.data?.content_type || "");
      const targetType = String(targetNode?.data?.node_type || targetNode?.data?.content_type || "");
      const allowedRef = (id: string) => id.startsWith("gn:") || id.startsWith("ki:") || id.startsWith("persona:") || id.startsWith("embedded:");
      if (!allowedRef(sourceId) || !allowedRef(targetId)) {
        setGraphNotice({ tone: "error", text: "Conexao permitida apenas entre blocos persistidos do grafo." });
        return;
      }
      if ((sourceId.startsWith("ki:") || targetId.startsWith("ki:")) && targetType !== "embedded") {
        setGraphNotice({ tone: "error", text: "Itens pendentes nao podem ser conectados pelo grafo antes da aprovacao." });
        return;
      }
      if (targetType === "embedded" && sourceType === "knowledge_item") {
        setGraphNotice({ tone: "error", text: "Aprove o FAQ primeiro. A publicacao no Golden Dataset parte do node FAQ aprovado." });
        return;
      }
      if (targetType === "embedded" && sourceType !== "faq") {
        setGraphNotice({ tone: "error", text: "Somente nodes FAQ aprovados podem ser publicados no Golden Dataset." });
        return;
      }
      if (targetType === "embedded" && sourceNode?.data?.validated === false) {
        setGraphNotice({ tone: "error", text: "Aprove o FAQ primeiro. Rascunhos cinza ainda nao podem ir para o Golden Dataset." });
        return;
      }
      const finalReceiverTypes = new Set(["gallery", "embedded"]);
      const finalReceiver = finalReceiverTypes.has(targetType);
      const involvesGallery = sourceType === "gallery" || targetType === "gallery";
      const relationType = targetType === "gallery" ? "gallery_asset" : "manual";
      try {
        setGraphNotice(null);
        await api.createGraphEdge({
          source_node_id: sourceId,
          target_node_id: targetId,
          relation_type: relationType,
          persona_id: effectivePersona?.id,
          weight: finalReceiver || involvesGallery ? 0.9 : 1,
          metadata: {
            direction: "source_to_target",
            created_from: finalReceiver ? "graph_ui_final_receiver" : involvesGallery ? "gallery_ui" : "graph_ui",
            primary_tree: !finalReceiver && !involvesGallery,
            gallery: involvesGallery,
          },
        });
        await load();
        setGraphNotice({
          tone: "success",
          text: targetType === "embedded"
            ? "FAQ publicado no Golden Dataset."
            : finalReceiver
              ? "Conexao criada para node final."
              : involvesGallery
                ? "Node adicionado a Gallery e Assets."
                : "Conexao criada.",
        });
        window.setTimeout(() => setGraphNotice(null), 2200);
      } catch (error) {
        setGraphNotice({
          tone: "error",
          text: error instanceof Error ? error.message : "Nao foi possivel criar a conexao.",
        });
      }
    },
    [data?.nodes, effectivePersona?.id, load],
  );

  const handleDeleteEdge = useCallback(
    async (edgeId: string) => {
      const rawEdgeId = String(edgeId || "");
      const geIndex = rawEdgeId.indexOf("ge:");
      const resolvedEdgeId = rawEdgeId.startsWith("ge:")
        ? rawEdgeId
        : geIndex >= 0
          ? rawEdgeId.slice(geIndex)
          : rawEdgeId;
      if (!resolvedEdgeId.startsWith("ge:")) {
        console.error("[graph-edge-delete] invalid edge id", { edgeId, resolvedEdgeId });
        setGraphNotice({ tone: "error", text: `Esta conexao nao pode ser apagada pela UI (${rawEdgeId || "sem id"}).` });
        return;
      }
      setData((current) => current ? {
        ...current,
        edges: (current.edges || []).filter((edge) => {
          const candidate = String(edge?.data?.original_edge_id || edge?.id || "");
          return candidate !== resolvedEdgeId && edge?.id !== resolvedEdgeId;
        }),
      } : current);
      try {
        console.info("[graph-edge-delete] deleting", { edgeId, resolvedEdgeId });
        await api.deleteGraphEdge(resolvedEdgeId);
        await load();
        console.info("[graph-edge-delete] deleted", { resolvedEdgeId });
        setGraphNotice({ tone: "success", text: "Conexao apagada." });
        window.setTimeout(() => setGraphNotice(null), 2200);
      } catch (error) {
        console.error("[graph-edge-delete] failed", { edgeId, resolvedEdgeId, error });
        await load();
        setGraphNotice({
          tone: "error",
          text: error instanceof Error ? error.message : "Nao foi possivel apagar a conexao.",
        });
      }
    },
    [load],
  );

  const handleDeleteNode = useCallback(
    async (nodeId: string) => {
      const node = data?.nodes?.find((item) => item.id === nodeId);
      const sourceTable = String(node?.data?.source_table || "");
      const sourceId = String(node?.data?.source_id || node?.data?.item_id || "");
      if (!nodeId.startsWith("gn:") && !(sourceTable === "knowledge_items" && sourceId)) {
        setGraphNotice({ tone: "error", text: "Este card nao pode ser apagado pela UI." });
        return;
      }
      const nodeType = String(node?.data?.node_type || "");
      if (["persona", "embedded", "gallery"].includes(nodeType) || node?.data?.protected) {
        setGraphNotice({ tone: "error", text: "Este node e protegido e nao pode ser excluido." });
        return;
      }
      try {
        if (sourceTable === "knowledge_items" && sourceId) {
          await api.deleteKnowledgeItem(sourceId);
        } else {
          await api.deleteGraphNode(nodeId);
        }
        if (selectedNode?.id === nodeId) setSelectedNode(null);
        await load();
        setGraphNotice({ tone: "success", text: "Card apagado." });
        window.setTimeout(() => setGraphNotice(null), 2200);
      } catch (error) {
        setGraphNotice({
          tone: "error",
          text: error instanceof Error ? error.message : "Nao foi possivel apagar o card.",
        });
      }
    },
    [data?.nodes, load, selectedNode?.id],
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
              className="w-full bg-transparent text-xs font-medium text-obs-text outline-none"
              disabled={!effectivePersonaSlug || graphFilterOptions.length === 0}
            >
              <option className="bg-obs-raised text-obs-text" value="">
                {effectivePersona?.name ? `${effectivePersona.name} no centro` : "Centro: persona"}
              </option>
              {graphFilterOptions.map((option) => (
                <option className="bg-obs-raised text-obs-text" key={option.value} value={option.value}>
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

          <ToggleChip
            active={includeEmbedded}
            onClick={() => updateParam({ embedded: includeEmbedded ? "0" : null })}
            icon={<Database size={10} />}
            label="Embedded"
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
            onNodeClick={(node) => {
              setSelectedNode(node);
              setSelectedNodes([node]);
            }}
            onSelectionChange={(nodes) => {
              setSelectedNodes(nodes);
              if (nodes.length > 1) setSelectedNode(null);
            }}
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
                .sort((a, b) => getVisualHierarchyRank(a.node_type) - getVisualHierarchyRank(b.node_type))
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
          selectedNodes={selectedNodes}
          onClose={() => {
            setSelectedNode(null);
            setSelectedNodes([]);
          }}
          onUpdated={load}
          focusPath={focusPath}
          directLinks={selectedDirectLinks}
          onFocusHere={() => selectedNode && onFocusNode(selectedNode)}
          onDeleteNode={handleDeleteNode}
          onDeleteEdge={handleDeleteEdge}
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
          <AddBlockPanel
            nodes={data?.nodes || []}
            edges={data?.edges || []}
            persona={effectivePersona}
            onClose={() => setAddPanelOpen(false)}
            onCreated={async (created) => {
              setAddPanelOpen(false);
              await load();
              const graphNode = created?.graph_node;
              if (graphNode?.slug && graphNode?.node_type) {
                updateParam({ focus: `${graphNode.node_type}:${graphNode.slug}` });
              }
              setGraphNotice({ tone: "success", text: "Bloco criado e conectado." });
              window.setTimeout(() => setGraphNotice(null), 2200);
            }}
          />
        )}
      </div>
    </div>
  );
}

function AddBlockPanel({
  nodes,
  edges,
  persona,
  onClose,
  onCreated,
}: {
  nodes: any[];
  edges: any[];
  persona?: any;
  onClose: () => void;
  onCreated: (created?: any) => void | Promise<void>;
}) {
  const nodeTypeOptions = [
    { value: "brand", label: "Brand" },
    { value: "campaign", label: "Campanha" },
    { value: "product", label: "Produto" },
    { value: "briefing", label: "Briefing" },
    { value: "audience", label: "Audiencia" },
    { value: "entity", label: "Entidade" },
    { value: "tone", label: "Tom" },
    { value: "rule", label: "Regra" },
    { value: "copy", label: "Copy" },
    { value: "faq", label: "FAQ" },
    { value: "asset", label: "Asset" },
  ];
  const parentOptions = useMemo(
    () => nodes
      .filter((node) => node.id?.startsWith("gn:"))
      .filter((node) => !["tag", "mention"].includes(node.data?.node_type))
      .map((node) => ({
        id: node.id.slice(3),
        graphId: node.id,
        label: node.data?.label || node.data?.slug || node.id,
        slug: node.data?.slug,
        type: node.data?.node_type || "node",
      }))
      .sort((a, b) => {
        const ar = getVisualHierarchyRank(a.type);
        const br = getVisualHierarchyRank(b.type);
        if (ar !== br) return ar - br;
        return a.label.localeCompare(b.label);
      })
      .slice(0, 120),
    [nodes],
  );
  const graphNodesById = useMemo(() => new Map(parentOptions.map((node) => [node.graphId, node])), [parentOptions]);
  const childOptionsByParent = useMemo(() => {
    const structural = new Set([
      "manual",
      "contains",
      "part_of_campaign",
      "about_product",
      "briefed_by",
      "answers_question",
      "supports_copy",
      "uses_asset",
      "belongs_to_persona",
    ]);
    const out = new Map<string, typeof parentOptions>();
    for (const edge of edges || []) {
      const relation = String(edge?.data?.relation_type || "").toLowerCase();
      if (!structural.has(relation)) continue;
      const source = edge?.source;
      const target = edge?.target;
      const child = graphNodesById.get(target);
      if (!source || !child || source === target) continue;
      const list = out.get(source) || [];
      if (!list.some((item) => item.graphId === child.graphId)) list.push(child);
      out.set(source, list);
    }
    for (const [key, list] of out) {
      out.set(key, [...list].sort((a, b) => {
        const ar = getVisualHierarchyRank(a.type);
        const br = getVisualHierarchyRank(b.type);
        if (ar !== br) return ar - br;
        return a.label.localeCompare(b.label);
      }));
    }
    return out;
  }, [edges, graphNodesById]);
  const campaignOptions = useMemo(() => {
    const campaigns = parentOptions.filter((node) => node.type === "campaign");
    return campaigns.length ? campaigns : parentOptions.filter((node) => ["brand", "campaign", "briefing"].includes(node.type));
  }, [parentOptions]);
  const [contentType, setContentType] = useState("product");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [pathIds, setPathIds] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const selectedParent = useMemo(() => {
    const last = pathIds[pathIds.length - 1];
    return parentOptions.find((node) => node.graphId === last);
  }, [parentOptions, pathIds]);
  const parentNodeId = selectedParent?.id || "";

  useEffect(() => {
    if (!pathIds.length && campaignOptions[0]?.graphId) setPathIds([campaignOptions[0].graphId]);
  }, [campaignOptions, pathIds.length]);

  const selectPathNode = (level: number, graphId: string) => {
    setPathIds((current) => [...current.slice(0, level), graphId]);
  };

  const pathColumns = useMemo(() => {
    const columns: Array<{ title: string; helper: string; options: typeof parentOptions; selected?: string }> = [
      {
        title: "Campanha",
        helper: "Clique para escolher o galho raiz.",
        options: campaignOptions,
        selected: pathIds[0],
      },
    ];
    const firstChildren = pathIds[0] ? childOptionsByParent.get(pathIds[0]) || [] : [];
    columns.push({
      title: "Alguma outra conexao?",
      helper: "Somente filhos imediatos da campanha.",
      options: firstChildren,
      selected: pathIds[1],
    });
    if (pathIds[1]) {
      columns.push({
        title: "Terceiro nivel",
        helper: "Refine com o proximo nivel hierarquico.",
        options: childOptionsByParent.get(pathIds[1]) || [],
        selected: pathIds[2],
      });
    }
    return columns;
  }, [campaignOptions, childOptionsByParent, pathIds]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!persona?.id) {
      setError("Selecione uma persona antes de criar o bloco.");
      return;
    }
    if (!title.trim() || !content.trim()) {
      setError("Titulo e conteudo sao obrigatorios.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const created = await api.intakeKnowledge({
        raw_text: content,
        persona_id: persona.id,
        source: "graph_ui_add_block",
        source_ref: title,
        title,
        content_type: contentType,
        tags: [contentType, persona.slug].filter(Boolean),
        metadata: {
          slug: title,
          markdown_document: true,
          parent_node_id: parentNodeId || undefined,
          parent_relation_type: "manual",
        },
        submitted_by: "graph_ui",
        validate: true,
        parent_node_id: parentNodeId || undefined,
        parent_relation_type: "manual",
      });
      await onCreated(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nao foi possivel criar o bloco.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="absolute inset-0 z-50 flex items-end justify-center bg-black/30 p-3">
      <form onSubmit={submit} className="w-full max-w-4xl rounded-xl border border-white/08 bg-obs-surface shadow-2xl">
        <div className="flex items-center justify-between border-b border-white/06 px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-obs-text">Adicionar bloco ao grafo</h2>
            <p className="mt-0.5 text-[11px] text-obs-subtle">Defina o tipo, conteudo e galho principal.</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-obs-subtle transition hover:bg-white/5 hover:text-white"
          >
            <X size={16} />
          </button>
        </div>

        <div className="max-h-[76vh] overflow-y-auto p-4">
          <section>
            <p className="mb-2 text-[9px] font-semibold uppercase tracking-[0.16em] text-obs-faint">Tipo</p>
            <div className="flex flex-wrap gap-1.5">
              {nodeTypeOptions.map((type) => (
                <button
                  key={type.value}
                  type="button"
                  onClick={() => setContentType(type.value)}
                  className={`rounded-md border px-2.5 py-1.5 text-left text-[11px] leading-none transition ${
                    contentType === type.value
                      ? "border-obs-violet/50 bg-obs-violet/15 text-white"
                      : "border-white/06 bg-white/[0.03] text-obs-subtle hover:border-obs-violet/35 hover:text-white"
                  }`}
                >
                  {type.label}
                </button>
              ))}
            </div>
            <input
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Titulo do bloco"
              className="mt-3 w-full rounded-md border border-white/06 bg-obs-base px-3 py-2 text-sm text-obs-text outline-none focus:border-obs-violet/50"
            />
            <textarea
              required
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={4}
              placeholder="Conteudo markdown do novo conhecimento..."
              className="mt-2.5 w-full resize-none rounded-md border border-white/06 bg-obs-base px-3 py-2 text-sm text-obs-text outline-none focus:border-obs-violet/50"
            />
            <div className="mt-3 grid gap-2 md:grid-cols-3">
              {pathColumns.map((column, index) => (
                <div key={`${column.title}-${index}`} className="min-h-[104px] rounded-md border border-white/06 bg-obs-base/70 p-2.5">
                  <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-obs-faint">{column.title}</p>
                  <p className="mt-0.5 truncate text-[10px] text-obs-subtle">{column.helper}</p>
                  <div className="mt-2 max-h-28 space-y-1.5 overflow-y-auto pr-1">
                    {column.options.length ? column.options.map((node) => (
                      <button
                        key={node.graphId}
                        type="button"
                        onClick={() => selectPathNode(index, node.graphId)}
                        className={`w-full rounded-md border px-2 py-1.5 text-left transition ${
                          column.selected === node.graphId
                            ? "border-obs-violet/60 bg-obs-violet/18 text-white"
                            : "border-white/06 bg-white/[0.03] text-obs-subtle hover:border-obs-violet/35 hover:text-white"
                        }`}
                      >
                        <span className="block text-[8px] uppercase tracking-[0.12em] text-obs-faint">{node.type}</span>
                        <span className="mt-0.5 block truncate text-[11px] font-medium leading-tight">{node.label}</span>
                      </button>
                    )) : (
                      <p className="rounded-md border border-dashed border-white/08 px-2 py-3 text-[11px] text-obs-faint">
                        Nenhum filho imediato nesse nivel.
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <p className="mt-2 truncate text-[11px] text-obs-subtle">
              Conexao principal selecionada: {selectedParent ? `${selectedParent.type} - ${selectedParent.label}` : "Persona ativa"}
            </p>
            {error && <p className="mt-3 text-xs text-red-200">{error}</p>}
          </section>
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-white/06 px-4 py-3">
          <button type="button" onClick={onClose} className="rounded-md border border-white/06 px-3 py-2 text-xs text-obs-subtle hover:text-white">
            Cancelar
          </button>
          <button type="submit" disabled={saving} className="rounded-md bg-obs-violet px-4 py-2 text-xs font-medium text-white disabled:opacity-50">
            {saving ? "Criando..." : "Criar node"}
          </button>
        </div>
      </form>
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
