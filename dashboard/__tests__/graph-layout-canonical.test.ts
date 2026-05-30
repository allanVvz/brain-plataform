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
});
