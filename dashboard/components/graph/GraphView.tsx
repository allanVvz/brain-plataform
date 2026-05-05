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
  KnowledgeViewMode,
} from "./knowledgeGraphLayout";

// â”€â”€ Types â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

type ViewMode = KnowledgeViewMode;

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

// â”€â”€ Layout helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function nodeSize(data: GraphNodeData): { w: number; h: number } {
  const importance = data.importance ?? 0.5;
  // Persona always wide
  if (data.node_type === "persona") return { w: 180, h: 56 };
  if (importance >= 0.85) return { w: 170, h: 52 };
  if (importance >= 0.65) return { w: 140, h: 44 };
  if (importance >= 0.50) return { w: 120, h: 38 };
  return { w: 104, h: 32 };
}

// Map level (0-95) â†’ dagre rank bucket so all persona share rank 0,
// brand/entity rank 1, campaign/product rank 2, etc.
function levelToRank(level: number | undefined): number {
  if (level == null) return 5;
  if (level >= 118) return 12;     // embedded/RAG root stays far below the tree
  if (level >= 105) return 11;     // gallery root sits below ordinary knowledge
  if (level <= 0) return 0;        // persona
  if (level <= 15) return 1;       // entity
  if (level <= 25) return 2;       // brand
  if (level <= 35) return 3;       // campaign
  if (level <= 45) return 4;       // product
  if (level <= 55) return 5;       // briefing/audience
  if (level <= 65) return 6;       // tone/rule
  if (level <= 72) return 7;       // copy
  if (level <= 78) return 8;       // faq
  if (level <= 85) return 9;       // asset
  return 10;                       // tag/mention/technical
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
    const r = levelToRank((n.data as GraphNodeData).level);
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
  const baseMaxY = Math.max(
    0,
    ...centered
      .filter((node) => !["embedded", "gallery"].includes(String((node.data as GraphNodeData)?.node_type || "")))
      .map((node) => node.position.y),
  );
  const galleryNodes = centered.filter((node) => (node.data as GraphNodeData)?.node_type === "gallery");
  const embeddedNodes = centered.filter((node) => (node.data as GraphNodeData)?.node_type === "embedded");
  if (!embeddedNodes.length && !galleryNodes.length) return centered;
  const galleryOffsetStart = -((galleryNodes.length - 1) * 160) / 2;
  const embeddedOffsetStart = -((embeddedNodes.length - 1) * 160) / 2;
  let galleryIndex = 0;
  let embeddedIndex = 0;
  return centered.map((node) => {
    const nodeType = (node.data as GraphNodeData)?.node_type;
    if (nodeType === "gallery") {
      const x = galleryOffsetStart + galleryIndex * 160;
      galleryIndex += 1;
      return { ...node, position: { x, y: baseMaxY + 180 } };
    }
    if (nodeType === "embedded") {
      const x = embeddedOffsetStart + embeddedIndex * 160;
      embeddedIndex += 1;
      return { ...node, position: { x, y: baseMaxY + 340 } };
    }
    return node;
  });
}

// â”€â”€ Filtering by mode â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function filterEdgesForMode(edges: Edge[], mode: ViewMode): Edge[] {
  return edges;
}

// â”€â”€ Edge style by tier â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function edgeStyle(data: GraphEdgeData | undefined, isInPath: boolean): Edge["style"] {
  const tier = data?.tier || "auxiliary";
  if (isInPath) {
    return { stroke: "#7c6fff", strokeWidth: 3, strokeOpacity: 0.95 };
  }
  if (data?.embedded_edge) {
    return { stroke: "rgba(255,255,255,0.78)", strokeWidth: 2.6, strokeOpacity: 0.88 };
  }
  if (data?.gallery_edge) {
    return { stroke: "rgba(240,171,252,0.78)", strokeWidth: 2.4, strokeOpacity: 0.86 };
  }
  if (data?.primary) {
    return { stroke: "rgba(190,210,255,0.74)", strokeWidth: 2.4, strokeOpacity: 0.86 };
  }
  if (data?.secondary) {
    return { stroke: "rgba(170,190,220,0.22)", strokeWidth: 1, strokeOpacity: 0.28, strokeDasharray: "5 5" };
  }
  if (tier === "strong") {
    return { stroke: "rgba(125,211,252,0.55)", strokeWidth: 2.2, strokeOpacity: 0.72 };
  }
  if (tier === "structural") {
    return { stroke: "rgba(255,255,255,0.34)", strokeWidth: 1.4, strokeOpacity: 0.48 };
  }
  if (tier === "curation") {
    return { stroke: "#f87171", strokeWidth: 2, strokeOpacity: 0.7 };
  }
  // auxiliary
  return { stroke: "rgba(255,255,255,0.18)", strokeWidth: 1, strokeOpacity: 0.25, strokeDasharray: "4 4" };
}

