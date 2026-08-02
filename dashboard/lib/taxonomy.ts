// Canonical fractal graph taxonomy — frontend mirror of api/services/knowledge_taxonomy.py.
// Kept in sync with supabase/migrations/039_graph_canonical_taxonomy.sql.
//
// Prefer reading the live snapshot via api.knowledgeTaxonomy() when accuracy
// matters; this file exists so static UIs (legends, dropdowns, validators) can
// render without an API round-trip.

export type GraphNodeType =
  | "persona"
  | "brand"
  | "briefing"
  | "campaign"
  | "audience"
  | "product_group"
  | "product"
  | "offer"
  | "copy"
  | "faq"
  | "gallery"
  | "embedded"
  | "marketing_workspace"
  | "rule"
  | "tone"
  | "asset";

export type GraphEdgeKind =
  | "primary"
  | "secondary"
  | "asset_pending"
  | "asset_approved";

export const CANONICAL_NODE_TYPES: readonly GraphNodeType[] = [
  "persona",
  "brand",
  "briefing",
  "campaign",
  "audience",
  "product_group",
  "product",
  "offer",
  "copy",
  "faq",
  "gallery",
  "embedded",
  "marketing_workspace",
  "rule",
  "tone",
  "asset",
] as const;

export const NODE_TYPE_ALIASES: Record<string, GraphNodeType> = {
  product_collection: "product_group",
  category: "product_group",
};

export const PRIMARY_CHAIN: readonly {
  source: GraphNodeType;
  target: GraphNodeType;
  relation: string;
  oneToOne: boolean;
}[] = [
  { source: "persona",       target: "brand",         relation: "persona_has_brand",          oneToOne: true  },
  { source: "brand",         target: "briefing",      relation: "brand_has_briefing",         oneToOne: false },
  { source: "briefing",      target: "campaign",      relation: "briefing_has_campaign",      oneToOne: false },
  { source: "campaign",      target: "audience",      relation: "campaign_has_audience",      oneToOne: false },
  { source: "audience",      target: "product_group", relation: "audience_has_product_group", oneToOne: false },
  { source: "product_group", target: "product",       relation: "product_group_has_product",  oneToOne: false },
  { source: "product",       target: "offer",         relation: "product_has_offer",          oneToOne: false },
  { source: "offer",         target: "copy",          relation: "offer_has_copy",             oneToOne: false },
  { source: "copy",          target: "faq",           relation: "copy_has_faq",               oneToOne: true  },
  { source: "copy",          target: "gallery",       relation: "copy_has_gallery",           oneToOne: true  },
  // Legacy alternatives kept valid so older content can still be repaired.
  { source: "brand",         target: "campaign",      relation: "contains",                  oneToOne: false },
  { source: "campaign",      target: "briefing",      relation: "contains",                  oneToOne: false },
  { source: "briefing",      target: "audience",      relation: "contains",                  oneToOne: false },
];

export const NODE_TYPE_LABEL: Record<GraphNodeType, string> = {
  persona: "Persona",
  brand: "Brand",
  briefing: "Briefing",
  campaign: "Campaign",
  audience: "Audience",
  product_group: "Product Group",
  product: "Product",
  offer: "Offer",
  copy: "Copy",
  faq: "FAQ",
  gallery: "Gallery",
  embedded: "Embedded",
  marketing_workspace: "Marketing Workspace",
  rule: "Rule",
  tone: "Tone",
  asset: "Asset",
};

export const NODE_TYPE_COLOR: Record<GraphNodeType, string> = {
  persona: "#7c6fff",
  brand: "#a78bfa",
  briefing: "#c084fc",
  campaign: "#fb923c",
  audience: "#f472b6",
  product_group: "#34d399",
  product: "#60a5fa",
  offer: "#facc15",
  copy: "#64748b",
  faq: "#4ade80",
  gallery: "#d946ef",
  embedded: "#8b5cf6",
  marketing_workspace: "#ec4899",
  rule: "#ef4444",
  tone: "#14b8a6",
  asset: "#f59e0b",
};

export function canonicalNodeType(raw: string | null | undefined): GraphNodeType | null {
  if (!raw) return null;
  const lower = raw.toLowerCase().trim();
  if (!lower) return null;
  if ((CANONICAL_NODE_TYPES as readonly string[]).includes(lower)) {
    return lower as GraphNodeType;
  }
  return NODE_TYPE_ALIASES[lower] ?? null;
}

export function isPrimaryEdgeAllowed(
  source: string | null | undefined,
  target: string | null | undefined,
  relation: string,
): boolean {
  const src = canonicalNodeType(source);
  const tgt = canonicalNodeType(target);
  if (!src || !tgt) return false;
  return PRIMARY_CHAIN.some(
    (link) => link.source === src && link.target === tgt && link.relation === relation,
  );
}
