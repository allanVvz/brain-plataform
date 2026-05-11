"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  BaseEdge,
  Controls,
  Connection,
  MiniMap,
  Node,
  Edge,
  EdgeLabelRenderer,
  EdgeProps,
  NodeTypes,
  EdgeTypes,
  useNodesState,
  useEdgesState,
  Handle,
  Position,
  NodeProps,
  ReactFlowProvider,
  Panel,
  MarkerType,
  ConnectionMode,
  Viewport,
  getSmoothStepPath,
  getBezierPath,
  useReactFlow,
} from "reactflow";
import dagre from "dagre";
import "reactflow/dist/style.css";
import { Database, Images } from "lucide-react";
import {
  buildNeuronGraphLayout,
  buildTreeFromGraph,
  GraphEdgeData,
  GraphNodeData,
  getVisualHierarchyRank,
  KnowledgeViewMode,
} from "./knowledgeGraphLayout";

// ── Types ──────────────────────────────────────────────────────

type ViewMode = KnowledgeViewMode;
type AppTheme = "clean" | "dark";

const GRAPH_NODE_OPACITY_STORAGE = "ai-brain-graph-node-opacity";

interface GraphViewProps {
  rawNodes: any[];
  rawEdges: any[];
  onNodeClick: (node: any) => void;
  onSelectionChange?: (nodes: any[]) => void;
  onConnectNodes?: (sourceId: string, targetId: string) => void | Promise<void>;
  onDeleteEdge?: (edgeId: string) => void | Promise<void>;
  mode: ViewMode;
  searchQuery?: string;
  focusNodeId?: string | null;
  showAllEdges?: boolean;
  branchDistance?: number;
}

type StoredViewport = Pick<Viewport, "x" | "y" | "zoom">;

const HANDLE_STYLE = {
  width: 7,
  height: 7,
  borderRadius: 999,
  border: "1px solid rgba(226,232,240,0.62)",
  background: "rgba(14,17,24,0.92)",
  boxShadow: "0 0 0 2px rgba(124,111,255,0.08), 0 0 7px rgba(124,111,255,0.22)",
  opacity: 0.86,
  zIndex: 20,
};

const GRAPH_HANDLE_STYLE = {
  ...HANDLE_STYLE,
  width: "100%",
  height: "100%",
  border: "0",
  borderRadius: 999,
  background: "transparent",
  boxShadow: "none",
  opacity: 0,
  top: 0,
  left: 0,
  transform: "none",
};

function readGraphNodeOpacity(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(GRAPH_NODE_OPACITY_STORAGE) === "true";
}

function readTheme(): AppTheme {
  if (typeof document === "undefined") return "clean";
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "clean";
}

function themeTextColor(theme: AppTheme, translucent: boolean): string {
  if (translucent) return theme === "dark" ? "#050709" : "#ffffff";
  return theme === "dark" ? "#ffffff" : "#111827";
}

// ── Layout helpers ─────────────────────────────────────────────

function nodeSize(data: GraphNodeData): { w: number; h: number } {
  const importance = data.importance ?? 0.5;
  // Persona always wide
  if (data.node_type === "persona") return { w: 180, h: 56 };
  if (importance >= 0.85) return { w: 170, h: 52 };
  if (importance >= 0.65) return { w: 140, h: 44 };
  if (importance >= 0.50) return { w: 120, h: 38 };
  return { w: 104, h: 32 };
}

function nodeToRank(data: GraphNodeData): number {
  const nodeType = String(data.node_type || data.content_type || "").toLowerCase();
  const topDownRank: Record<string, number> = {
    persona: 0,
    brand: 1,
    briefing: 2,
    campaign: 3,
    audience: 4,
    product: 5,
    offer: 6,
    copy: 7,
    faq: 8,
    asset: 8,
    embedded: 9,
    gallery: 9,
    rule: 10,
    tone: 10,
    entity: 11,
  };
  if (topDownRank[nodeType] !== undefined) return topDownRank[nodeType];
  if (nodeType === "knowledge_item" || nodeType === "kb_entry") return 13;
  if (nodeType === "tag" || nodeType === "mention") return 14;
  return getVisualHierarchyRank(nodeType);
}

