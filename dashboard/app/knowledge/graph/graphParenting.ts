export type ParentOption = {
  id: string;
  graphId: string;
  label: string;
  slug?: string;
  type: string;
};

export const ADD_BLOCK_PARENT_TYPES: Record<string, string[]> = {
  brand: ["persona"],
  briefing: ["brand", "campaign", "persona"],
  campaign: ["briefing", "brand", "persona"],
  audience: ["campaign", "briefing", "brand"],
  product_group: ["audience"],
  product: ["product_group"],
  copy: ["product", "product_group"],
  faq: ["copy", "product", "product_group"],
  asset: ["product", "product_group", "campaign", "brand"],
  entity: ["product", "product_group", "audience", "campaign", "brand"],
  tone: ["brand", "campaign", "briefing"],
  rule: ["product", "product_group", "audience", "campaign", "brand"],
};

export const ADD_BLOCK_PARENT_RELATIONS: Record<string, Record<string, string>> = {
  brand: { persona: "persona_has_brand" },
  briefing: { brand: "brand_has_briefing", campaign: "campaign_has_briefing", persona: "contains" },
  campaign: { briefing: "briefing_has_campaign", brand: "contains", persona: "contains" },
  audience: { campaign: "campaign_has_audience", briefing: "contains", brand: "contains" },
  product_group: { audience: "audience_has_product_group" },
  product: { product_group: "product_group_has_product" },
  copy: { product: "product_has_copy", product_group: "contains" },
  faq: { copy: "copy_has_faq", product: "product_has_faq", product_group: "contains" },
};

export function compatibleParentTypes(childType: string): string[] {
  return ADD_BLOCK_PARENT_TYPES[String(childType || "").toLowerCase()] || ["product", "product_group", "audience", "campaign", "brand"];
}

export function relationForParentChild(parentType: string, childType: string): string {
  const child = String(childType || "").toLowerCase();
  const parent = String(parentType || "").toLowerCase();
  return ADD_BLOCK_PARENT_RELATIONS[child]?.[parent] || "contains";
}

export function chooseAddBlockParent(
  childType: string,
  options: ParentOption[],
  selectedGraphId?: string | null,
): ParentOption | null {
  const compatible = compatibleParentTypes(childType);
  const selected = selectedGraphId ? options.find((option) => option.graphId === selectedGraphId) : null;
  if (selected && compatible.includes(selected.type)) return selected;
  for (const type of compatible) {
    const found = options.find((option) => option.type === type);
    if (found) return found;
  }
  return options[0] || null;
}
