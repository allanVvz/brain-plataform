import { describe, expect, it } from "vitest";
import { buildTreeFromGraph, getVisualHierarchyRank } from "@/components/graph/knowledgeGraphLayout";

const node = (id: string, nodeType: string, label = id) => ({
  id,
  type: "knowledgeNode",
  position: { x: 0, y: 0 },
  data: { label, node_type: nodeType, slug: id },
});

const edge = (id: string, source: string, target: string, relationType: string) => ({
  id,
  source,
  target,
  type: "smoothstep",
  data: { relation_type: relationType, primary_tree: true, weight: 1 },
});

describe("canonical graph tree relations", () => {
  it("treats persona_has_brand as Persona -> Brand in the tree", () => {
    const nodes = [node("persona", "persona"), node("brand", "brand")];
    const edges = [edge("e-persona-brand", "persona", "brand", "persona_has_brand")];

    const tree = buildTreeFromGraph(nodes, edges, true);

    expect(tree.edges).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ source: "persona", target: "brand" }),
      ]),
    );
  });

  it("orders product_group between audience and product", () => {
    expect(getVisualHierarchyRank("audience")).toBeLessThan(getVisualHierarchyRank("product_group"));
    expect(getVisualHierarchyRank("product_group")).toBeLessThan(getVisualHierarchyRank("product"));
  });

  it("keeps the Tock Fatal main tree in series from briefing to faq", () => {
    const nodes = [
      node("persona", "persona"),
      node("brand", "brand"),
      node("briefing", "briefing"),
      node("campaign", "campaign"),
      node("audience", "audience"),
      node("group", "product_group"),
      node("product-1", "product"),
      node("product-2", "product"),
      node("copy-1", "copy"),
      node("copy-2", "copy"),
      node("faq-1", "faq"),
      node("faq-2", "faq"),
    ];
    const edges = [
      edge("e1", "persona", "brand", "persona_has_brand"),
      edge("e2", "brand", "briefing", "brand_has_briefing"),
      edge("e3", "briefing", "campaign", "briefing_has_campaign"),
      edge("e4", "campaign", "audience", "campaign_has_audience"),
      edge("e5", "audience", "group", "audience_has_product_group"),
      edge("e6", "group", "product-1", "product_group_has_product"),
      edge("e7", "group", "product-2", "product_group_has_product"),
      edge("e8", "product-1", "copy-1", "product_has_copy"),
      edge("e9", "product-2", "copy-2", "product_has_copy"),
      edge("e10", "copy-1", "faq-1", "copy_has_faq"),
      edge("e11", "copy-2", "faq-2", "copy_has_faq"),
    ];

    const tree = buildTreeFromGraph(nodes, edges, true);
    const primary = tree.edges.filter((item) => item.data?.primary === true);

    expect(primary.map((item) => `${item.source}->${item.target}`)).toEqual([
      "persona->brand",
      "brand->briefing",
      "briefing->campaign",
      "campaign->audience",
      "audience->group",
      "group->product-1",
      "group->product-2",
      "product-1->copy-1",
      "product-2->copy-2",
      "copy-1->faq-1",
      "copy-2->faq-2",
    ]);
  });
});