function spacingConfig(branchDistance = 48) {
  const value = Math.max(0, Math.min(100, branchDistance));
  return {
    rankSep: 52 + value * 1.05,
    nodeSep: 14 + value * 0.68,
    graphScale: 0.72 + value / 72,
  };
}

function applyLayoutLayered(nodes: Node[], edges: Edge[], branchDistance = 48): Node[] {
  const spacing = spacingConfig(branchDistance);
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", ranksep: spacing.rankSep, nodesep: spacing.nodeSep, edgesep: 8, ranker: "network-simplex" });

  nodes.forEach((n) => {
    const data = n.data as GraphNodeData;
    const { w, h } = nodeSize(data);
    g.setNode(n.id, { width: w, height: h });
  });

  // Group nodes by rank and add invisible "rank-anchor" edges so dagre
  // honors the level hierarchy even when real edges are sparse.
  const ranks = new Map<number, string[]>();
  nodes.forEach((n) => {
    const r = nodeToRank(n.data as GraphNodeData);
    if (!ranks.has(r)) ranks.set(r, []);
    ranks.get(r)!.push(n.id);
  });
  const rankList = Array.from(ranks.keys()).sort((a, b) => a - b);
  for (let i = 0; i < rankList.length - 1; i++) {
    const a = ranks.get(rankList[i])![0];
    const b = ranks.get(rankList[i + 1])![0];
    if (a && b) g.setEdge(a, b, { weight: 0.001 });
  }

  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    if (!pos) return n;
    const { w, h } = nodeSize(n.data as GraphNodeData);
    return { ...n, position: { x: pos.x - w / 2, y: pos.y - h / 2 } };
  });
}

function applyLayoutGraphSeed(nodes: Node[], edges: Edge[], branchDistance = 48): Node[] {
  return buildNeuronGraphLayout(nodes as Node<GraphNodeData>[], edges as Edge<GraphEdgeData>[], spacingConfig(branchDistance).graphScale);
}

