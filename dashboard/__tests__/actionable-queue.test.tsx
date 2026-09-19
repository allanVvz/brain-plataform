import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReleaseQueuePanel } from "@/components/disparos/ReleaseQueuePanel";

const mocks = vi.hoisted(() => ({ queue: vi.fn(), control: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: { messagingQueue: mocks.queue, controlMessagingQueue: mocks.control },
}));

vi.mock("@/lib/useGlobalPersona", () => ({
  useGlobalPersona: () => ({ id: "tock-persona", slug: "tock-fatal" }),
}));

describe("actionable message queue", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.queue.mockResolvedValue({
      items: [{
        id: "technical-inbound", persona_id: "tock-persona", preview: "oi", queue_state: "technical_failure",
        origin: "conversation", available_at: "2026-09-18T12:00:00.000Z",
        lead: { nome: "Teste" }, persona: { name: "Tock Fatal" }, actions: ["reprocess"],
      }], next_offset: null,
    });
    mocks.control.mockResolvedValue({ items: [{ result: "preview_gerado" }] });
  });

  it("removes the misleading global label and generates a preview without asking for a reason", async () => {
    render(<ReleaseQueuePanel />);

    expect(await screen.findByText("Mensagens ativas.", { exact: false })).toBeInTheDocument();
    expect(screen.queryByText("Global")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Lead")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Selecionar mensagem"));
    fireEvent.click(screen.getAllByRole("button", { name: "Corrigir e gerar resposta" }).at(-1)!);

    await waitFor(() => expect(mocks.queue).toHaveBeenCalledWith(expect.objectContaining({ personaId: "tock-persona" })));
    await waitFor(() => expect(mocks.control).toHaveBeenCalledWith("reprocess", { buffer_ids: ["technical-inbound"] }));
  });

  it("creates a separate reactivation preview from the inline action", async () => {
    mocks.queue.mockResolvedValue({
      items: [{
        id: "sent-outbound", persona_id: "tock-persona", preview: "Posso ajudar?", preview_text: "Posso ajudar?",
        latest_message: "Ultima mensagem da cliente", last_agent_message: "Posso ajudar?", queue_state: "awaiting_customer",
        origin: "conversation", lead: { nome: "Teste" }, persona: { name: "Tock Fatal" },
        actions: ["reactivate"],
      }], next_offset: null,
    });
    render(<ReleaseQueuePanel />);

    expect(await screen.findByText("Posso ajudar?")).toBeInTheDocument();
    expect(screen.getByText("Nenhuma prévia nova gerada")).toBeInTheDocument();
    expect(screen.queryByText("Ultima mensagem da cliente")).not.toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: "Reativar cliente" }));

    await waitFor(() => expect(mocks.control).toHaveBeenCalledWith("reactivate", { buffer_ids: ["sent-outbound"] }));
  });

  it("renders a contextual pair as a connected journey without generic context", async () => {
    mocks.queue.mockResolvedValue({
      items: [
        {
          id: "pair-1", persona_id: "tock-persona", queue_state: "preview_ready", origin: "proactive",
          latest_message: "Última mensagem real da cliente", last_agent_message: "Resposta anterior do modelo", preview_text: "Prévia de retomada",
          reactivation_group_id: "12345678-1234-1234-1234-123456789012", sequence_index: 1,
          line_kind: "apology", preview_revision: 2, lead: { nome: "Teste" }, persona: { name: "Tock Fatal" }, actions: [],
        },
        {
          id: "pair-2", persona_id: "tock-persona", queue_state: "preview_ready", origin: "proactive",
          first_preview_text: "Prévia de retomada", preview_text: "Prévia contextual diferente",
          reactivation_group_id: "12345678-1234-1234-1234-123456789012", sequence_index: 2,
          line_kind: "context", preview_revision: 2, lead: { nome: "Teste" }, persona: { name: "Tock Fatal" }, actions: [],
        },
      ], next_offset: null,
    });

    render(<ReleaseQueuePanel />);

    expect(await screen.findByText("Resposta anterior do modelo")).toBeInTheDocument();
    expect(screen.getAllByText("Prévia de retomada")).toHaveLength(2);
    expect(screen.getByText("Prévia contextual diferente")).toBeInTheDocument();
    expect(screen.queryByText(/Contexto:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/independentemente da primeira/)).not.toBeInTheDocument();
  });

  it("keeps generation separate from sending an existing preview", async () => {
    mocks.queue.mockResolvedValue({
      items: [{
        id: "preview-1", persona_id: "tock-persona", queue_state: "preview_ready",
        preview_text: "Resposta pronta para revisão", lead: { nome: "Allan" },
        persona: { name: "Tock Fatal" }, actions: ["send_preview", "pause"],
      }], next_offset: null,
    });

    render(<ReleaseQueuePanel />);

    expect(await screen.findByText("Resposta pronta para revisão")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enviar" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Corrigir e gerar resposta" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));

    await waitFor(() => expect(mocks.control).toHaveBeenCalledWith(
      "send-preview", { buffer_ids: ["preview-1"] },
    ));
  });

  it("uses the last agent message as the row anchor and keeps the combined context in a dropdown", async () => {
    mocks.queue.mockResolvedValue({
      items: [{
        id: "pending-inbound", persona_id: "tock-persona", queue_state: "pending_response",
        latest_message: "A nova mensagem do cliente", last_agent_message: "Resposta anterior da Vitoria",
        recent_context: [
          { id: "agent-1", direction: "outbound", role: "assistant", content: "Resposta anterior da Vitoria" },
          { id: "client-1", direction: "inbound", role: "user", content: "A nova mensagem do cliente" },
        ],
        lead: { nome: "Allan" }, persona: { name: "Tock Fatal" }, actions: [],
      }], next_offset: null,
    });

    render(<ReleaseQueuePanel />);

    expect((await screen.findAllByText("Resposta anterior da Vitoria"))[0]).toBeInTheDocument();
    expect(screen.getAllByText("Aguardando resposta da IA").length).toBeGreaterThan(0);
    const dropdown = screen.getByText("Ver contexto (2)");
    expect(dropdown).toBeInTheDocument();
    fireEvent.click(dropdown);
    expect(screen.getByText("A nova mensagem do cliente")).toBeInTheDocument();
  });

  it("does not replace a missing agent message with the customer's message", async () => {
    mocks.queue.mockResolvedValue({
      items: [{
        id: "blocked-inbound", persona_id: "tock-persona", queue_state: "blocked",
        latest_message: "Mensagem recente do cliente", last_error: "binding safety paused",
        lead: { nome: "Allan" }, persona: { name: "Tock Fatal" }, actions: [],
      }], next_offset: null,
    });

    render(<ReleaseQueuePanel />);

    expect(await screen.findByText("Nenhuma mensagem anterior do agente registrada")).toBeInTheDocument();
    expect(screen.queryByText("Mensagem recente do cliente")).not.toBeInTheDocument();
    expect(screen.getAllByText("Bloqueada").length).toBeGreaterThan(0);
    expect(screen.getAllByText("binding safety paused").length).toBeGreaterThan(0);
    expect(screen.getByText("Sem ação segura disponível")).toBeInTheDocument();
  });
});
