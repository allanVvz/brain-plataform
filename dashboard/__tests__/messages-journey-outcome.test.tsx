import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import {
  isJourneySettled,
  normalizeJourneyOutcome,
  JOURNEY_OUTCOMES,
} from "@/lib/lead-state";

function makeLead(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    lead_id: "1",
    nome: "Ana Paula",
    telefone: "+5511988124471",
    stage: "qualificado",
    ai_enabled: true,
    ai_paused: false,
    handoff_level: "none" as const,
    ultima_mensagem: "oi",
    last_update: "2026-08-13T00:00:00Z",
    updated_at: "2026-08-13T00:00:00Z",
    persona_id: "p1",
    interesse_produto: "Kit Modal 1 — azul marinho",
    metadata: {
      commercial_note: {
        quantidade: "5 peças",
        cores: "azul marinho, cinza",
        entrega: "Sedex · 12/09",
        pagamento: "pix",
        observacao: "aceita frete grátis",
        prazo: "fecha hoje",
        updated_at: "2026-08-13T00:00:00Z",
      },
    },
    qualification_score: 72,
    journey_outcome: "vendido",
    ...overrides,
  };
}

// vi.mock é içado para o topo do arquivo, então tudo que a factory referencia
// precisa nascer em vi.hoisted — senão o módulo é mockado antes das variáveis
// existirem.
const h = vi.hoisted(() => ({
  recordJourneyEvent: vi.fn(async () => ({
    event_type: "delivered", deduplicated: false, new_journey_created: false,
  })),
  lead: { current: null as any },
}));
const recordJourneyEvent = h.recordJourneyEvent;

function setLead(lead: Record<string, unknown>) {
  h.lead.current = lead;
}
setLead(makeLead());

vi.mock("@/lib/api", () => ({
  api: {
    portalLeads: vi.fn(async () => [h.lead.current]),
    portalConversations: vi.fn(async () => []),
    portalLead: vi.fn(async () => h.lead.current),
    portalConversationMessages: vi.fn(async () => ({
      items: [], before_cursor: null, after_cursor: null, next_cursor: null, has_more: false,
    })),
    portalKnowledgeChatContext: vi.fn(async () => ({
      query_terms: [], nodes: [], edges: [], kb_entries: [], assets: [], summary: "",
    })),
    portalSendMessage: vi.fn(async () => ({})),
    portalPauseAi: vi.fn(async () => ({})),
    portalResumeAi: vi.fn(async () => ({})),
    portalAcknowledgeHandoff: vi.fn(async () => ({})),
    recordJourneyEvent: h.recordJourneyEvent,
  },
  ApiError: class ApiError extends Error {},
}));

import { MessagesLayout } from "@/app/messages/MessagesLayout";

function installMatchMedia() {
  (window as any).matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false, media: query, onchange: null,
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
  }));
}

async function openLeadWithRail() {
  render(<MessagesLayout portalSlug="test-persona" canEdit />);
  fireEvent.click(await screen.findByText("Ana Paula"));
  await waitFor(() => expect(document.querySelector(".message-panel")).toBeTruthy());
  const toggle = screen.getByTitle("Mostrar conhecimento");
  fireEvent.click(toggle);
  await waitFor(() => expect(document.querySelector(".knowledge-panel")).toBeTruthy());
  return document.querySelector(".knowledge-panel") as HTMLElement;
}

describe("lead-state — eixo do desfecho", () => {
  it("normaliza só os desfechos publicados", () => {
    for (const outcome of JOURNEY_OUTCOMES) {
      expect(normalizeJourneyOutcome(outcome)).toBe(outcome);
      expect(normalizeJourneyOutcome(outcome.toUpperCase())).toBe(outcome);
    }
    expect(normalizeJourneyOutcome("fechado")).toBeNull();
    expect(normalizeJourneyOutcome(null)).toBeNull();
    expect(normalizeJourneyOutcome(undefined)).toBeNull();
    expect(normalizeJourneyOutcome("")).toBeNull();
  });

  it("só entregue e cancelado fecham a jornada", () => {
    expect(isJourneySettled("entregue")).toBe(true);
    expect(isJourneySettled("cancelado")).toBe(true);
    expect(isJourneySettled("vendido")).toBe(false);
    expect(isJourneySettled("convertido")).toBe(false);
    expect(isJourneySettled("qualificado")).toBe(false);
    expect(isJourneySettled(null)).toBe(false);
  });
});

