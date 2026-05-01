"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Node,
  Edge,
  NodeTypes,
  useNodesState,
  useEdgesState,
  Handle,
  Position,
  NodeProps,
  ReactFlowProvider,
  Panel,
} from "reactflow";
import dagre from "dagre";
import "reactflow/dist/style.css";

// ── Types ──────────────────────────────────────────────────────

interface GraphNode extends Node {
  data: {
    label: string;
    slug?: string;
    description?: string;
    status?: string;
    content_type?: string;
    file_type?: string;
    file_path?: string;
    content_preview?: string;
    nodeClass: "persona" | "validated" | "pending" | "rejected" | "orphan";
    item_id?: string;
  };
}

interface GraphViewProps {
  rawNodes: any[];
  rawEdges: any[];
  onNodeClick: (node: GraphNode) => void;
}

type ViewMode = "type" | "status";

// ── Dagre layout (TB — top-down tree) ─────────────────────────

const NODE_DIMS: Record<string, { w: number; h: number }> = {
  personaNode:   { w: 160, h: 48 },
  branchNode:    { w: 130, h: 36 },
  knowledgeNode: { w: 140, h: 48 },
};

function applyLayout(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", ranksep: 56, nodesep: 18, edgesep: 8 });

  nodes.forEach((n) => {
    const { w, h } = NODE_DIMS[n.type!] ?? NODE_DIMS.knowledgeNode;
    g.setNode(n.id, { width: w, height: h });
  });
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    if (!pos) return n;
    const { w, h } = NODE_DIMS[n.type!] ?? NODE_DIMS.knowledgeNode;
    return { ...n, position: { x: pos.x - w / 2, y: pos.y - h / 2 } };
  });
}

// ── Branch palette ─────────────────────────────────────────────

const BRANCH_PALETTE: Record<string, { cls: string; hex: string }> = {
  asset:          { cls: "border-obs-amber/70 bg-obs-amber/10 text-obs-amber",       hex: "#f59e0b" },
  brand:          { cls: "border-obs-violet/70 bg-obs-violet/10 text-obs-violet",    hex: "#7c6fff" },
  product:        { cls: "border-blue-400/70 bg-blue-400/10 text-blue-400",          hex: "#60a5fa" },
  faq:            { cls: "border-green-400/70 bg-green-400/10 text-green-400",       hex: "#4ade80" },
  rule:           { cls: "border-obs-rose/70 bg-obs-rose/10 text-obs-rose",          hex: "#f87171" },
  copy:           { cls: "border-obs-slate/70 bg-obs-slate/10 text-obs-slate",       hex: "#64748b" },
  tone:           { cls: "border-cyan-400/70 bg-cyan-400/10 text-cyan-400",          hex: "#22d3ee" },
  briefing:       { cls: "border-purple-400/70 bg-purple-400/10 text-purple-400",    hex: "#c084fc" },
  campaign:       { cls: "border-orange-400/70 bg-orange-400/10 text-orange-400",    hex: "#fb923c" },
  audience:       { cls: "border-pink-400/70 bg-pink-400/10 text-pink-400",          hex: "#f472b6" },
  competitor:     { cls: "border-red-400/70 bg-red-400/10 text-red-400",             hex: "#f87171" },
  prompt:         { cls: "border-indigo-400/70 bg-indigo-400/10 text-indigo-400",    hex: "#818cf8" },
  maker_material: { cls: "border-yellow-400/70 bg-yellow-400/10 text-yellow-400",   hex: "#facc15" },
  other:          { cls: "border-white/20 bg-white/5 text-obs-subtle",              hex: "#475569" },
  // status mode keys
  validated:      { cls: "border-obs-slate/70 bg-obs-slate/10 text-obs-slate",       hex: "#64748b" },
  pending:        { cls: "border-obs-amber/70 bg-obs-amber/10 text-obs-amber",       hex: "#f59e0b" },
  rejected:       { cls: "border-obs-rose/70 bg-obs-rose/10 text-obs-rose",          hex: "#f87171" },
  orphan:         { cls: "border-white/20 bg-white/5 text-obs-faint",               hex: "#3d4559" },
};

