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
  MarkerType,
  useReactFlow,
} from "reactflow";
import dagre from "dagre";
import "reactflow/dist/style.css";
import {
  buildNeuronGraphLayout,
  buildTreeFromGraph,
  GraphEdgeData,
  GraphNodeData,
  KnowledgeViewMode,
} from "./knowledgeGraphLayout";

// ── Types ──────────────────────────────────────────────────────

type ViewMode = KnowledgeViewMode;

interface GraphViewProps {
  rawNodes: any[];
  rawEdges: any[];
  onNodeClick: (node: any) => void;
  mode: ViewMode;
  searchQuery?: string;
  focusNodeId?: string | null;
  onlyPrimaryTreeEdges?: boolean;
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

// Map level (0-95) → dagre rank bucket so all persona share rank 0,
// brand/entity rank 1, campaign/product rank 2, etc.
function levelToRank(level: number | undefined): number {
  if (level == null) return 5;
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

function applyLayoutLayered(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", ranksep: 80, nodesep: 24, edgesep: 8, ranker: "network-simplex" });

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

function applyLayoutGraphSeed(nodes: Node[], edges: Edge[]): Node[] {
  return buildNeuronGraphLayout(nodes as Node<GraphNodeData>[], edges as Edge<GraphEdgeData>[]);
}

function applyLayoutTree(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", ranksep: 92, nodesep: 34, edgesep: 10, ranker: "tight-tree" });
  nodes.forEach((n) => {
    const { w, h } = nodeSize(n.data as GraphNodeData);
    g.setNode(n.id, { width: w, height: h });
  });
  edges
    .filter((e) => (e.data as GraphEdgeData | undefined)?.primary)
    .forEach((e) => g.setEdge(e.source, e.target, { weight: 2 }));
  dagre.layout(g);
  return nodes.map((n) => {
    const pos = g.node(n.id);
    if (!pos) return n;
    const { w, h } = nodeSize(n.data as GraphNodeData);
    return { ...n, position: { x: pos.x - w / 2, y: pos.y - h / 2 } };
  });
}

// ── Filtering by mode ──────────────────────────────────────────

function filterEdgesForMode(edges: Edge[], mode: ViewMode): Edge[] {
  return edges;
}

// ── Edge style by tier ─────────────────────────────────────────

function edgeStyle(data: GraphEdgeData | undefined, isInPath: boolean): Edge["style"] {
  const tier = data?.tier || "auxiliary";
  if (isInPath) {
    return { stroke: "#7c6fff", strokeWidth: 3, strokeOpacity: 0.95 };
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

// ── Node component ─────────────────────────────────────────────

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
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
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
  const color = d.color || "#94a3b8";
  const isGraphMode = d._viewMode === "graph";

  return (
    <div
      className={`rounded-lg border glass cursor-pointer transition-all ${focused ? "ring-2 ring-obs-violet" : ""} ${selected ? "ring-1 ring-obs-violet" : ""}`}
      style={{
        minWidth: importance >= 0.85 ? 150 : importance >= 0.65 ? 130 : importance >= 0.5 ? 110 : 96,
        maxWidth: importance >= 0.85 ? 180 : 150,
        padding: importance >= 0.85 ? "8px 12px" : importance >= 0.5 ? "6px 10px" : "4px 8px",
        borderColor: focused ? "#a78bfa" : `${color}99`,
        background: focused ? `${color}33` : isGraphMode ? `radial-gradient(circle at 35% 25%, ${color}3D, ${color}14 58%, rgba(5,7,9,0.68))` : `${color}14`,
        boxShadow: focused
          ? `0 0 20px ${color}CC, 0 0 44px ${color}33`
          : isGraphMode
            ? `0 0 ${10 + importance * 18}px ${color}55`
            : (inPath ? `0 0 10px ${color}77` : "none"),
        opacity: isAuxiliary ? 0.75 : 1,
      }}
    >
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
      <div className="flex items-center gap-1.5 mb-0.5">
        <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: color }} />
        <span className="text-[9px] uppercase tracking-wider truncate flex-1" style={{ color: `${color}DD` }}>
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

// ── Main component ─────────────────────────────────────────────

function GraphInner({ rawNodes, rawEdges, onNodeClick, mode, searchQuery, focusNodeId, onlyPrimaryTreeEdges = true }: GraphViewProps) {
  const { fitView } = useReactFlow();
  const visibleEdges = useMemo(
    () => filterEdgesForMode(rawEdges as Edge[], mode),
    [rawEdges, mode],
  );

  const treeGraph = useMemo(() => {
    if (mode !== "semantic_tree") {
      return { nodes: rawNodes as Node<GraphNodeData>[], edges: visibleEdges as Edge<GraphEdgeData>[] };
    }
    return buildTreeFromGraph(
      rawNodes as Node<GraphNodeData>[],
      visibleEdges as Edge<GraphEdgeData>[],
      onlyPrimaryTreeEdges,
    );
  }, [mode, rawNodes, visibleEdges, onlyPrimaryTreeEdges]);

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
    (s || "").toString().toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "");
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
        type: mode === "graph" ? "default" : "smoothstep",
        animated: inPath || (mode === "graph" && (data.primary || data.tier === "strong")),
        style: dimmed ? { ...style, strokeOpacity: 0.12 } : style,
        markerEnd: directional && data.tier !== "auxiliary" ? {
          type: MarkerType.ArrowClosed,
          color: (style?.stroke as string) || "rgba(255,255,255,0.35)",
          width: 14,
          height: 14,
        } : undefined,
        // Secondary edges stay visible in graph/layered mode and are dimmed
        // when focus is active.
      };
    });
  }, [activeRawEdges, focusNodeId, mode]);

  // Decorate nodes with search/focus state for fade-out.
  const decoratedNodes = useMemo<Node[]>(() => {
    return (activeRawNodes as Node[]).map((n) => {
      const data = n.data as GraphNodeData;
      const matchesSearch = !q || isSearchHit(n);
      const nearFocus = !focusNodeId || neighborIds.has(n.id) || data.in_focus_path || data.is_focus;
      const visible = matchesSearch && nearFocus;
      return {
        ...n,
        data: { ...data, _faded: !visible, _viewMode: mode },
        style: visible ? n.style : { ...n.style, opacity: 0.18 },
      };
    });
  }, [activeRawNodes, q, isSearchHit, focusNodeId, neighborIds, mode]);

  const laid = useMemo<Node[]>(() => {
    const layoutFn = mode === "graph" ? applyLayoutGraphSeed : mode === "semantic_tree" ? applyLayoutTree : applyLayoutLayered;
    return layoutFn(decoratedNodes, styledEdges);
  }, [decoratedNodes, styledEdges, mode]);

  const [nodes, setNodes, onNodesChange] = useNodesState(laid);
  const [edges, setEdges, onEdgesChange] = useEdgesState(styledEdges);

  useEffect(() => {
    setNodes(laid);
  }, [laid, setNodes]);

  useEffect(() => {
    setEdges(styledEdges);
  }, [styledEdges, setEdges]);

  useEffect(() => {
    const targetId =
      focusNodeId
      || laid.find((node) => (node.data as GraphNodeData)?.node_type === "persona")?.id
      || laid[0]?.id;
    if (!targetId) return;
    const handle = window.setTimeout(() => {
      fitView({
        nodes: [{ id: targetId }],
        duration: 400,
        padding: 0.55,
        maxZoom: mode === "graph" ? 1.1 : 1.0,
      });
    }, 60);
    return () => window.clearTimeout(handle);
  }, [fitView, focusNodeId, laid, mode]);

  const handleClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeClick(node);
    },
    [onNodeClick],
  );

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={handleClick}
      nodeTypes={nodeTypes}
      fitView
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
