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
    business_model: "sales",
    lead_converted: true,
    journey_is_open: true,
    ...overrides,
  };
}

// vi.mock é içado para o topo, então tudo que a factory referencia precisa
// nascer em vi.hoisted.
const h = vi.hoisted(() => ({
  setJourneyState: vi.fn(async () => ({ target: "vendido", from: "convertido", changed: true })),
  portalSetJourneyState: vi.fn(async () => ({ target: "vendido", from: "convertido", changed: true })),
  lead: { current: null as any },
}));
const setState = h.portalSetJourneyState;
const setStateAdmin = h.setJourneyState;

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
    setJourneyState: h.setJourneyState,
    portalSetJourneyState: h.portalSetJourneyState,
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

async function abrirRail() {
  render(<MessagesLayout portalSlug="test-persona" canEdit />);
  fireEvent.click(await screen.findByText("Ana Paula"));
  await waitFor(() => expect(document.querySelector(".message-panel")).toBeTruthy());
  fireEvent.click(screen.getByTitle("Mostrar conhecimento"));
  await waitFor(() => expect(document.querySelector(".knowledge-panel")).toBeTruthy());
  return document.querySelector(".knowledge-panel") as HTMLElement;
}

async function abrirSeletor() {
  const rail = await abrirRail();
  fireEvent.click(within(rail).getByRole("button", { name: "Estado do pedido" }));
  return within(rail).getByRole("listbox");
}

describe("lead-state — eixo do desfecho", () => {
  it("normaliza só os desfechos publicados", () => {
    for (const outcome of JOURNEY_OUTCOMES) {
      expect(normalizeJourneyOutcome(outcome)).toBe(outcome);
      expect(normalizeJourneyOutcome(outcome.toUpperCase())).toBe(outcome);
    }
    expect(normalizeJourneyOutcome("fechado")).toBeNull();
    expect(normalizeJourneyOutcome(null)).toBeNull();
  });

  it("só entregue e cancelado fecham o pedido", () => {
    expect(isJourneySettled("entregue")).toBe(true);
    expect(isJourneySettled("cancelado")).toBe(true);
    expect(isJourneySettled("vendido")).toBe(false);
    expect(isJourneySettled(null)).toBe(false);
  });
});

