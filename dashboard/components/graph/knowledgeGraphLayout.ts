import { Edge, Node } from "reactflow";

export type KnowledgeViewMode = "layered" | "semantic_tree" | "graph";
export type EdgeTier = "strong" | "structural" | "auxiliary" | "curation";

export interface GraphNodeData {
  label: string;
  slug?: string;
  status?: string;
  node_type?: string;
  content_type?: string;
  file_type?: string;
  file_path?: string | null;
  content_preview?: string;
  level?: number;
  importance?: number;
  confidence?: number | null;
  color?: string;
  is_auxiliary?: boolean;
  is_focus?: boolean;
  in_focus_path?: boolean;
  graph_distance?: number | null;
  [key: string]: unknown;
}

export interface GraphEdgeData {
  relation_type?: string;
  tier?: EdgeTier;
  weight?: number;
  directional?: boolean;
  in_focus_path?: boolean;
  label?: string;
  primary?: boolean;
  secondary?: boolean;
  original_edge_id?: string;
  [key: string]: unknown;
}

type ParentCandidate = {
  child: Node<GraphNodeData>;
  parent: Node<GraphNodeData>;
  edge: Edge<GraphEdgeData>;
  score: number;
  relationRank: number;
  typeRank: number;
};

const EXPECTED_PARENT_TYPES: Record<string, string[]> = {
  campaign: ["brand", "persona"],
  briefing: ["campaign", "brand", "persona"],
  audience: ["briefing", "campaign", "brand", "persona"],
  gallery: ["copy", "faq", "asset", "background", "texture", "product", "campaign", "brand", "persona"],
  embedded: ["faq"],
  product: ["audience", "briefing", "campaign", "brand", "persona"],
  faq: ["product", "entity", "audience", "briefing", "campaign", "brand"],
  copy: ["product", "audience", "briefing", "campaign", "brand"],
  rule: ["product", "entity", "audience", "briefing", "campaign", "brand"],
  asset: ["product", "audience", "briefing", "campaign", "brand"],
  background: ["product", "audience", "briefing", "campaign", "brand"],
  texture: ["product", "audience", "briefing", "campaign", "brand"],
  entity: ["product", "audience", "briefing", "campaign", "brand"],
  tone: ["brand", "campaign", "briefing"],
  tag: ["product", "campaign", "brand", "faq", "copy"],
  mention: ["product", "campaign", "brand", "faq", "copy"],
  knowledge_item: ["product", "faq", "copy", "briefing", "campaign", "brand"],
  kb_entry: ["product", "faq", "copy", "briefing", "campaign", "brand"],
};

const STRUCTURAL_RELATIONS = new Set([
  "belongs_to",
  "belongs_to_persona",
  "part_of",
  "part_of_campaign",
  "under",
  "parent_of",
  "contains",
  "manual",
  "audience_of",
  "product_of",
  "briefing_of",
  "campaign_of",
  "brand_of",
]);

const STRONG_RELATIONS = new Set([
  "about",
  "about_product",
  "answers_question",
  "applies_to",
  "targets",
  "related_to_product",
  "defines_brand",
  "briefed_by",
  "supports_copy",
  "supports_campaign",
  "has_tone",
]);

const AUXILIARY_RELATIONS = new Set(["has_tag", "mentions", "references", "uses_asset", "same_topic_as"]);
const CURATION_RELATIONS = new Set(["duplicate_of", "similar_to", "alias_of"]);

const HIERARCHY_RANK: Record<string, number> = {
  persona: 0,
  brand: 1,
  campaign: 2,
  briefing: 3,
  audience: 4,
  product: 5,
  entity: 6,
  tone: 7,
  rule: 8,
  copy: 9,
  asset: 10,
  background: 10,
  texture: 10,
  faq: 11,
  gallery: 97,
  embedded: 98,
  knowledge_item: 98,
  kb_entry: 98,
  tag: 99,
  mention: 99,
};

export function getVisualHierarchyRank(nodeTypeValue?: string | null): number {
  const key = String(nodeTypeValue || "").toLowerCase();
  return HIERARCHY_RANK[key] ?? 50;
}

function nodeType(node: Node<GraphNodeData>): string {
  return String(node.data?.node_type || node.data?.content_type || "").toLowerCase();
}

function relationType(edge: Edge<GraphEdgeData>): string {
  return String(edge.data?.relation_type || "").toLowerCase();
}

