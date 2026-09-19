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
    fireEvent.click(screen.getByRole("button", { name: "Gerar preview" }));

    await waitFor(() => expect(mocks.queue).toHaveBeenCalledWith(expect.objectContaining({ personaId: "tock-persona" })));
    await waitFor(() => expect(mocks.control).toHaveBeenCalledWith("reprocess", { buffer_ids: ["technical-inbound"] }));
  });

  it("creates a separate reactivation preview from the inline action", async () => {
    mocks.queue.mockResolvedValue({
      items: [{
        id: "sent-outbound", persona_id: "tock-persona", preview: "Posso ajudar?", preview_text: "Posso ajudar?",
        latest_message: "Ultima mensagem da cliente", queue_state: "awaiting_customer",
        origin: "conversation", lead: { nome: "Teste" }, persona: { name: "Tock Fatal" },
        actions: ["reactivate"],
      }], next_offset: null,
    });
    render(<ReleaseQueuePanel />);

    expect(await screen.findByText("Ultima mensagem da cliente")).toBeInTheDocument();
    expect(screen.getByText("Nenhuma prévia nova gerada")).toBeInTheDocument();
    expect(screen.queryByText("Posso ajudar?")).not.toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: "Reativar cliente" }));

    await waitFor(() => expect(mocks.control).toHaveBeenCalledWith("reactivate", { buffer_ids: ["sent-outbound"] }));
  });

  it("renders a contextual pair as a connected journey without generic context", async () => {
    mocks.queue.mockResolvedValue({
      items: [
        {
          id: "pair-1", persona_id: "tock-persona", queue_state: "preview_ready", origin: "proactive",
          latest_message: "Última mensagem real da cliente", preview_text: "Prévia de retomada",
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

    expect(await screen.findByText("Última mensagem real da cliente")).toBeInTheDocument();
    expect(screen.getAllByText("Prévia de retomada")).toHaveLength(2);
    expect(screen.getByText("Prévia contextual diferente")).toBeInTheDocument();
    expect(screen.queryByText(/Contexto:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/independentemente da primeira/)).not.toBeInTheDocument();
  });
});
