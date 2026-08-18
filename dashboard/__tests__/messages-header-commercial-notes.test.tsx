import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

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
        updated_at: "2026-08-13T00:00:00Z",
      },
    },
    qualification_score: 72,
    journey_outcome: null,
    business_model: "sales",
    lead_converted: false,
    journey_is_open: true,
    ...overrides,
  };
}

const h = vi.hoisted(() => ({ lead: { current: null as any } }));
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

async function abrirConversa() {
  render(<MessagesLayout portalSlug="test-persona" canEdit />);
  fireEvent.click(await screen.findByText("Ana Paula"));
  await waitFor(() => expect(document.querySelector(".message-panel")).toBeTruthy());
  return document.querySelector(".message-panel") as HTMLElement;
}

describe("Mensagens — cabeçalho da conversa", () => {
  beforeEach(() => {
    installMatchMedia();
    setLead(makeLead());
  });

  it("não repete o produto de interesse como span solto no cabeçalho", async () => {
    const header = await abrirConversa();
    // O nome do produto só deve aparecer via chip de nota comercial (se
    // bater com algum fato), nunca como span isolado duplicando o que os
    // chips já mostram.
    expect(within(header).queryByText("Kit Modal 1 — azul marinho")).toBeNull();
  });

  it("mostra as notas comerciais mesmo sem commercial_note_projection populada", async () => {
    // Lead ainda sem nenhum galho ativo confirmado: commercial_note_projection
    // vem com services={} (não ausente), o que antes fazia os chips
    // desaparecerem por completo mesmo com commercial_note preenchida.
    setLead(makeLead({
      metadata: {
        commercial_note: { quantidade: "5 peças", cores: "azul marinho, cinza" },
        commercial_note_projection: {
          version: 1, focused_service_id: null, active_service_ids: [],
          common_facts: {}, services: {},
        },
      },
    }));
    const header = await abrirConversa();
    expect(within(header).getByText("5 peças")).toBeTruthy();
  });

  it("renderiza o fato do seletor de serviço já humanizado, sem slug cru", async () => {
    // O backend (graph_agent_runtime_v3._commercial_note_projection) agora
    // manda o valor do campo seletor já humanizado ("Chapeação"), não o
    // slug cru ("chapeacao") -- este teste garante que offeringChipEntries
    // segue fielmente o que a projeção manda, sem reintroduzir o slug cru
    // em algum humanizer só do frontend.
    setLead(makeLead({
      metadata: {
        commercial_note_projection: {
          version: 1, focused_service_id: "branch:a", active_service_ids: ["branch:a"],
          common_facts: {},
          services: {
            "branch:a": { slug: "chapeacao", title: "Chapeação", facts: { servico: "Chapeação" } },
          },
        },
      },
    }));
    const header = await abrirConversa();
    expect(within(header).queryByText(/chapeacao/i)).toBeNull();
    expect(within(header).getByText(/Chapeação/)).toBeTruthy();
  });

  it("usa o selo de pausa (não o de atenção) quando handoff_level é partial", async () => {
    // handoff_level="partial" é a IA sinalizando uma primeira dúvida/handoff
    // sem qualificação completa -- para o operador olhando o header isso lê
    // como "a IA parou de tocar sozinha aqui", igual a handoff_level="full".
    // O badge não deve usar o amarelo de "Atenção": deve ler "Pausada", com
    // a mesma cor de "full".
    setLead(makeLead({ handoff_level: "partial", ai_paused: false }));
    const header = await abrirConversa();
    const button = within(header).getByRole("button", { name: /Pausada/ });
    expect(button.className).not.toMatch(/amber/);
    expect(button.className).toMatch(/red/);
    expect(within(header).queryByText("Atenção")).toBeNull();
  });

  it("o toggle manual desligado sempre prevalece sobre o estado partial", async () => {
    setLead(makeLead({ handoff_level: "full", ai_paused: true }));
    const header = await abrirConversa();
    const button = within(header).getByRole("button", { name: /Pausada/ });
    expect(button.title).toMatch(/clique para retomar/i);
  });
});