function applyLayoutTree(nodes: Node[], edges: Edge[], branchDistance = 48): Node[] {
  const spacing = spacingConfig(branchDistance);
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", ranksep: spacing.rankSep + 14, nodesep: spacing.nodeSep + 8, edgesep: 10, ranker: "tight-tree" });
  nodes.forEach((n) => {
    const { w, h } = nodeSize(n.data as GraphNodeData);
    g.setNode(n.id, { width: w, height: h });
  });
  edges
    .filter((e) => (e.data as GraphEdgeData | undefined)?.primary)
    .forEach((e) => g.setEdge(e.source, e.target, { weight: 2 }));
  dagre.layout(g);
  const laid = nodes.map((n) => {
    const pos = g.node(n.id);
    if (!pos) return n;
    const { w, h } = nodeSize(n.data as GraphNodeData);
    return { ...n, position: { x: pos.x - w / 2, y: pos.y - h / 2 } };
  });
  const persona = laid.find((node) => (node.data as GraphNodeData)?.node_type === "persona");
  if (!persona) return laid;
  const dx = persona.position.x;
  const dy = persona.position.y;
  const centered = laid.map((node) => ({
    ...node,
    position: {
      x: node.position.x - dx,
      y: node.position.y - dy,
    },
  }));
  const structuralNodes = centered.filter((node) => !["embedded", "gallery"].includes(String((node.data as GraphNodeData)?.node_type || "")));
  const ranks = new Map<number, Node[]>();
  for (const node of structuralNodes) {
    const rank = nodeToRank(node.data as GraphNodeData);
    if (!ranks.has(rank)) ranks.set(rank, []);
    ranks.get(rank)!.push(node);
  }
  const mirroredPositions = new Map<string, { x: number; y: number }>();
  Array.from(ranks.entries()).sort(([a], [b]) => a - b).forEach(([rank, rankNodes]) => {
    const sorted = [...rankNodes].sort((a, b) => {
      const ax = a.position.x;
      const bx = b.position.x;
      if (ax !== bx) return ax - bx;
      return a.id.localeCompare(b.id);
    });
    const rankWidth = (sorted.length - 1) * (118 + spacing.nodeSep);
    const y = rank * (74 + spacing.rankSep * 0.72);
    sorted.forEach((node, index) => {
      const x = index * (118 + spacing.nodeSep) - rankWidth / 2;
      mirroredPositions.set(node.id, { x, y });
    });
  });
  const mirrored = centered.map((node) => {
    const next = mirroredPositions.get(node.id);
    return next ? { ...node, position: next } : node;
  });
  const baseMaxY = Math.max(
    0,
    ...mirrored
      .filter((node) => !["embedded", "gallery"].includes(String((node.data as GraphNodeData)?.node_type || "")))
      .map((node) => node.position.y),
  );
  const galleryNodes = mirrored.filter((node) => (node.data as GraphNodeData)?.node_type === "gallery");
  const embeddedNodes = mirrored.filter((node) => (node.data as GraphNodeData)?.node_type === "embedded");
  if (!embeddedNodes.length && !galleryNodes.length) return mirrored;
  const galleryOffsetStart = -((galleryNodes.length - 1) * 160) / 2;
  const embeddedOffsetStart = -((embeddedNodes.length - 1) * 160) / 2;
  const terminalShift = galleryNodes.length && embeddedNodes.length ? 90 : 0;
  let galleryIndex = 0;
  let embeddedIndex = 0;
  return mirrored.map((node) => {
    const nodeType = (node.data as GraphNodeData)?.node_type;
    if (nodeType === "gallery") {
      const x = galleryOffsetStart + galleryIndex * 160 - terminalShift;
      galleryIndex += 1;
      return { ...node, position: { x, y: baseMaxY + 180 } };
    }
    if (nodeType === "embedded") {
      const x = embeddedOffsetStart + embeddedIndex * 160 + terminalShift;
      embeddedIndex += 1;
      return { ...node, position: { x, y: baseMaxY + 180 } };
    }
    return node;
  });
}

// ── Filtering by mode ──────────────────────────────────────────

function filterEdgesForMode(edges: Edge[], mode: ViewMode): Edge[] {
  return edges.filter((edge) => {
    const data = (edge.data || {}) as GraphEdgeData;
    const metadata = (data.metadata || {}) as Record<string, unknown>;
    if (metadata.active === false) return false;
    if (metadata.visual_hidden === true) return false;
    if (mode !== "graph") {
      return data.primary_tree === true || metadata.primary_tree === true || data.embedded_edge === true || data.gallery_edge === true || (data as any).draft_terminal_edge === true;
    }
    return true;
  });
}

// ── Edge style by tier ─────────────────────────────────────────

function edgeStyle(data: GraphEdgeData | undefined, isInPath: boolean): Edge["style"] {
  const tier = data?.tier || "auxiliary";
  if ((data as any)?.branch_complete_validated) {
    return { stroke: "#22c55e", strokeWidth: 2.7, strokeOpacity: 0.9 };
  }
  if (isInPath) {
    return { stroke: "#7c6fff", strokeWidth: 2.6, strokeOpacity: 0.86 };
  }
  if ((data as any)?.draft_terminal_edge) {
    return { stroke: "rgba(148,163,184,0.64)", strokeWidth: 1.9, strokeOpacity: 0.68, strokeDasharray: "6 5" };
  }
  if (data?.embedded_edge) {
    return { stroke: "var(--rf-edge-active)", strokeWidth: 2.3, strokeOpacity: 0.78 };
  }
  if (data?.gallery_edge) {
    return { stroke: "rgba(217,70,239,0.66)", strokeWidth: 2.2, strokeOpacity: 0.74 };
  }
  if (data?.primary) {
    return { stroke: "var(--rf-edge)", strokeWidth: 2.2, strokeOpacity: 0.78 };
  }
  if (data?.secondary) {
    return { stroke: "rgba(170,190,220,0.22)", strokeWidth: 1, strokeOpacity: 0.28, strokeDasharray: "5 5" };
  }
  if (tier === "strong") {
    return { stroke: "rgba(125,211,252,0.55)", strokeWidth: 2.2, strokeOpacity: 0.72 };
  }
  if (tier === "structural") {
    return { stroke: "var(--rf-edge)", strokeWidth: 1.3, strokeOpacity: 0.42 };
  }
  if (tier === "curation") {
    return { stroke: "#f87171", strokeWidth: 2, strokeOpacity: 0.7 };
  }
  // auxiliary
  return { stroke: "var(--rf-edge)", strokeWidth: 1, strokeOpacity: 0.22, strokeDasharray: "4 4" };
}