describe("Mensagens — seletor de estado do pedido", () => {
  beforeEach(() => {
    installMatchMedia();
    setState.mockClear();
    setStateAdmin.mockClear();
    setLead(makeLead());
  });

  it("o closer muda o estado em qualquer direção", async () => {
    // O pedido está vendido; voltar para convertido precisa ser possível —
    // antes o controle travava e não havia como corrigir um clique errado.
    const menu = await abrirSeletor();
    fireEvent.click(within(menu).getByRole("option", { name: /convertido/i }));
    await waitFor(() => expect(setState).toHaveBeenCalledTimes(1));
    expect(setState).toHaveBeenCalledWith("test-persona", 1, expect.objectContaining({
      target: "convertido",
      source: "dashboard",
    }));
  });

  it("produto e serviço nomeiam os mesmos passos de formas diferentes", async () => {
    setLead(makeLead({ business_model: "appointment", journey_outcome: "convertido" }));
    const menu = await abrirSeletor();
    expect(within(menu).getByRole("option", { name: /agendado/i })).toBeTruthy();
    expect(within(menu).getByRole("option", { name: /concluído/i })).toBeTruthy();
    expect(within(menu).queryByRole("option", { name: /^comprado/i })).toBeNull();
  });

  it("lead já convertida não recebe qualificado como opção", async () => {
    const menu = await abrirSeletor();
    expect(within(menu).queryByRole("option", { name: /qualificado/i })).toBeNull();
    expect(within(menu).getByRole("option", { name: /convertido/i })).toBeTruthy();
  });

  it("lead que nunca converteu ainda pode voltar a qualificado", async () => {
    setLead(makeLead({ lead_converted: false, journey_outcome: "convertido" }));
    const menu = await abrirSeletor();
    expect(within(menu).getByRole("option", { name: /qualificado/i })).toBeTruthy();
  });

  it("fechar o pedido pede confirmação e avisa que a IA volta", async () => {
    const menu = await abrirSeletor();
    fireEvent.click(within(menu).getByRole("option", { name: /entregue/i }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/devolve a conversa para a IA/)).toBeTruthy();
    expect(setState).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Confirmar" }));
    await waitFor(() => expect(setState).toHaveBeenCalledTimes(1));
    expect(setState).toHaveBeenCalledWith("test-persona", 1, expect.objectContaining({
      target: "entregue",
    }));
  });

  it("mudar para um estado aberto não pede confirmação", async () => {
    setLead(makeLead({ journey_outcome: "convertido" }));
    const menu = await abrirSeletor();
    fireEvent.click(within(menu).getByRole("option", { name: /comprado/i }));
    await waitFor(() => expect(setState).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("um pedido fechado continua editável", async () => {
    // `is_current=false` não pode travar o closer: reabrir é justamente o que
    // faltava. Quem recusa é o backend, se já houver pedido mais novo.
    setLead(makeLead({ journey_outcome: "entregue", journey_is_open: false }));
    const menu = await abrirSeletor();
    fireEvent.click(within(menu).getByRole("option", { name: /comprado/i }));
    await waitFor(() => expect(setState).toHaveBeenCalledTimes(1));
    expect(setState).toHaveBeenCalledWith("test-persona", 1, expect.objectContaining({
      target: "vendido",
    }));
  });

  it("a recusa do backend aparece na tela, não some", async () => {
    setState.mockRejectedValueOnce(
      new Error("Ja existe um pedido mais novo para esta lead; nao da para reabrir o anterior."),
    );
    setLead(makeLead({ journey_outcome: "cancelado", journey_is_open: false }));
    const menu = await abrirSeletor();
    fireEvent.click(within(menu).getByRole("option", { name: /convertido/i }));
    expect(await screen.findByText(/pedido mais novo/)).toBeTruthy();
  });

  it("no portal o estado vai pela rota do portal, nunca por /agents", async () => {
    const menu = await abrirSeletor();
    fireEvent.click(within(menu).getByRole("option", { name: /convertido/i }));
    await waitFor(() => expect(setState).toHaveBeenCalled());
    expect(setStateAdmin).not.toHaveBeenCalled();
  });

  it("sem permissão de edição o estado vira leitura", async () => {
    render(<MessagesLayout portalSlug="test-persona" canEdit={false} />);
    fireEvent.click(await screen.findByText("Ana Paula"));
    await waitFor(() => expect(document.querySelector(".message-panel")).toBeTruthy());
    fireEvent.click(screen.getByTitle("Mostrar conhecimento"));
    await waitFor(() => expect(document.querySelector(".knowledge-panel")).toBeTruthy());
    const rail = document.querySelector(".knowledge-panel") as HTMLElement;
    expect(within(rail).queryByRole("button", { name: "Estado do pedido" })).toBeNull();
    expect(rail.querySelector('[data-outcome="vendido"]')).toBeTruthy();
    // O pedido continua legível — só o controle some.
    expect(within(rail).getByText("Pedido")).toBeTruthy();
  });

  it("o rail mostra as notas comerciais por inteiro, sem repetir o produto", async () => {
    const rail = await abrirRail();
    expect(within(rail).getAllByText("Kit Modal 1 — azul marinho")).toHaveLength(1);
    expect(within(rail).getByText("5 peças")).toBeTruthy();
    expect(within(rail).getByText("+2 campos")).toBeTruthy();
  });

  it("a lista pinta o desfecho e não repete o estágio", async () => {
    render(<MessagesLayout portalSlug="test-persona" canEdit />);
    await screen.findByText("Ana Paula");
    const lista = document.querySelector(".conversation-sidebar") as HTMLElement;
    expect(lista.querySelector('[data-outcome="vendido"]')).toBeTruthy();
    expect(within(lista).queryByText("qualificado")).toBeNull();
  });

  it("sem jornada, a lista volta a mostrar o estágio", async () => {
    setLead(makeLead({ journey_outcome: null }));
    render(<MessagesLayout portalSlug="test-persona" canEdit />);
    await screen.findByText("Ana Paula");
    const lista = document.querySelector(".conversation-sidebar") as HTMLElement;
    expect(within(lista).getByText("qualificado")).toBeTruthy();
  });
});