function tierRank(edge: Edge<GraphEdgeData>): number {
  const rt = relationType(edge);
  const tier = edge.data?.tier;
  if (isExplicitPrimaryEdge(edge)) return -1;
  if (STRUCTURAL_RELATIONS.has(rt) || tier === "structural") return 0;
  if (STRONG_RELATIONS.has(rt) || tier === "strong") return 1;
  if (AUXILIARY_RELATIONS.has(rt) || tier === "auxiliary") return 2;
  if (CURATION_RELATIONS.has(rt) || tier === "curation") return 3;
  return 4;
}

function expectedTypeRank(childType: string, parentType: string): number {
  const expected = EXPECTED_PARENT_TYPES[childType] || [];
  const idx = expected.indexOf(parentType);
  if (idx >= 0) return idx;

  const childRank = HIERARCHY_RANK[childType] ?? 50;
  const parentRank = HIERARCHY_RANK[parentType] ?? 50;
  return parentRank < childRank ? 20 + childRank - parentRank : 80;
}

function directionBonus(childId: string, parentId: string, edge: Edge<GraphEdgeData>): number {
  const rt = relationType(edge);
  if (edge.source === childId && edge.target === parentId) {
    if (["belongs_to", "belongs_to_persona", "part_of", "part_of_campaign", "derived_from", "briefed_by", "answers_question", "about_product", "product_of", "audience_of", "campaign_of", "brand_of"].includes(rt)) {
      return 0.18;
    }
  }
  if (edge.source === parentId && edge.target === childId) {
    if (["contains", "parent_of", "targets", "supports_copy", "supports_campaign", "defines_brand", "has_tone", "about", "about_product", "manual", "belongs_to_persona"].includes(rt)) {
      return 0.16;
    }
  }
  return 0;
}

function isExplicitPrimaryEdge(edge: Edge<GraphEdgeData>): boolean {
  const data = edge.data || {};
  const metadata = (data.metadata || {}) as Record<string, unknown>;
  return data.primary_tree === true || metadata.primary_tree === true || relationType(edge) === "manual";
}

function relationAllowsParentCandidate(childId: string, parentId: string, edge: Edge<GraphEdgeData>): boolean {
  const rt = relationType(edge);
  if (["manual", "contains", "parent_of", "targets", "supports_copy", "supports_campaign", "defines_brand", "has_tone", "gallery_asset"].includes(rt)) {
    return edge.source === parentId && edge.target === childId;
  }
  if (["belongs_to", "part_of", "derived_from", "product_of", "audience_of", "campaign_of", "brand_of"].includes(rt)) {
    return edge.source === childId && edge.target === parentId;
  }
  return true;
}

function relationPriority(edge: Edge<GraphEdgeData>): number {
  const rt = relationType(edge);
  if (rt === "manual") return 0;
  if (rt === "contains" || rt === "parent_of") return 1;
  if (rt === "part_of_campaign" || rt === "campaign_of") return 2;
  if (rt === "about_product" || rt === "product_of") return 3;
  if (rt === "briefed_by" || rt === "briefing_of") return 4;
  if (rt === "answers_question" || rt === "supports_copy") return 5;
  if (rt === "gallery_asset") return 5;
  if (rt === "belongs_to_persona") return 8;
  if (rt === "derived_from") return 9;
  return 6;
}

function isAllowedRoot(type: string): boolean {
  return type === "brand" || type === "persona";
}

export function getEdgeImportanceScore(
  child: Node<GraphNodeData>,
  parent: Node<GraphNodeData>,
  edge: Edge<GraphEdgeData>,
): number {
  const childT = nodeType(child);
  const parentT = nodeType(parent);
  const typeScore = Math.max(0, 1.2 - expectedTypeRank(childT, parentT) * 0.12);
  const relationScore = Math.max(0, 0.9 - tierRank(edge) * 0.18);
  const weightScore = Number(edge.data?.weight ?? 0.5) * 0.45;
  const parentImportance = Number(parent.data?.importance ?? 0.5) * 0.12;
  const semanticDistance = Math.abs((HIERARCHY_RANK[childT] ?? 50) - (HIERARCHY_RANK[parentT] ?? 50));
  const distanceScore = semanticDistance > 0 && semanticDistance < 5 ? 0.08 : 0;
  return typeScore + relationScore + weightScore + parentImportance + distanceScore + directionBonus(child.id, parent.id, edge);
}