// â”€â”€ Node component â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function PersonaNode({ data, selected }: NodeProps) {
  const d = data as GraphNodeData;
  const focused = !!d.is_focus;
  const inPath = !!d.in_focus_path;
  return (
    <div
      className={`rounded-xl border-2 px-4 py-2.5 text-sm font-semibold tracking-wide cursor-pointer transition-all ${selected || focused ? "scale-105" : ""}`}
      style={{
        minWidth: 160, textAlign: "center",
        borderColor: focused ? "#a78bfa" : (d.color || "#7c6fff"),
        background: `${d.color || "#7c6fff"}1A`,
        color: d.color || "#a78bfa",
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
  const color = isEmbedded ? "#ffffff" : isGallery ? "#f0abfc" : d.color || "#94a3b8";
  const isGraphMode = d._viewMode === "graph";

  return (
    <div
      className={`relative rounded-lg border glass cursor-pointer transition-all ${focused ? "ring-2 ring-obs-violet" : ""} ${selected ? "ring-1 ring-obs-violet" : ""}`}
      style={{
        minWidth: importance >= 0.85 ? 150 : importance >= 0.65 ? 130 : importance >= 0.5 ? 110 : 96,
        maxWidth: importance >= 0.85 ? 180 : 150,
        padding: importance >= 0.85 ? "8px 12px" : importance >= 0.5 ? "6px 10px" : "4px 8px",
        borderColor: isEmbedded ? "rgba(255,255,255,0.95)" : isGallery ? "rgba(240,171,252,0.95)" : focused ? "#a78bfa" : `${color}99`,
        background: isEmbedded
          ? "linear-gradient(145deg, rgba(255,255,255,0.16), rgba(30,41,59,0.62))"
          : isGallery
            ? "linear-gradient(145deg, rgba(240,171,252,0.20), rgba(88,28,135,0.42))"
          : focused ? `${color}33` : isGraphMode ? `radial-gradient(circle at 35% 25%, ${color}3D, ${color}14 58%, rgba(5,7,9,0.68))` : `${color}14`,
        boxShadow: focused
          ? `0 0 20px ${color}CC, 0 0 44px ${color}33`
          : isEmbedded
            ? "0 0 18px rgba(255,255,255,0.22), inset 0 0 18px rgba(255,255,255,0.08)"
          : isGallery
            ? "0 0 18px rgba(240,171,252,0.28), inset 0 0 18px rgba(240,171,252,0.08)"
          : isGraphMode
            ? `0 0 ${10 + importance * 18}px ${color}55`
            : (inPath ? `0 0 10px ${color}77` : "none"),
        opacity: isAuxiliary ? 0.75 : 1,
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
        <span className="text-[9px] uppercase tracking-wider truncate flex-1" style={{ color: `${color}DD` }}>
          {d.node_type || d.content_type}
        </span>
        {isVideo && <span className="text-[8px] text-obs-amber">â–¶</span>}
        {isImage && <span className="text-[8px] text-obs-slate">â¬›</span>}
        {typeof d.graph_distance === "number" && d.graph_distance > 0 && (
          <span className="text-[8px] text-obs-faint">d{d.graph_distance}</span>
        )}
      </div>
      <div
        className="font-medium truncate"
        style={{
          color: focused ? "#fff" : "rgba(255,255,255,0.85)",
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

// â”€â”€ Main component â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function GraphInner({ rawNodes, rawEdges, onNodeClick, onSelectionChange, onConnectNodes, onDeleteEdge, mode, searchQuery, focusNodeId, showAllEdges = false, branchDistance = 48 }: GraphViewProps) {
  const { fitView, getViewport, setViewport } = useReactFlow();
  const [panActive, setPanActive] = useState(false);
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

  const treeGraph = useMemo(() => {
    return buildTreeFromGraph(
      rawNodes as Node<GraphNodeData>[],
      visibleEdges as Edge<GraphEdgeData>[],
      !showAllEdges,
    );
  }, [rawNodes, visibleEdges, showAllEdges]);

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

  // Search filter â€” matched nodes get full opacity, others fade.
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
        data: { ...data, _faded: !visible, _viewMode: mode, _nodeId: n.id },
        style: visible ? n.style : { ...n.style, opacity: 0.18 },
      };
    });
  }, [activeRawNodes, q, isSearchHit, focusNodeId, neighborIds, mode]);

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
        nodes: [{ id: targetId }],
        duration: focusChanged && focusNodeId ? 400 : 0,
        padding: 0.55,
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