describe("Mensagens — desfecho da jornada", () => {
  beforeEach(() => {
    installMatchMedia();
    recordJourneyEvent.mockClear();
    setLead(makeLead());
  });

  it("a lista pinta o desfecho no lugar do estágio", async () => {
    render(<MessagesLayout portalSlug="test-persona" canEdit />);
    await screen.findByText("Ana Paula");
    const marca = document.querySelector('[data-outcome="vendido"]');
    expect(marca).toBeTruthy();
    // O estágio não some do produto: sai desta linha, continua no rail.
    const lista = document.querySelector(".conversation-sidebar") as HTMLElement;
    expect(within(lista).queryByText("qualificado")).toBeNull();
  });

  it("sem jornada, a lista volta a mostrar o estágio", async () => {
    setLead(makeLead({ journey_outcome: null }));
    render(<MessagesLayout portalSlug="test-persona" canEdit />);
    await screen.findByText("Ana Paula");
    expect(document.querySelector("[data-outcome]")).toBeNull();
    const lista = document.querySelector(".conversation-sidebar") as HTMLElement;
    expect(within(lista).getByText("qualificado")).toBeTruthy();
  });

  it("o rail mostra as notas comerciais por inteiro, não o resumo de duas chaves", async () => {
    const rail = await openLeadWithRail();
    expect(within(rail).getByText("Pedido")).toBeTruthy();
    // O nome do produto vive no resumo do topo e não se repete no bloco.
    expect(within(rail).getAllByText("Kit Modal 1 — azul marinho")).toHaveLength(1);
    expect(within(rail).getByText("5 peças")).toBeTruthy();
    expect(within(rail).getByText("Sedex · 12/09")).toBeTruthy();
    // 6 notas úteis (updated_at é metadado): 4 visíveis + o revelador.
    expect(within(rail).getByText("+2 campos")).toBeTruthy();
    fireEvent.click(within(rail).getByText("+2 campos"));
    expect(within(rail).getByText("aceita frete grátis")).toBeTruthy();
  });

  it("sobram duas ações: só venda e cancelamento comprometem o pedido", async () => {
    const rail = await openLeadWithRail();
    expect(within(rail).getByRole("button", { name: /Venda/ })).toBeTruthy();
    expect(within(rail).getByRole("button", { name: /Cancelamento/ })).toBeTruthy();
    // Conversão virou toggle; entrega chega por integração, não pelo operador.
    expect(within(rail).queryByRole("button", { name: /Entregue/ })).toBeNull();
    expect(within(rail).queryByRole("button", { name: /^Conversão$/ })).toBeNull();
    // vendido: a venda já está registrada.
    expect(within(rail).getByRole("button", { name: /Venda/ })).toBeDisabled();
    expect(within(rail).getByRole("button", { name: /Cancelamento/ })).not.toBeDisabled();
  });

  it("jornada fechada não aceita mais nenhum evento", async () => {
    setLead(makeLead({ journey_outcome: "cancelado" }));
    const rail = await openLeadWithRail();
    for (const label of ["Venda", "Cancelamento"]) {
      expect(within(rail).getByRole("button", { name: new RegExp(label) })).toBeDisabled();
    }
  });

  it("o toggle alterna qualificado para convertido", async () => {
    setLead(makeLead({ journey_outcome: "qualificado" }));
    const rail = await openLeadWithRail();
    const toggle = within(rail).getByRole("switch", { name: "Conversão do pedido" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(within(toggle).getByText("qualificado")).toBeTruthy();

    fireEvent.click(toggle);
    await waitFor(() => expect(recordJourneyEvent).toHaveBeenCalledTimes(1));
    expect(recordJourneyEvent).toHaveBeenCalledWith(1, expect.objectContaining({
      event_type: "converted",
      idempotency_key: "dashboard:1:converted",
    }));
  });

  it("o toggle desfaz a conversão enquanto não há venda", async () => {
    setLead(makeLead({ journey_outcome: "convertido" }));
    const rail = await openLeadWithRail();
    const toggle = within(rail).getByRole("switch", { name: "Conversão do pedido" });
    expect(toggle).toHaveAttribute("aria-checked", "true");

    fireEvent.click(toggle);
    await waitFor(() => expect(recordJourneyEvent).toHaveBeenCalledTimes(1));
    expect(recordJourneyEvent).toHaveBeenCalledWith(1, expect.objectContaining({
      event_type: "conversion_reverted",
      idempotency_key: "dashboard:1:conversion_reverted",
    }));
  });

  it("depois da venda a conversão deixa de ser reversível", async () => {
    const rail = await openLeadWithRail(); // vendido
    expect(within(rail).queryByRole("switch")).toBeNull();
    const marca = rail.querySelector('[data-outcome="vendido"]');
    expect(marca).toBeTruthy();
    expect(marca).toHaveAttribute(
      "title",
      "A venda já foi registrada — a conversão deixou de ser reversível",
    );
  });

  it("cancelamento pede confirmação antes de fechar o pedido", async () => {
    const rail = await openLeadWithRail();
    fireEvent.click(within(rail).getByRole("button", { name: /Cancelamento/ }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/fecha o pedido/)).toBeTruthy();
    expect(recordJourneyEvent).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Confirmar" }));
    await waitFor(() => expect(recordJourneyEvent).toHaveBeenCalledTimes(1));
    expect(recordJourneyEvent).toHaveBeenCalledWith(1, expect.objectContaining({
      event_type: "cancelled",
      idempotency_key: "dashboard:1:cancelled",
      source: "dashboard",
    }));
  });

  it("a chave de idempotência é determinística — clique duplo não duplica evento", async () => {
    setLead(makeLead({ journey_outcome: "convertido" }));
    const rail = await openLeadWithRail();
    const botao = within(rail).getByRole("button", { name: /Venda/ });
    fireEvent.click(botao);
    fireEvent.click(botao);
    await waitFor(() => expect(recordJourneyEvent).toHaveBeenCalled());
    const chaves = new Set(recordJourneyEvent.mock.calls.map((c: any[]) => c[1].idempotency_key));
    expect(chaves).toEqual(new Set(["dashboard:1:sale_recorded"]));
  });

  it("sem permissão de edição, nenhuma ação é oferecida", async () => {
    render(<MessagesLayout portalSlug="test-persona" canEdit={false} />);
    fireEvent.click(await screen.findByText("Ana Paula"));
    await waitFor(() => expect(document.querySelector(".message-panel")).toBeTruthy());
    fireEvent.click(screen.getByTitle("Mostrar conhecimento"));
    await waitFor(() => expect(document.querySelector(".knowledge-panel")).toBeTruthy());
    const rail = document.querySelector(".knowledge-panel") as HTMLElement;
    expect(within(rail).queryByRole("button", { name: /Cancelamento/ })).toBeNull();
    // O pedido continua legível — só as ações somem.
    expect(within(rail).getByText("Pedido")).toBeTruthy();
  });
});
