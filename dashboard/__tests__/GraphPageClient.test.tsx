import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import GraphPageClient from "@/app/knowledge/graph/GraphPageClient";
import { api } from "@/lib/api";

const navigationMocks = vi.hoisted(() => ({
  replaceMock: vi.fn(),
  searchParams: "",
}));

vi.mock("next/dynamic", () => ({
  default: () => () => <div data-testid="graph-view">graph-view</div>,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: navigationMocks.replaceMock }),
  useSearchParams: () => new URLSearchParams(navigationMocks.searchParams),
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
    navigationMocks.replaceMock.mockReset();
    navigationMocks.searchParams = "";
    window.localStorage.setItem("ai-brain-persona-slug", "allanvvz");
    vi.spyOn(api, "personas").mockResolvedValue([{ id: "p1", slug: "allanvvz", name: "Allan" }]);
    vi.spyOn(api, "sofiaGraphCommand").mockResolvedValue({});
  });

  it("uses graph_json v2 document when payload is valid", async () => {
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
    await waitFor(() =>
      expect(screen.queryByText("Selecione uma persona para carregar o Graph JSON v2.")).not.toBeInTheDocument(),
    );
    expect(graphData).not.toHaveBeenCalledWith("allanvvz", expect.anything());
  });

  it("does not fall back to v1 graphData when v2 payload is unavailable", async () => {
    const getGraphDocument = vi.spyOn(api, "getGraphDocument").mockResolvedValue({});
    const graphData = vi.spyOn(api, "graphData").mockResolvedValue({ nodes: [], edges: [], meta: {} });

    render(<GraphPageClient />);
    await screen.findByText("Grafo de Conhecimento");

    await waitFor(() => expect(getGraphDocument).toHaveBeenCalledWith("allanvvz"));
    expect(graphData).not.toHaveBeenCalled();
    await screen.findByText("Nenhum Graph JSON v2 publicado para esta persona.");
  });

  it("clears the previous persona graph before the next document resolves", async () => {
    let resolveNext: ((value: unknown) => void) | undefined;
    const pending = new Promise((resolve) => { resolveNext = resolve; });
    const getGraphDocument = vi.spyOn(api, "getGraphDocument")
      .mockResolvedValueOnce({
        graph_json: {
          nodes: [{ id: "aurora", slug: "aurora", node_type: "persona", title: "Aurora" }],
          edges: [],
        },
      })
      .mockReturnValueOnce(pending as any);

    render(<GraphPageClient />);
    await screen.findByText(/1 nodes/);

    window.localStorage.setItem("ai-brain-persona-slug", "vz-lupas");
    window.dispatchEvent(new CustomEvent("ai-brain-persona-change", {
      detail: { slug: "vz-lupas" },
    }));

    await screen.findByText(/0 nodes/);
    expect(screen.queryByText(/1 nodes/)).not.toBeInTheDocument();
    expect(getGraphDocument).toHaveBeenLastCalledWith("vz-lupas");
    resolveNext?.({});
  });

  it("opens Tree explicitly and clears any stale focus", async () => {
    navigationMocks.searchParams = "mode=graph&focus=product%3Atest";
    vi.spyOn(api, "getGraphDocument").mockResolvedValue({
      graph_json: {
        graph_id: "allanvvz-main",
        nodes: [{ id: "gn:1", slug: "allanvvz", node_type: "persona", label: "Allan" }],
        edges: [],
      },
    });

    render(<GraphPageClient />);
    const treeTab = await screen.findByRole("tab", { name: "Tree" });
    expect(treeTab).toHaveAttribute("aria-selected", "false");

    expect(treeTab).toHaveAttribute("href", "/knowledge/graph?mode=semantic_tree");
    expect(navigationMocks.replaceMock).not.toHaveBeenCalled();
  });
});
