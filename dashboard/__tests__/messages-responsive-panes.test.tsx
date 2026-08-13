import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

const lead = {
  id: 1,
  lead_id: "1",
  nome: "Jose Debug",
  telefone: "+5511999999999",
  stage: "qualificado",
  ai_enabled: true,
  ai_paused: true,
  handoff_level: "full" as const,
  ultima_mensagem: "oi",
  last_update: "2026-08-13T00:00:00Z",
  updated_at: "2026-08-13T00:00:00Z",
  persona_id: "p1",
  interesse_produto: "teste",
  metadata: {},
  qualification_score: 50,
};
const conv = {
  key: "1",
  nome: "Jose Debug",
  lead_id: "1",
  lead_ref: 1,
  persona_id: "p1",
  interesse_produto: "teste",
  Lead_Stage: "qualificado",
  last_message: "oi",
  last_direction: "inbound",
  last_sender_type: "client",
  last_at: "2026-08-13T00:00:00Z",
  qualification_score: 50,
};

vi.mock("@/lib/api", () => ({
  api: {
    portalLeads: vi.fn(async () => [lead]),
    portalConversations: vi.fn(async () => [conv]),
    portalLead: vi.fn(async () => lead),
    portalConversationMessages: vi.fn(async () => ({ items: [], before_cursor: null, after_cursor: null, next_cursor: null, has_more: false })),
    portalKnowledgeChatContext: vi.fn(async () => ({ query_terms: [], nodes: [], edges: [], kb_entries: [], assets: [], summary: "" })),
    portalSendMessage: vi.fn(async () => ({})),
    portalPauseAi: vi.fn(async () => ({})),
    portalResumeAi: vi.fn(async () => ({})),
    portalAcknowledgeHandoff: vi.fn(async () => ({})),
  },
  ApiError: class ApiError extends Error {},
}));

import { MessagesLayout } from "@/app/messages/MessagesLayout";

// A single fake MediaQueryList shared across window.matchMedia calls, whose
// `matches` we flip per test — this is what the component's own
// useEffect(() => { const mq = matchMedia(...); ... }, []) subscribes to.
function installMatchMedia(mode: "single" | "dual" | "triple") {
  const singleMatches = mode === "single";
  const dualMatches = mode === "dual";
  (window as any).matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes("max-width: 1023px") ? singleMatches : dualMatches,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

describe("Mensagens — modos responsivos (single/dual/triple)", () => {
  beforeEach(() => {
    installMatchMedia("single");
  });

  it("single: abrir um lead troca da lista para a thread", async () => {
    render(<MessagesLayout portalSlug="test-persona" canEdit />);
    const leadButton = await screen.findByText("Jose Debug");

    // Antes de abrir, só a lista existe — a thread não deve estar montada.
    expect(document.querySelector(".message-panel")).toBeNull();

    fireEvent.click(leadButton);

    await waitFor(() => {
      expect(document.querySelector(".message-panel")).toBeTruthy();
    });
    // E a lista sai da árvore — só um painel por vez no modo single.
    expect(document.querySelector(".conversation-sidebar")).toBeNull();
  });

  it("single: o botão voltar do ChatHeader retorna da thread para a lista", async () => {
    render(<MessagesLayout portalSlug="test-persona" canEdit />);
    const leadButton = await screen.findByText("Jose Debug");
    fireEvent.click(leadButton);
    await waitFor(() => expect(document.querySelector(".message-panel")).toBeTruthy());

    const backButton = screen.getByRole("button", { name: "Voltar para a lista" });
    fireEvent.click(backButton);

    await waitFor(() => {
      expect(document.querySelector(".conversation-sidebar")).toBeTruthy();
      expect(document.querySelector(".message-panel")).toBeNull();
    });
  });

  it("dual: lista e thread convivem lado a lado", async () => {
    installMatchMedia("dual");
    render(<MessagesLayout portalSlug="test-persona" canEdit />);
    const leadButton = await screen.findByText("Jose Debug");
    fireEvent.click(leadButton);

    await waitFor(() => {
      expect(document.querySelector(".message-panel")).toBeTruthy();
    });
    // Ao contrário do modo single, a lista continua montada.
    expect(document.querySelector(".conversation-sidebar")).toBeTruthy();
  });

  it("triple: comportamento de desktop inalterado (lista + thread juntas)", async () => {
    installMatchMedia("triple");
    render(<MessagesLayout portalSlug="test-persona" canEdit />);
    const leadButton = await screen.findByText("Jose Debug");
    fireEvent.click(leadButton);

    await waitFor(() => {
      expect(document.querySelector(".message-panel")).toBeTruthy();
    });
    expect(document.querySelector(".conversation-sidebar")).toBeTruthy();
  });
});