export function getPrimaryParentEdge(
  child: Node<GraphNodeData>,
  nodesById: Map<string, Node<GraphNodeData>>,
  edges: Edge<GraphEdgeData>[],
): ParentCandidate | null {
  const childT = nodeType(child);
  if (isAllowedRoot(childT)) return null;

  const candidates: ParentCandidate[] = [];
  for (const edge of edges) {
    if (edge.source !== child.id && edge.target !== child.id) continue;
    const otherId = edge.source === child.id ? edge.target : edge.source;
    const parent = nodesById.get(otherId);
    if (!parent) continue;

    const parentT = nodeType(parent);
    const explicitPrimary = isExplicitPrimaryEdge(edge);
    if (!relationAllowsParentCandidate(child.id, parent.id, edge)) continue;
    if (parentT === childT && !explicitPrimary && !["faq", "copy"].includes(childT)) continue;
    if (!explicitPrimary && expectedTypeRank(childT, parentT) >= 80) continue;

    candidates.push({
      child,
      parent,
      edge,
      score: getEdgeImportanceScore(child, parent, edge),
      relationRank: tierRank(edge),
      typeRank: expectedTypeRank(childT, parentT),
    });
  }

  candidates.sort((a, b) => {
    const aExplicit = isExplicitPrimaryEdge(a.edge);
    const bExplicit = isExplicitPrimaryEdge(b.edge);
    if (aExplicit !== bExplicit) return aExplicit ? -1 : 1;
    if (a.typeRank !== b.typeRank) return a.typeRank - b.typeRank;
    if (a.relationRank !== b.relationRank) return a.relationRank - b.relationRank;
    const aRelationPriority = relationPriority(a.edge);
    const bRelationPriority = relationPriority(b.edge);
    if (aRelationPriority !== bRelationPriority) return aRelationPriority - bRelationPriority;
    if (b.score !== a.score) return b.score - a.score;
    const aWeight = Number(a.edge.data?.weight ?? 0);
    const bWeight = Number(b.edge.data?.weight ?? 0);
    if (bWeight !== aWeight) return bWeight - aWeight;
    const rel = relationType(a.edge).localeCompare(relationType(b.edge));
    if (rel !== 0) return rel;
    return `${a.parent.id}:${a.edge.id}`.localeCompare(`${b.parent.id}:${b.edge.id}`);
  });

  return candidates[0] || null;
}

function wouldCreateCycle(childId: string, parentId: string, parentByChild: Map<string, string>): boolean {
  let current: string | undefined = parentId;
  const seen = new Set<string>([childId]);
  while (current) {
    if (seen.has(current)) return true;
    seen.add(current);
    current = parentByChild.get(current);
  }
  return false;
}

export function buildTreeFromGraph(
  nodes: Node<GraphNodeData>[],
  edges: Edge<GraphEdgeData>[],
  onlyPrimaryEdges: boolean,
): { nodes: Node<GraphNodeData>[]; edges: Edge<GraphEdgeData>[]; primaryEdgeIds: Set<string> } {
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  const parentByChild = new Map<string, string>();
  const primaryEdgeIds = new Set<string>();
  const primaryEdges: Edge<GraphEdgeData>[] = [];

  const sortedNodes = [...nodes].sort((a, b) => {
    const ar = HIERARCHY_RANK[nodeType(a)] ?? 50;
    const br = HIERARCHY_RANK[nodeType(b)] ?? 50;
    if (ar !== br) return ar - br;
    return a.id.localeCompare(b.id);
  });

  for (const child of sortedNodes) {
    const candidate = getPrimaryParentEdge(child, nodesById, edges);
    if (!candidate || wouldCreateCycle(child.id, candidate.parent.id, parentByChild)) continue;

    parentByChild.set(child.id, candidate.parent.id);
    primaryEdgeIds.add(candidate.edge.id);
    const originalEdgeId = candidate.edge.data?.original_edge_id || candidate.edge.id;
    primaryEdges.push({
      ...candidate.edge,
      id: `tree:${candidate.parent.id}->${child.id}`,
      source: candidate.parent.id,
      target: child.id,
      type: "smoothstep",
      data: {
        ...(candidate.edge.data || {}),
        primary: true,
        secondary: false,
        original_edge_id: originalEdgeId,
      },
    });
  }

  const embeddedEdges = edges
    .filter((edge) => (edge.data as GraphEdgeData | undefined)?.embedded_edge)
    .map((edge) => ({
      ...edge,
      data: { ...(edge.data || {}), primary: true, secondary: false },
    }));
  const galleryEdges = edges
    .filter((edge) => (edge.data as GraphEdgeData | undefined)?.gallery_edge && !primaryEdgeIds.has(edge.id))
    .map((edge) => ({
      ...edge,
      data: { ...(edge.data || {}), primary: true, secondary: false },
    }));

  const secondaryEdges = onlyPrimaryEdges
    ? []
    : edges
        .filter((edge) => {
          const data = edge.data as GraphEdgeData | undefined;
          return !primaryEdgeIds.has(edge.id) && !data?.embedded_edge && !data?.gallery_edge;
        })
        .map((edge) => ({
          ...edge,
          data: { ...(edge.data || {}), primary: false, secondary: true },
        }));

  return {
    nodes,
    edges: [...primaryEdges, ...galleryEdges, ...embeddedEdges, ...secondaryEdges],
    primaryEdgeIds,
  };
}