const TYPE_LABELS: Record<string, string> = {
  asset: "Asset", brand: "Brand", product: "Produto", faq: "FAQ",
  rule: "Regra", copy: "Copy", tone: "Tom", briefing: "Briefing",
  campaign: "Campanha", audience: "Audiência", competitor: "Concorrente",
  prompt: "Prompt", maker_material: "Maker", other: "Outros",
  validated: "Validado", pending: "Pendente", rejected: "Rejeitado", orphan: "Sem Persona",
};

// ── Tree builder — inserts branch layer between personas and items ──

function buildTree(
  rawNodes: Node[],
  rawEdges: Edge[],
  viewMode: ViewMode,
  typeFilter: string | null,
): { nodes: Node[]; edges: Edge[] } {
  // item id → parent id (persona:xxx or "orphan")
  const parentMap = new Map<string, string>();
  rawEdges.forEach((e) => {
    if (e.source.startsWith("persona:") || e.source === "orphan") {
      parentMap.set(e.target, e.source);
    }
  });

  const personaNodes = rawNodes.filter((n) => n.type === "personaNode");
  const itemNodes    = rawNodes.filter((n) => n.type === "knowledgeNode");

  // persona id → Set of branch keys that will exist
  const personaHasChildren = new Set<string>();

  // group key = "parentId__branchKey"
  const groups = new Map<string, Node[]>();

  itemNodes.forEach((item) => {
    const parentId  = parentMap.get(item.id) ?? "orphan";
    const branchKey = viewMode === "type"
      ? (item.data.content_type || "other")
      : (item.data.nodeClass   || "pending");

    if (typeFilter && viewMode === "type" && branchKey !== typeFilter) return;

    const key = `${parentId}__${branchKey}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(item);
    personaHasChildren.add(parentId);
  });

  // Only keep persona nodes that have visible children (when filter is active)
  const visiblePersonas = typeFilter
    ? personaNodes.filter((n) => personaHasChildren.has(n.id))
    : personaNodes;

  const resultNodes: Node[] = [...visiblePersonas];
  const resultEdges: Edge[] = [];

  groups.forEach((items, groupKey) => {
    const sep       = groupKey.indexOf("__");
    const parentId  = groupKey.slice(0, sep);
    const branchKey = groupKey.slice(sep + 2);

    // Skip if parent persona was filtered away
    if (!visiblePersonas.some((n) => n.id === parentId)) return;

    const branchId = `branch:${parentId}:${branchKey}`;

    resultNodes.push({
      id: branchId,
      type: "branchNode",
      position: { x: 0, y: 0 },
      data: {
        label:     TYPE_LABELS[branchKey] ?? branchKey,
        branchKey,
        count:     items.length,
        viewMode,
      },
    });

    resultEdges.push({
      id:     `e:p-b:${parentId}:${branchKey}`,
      source: parentId,
      target: branchId,
      type:   "smoothstep",
      style:  { strokeOpacity: 0.35, strokeWidth: 1 },
    });

    items.forEach((item) => {
      resultNodes.push(item);
      resultEdges.push({
        id:     `e:b-i:${branchId}:${item.id}`,
        source: branchId,
        target: item.id,
        type:   "smoothstep",
        style:  { strokeOpacity: 0.18, strokeWidth: 1 },
      });
    });
  });

  return { nodes: resultNodes, edges: resultEdges };
}

// ── Node components ────────────────────────────────────────────

const PERSONA_STYLES: Record<string, string> = {
  persona: "border-obs-violet bg-obs-violet-glow glow-violet text-obs-violet",
  orphan:  "border-obs-faint bg-obs-raised text-obs-subtle",
};

const KI_STYLES: Record<string, { ring: string; dot: string; label: string }> = {
  validated: { ring: "border-obs-slate/40",           dot: "bg-obs-slate",  label: "text-obs-text/80" },
  pending:   { ring: "border-obs-amber/40 glow-amber", dot: "bg-obs-amber", label: "text-obs-amber" },
  rejected:  { ring: "border-obs-rose/30",             dot: "bg-obs-rose",  label: "text-obs-subtle line-through" },
};

function PersonaNode({ data, selected }: NodeProps) {
  const style = PERSONA_STYLES[data.nodeClass] || PERSONA_STYLES.persona;
  return (
    <div
      className={`rounded-xl border px-4 py-2.5 text-sm font-semibold tracking-wide cursor-pointer transition-all ${style} ${selected ? "scale-105" : ""}`}
      style={{ minWidth: 140, textAlign: "center" }}
    >
      <Handle type="target" position={Position.Top}    style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
      <div className="text-[10px] uppercase tracking-widest opacity-60 mb-0.5">persona</div>
      {data.label}
    </div>
  );
}

function BranchNode({ data, selected }: NodeProps) {
  const palette = BRANCH_PALETTE[data.branchKey] ?? BRANCH_PALETTE.other;
  return (
    <div
      className={`rounded-lg border px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider transition-all ${palette.cls} ${selected ? "scale-105" : ""}`}
      style={{ minWidth: 110, textAlign: "center" }}
    >
      <Handle type="target" position={Position.Top}    style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
      <span>{data.label}</span>
      <span className="ml-1.5 text-[10px] opacity-55 font-mono normal-case">{data.count}</span>
    </div>
  );
}

function KnowledgeNode({ data, selected }: NodeProps) {
  const cls    = KI_STYLES[data.nodeClass] || KI_STYLES.pending;
  const isVideo = ["mp4", "mov", "webm"].includes(data.file_type || "");
  const isImage = ["png", "jpg", "jpeg", "webp", "svg"].includes(data.file_type || "");

  return (
    <div
      className={`rounded-lg border glass px-3 py-2 cursor-pointer transition-all node-obs ${cls.ring} ${selected ? "ring-1 ring-obs-violet" : ""}`}
      style={{ minWidth: 120, maxWidth: 140 }}
    >
      <Handle type="target" position={Position.Top}    style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
      <div className="flex items-center gap-1.5 mb-1">
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cls.dot}`} />
        <span className="text-[9px] text-obs-subtle uppercase tracking-wider truncate flex-1">
          {data.content_type}
        </span>
        {isVideo && <span className="text-[8px] text-obs-amber">▶</span>}
        {isImage && <span className="text-[8px] text-obs-slate">⬛</span>}
        {(data as any).source === "vault" && (
          <span className="text-[8px] text-obs-slate opacity-60">V</span>
        )}
      </div>
      <div className={`text-xs font-medium truncate ${cls.label}`}>{data.label}</div>
    </div>
  );
}

