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

// ── Dagre layout ───────────────────────────────────────────────

const NODE_W = { personaNode: 160, knowledgeNode: 140 };
const NODE_H = 48;

function applyDagreLayout(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", ranksep: 80, nodesep: 20, edgesep: 10 });

  nodes.forEach((n) => {
    const w = n.type === "personaNode" ? NODE_W.personaNode : NODE_W.knowledgeNode;
    g.setNode(n.id, { width: w, height: NODE_H });
  });
  edges.forEach((e) => g.setEdge(e.source, e.target));

  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    const w = n.type === "personaNode" ? NODE_W.personaNode : NODE_W.knowledgeNode;
    return {
      ...n,
      position: { x: pos.x - w / 2, y: pos.y - NODE_H / 2 },
    };
  });
}

// ── Node components ────────────────────────────────────────────

const PERSONA_STYLES: Record<string, string> = {
  persona: "border-obs-violet bg-obs-violet-glow glow-violet text-obs-violet",
  orphan:  "border-obs-faint bg-obs-raised text-obs-subtle",
};

const KI_STYLES: Record<string, { ring: string; dot: string; label: string }> = {
  validated: {
    ring:  "border-obs-slate/40",
    dot:   "bg-obs-slate",
    label: "text-obs-text/80",
  },
  pending: {
    ring:  "border-obs-amber/40 glow-amber",
    dot:   "bg-obs-amber",
    label: "text-obs-amber",
  },
  rejected: {
    ring:  "border-obs-rose/30",
    dot:   "bg-obs-rose",
    label: "text-obs-subtle line-through",
  },
};

function PersonaNode({ data, selected }: NodeProps) {
  const style = PERSONA_STYLES[data.nodeClass] || PERSONA_STYLES.persona;
  return (
    <div
      className={`rounded-xl border px-4 py-2.5 text-sm font-semibold tracking-wide cursor-pointer transition-all ${style} ${selected ? "scale-105" : ""}`}
      style={{ minWidth: 140, textAlign: "center" }}
    >
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div className="text-[10px] uppercase tracking-widest opacity-60 mb-0.5">persona</div>
      {data.label}
    </div>
  );
}

function KnowledgeNode({ data, selected }: NodeProps) {
  const cls = KI_STYLES[data.nodeClass] || KI_STYLES.pending;
  const isVideo = ["mp4", "mov", "webm"].includes(data.file_type || "");
  const isImage = ["png", "jpg", "jpeg", "webp", "svg"].includes(data.file_type || "");

  return (
    <div
      className={`rounded-lg border glass px-3 py-2 cursor-pointer transition-all node-obs ${cls.ring} ${selected ? "ring-1 ring-obs-violet" : ""}`}
      style={{ minWidth: 120, maxWidth: 140 }}
    >
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
      <div className="flex items-center gap-1.5 mb-1">
        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cls.dot}`} />
        <span className="text-[9px] text-obs-subtle uppercase tracking-wider truncate">{data.content_type}</span>
        {isVideo && <span className="text-[8px] text-obs-amber ml-auto">▶</span>}
        {isImage && <span className="text-[8px] text-obs-slate ml-auto">⬛</span>}
      </div>
      <div className={`text-xs font-medium truncate ${cls.label}`}>{data.label}</div>
    </div>
  );
}

const nodeTypes: NodeTypes = {
  personaNode: PersonaNode,
  knowledgeNode: KnowledgeNode,
};

// ── Main component ─────────────────────────────────────────────

function GraphInner({ rawNodes, rawEdges, onNodeClick }: GraphViewProps) {
  const [filter, setFilter] = useState<"all" | "pending" | "validated">("all");

  const { filteredNodes, filteredEdges } = useMemo(() => {
    let fn = rawNodes;
    if (filter === "pending") fn = rawNodes.filter((n) => n.type === "personaNode" || n.data?.nodeClass === "pending");
    if (filter === "validated") fn = rawNodes.filter((n) => n.type === "personaNode" || n.data?.nodeClass === "validated");
    const ids = new Set(fn.map((n) => n.id));
    const fe = rawEdges.filter((e) => ids.has(e.source) && ids.has(e.target));
    return { filteredNodes: fn, filteredEdges: fe };
  }, [rawNodes, rawEdges, filter]);

  const laid = useMemo(
    () => applyDagreLayout(filteredNodes as Node[], filteredEdges as Edge[]),
    [filteredNodes, filteredEdges]
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(laid);
  const [edges, , onEdgesChange] = useEdgesState(filteredEdges as Edge[]);

  useEffect(() => {
    setNodes(applyDagreLayout(filteredNodes as Node[], filteredEdges as Edge[]));
  }, [filteredNodes, filteredEdges]);

  const handleClick = useCallback(
    (_: React.MouseEvent, node: Node) => onNodeClick(node as GraphNode),
    [onNodeClick]
  );

  const pendingCount = rawNodes.filter((n) => n.data?.nodeClass === "pending").length;

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={handleClick}
      nodeTypes={nodeTypes}
      fitView
      fitViewOptions={{ padding: 0.15 }}
      minZoom={0.2}
      maxZoom={2}
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="rgba(255,255,255,0.04)" />
      <Controls showInteractive={false} />
      <MiniMap
        nodeColor={(n) => {
          const cls = (n.data as any)?.nodeClass;
          if (cls === "persona") return "#7c6fff";
          if (cls === "pending") return "#f59e0b";
          if (cls === "validated") return "#64748b";
          return "#3d4559";
        }}
        maskColor="rgba(5,7,9,0.8)"
      />

      <Panel position="top-left">
        <div className="flex gap-1.5">
          {(["all", "pending", "validated"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`text-[10px] px-2.5 py-1 rounded-md border transition-colors ${
                filter === f
                  ? "bg-obs-violet/20 border-obs-violet text-obs-violet"
                  : "glass border-white/10 text-obs-subtle hover:text-obs-text"
              }`}
            >
              {f === "all" ? `Todos (${rawNodes.length})` : f === "pending" ? `Pendentes (${pendingCount})` : "Validados"}
            </button>
          ))}
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
