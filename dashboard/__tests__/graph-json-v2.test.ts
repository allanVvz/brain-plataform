import { describe, expect, it } from "vitest";
import { parseGraphJsonV2Payload } from "@/lib/graph-json-v2";

describe("parseGraphJsonV2Payload", () => {
  it("maps nodes/edges and respects layout positions", () => {
    const parsed = parseGraphJsonV2Payload({
      graph_json: {
        nodes: [{
          id: "gn:1",
          slug: "allanvvz",
          node_type: "persona",
          title: "Allan",
          data: { source: "personas", status: "validated", persona_id: "p1" },
        }],
        edges: [{ id: "ge:1", source: "gn:1", target: "gn:2", relation: "belongs_to_persona" }],
        layout: { positions: { "gn:1": [12, 34] } },
      },
    });

    expect(parsed).not.toBeNull();
    expect(parsed?.nodes[0].type).toBe("personaNode");
    expect(parsed?.nodes[0].position).toEqual({ x: 12, y: 34 });
    expect(parsed?.nodes[0].data.label).toBe("Allan");
    expect(parsed?.nodes[0].data.persona_id).toBe("p1");
    expect(parsed?.nodes[0].data.status).toBe("validated");
    expect(parsed?.edges[0].data.relation_type).toBe("belongs_to_persona");
  });

  it("maps non-persona nodes to the custom knowledge node renderer", () => {
    const parsed = parseGraphJsonV2Payload({
      graph_json: {
        nodes: [{ id: "gn:2", slug: "brand", node_type: "brand", label: "Brand" }],
        edges: [],
      },
    });

    expect(parsed?.nodes[0].type).toBe("knowledgeNode");
  });

  it("returns null for empty v2 payloads", () => {
    expect(parseGraphJsonV2Payload({ graph_json: { nodes: [], edges: [] } })).toBeNull();
    expect(parseGraphJsonV2Payload(null)).toBeNull();
  });
});