const nodeTypes: NodeTypes = {
  personaNode:   PersonaNode,
  branchNode:    BranchNode,
  knowledgeNode: KnowledgeNode,
};

// ── Main component ─────────────────────────────────────────────

function GraphInner({ rawNodes, rawEdges, onNodeClick }: GraphViewProps) {
  const [viewMode,    setViewMode]    = useState<ViewMode>("type");
  const [typeFilter,  setTypeFilter]  = useState<string | null>(null);

  // Unique content types present in data
  const availableTypes = useMemo(() => {
    const types = new Set<string>();
    rawNodes.forEach((n) => {
      if (n.type === "knowledgeNode" && n.data?.content_type) {
        types.add(n.data.content_type as string);
      }
    });
    return Array.from(types).sort();
  }, [rawNodes]);

  const { nodes: treeNodes, edges: treeEdges } = useMemo(
    () => buildTree(rawNodes, rawEdges, viewMode, typeFilter),
    [rawNodes, rawEdges, viewMode, typeFilter],
  );

  const laid = useMemo(
    () => applyLayout(treeNodes as Node[], treeEdges as Edge[]),
    [treeNodes, treeEdges],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(laid);
  const [edges, ,          onEdgesChange] = useEdgesState(treeEdges as Edge[]);

  useEffect(() => {
    setNodes(applyLayout(treeNodes as Node[], treeEdges as Edge[]));
  }, [treeNodes, treeEdges]);

  const handleClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      if (node.type === "branchNode") return;
      onNodeClick(node as GraphNode);
    },
    [onNodeClick],
  );

  const pendingCount   = rawNodes.filter((n) => n.data?.nodeClass === "pending").length;
  const validatedCount = rawNodes.filter((n) => n.data?.nodeClass === "validated").length;

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={handleClick}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.12 }}
      minZoom={0.08}
      maxZoom={2}
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="rgba(255,255,255,0.04)" />
      <Controls showInteractive={false} />
      <MiniMap
        nodeColor={(n) => {
          if (n.type === "branchNode") {
            return BRANCH_PALETTE[(n.data as any)?.branchKey]?.hex ?? "#3d4559";
          }
          const cls = (n.data as any)?.nodeClass;
          if (cls === "persona") return "#7c6fff";
          if (cls === "pending") return "#f59e0b";
          if (cls === "validated") return "#64748b";
          return "#3d4559";
        }}
        maskColor="rgba(5,7,9,0.8)"
      />

      <Panel position="top-left">
        <div className="flex flex-col gap-2">

          {/* View mode toggle */}
          <div className="flex gap-1">
            {(["type", "status"] as ViewMode[]).map((m) => (
              <button
                key={m}
                onClick={() => { setViewMode(m); setTypeFilter(null); }}
                className={`text-[10px] px-2.5 py-1 rounded-md border transition-colors ${
                  viewMode === m
                    ? "bg-obs-violet/20 border-obs-violet text-obs-violet"
                    : "glass border-white/10 text-obs-subtle hover:text-obs-text"
                }`}
              >
                {m === "type" ? "Por Tipo" : "Por Validação"}
              </button>
            ))}
          </div>

          {/* Type filter chips — only in "Por Tipo" mode */}
          {viewMode === "type" && availableTypes.length > 0 && (
            <div className="flex flex-wrap gap-1 max-w-[380px]">
              <button
                onClick={() => setTypeFilter(null)}
                className={`text-[9px] px-2 py-0.5 rounded-full border transition-colors ${
                  typeFilter === null
                    ? "bg-white/10 border-white/25 text-obs-text"
                    : "border-white/10 text-obs-faint hover:text-obs-subtle"
                }`}
              >
                Todos
              </button>
              {availableTypes.map((t) => {
                const active = typeFilter === t;
                const pal    = BRANCH_PALETTE[t];
                return (
                  <button
                    key={t}
                    onClick={() => setTypeFilter(active ? null : t)}
                    style={active && pal
                      ? { borderColor: pal.hex + "90", backgroundColor: pal.hex + "22", color: pal.hex }
                      : undefined}
                    className={`text-[9px] px-2 py-0.5 rounded-full border transition-colors ${
                      active ? "" : "border-white/10 text-obs-faint hover:text-obs-subtle"
                    }`}
                  >
                    {TYPE_LABELS[t] ?? t}
                  </button>
                );
              })}
            </div>
          )}

          {/* Quick stats */}
          <div className="text-[9px] text-obs-faint flex gap-2.5">
            <span className="text-obs-slate">{validatedCount} validados</span>
            <span className="text-obs-amber">{pendingCount} pendentes</span>
          </div>
        </div>
      </Panel>
    </ReactFlow>
  );
}

export default function GraphView(props: GraphViewProps) {
  return (
    <ReactFlowProvider>
      <GraphInner {...props} />
    </ReactFlowProvider>
  );
}
