export interface GraphJsonV2Node {
  id: string;
  slug?: string;
  node_type?: string;
  label?: string;
  title?: string;
  status?: string;
  validated?: boolean;
  data?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  position?: { x?: number; y?: number };
}

export interface GraphJsonV2Edge {
  id: string;
  source: string;
  target: string;
  relation?: string;
  relation_type?: string;
  primary_tree?: boolean;
  invalid?: boolean;
  metadata?: Record<string, unknown>;
}

export interface GraphJsonV2Document {
  version?: string;
  nodes?: GraphJsonV2Node[];
  edges?: GraphJsonV2Edge[];
  layout?: { positions?: Record<string, { x?: number; y?: number } | [number, number]> };
  meta?: Record<string, unknown>;
}

function normalizePosition(position: { x?: number; y?: number } | [number, number] | undefined) {
  if (Array.isArray(position)) {
    return {
      x: Number.isFinite(Number(position[0])) ? Number(position[0]) : 0,
      y: Number.isFinite(Number(position[1])) ? Number(position[1]) : 0,
    };
  }
  return {
    x: Number.isFinite(Number(position?.x)) ? Number(position?.x) : 0,
    y: Number.isFinite(Number(position?.y)) ? Number(position?.y) : 0,
  };
}

function toGraphNode(
  node: GraphJsonV2Node,
  positions: Record<string, { x?: number; y?: number } | [number, number]>,
) {
  const flexibleData = {
    ...(node.data || {}),
    ...(node.metadata || {}),
  };
  const nodeType = node.node_type || String(flexibleData.node_type || "");
  const label = node.label || node.title || String(flexibleData.label || "") || node.slug || node.id;
  return {
    id: node.id,
    type: nodeType === "persona" ? "personaNode" : "knowledgeNode",
    position: normalizePosition(positions[node.id] || node.position),
    data: {
      ...flexibleData,
      slug: node.slug || flexibleData.slug,
      node_type: nodeType,
      label,
      validated: node.validated ?? flexibleData.validated,
      status: node.status || flexibleData.status,
      metadata: flexibleData,
    },
  };
}

function toGraphEdge(edge: GraphJsonV2Edge) {
  const metadata = edge.metadata || {};
  const relationType =
    edge.relation_type ||
    edge.relation ||
    String(metadata.relation_type || metadata.relation || "") ||
    "contains";
  const primaryTree = edge.primary_tree === true || metadata.primary_tree === true;
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    data: {
      ...metadata,
      relation_type: relationType,
      primary_tree: primaryTree,
      invalid: edge.invalid === true,
      metadata,
    },
  };
}

export function parseGraphJsonV2Payload(payload: any): { nodes: any[]; edges: any[]; meta: Record<string, unknown> } | null {
  const graphJson = payload?.graph_json || payload?.document?.graph_json || payload?.document || payload;
  if (!graphJson || typeof graphJson !== "object") return null;
  const doc = graphJson as GraphJsonV2Document;
  const nodes = Array.isArray(doc.nodes) ? doc.nodes : [];
  const edges = Array.isArray(doc.edges) ? doc.edges : [];
  if (!nodes.length && !edges.length) return null;
  const positions = doc.layout?.positions || {};
  return {
    nodes: nodes.map((node) => toGraphNode(node, positions)),
    edges: edges.map(toGraphEdge),
    meta: {
      ...(doc.meta || {}),
      total_items: nodes.length,
      semantic_nodes: nodes.length,
      semantic_edges: edges.length,
    },
  };
}
