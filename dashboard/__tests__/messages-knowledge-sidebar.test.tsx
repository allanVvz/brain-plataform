import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { KnowledgeSidebar } from "@/app/messages/MessagesLayout";

function card(overrides: Record<string, unknown> = {}) {
  return {
    id: "card:kit-modal",
    node_type: "product",
    slug: "kit-modal-1",
    title: "Kit Modal 1 — 9 cores",
    rendered_content: "Blusa canelada de modal, 9 cores para revenda.",
    editable_content: "Blusa canelada de modal, 9 cores para revenda.",
    content_checksum: "sha256:aaa",
    revision: 1,
    graph_version: 51,
    graph_checksum: "sha256:bbb",
    context_role: "primary",
    position: 0,
    selection_reason: {},
    path: [],
    chunk_refs: [],
    source: "graph",
    status: "validated",
    relations: [],
    technical_metadata: {},
    ...overrides,
  };
}

function ctx(overrides: Record<string, unknown> = {}) {
  return {
    query_terms: [],
    nodes: [],
    edges: [],
    kb_entries: [],
    assets: [],
    summary: "",
    mode: "exact",
    persona_slug: "vz-lupas",
    graph_version: 51,
    current_graph_version: 51,
    response: { message_id: "m1", created_at: "2026-08-13T09:13:00Z", text: "..." },
    used_cards: [card()],
    related_cards: [],
    current_cards: {},
    decisive_node_ids: ["card:kit-modal"],
    ...overrides,
  } as any;
}

describe("aba Conhecimento", () => {
  it("mostra o que o agente usou para responder", () => {
    render(<KnowledgeSidebar loading={false} leadSelected ctx={ctx()} />);
    expect(screen.getByText("Kit Modal 1 — 9 cores")).toBeInTheDocument();
    expect(screen.getByText("espelho exato")).toBeInTheDocument();
  });

  it("não renderiza conhecimento que ficou de fora da resposta", () => {
    // `related_cards` continua vindo do backend; a aba deliberadamente não o
    // desenha — conhecimento que não entrou na decisão é ruído ao lado da
    // evidência, não evidência.
    render(
      <KnowledgeSidebar
        loading={false}
        leadSelected
        ctx={ctx({
          related_cards: [card({ id: "card:frete", title: "Frete e prazo de entrega" })],
        })}
      />,
    );
    expect(screen.getByText("Kit Modal 1 — 9 cores")).toBeInTheDocument();
    expect(screen.queryByText("Frete e prazo de entrega")).toBeNull();
    expect(screen.queryByText(/Relacionados/)).toBeNull();
    expect(screen.queryByText(/Não usados/)).toBeNull();
  });

  it("distingue espelho exato de evidência reconstruída", () => {
    render(<KnowledgeSidebar loading={false} leadSelected ctx={ctx({ mode: "reconstructed" })} />);
    // A diferença entre "isto é o que o agente usou" e "isto é uma
    // aproximação" é a única meta-informação que sobrou na aba.
    expect(screen.getByText("evidência reconstruída")).toBeInTheDocument();
  });

  it("uma resposta sem card confirmado diz isso, não inventa contexto", () => {
    render(<KnowledgeSidebar loading={false} leadSelected ctx={ctx({ used_cards: [] })} />);
    expect(screen.getByText("Nenhum card confirmado para esta resposta.")).toBeInTheDocument();
  });

  it("sem lead selecionado, não busca nem mostra nada", () => {
    render(<KnowledgeSidebar loading={false} leadSelected={false} ctx={null} />);
    expect(screen.getByText(/Selecione um lead/)).toBeInTheDocument();
  });
});