// ── Node component ─────────────────────────────────────────────

function PersonaNode({ data, selected }: NodeProps) {
  const d = data as GraphNodeData;
  const focused = !!d.is_focus;
  const inPath = !!d.in_focus_path;
  const branchComplete = Boolean((d as any).branch_complete_validated);
  const personaColor = branchComplete ? "#22c55e" : (d.color || "#7c6fff");
  return (
    <div
      className={`rounded-xl border-2 px-4 py-2.5 text-sm font-semibold tracking-wide cursor-pointer transition-all ${selected || focused ? "scale-105" : ""}`}
      style={{
        minWidth: 160, textAlign: "center",
        borderColor: focused ? "#a78bfa" : personaColor,
        background: `${personaColor}1A`,
        color: personaColor,
        boxShadow: focused ? "0 0 16px rgba(167,139,250,0.55)" : (inPath ? "0 0 10px rgba(124,111,255,0.4)" : "none"),
        opacity: 1,
      }}
    >
      <Handle id="bottom-source" type="source" position={Position.Bottom} style={HANDLE_STYLE} />
      <div className="text-[10px] uppercase tracking-widest opacity-60 mb-0.5">{d.node_type || "persona"}</div>
      {d.label}
    </div>
  );
}

function KnowledgeNode({ data, selected }: NodeProps) {
  const d = data as GraphNodeData;
  const focused = !!d.is_focus;
  const inPath = !!d.in_focus_path;
  const isVideo = ["mp4", "mov", "webm"].includes(d.file_type || "");
  const isImage = ["png", "jpg", "jpeg", "webp", "svg"].includes(d.file_type || "");
  const importance = d.importance ?? 0.5;
  const isAuxiliary = !!d.is_auxiliary;
  const isEmbedded = d.node_type === "embedded";
  const isGallery = d.node_type === "gallery";
  const isPending = d.validated === false;
  const branchComplete = Boolean((d as any).branch_complete_validated);
  const color = branchComplete
    ? "#22c55e"
    : isEmbedded
      ? "#ffffff"
      : isGallery
        ? "#f0abfc"
        : isPending
          ? "#94a3b8"
          : d.color || "#94a3b8";
  const isGraphMode = d._viewMode === "graph";
  const theme = (d._theme === "dark" ? "dark" : "clean") as AppTheme;
  const translucent = Boolean(d._graphNodeOpacity);
  const labelColor = themeTextColor(theme, translucent);
  const nodeFill = translucent
    ? `radial-gradient(circle at 35% 25%, ${color}73, ${color}40 58%, ${color}24)`
    : color;
  const subduedGlow = focused
    ? `0 0 12px ${color}99, 0 0 22px ${color}33`
    : inPath
      ? `0 0 10px ${color}44`
      : isGraphMode
        ? `0 0 ${6 + importance * 8}px ${color}38`
        : `0 4px 16px ${color}20`;

  if (isGraphMode) {
    const size = importance >= 0.85 ? 82 : importance >= 0.65 ? 72 : importance >= 0.5 ? 62 : 54;
    return (
      <div className="relative flex flex-col items-center cursor-pointer transition-all" style={{ width: Math.max(92, size + 24) }}>
        <div
          className={`relative rounded-full border transition-all ${focused ? "ring-2 ring-obs-violet" : ""} ${selected ? "ring-1 ring-obs-violet" : ""}`}
          style={{
            width: size,
            height: size,
            borderColor: focused ? "#a78bfa" : `${color}AA`,
            background: nodeFill,
            boxShadow: subduedGlow,
            opacity: isPending ? 0.66 : isAuxiliary ? 0.78 : 1,
          }}
        >
          <Handle id="graph-top-target" type="target" position={Position.Top} style={GRAPH_HANDLE_STYLE} />
          <Handle id="graph-top-source" type="source" position={Position.Top} style={GRAPH_HANDLE_STYLE} />
          <Handle id="graph-right-target" type="target" position={Position.Right} style={GRAPH_HANDLE_STYLE} />
          <Handle id="graph-right-source" type="source" position={Position.Right} style={GRAPH_HANDLE_STYLE} />
          <Handle id="graph-bottom-target" type="target" position={Position.Bottom} style={GRAPH_HANDLE_STYLE} />
          <Handle id="graph-bottom-source" type="source" position={Position.Bottom} style={GRAPH_HANDLE_STYLE} />
          <Handle id="graph-left-target" type="target" position={Position.Left} style={GRAPH_HANDLE_STYLE} />
          <Handle id="graph-left-source" type="source" position={Position.Left} style={GRAPH_HANDLE_STYLE} />
          <div className="absolute inset-0 flex items-center justify-center">
            {isEmbedded ? (
              <Database size={18} className="shrink-0" style={{ color: labelColor }} strokeWidth={2.2} />
            ) : isGallery ? (
              <Images size={18} className="shrink-0" style={{ color: labelColor }} strokeWidth={2.2} />
            ) : (
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: labelColor }} />
            )}
          </div>
        </div>
        <div
          className="mt-2 max-w-[120px] truncate text-center text-[11px] font-semibold leading-tight"
          style={{ color: "rgb(var(--obs-text))" }}
          title={d.label}
        >
          {d.label}
        </div>
        <div className="mt-0.5 max-w-[100px] truncate text-center text-[8px] uppercase tracking-wider text-obs-subtle">
          {d.node_type || d.content_type}
        </div>
      </div>
    );
  }

  return (
    <div
      className={`relative rounded-2xl border cursor-pointer transition-all ${translucent ? "glass" : ""} ${focused ? "ring-2 ring-obs-violet" : ""} ${selected ? "ring-1 ring-obs-violet" : ""}`}
      style={{
        minWidth: importance >= 0.85 ? 150 : importance >= 0.65 ? 130 : importance >= 0.5 ? 110 : 96,
        maxWidth: importance >= 0.85 ? 180 : 150,
        padding: importance >= 0.85 ? "8px 12px" : importance >= 0.5 ? "6px 10px" : "4px 8px",
        borderColor: isEmbedded ? "rgba(255,255,255,0.72)" : isGallery ? "rgba(217,70,239,0.72)" : focused ? "#a78bfa" : `${color}AA`,
        background: isEmbedded
          ? (translucent ? "linear-gradient(145deg, rgba(255,255,255,0.34), rgba(148,163,184,0.28))" : "#64748b")
          : isGallery
            ? (translucent ? "linear-gradient(145deg, rgba(240,171,252,0.34), rgba(217,70,239,0.22))" : "#d946ef")
          : focused ? `${color}CC` : nodeFill,
        boxShadow: subduedGlow,
        opacity: isPending ? 0.68 : isAuxiliary ? 0.75 : 1,
      }}
    >
      <Handle id="top-target" type="target" position={Position.Top} style={HANDLE_STYLE} />
      {!isEmbedded && !isGallery && (
        <Handle id="bottom-source" type="source" position={Position.Bottom} style={HANDLE_STYLE} />
      )}
      <div className="flex items-center gap-1.5 mb-0.5">
        {isEmbedded ? (
          <Database size={12} className="shrink-0 text-white" strokeWidth={2.2} />
        ) : isGallery ? (
          <Images size={12} className="shrink-0 text-fuchsia-200" strokeWidth={2.2} />
        ) : (
          <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: color }} />
        )}
        <span className="text-[9px] uppercase tracking-wider truncate flex-1" style={{ color: labelColor }}>
          {d.node_type || d.content_type}
        </span>
        {isVideo && <span className="text-[8px] text-obs-amber">▶</span>}
        {isImage && <span className="text-[8px] text-obs-slate">⬛</span>}
        {typeof d.graph_distance === "number" && d.graph_distance > 0 && (
          <span className="text-[8px] text-obs-faint">d{d.graph_distance}</span>
        )}
      </div>
      <div
        className="font-medium truncate"
        style={{
          color: labelColor,
          fontSize: importance >= 0.85 ? 13 : importance >= 0.5 ? 12 : 11,
        }}
      >
        {d.label}
      </div>
    </div>
  );
}

