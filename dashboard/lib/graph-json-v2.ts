export interface GraphJsonV2Node {
  id: string;
  slug?: string;
  node_type?: string;
  label?: string;
  title?: string;
  status?: string;
  validated?: boolean;
  parent_id?: string | null;
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
  schema_version?: string;
  graph_id?: string;
  persona_slug?: string;
  status?: string;
  nodes?: GraphJsonV2Node[];
  edges?: GraphJsonV2Edge[];
  layout?: { positions?: Record<string, [number, number] | { x?: number; y?: number }> };
  meta?: Record<string, unknown>;
}

function positionFor(raw: [number, number] | { x?: number; y?: number } | undefined, fallback?: { x?: number; y?: number }) {
  if (Array.isArray(raw)) return { x: Number(raw[0] || 0), y: Number(raw[1] || 0) };
  const pos = raw || fallback || {};
  return { x: Number(pos.x || 0), y: Number(pos.y || 0) };
}

function toGraphNode(node: GraphJsonV2Node, positions: NonNullable<GraphJsonV2Document["layout"]>["positions"] = {}) {
  const data = node.data || node.metadata || {};
  return {
    id: node.id,
    position: positionFor(positions[node.id], node.position),
    data: {
      slug: node.slug,
      node_type: node.node_type,
      label: node.label || node.title || node.slug || node.id,
      validated: node.validated,
      status: node.status || (data.status as string | undefined),
      parent_id: node.parent_id,
      ...data,
      metadata: data,
    },
  };
}

function toGraphEdge(edge: GraphJsonV2Edge) {
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    data: {
      relation_type: edge.relation_type || edge.relation || "main",
      primary_tree: edge.primary_tree === true,
      invalid: edge.invalid === true,
      ...(edge.metadata || {}),
      metadata: edge.metadata || {},
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
      schema_version: doc.schema_version,
      graph_id: doc.graph_id,
      persona_slug: doc.persona_slug,
      graph_status: doc.status,
      total_items: nodes.length,
      semantic_nodes: nodes.length,
      semantic_edges: edges.length,
    },
  };
}
