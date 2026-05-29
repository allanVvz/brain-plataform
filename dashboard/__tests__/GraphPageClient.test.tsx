import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import GraphPageClient from "@/app/knowledge/graph/GraphPageClient";
import { api } from "@/lib/api";

vi.mock("next/dynamic", () => ({
  default: () => () => <div data-testid="graph-view">graph-view</div>,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));

vi.mock("lucide-react", () => {
  const Icon = () => <span data-testid="icon" />;
  return {
    RefreshCw: Icon,
    Search: Icon,
    Network: Icon,
    GitBranch: Icon,
    Tag: Icon,
    AtSign: Icon,
    Database: Icon,
    Crosshair: Icon,
    Layers3: Icon,
    Plus: Icon,
    X: Icon,
  };
});

vi.mock("@/components/graph/NodeDrawer", () => ({
  default: () => <div data-testid="node-drawer" />,
}));

vi.mock("@/app/knowledge/graph/SofiaChatPanel", () => ({
  default: () => <div data-testid="sofia-panel" />,
}));

vi.mock("@/app/knowledge/graph/sofiaReactFlowTools", () => ({
  resolveSofiaToolFromInput: () => null,
  SOFIA_REACT_FLOW_TOOLS: {
    apply_patch_visual: { command: () => "apply_patch_visual" },
    mark_pending: { command: () => "mark_pending" },
    undo_pending: { command: () => "undo_pending" },
    confirm_pending: { command: () => "confirm_pending" },
    select_node: { command: () => "select_node" },
    focus_node: { command: () => "focus_node" },
    update_layout: { command: () => "update_layout" },
    highlight_edges: { command: () => "highlight_edges" },
  },
}));

describe("GraphPageClient v2 loading", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.localStorage.setItem("ai-brain-persona-slug", "allanvvz");
    vi.spyOn(api, "personas").mockResolvedValue([{ id: "p1", slug: "allanvvz", name: "Allan" }]);
    vi.spyOn(api, "sofiaGraphCommand").mockResolvedValue({});
  });

  it("uses graph_json v2 document when feature flag is enabled and payload is valid", async () => {
    vi.stubEnv("NEXT_PUBLIC_GRAPH_JSON_V2", "1");
    const getGraphDocument = vi.spyOn(api, "getGraphDocument").mockResolvedValue({
      graph_json: {
        nodes: [{ id: "gn:1", slug: "allanvvz", node_type: "persona", title: "Allan" }],
        edges: [],
      },
    });
    const graphData = vi.spyOn(api, "graphData").mockResolvedValue({ nodes: [], edges: [], meta: {} });

    render(<GraphPageClient />);
    await screen.findByText("Grafo de Conhecimento");

    await waitFor(() => expect(getGraphDocument).toHaveBeenCalledWith("allanvvz"));
    expect(graphData).not.toHaveBeenCalledWith("allanvvz", expect.anything());
  });

  it("falls back to v1 graphData when v2 payload is unavailable", async () => {
    vi.stubEnv("NEXT_PUBLIC_GRAPH_JSON_V2", "1");
    const getGraphDocument = vi.spyOn(api, "getGraphDocument").mockResolvedValue({});
    const graphData = vi.spyOn(api, "graphData").mockResolvedValue({ nodes: [], edges: [], meta: {} });

    render(<GraphPageClient />);
    await screen.findByText("Grafo de Conhecimento");

    await waitFor(() => expect(getGraphDocument).toHaveBeenCalledWith("allanvvz"));
    await waitFor(() => expect(graphData).toHaveBeenCalled());
  });
});