const nodeTypes: NodeTypes = {
  personaNode: PersonaNode,
  knowledgeNode: KnowledgeNode,
};

function DeletableEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style,
  markerEnd,
  selected,
  data,
}: EdgeProps) {
  const pathArgs = {
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  };
  const [edgePath, labelX, labelY] = (data as any)?.viewMode === "graph"
    ? getBezierPath({ ...pathArgs, curvature: 0.34 })
    : getSmoothStepPath(pathArgs);
  const onDelete = (data as any)?.onDelete;
  const edgeIdForDelete = (data as any)?.original_edge_id || id;
  const canDelete = (data as any)?.deletable !== false;
  return (
    <>
      <BaseEdge id={id} path={edgePath} style={style} markerEnd={markerEnd} interactionWidth={18} />
      {selected && onDelete && canDelete && (
        <EdgeLabelRenderer>
          <button
            type="button"
            aria-label="Excluir conexao"
            data-testid={`delete-edge-${id}`}
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              console.info("[graph-edge-delete] click", { id, edgeIdForDelete, data });
              Promise.resolve(onDelete(edgeIdForDelete)).catch((error: unknown) => {
                console.error("[graph-edge-delete] onDelete failed", { id, edgeIdForDelete, error });
              });
            }}
            className="nodrag nopan absolute flex h-7 w-7 items-center justify-center rounded-full border border-red-400/45 bg-red-500/95 text-[13px] text-white shadow-lg transition hover:bg-red-400"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`, pointerEvents: "all", zIndex: 30 }}
            title="Excluir conexao"
          >
            ×
          </button>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const edgeTypes: EdgeTypes = {
  deletable: DeletableEdge,
};

// ── Main component ─────────────────────────────────────────────

function GraphInner({ rawNodes, rawEdges, onNodeClick, onSelectionChange, onConnectNodes, onDeleteEdge, mode, searchQuery, focusNodeId, showAllEdges = false, branchDistance = 48 }: GraphViewProps) {
  const { fitView, getViewport, setViewport } = useReactFlow();
  const [panActive, setPanActive] = useState(false);
  const [graphNodeOpacity, setGraphNodeOpacity] = useState(false);
  const [theme, setTheme] = useState<AppTheme>("clean");
  const viewportKey = useMemo(() => {
    const personaIds = Array.from(new Set((rawNodes || []).map((n: any) => n?.data?.persona_slug || n?.data?.persona_id || n?.id).filter(Boolean))).slice(0, 3).join("|");
    return `knowledge-graph-viewport:${personaIds || "global"}:${mode}:${focusNodeId || "all"}`;
  }, [rawNodes, mode, focusNodeId]);
  const initialViewportDone = useRef(false);
  const lastFocusNodeId = useRef<string | null | undefined>(undefined);
  const visibleEdges = useMemo(
    () => filterEdgesForMode(rawEdges as Edge[], mode),
    [rawEdges, mode],
  );

  useEffect(() => {
    setGraphNodeOpacity(readGraphNodeOpacity());
    setTheme(readTheme());
    const onAppearanceChange = () => setGraphNodeOpacity(readGraphNodeOpacity());
    window.addEventListener("ai-brain-graph-appearance-change", onAppearanceChange);
    const observer = new MutationObserver(() => setTheme(readTheme()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      window.removeEventListener("ai-brain-graph-appearance-change", onAppearanceChange);
      observer.disconnect();
    };
  }, []);

  const treeGraph = useMemo(() => {
    if (mode === "graph") {
      return {
        nodes: rawNodes as Node<GraphNodeData>[],
        edges: visibleEdges as Edge<GraphEdgeData>[],
        primaryEdgeIds: new Set<string>(),
      };
    }
    return buildTreeFromGraph(
      rawNodes as Node<GraphNodeData>[],
      visibleEdges as Edge<GraphEdgeData>[],
      !showAllEdges,
    );
  }, [rawNodes, visibleEdges, showAllEdges, mode]);

  const activeRawNodes = treeGraph.nodes as Node[];
  const activeRawEdges = treeGraph.edges as Edge[];

  const neighborIds = useMemo(() => {
    const ids = new Set<string>();
    if (!focusNodeId) return ids;
    ids.add(focusNodeId);
    for (const edge of activeRawEdges) {
      if (edge.source === focusNodeId) ids.add(edge.target);
      if (edge.target === focusNodeId) ids.add(edge.source);
    }
    return ids;
  }, [activeRawEdges, focusNodeId]);

  // Search filter — matched nodes get full opacity, others fade.
  const fold = (s: string) =>
    (s || "").toString().toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
  const q = fold(searchQuery || "");
  const isSearchHit = useCallback(
    (n: any) => {
      if (!q) return true;
      const data = n.data || {};
      return (
        fold(data.label).includes(q) ||
        fold(data.slug || "").includes(q) ||
        fold(data.content_type || "").includes(q) ||
        fold(data.node_type || "").includes(q)
      );
    },
    [q],
  );

  // Decorate edges with style+marker based on tier and focus path.
  const styledEdges = useMemo<Edge[]>(() => {
    return activeRawEdges.map((e) => {
      const data = (e.data || {}) as GraphEdgeData;
      const inPath = !!data.in_focus_path;
      const style = edgeStyle(data, inPath);
      const directional = data.directional !== false;
      const dimmed = focusNodeId && e.source !== focusNodeId && e.target !== focusNodeId && !inPath;
      return {
        ...e,
        type: "deletable",
        animated: inPath || (mode === "graph" && (data.primary || data.tier === "strong")),
        style: dimmed ? { ...style, strokeOpacity: 0.12 } : style,
        markerEnd: directional && data.tier !== "auxiliary" ? {
          type: MarkerType.ArrowClosed,
          color: (style?.stroke as string) || "rgba(255,255,255,0.35)",
          width: 14,
          height: 14,
        } : undefined,
        data: { ...data, onDelete: onDeleteEdge, viewMode: mode },
      };
    });
  }, [activeRawEdges, focusNodeId, mode, onDeleteEdge]);

  // Decorate nodes with search/focus state for fade-out.
  const decoratedNodes = useMemo<Node[]>(() => {
    return (activeRawNodes as Node[]).map((n) => {
      const data = n.data as GraphNodeData;
      const matchesSearch = !q || isSearchHit(n);
      const nearFocus = !focusNodeId || neighborIds.has(n.id) || data.in_focus_path || data.is_focus;
      const visible = matchesSearch && nearFocus;
      return {
        ...n,
        data: { ...data, _faded: !visible, _viewMode: mode, _nodeId: n.id, _graphNodeOpacity: graphNodeOpacity, _theme: theme },
        style: visible ? n.style : { ...n.style, opacity: 0.18 },
      };
    });
  }, [activeRawNodes, q, isSearchHit, focusNodeId, neighborIds, mode, graphNodeOpacity, theme]);

  const laid = useMemo<Node[]>(() => {
    const layoutFn = mode === "graph" ? applyLayoutGraphSeed : mode === "semantic_tree" ? applyLayoutTree : applyLayoutLayered;
    return layoutFn(decoratedNodes, styledEdges, branchDistance);
  }, [decoratedNodes, styledEdges, mode, branchDistance]);

  const [nodes, setNodes, onNodesChange] = useNodesState(laid);
  const [edges, setEdges, onEdgesChange] = useEdgesState(styledEdges);

  useEffect(() => {
    setNodes(laid);
  }, [laid, setNodes]);

  useEffect(() => {
    setEdges(styledEdges);
  }, [styledEdges, setEdges]);

  useEffect(() => {
    if (!laid.length) return;
    const focusChanged = lastFocusNodeId.current !== focusNodeId;
    lastFocusNodeId.current = focusNodeId;
    const stored = typeof window !== "undefined" ? window.localStorage.getItem(viewportKey) : null;
    if (!initialViewportDone.current && stored && !focusNodeId) {
      try {
        const parsed = JSON.parse(stored) as StoredViewport;
        if (Number.isFinite(parsed.x) && Number.isFinite(parsed.y) && Number.isFinite(parsed.zoom)) {
          setViewport(parsed, { duration: 0 });
          initialViewportDone.current = true;
          return;
        }
      } catch {
        // Ignore corrupt viewport state and fall back to first fit.
      }
    }
    if (initialViewportDone.current && !focusChanged) return;
    const targetId =
      focusNodeId
      || laid.find((node) => (node.data as GraphNodeData)?.node_type === "persona")?.id
      || laid[0]?.id;
    if (!targetId) return;
    const handle = window.setTimeout(() => {
      fitView({
        nodes: focusNodeId ? [{ id: targetId }] : undefined,
        duration: focusChanged && focusNodeId ? 400 : 0,
        padding: mode === "semantic_tree" && !focusNodeId ? 0.2 : 0.55,
        maxZoom: mode === "graph" ? 1.1 : 1.0,
      });
      initialViewportDone.current = true;
    }, 60);
    return () => window.clearTimeout(handle);
  }, [fitView, focusNodeId, laid, mode, setViewport, viewportKey]);

  const saveViewport = useCallback(() => {
    if (typeof window === "undefined") return;
    const viewport = getViewport();
    window.localStorage.setItem(viewportKey, JSON.stringify({
      x: viewport.x,
      y: viewport.y,
      zoom: viewport.zoom,
    }));
  }, [getViewport, viewportKey]);

  const handleClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeClick(node);
    },
    [onNodeClick],
  );

  const handleConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target || connection.source === connection.target) return;
      onConnectNodes?.(connection.source, connection.target);
    },
    [onConnectNodes],
  );

  useEffect(() => {
    const blur = () => setPanActive(false);
    const down = (event: KeyboardEvent) => {
      const configured = window.localStorage.getItem("ai-brain-graph-pan-key") || "Control";
      if (event.key === configured || (configured === "Control" && event.ctrlKey)) setPanActive(true);
    };
    const up = (event: KeyboardEvent) => {
      const configured = window.localStorage.getItem("ai-brain-graph-pan-key") || "Control";
      if (event.key === configured || !event.ctrlKey) setPanActive(false);
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
    };
  }, []);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={handleConnect}
      onNodeClick={handleClick}
      onSelectionChange={({ nodes: selected }) => onSelectionChange?.(selected)}
      onMoveEnd={saveViewport}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      connectionMode={ConnectionMode.Loose}
      connectionRadius={28}
      edgesFocusable
      edgesUpdatable={false}
      selectNodesOnDrag={false}
      selectionOnDrag={!panActive}
      selectionKeyCode={null}
      panOnDrag={panActive}
      nodesDraggable
      fitViewOptions={{ padding: 0.18 }}
      minZoom={0.08}
      maxZoom={2}
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="rgba(255,255,255,0.04)" />
      <Controls showInteractive={false} />
      <MiniMap
        nodeColor={(n) => {
          const c = (n.data as GraphNodeData)?.color;
          return c || "#3d4559";
        }}
        maskColor="rgba(5,7,9,0.8)"
      />
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