export function buildNeuronGraphLayout(nodes: Node<GraphNodeData>[], edges: Edge<GraphEdgeData>[], distanceScale = 1): Node<GraphNodeData>[] {
  const degree = new Map<string, number>();
  for (const node of nodes) degree.set(node.id, 0);
  for (const edge of edges) {
    degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
  }

  const sorted = [...nodes].sort((a, b) => {
    const da = degree.get(a.id) || 0;
    const db = degree.get(b.id) || 0;
    if (db !== da) return db - da;
    return a.id.localeCompare(b.id);
  });

  const golden = Math.PI * (3 - Math.sqrt(5));
  const seeded = sorted.map((node, index) => {
    const importance = Number(node.data?.importance ?? 0.5);
    const centrality = (degree.get(node.id) || 0) / Math.max(1, edges.length);
    const radius = (80 + Math.sqrt(index + 1) * 92 - importance * 70 - centrality * 160) * distanceScale;
    const angle = index * golden;
    const ringNoise = Math.sin(index * 1.618) * 24;
    return {
      ...node,
      position: {
        x: Math.cos(angle) * (radius + ringNoise),
        y: Math.sin(angle) * (radius - ringNoise) * 0.72,
      },
    };
  });

  const position = new Map(seeded.map((node) => [node.id, { x: node.position.x, y: node.position.y }]));
  const area = Math.max(120_000, seeded.length * 18_000) * distanceScale * distanceScale;
  const k = Math.sqrt(area / Math.max(1, seeded.length));

  for (let step = 0; step < 180; step++) {
    const temp = 38 * (1 - step / 180);
    const delta = new Map(seeded.map((node) => [node.id, { x: 0, y: 0 }]));

    for (let i = 0; i < seeded.length; i++) {
      for (let j = i + 1; j < seeded.length; j++) {
        const a = seeded[i];
        const b = seeded[j];
        const pa = position.get(a.id)!;
        const pb = position.get(b.id)!;
        const dx = pa.x - pb.x || 0.01;
        const dy = pa.y - pb.y || 0.01;
        const dist = Math.sqrt(dx * dx + dy * dy);
        const force = (k * k) / dist;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        delta.get(a.id)!.x += fx;
        delta.get(a.id)!.y += fy;
        delta.get(b.id)!.x -= fx;
        delta.get(b.id)!.y -= fy;
      }
    }

    for (const edge of edges) {
      const pa = position.get(edge.source);
      const pb = position.get(edge.target);
      if (!pa || !pb) continue;
      const dx = pa.x - pb.x || 0.01;
      const dy = pa.y - pb.y || 0.01;
      const dist = Math.sqrt(dx * dx + dy * dy);
      const weight = Number(edge.data?.weight ?? 0.6);
      const force = ((dist * dist) / k) * (0.12 + weight * 0.2);
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      delta.get(edge.source)!.x -= fx;
      delta.get(edge.source)!.y -= fy;
      delta.get(edge.target)!.x += fx;
      delta.get(edge.target)!.y += fy;
    }

    for (const node of seeded) {
      const p = position.get(node.id)!;
      const d = delta.get(node.id)!;
      const len = Math.max(0.01, Math.sqrt(d.x * d.x + d.y * d.y));
      const importance = Number(node.data?.importance ?? 0.5);
      p.x += (d.x / len) * Math.min(len, temp) * (1 - importance * 0.22);
      p.y += (d.y / len) * Math.min(len, temp) * (1 - importance * 0.22);
    }
  }

  return seeded.map((node) => ({
    ...node,
    position: position.get(node.id) || node.position,
  }));
}
