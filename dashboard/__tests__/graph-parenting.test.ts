import { describe, expect, it } from "vitest";
import { chooseAddBlockParent } from "@/app/knowledge/graph/graphParenting";

const option = (graphId: string, type: string, label = graphId) => ({
  id: graphId.replace(/^gn:/, ""),
  graphId,
  label,
  slug: label.toLowerCase(),
  type,
});

describe("Add block parent selection", () => {
  const options = [
    option("gn:campaign", "campaign", "Catalogo"),
    option("gn:audience", "audience", "Padrao"),
    option("gn:group", "product_group", "Juliet"),
    option("gn:product", "product", "Juliet Preta"),
  ];

  it("suggests product_group for product", () => {
    expect(chooseAddBlockParent("product", options)?.type).toBe("product_group");
  });

  it("suggests audience for product_group", () => {
    expect(chooseAddBlockParent("product_group", options)?.type).toBe("audience");
  });

  it("does not fall back to campaign for copy when a more specific parent exists", () => {
    expect(chooseAddBlockParent("copy", options)?.type).toBe("product");
  });

  it("prioritizes selected compatible node over generic fallback", () => {
    expect(chooseAddBlockParent("copy", options, "gn:group")?.graphId).toBe("gn:group");
  });
});
