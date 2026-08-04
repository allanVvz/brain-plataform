import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { KnowledgeSidebar } from "@/app/messages/MessagesLayout";

describe("operator knowledge sidebar", () => {
  it("keeps the three operator sections visible when evidence is empty", () => {
    render(
      <KnowledgeSidebar
        loading={false}
        leadSelected
        ctx={{
          query_terms: [],
          nodes: [],
          edges: [],
          kb_entries: [],
          assets: [],
          summary: "",
          operator_context: {
            primary: [],
            faq_rules: [],
            graph_path: [],
          },
        }}
      />,
    );

    expect(screen.getByText("Usado nesta resposta")).toBeInTheDocument();
    expect(screen.getByText("FAQ e regras relacionadas")).toBeInTheDocument();
    expect(screen.getByText("Caminho no grafo")).toBeInTheDocument();
    expect(screen.getByText("Nenhuma evidência registrada na última decisão.")).toBeInTheDocument();
    expect(screen.getByText("Nenhuma FAQ ou regra relacionada neste contexto.")).toBeInTheDocument();
    expect(screen.getByText("Caminho indisponível para esta evidência.")).toBeInTheDocument();
  });

  it("shows every injected card for the selected response without the legacy four-card cut", () => {
    const cards = Array.from({ length: 6 }, (_, index) => ({
      id: `card-${index}`,
      node_type: index === 0 ? "persona" : "faq",
      slug: `card-${index}`,
      title: `Card ${index}`,
      rendered_content: `# Card ${index}\n\nConteúdo exato ${index}`,
      editable_content: `Conteúdo exato ${index}`,
      content_checksum: `sha256:${index}`,
      revision: 1,
      graph_version: 7,
      graph_checksum: "sha256:graph",
      context_role: index === 0 ? "permanent" : "contextual",
      position: index,
      selection_reason: { reason: "fixture" },
      path: [`card-${index}`],
      chunk_refs: [],
      source: "fixture",
      status: "approved",
      relations: [],
      technical_metadata: {},
    }));
    render(
      <KnowledgeSidebar
        loading={false}
        leadSelected
        ctx={{
          query_terms: [], nodes: [], edges: [], kb_entries: [], assets: [], summary: "",
          mode: "exact",
          persona_slug: "aurora",
          graph_version: 7,
          current_graph_version: 7,
          response: { message_id: "ai:7", created_at: "2026-08-04T03:00:00Z" },
          used_cards: cards,
          related_cards: [],
          current_cards: Object.fromEntries(cards.map((card) => [card.id, card])),
          decisive_node_ids: ["card-5"],
        }}
      />,
    );

    expect(screen.getByText("espelho exato")).toBeInTheDocument();
    for (let index = 0; index < 6; index += 1) {
      expect(screen.getByText(`Card ${index}`)).toBeInTheDocument();
    }
    expect(screen.getByText("decisivo")).toBeInTheDocument();
  });
});
