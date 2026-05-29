import { describe, expect, it } from "vitest";
import { parseGraphJsonV2Payload } from "@/lib/graph-json-v2";

describe("parseGraphJsonV2Payload", () => {
  it("maps nodes/edges and respects layout positions", () => {
    const parsed = parseGraphJsonV2Payload({
      graph_json: {
        nodes: [{ id: "gn:1", slug: "allanvvz", node_type: "persona", title: "Allan" }],
        edges: [{ id: "ge:1", source: "gn:1", target: "gn:2", relation_type: "reference" }],
        layout: { positions: { "gn:1": { x: 12, y: 34 } } },
      },
    });

    expect(parsed).not.toBeNull();
    expect(parsed?.nodes[0].position).toEqual({ x: 12, y: 34 });
    expect(parsed?.nodes[0].data.label).toBe("Allan");
    expect(parsed?.edges[0].data.relation_type).toBe("reference");
  });

  it("returns null for empty v2 payloads", () => {
    expect(parseGraphJsonV2Payload({ graph_json: { nodes: [], edges: [] } })).toBeNull();
    expect(parseGraphJsonV2Payload(null)).toBeNull();
  });
});
