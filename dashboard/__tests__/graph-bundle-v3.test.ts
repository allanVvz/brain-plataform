import { describe, expect, it } from "vitest";
import {
  branchMembershipsForNode,
  graphBundleLayoutScope,
  graphBundleToReactFlow,
  GraphBundleViewPayload,
} from "@/lib/graph-bundle-v3";

function view(overrides: Partial<GraphBundleViewPayload> = {}): GraphBundleViewPayload {
  return {
    backend: "v3",
    persona: { id: "persona-1", slug: "alpha", name: "Alpha" },
    source: "draft",
    ref: "bundle:v1.json",
    origin: "versioned_bundle",
    state: "blocked",
    version: "v1",
    checksum: "sha256:draft-one",
    runtime_checksum: null,
    validation_errors: ["bundle_node_source_pending:faq:one"],
    document: {
      nodes: [
        { id: "persona:alpha", node_type: "persona", slug: "alpha", title: "Alpha", status: "validated", data: { source: "fixture" } },
        { id: "faq:one", node_type: "faq", slug: "one", title: "Pergunta", summary: "Resposta", status: "pending_source", data: { source: "pending_source" } },
      ],
      edges: [{ id: "edge:one", source: "persona:alpha", target: "faq:one", relation_type: "contains" }],
    },
    branch_memberships: { "persona:alpha": { "persona:alpha": {}, "faq:one": {} } },
    read_only: true,
    ...overrides,
  };
}

describe("GraphBundle v3 view adapter", () => {
  it("renders blocked drafts without dropping authored nodes", () => {
    const payload = graphBundleToReactFlow(view());
    expect(payload.nodes).toHaveLength(2);
    expect(payload.nodes[1].data.status).toBe("pending_source");
    expect(payload.edges[0].data.primary_tree).toBe(true);
    expect(payload.edges[0].data.deletable).toBe(false);
  });

  it("isolates layout by persona and semantic version identity", () => {
    const first = graphBundleLayoutScope(view());
    const otherVersion = graphBundleLayoutScope(view({ checksum: "sha256:draft-two" }));
    const otherPersona = graphBundleLayoutScope(view({ persona: { id: "persona-2", slug: "beta" } }));
    expect(first).not.toBe(otherVersion);
    expect(first).not.toBe(otherPersona);
    expect(first).toContain("v3:alpha");
  });

  it("reports branch memberships for the drawer", () => {
    expect(branchMembershipsForNode(view(), "faq:one")).toEqual(["persona:alpha"]);
  });
});
