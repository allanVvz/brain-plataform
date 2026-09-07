export type GraphBundleSource = "draft" | "publication";
export type GraphBundleState = "draft" | "blocked" | "staged" | "active";

export interface GraphBundleVersion {
  ref: string;
  source: GraphBundleSource;
  origin: string;
  state: GraphBundleState;
  label: string;
  version?: string | number | null;
  checksum?: string | null;
  runtime_checksum?: string | null;
  compiler_version?: string | null;
  validation_error_count: number;
  updated_at?: string | null;
}

export interface GraphBundleVersionsPayload {
  backend: "v3";
  persona: { id: string; slug: string; name?: string | null };
  versions: GraphBundleVersion[];
  default_ref?: string | null;
  read_only: boolean;
}

export interface GraphBundleViewPayload {
  backend: "v3";
  persona: { id: string; slug: string; name?: string | null };
  source: GraphBundleSource;
  ref: string;
  origin: string;
  state: GraphBundleState;
  version?: string | number | null;
  checksum?: string | null;
  runtime_checksum?: string | null;
  compiler_version?: string | null;
  disposition?: string | null;
  validation_errors: string[];
  document: Record<string, any>;
  branch_memberships: Record<string, Record<string, any>>;
  read_only: boolean;
}

export interface GraphBundleDraftSnapshot {
  draft_ref: string;
  persona_id: string;
  persona_slug: string;
  base_publication_id: string;
  base_runtime_checksum: string;
  revision: number;
  draft_checksum: string;
  bundle: Record<string, any>;
  state: "draft" | "blocked" | "published";
  change_summary?: {
    faq_nodes_requiring_review?: string[];
    nodes_changed?: string[];
    edges_changed?: string[];
  };
}

export type GraphBundleDraftOperation =
  | { op: "update_node"; node_id: string; patch: Record<string, any> }
  | { op: "add_node"; node: Record<string, any> }
  | { op: "archive_node"; node_id: string }
  | { op: "add_edge"; edge: Record<string, any> }
  | { op: "revoke_edge"; edge_id: string }
  | { op: "approve_faq"; node_id: string }
  | { op: "reject_faq"; node_id: string }
  | { op: "add_faq_proposal"; node_id: string; slug: string; question: string; answer: string; source: string; source_node_id: string; source_node_type: string; branch_path: string[]; question_aliases: string[]; generator: string; generation_batch_id: string };

export function draftSnapshotToView(draft: GraphBundleDraftSnapshot): GraphBundleViewPayload {
  return {
    backend: "v3",
    persona: { id: draft.persona_id, slug: draft.persona_slug },
    source: "draft",
    ref: draft.draft_ref,
    origin: "system_events",
    state: draft.state === "blocked" ? "blocked" : "draft",
    checksum: draft.draft_checksum,
    runtime_checksum: null,
    validation_errors: [],
    document: draft.bundle,
    branch_memberships: {},
    read_only: false,
  };
}

const NODE_COLORS: Record<string, string> = {
  persona: "#8b5cf6",
  brand: "#6366f1",
  briefing: "#3b82f6",
  campaign: "#0ea5e9",
  audience: "#14b8a6",
  product_group: "#22c55e",
  product: "#84cc16",
  offer: "#eab308",
  copy: "#f59e0b",
  faq: "#f97316",
  rule: "#ef4444",
  tone: "#ec4899",
  asset: "#a855f7",
  gallery: "#d946ef",
  embedded: "#64748b",
};

export function graphBundleLayoutScope(view: GraphBundleViewPayload): string {
  const identity = view.checksum || view.runtime_checksum || String(view.version || view.ref);
  return `v3:${view.persona.slug}:${identity}`;
}

export function graphBundleToReactFlow(view: GraphBundleViewPayload) {
  const document = view.document || {};
  const nodes = Array.isArray(document.nodes) ? document.nodes : [];
  const edges = Array.isArray(document.edges) ? document.edges : [];
  const coordinates = document.coordinates && typeof document.coordinates === "object"
    ? document.coordinates
    : {};

  return {
    nodes: nodes.map((node: any) => {
      const nodeType = String(node.node_type || node.data?.node_type || "knowledge_item").toLowerCase();
      const coordinate = coordinates[node.id] || {};
      return {
        id: String(node.id),
        type: nodeType === "persona" ? "personaNode" : "knowledgeNode",
        position: {
          x: Number.isFinite(Number(coordinate.x)) ? Number(coordinate.x) : 0,
          y: Number.isFinite(Number(coordinate.y)) ? Number(coordinate.y) : 0,
        },
        data: {
          ...(node.data || {}),
          bundle_node: node,
          persona_id: view.persona.id,
          persona_slug: view.persona.slug,
          node_type: nodeType,
          slug: node.slug,
          label: node.title || node.slug || node.id,
          title: node.title,
          summary: node.summary,
          content_preview: node.summary || node.data?.content || "",
          tags: node.tags || [],
          status: node.status || node.data?.status,
          source: node.data?.source,
          projection_node_id: node.projection_node_id,
          color: NODE_COLORS[nodeType] || "#64748b",
        },
      };
    }),
    edges: edges.map((edge: any) => {
      const relationType = edge.relation_type || edge.relation || "contains";
      const metadata = edge.metadata || {};
      const primary = edge.primary === true || relationType === "contains" || metadata.primary_tree === true;
      return {
        id: String(edge.id || `${edge.source}:${relationType}:${edge.target}`),
        source: String(edge.source),
        target: String(edge.target),
        data: {
          ...metadata,
          relation_type: relationType,
          weight: edge.weight,
          primary,
          primary_tree: primary,
          metadata: { ...metadata, primary_tree: primary },
          directional: true,
          deletable: view.read_only === false,
          bundle_edge: edge,
        },
      };
    }),
    meta: {
      backend: "v3",
      source: view.source,
      state: view.state,
      checksum: view.checksum,
      version: view.version,
      semantic_nodes: nodes.length,
      semantic_edges: edges.length,
    },
  };
}

export function branchMembershipsForNode(view: GraphBundleViewPayload, nodeId: string): string[] {
  return Object.entries(view.branch_memberships || {})
    .filter(([, members]) => Boolean(members && Object.prototype.hasOwnProperty.call(members, nodeId)))
    .map(([branchId]) => branchId)
    .sort();
}
