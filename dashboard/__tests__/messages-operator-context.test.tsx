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
});
