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
        id: "sent-outbound", persona_id: "tock-persona", preview: "Posso ajudar?", queue_state: "awaiting_customer",
        origin: "conversation", lead: { nome: "Teste" }, persona: { name: "Tock Fatal" },
        actions: ["reactivate"],
      }], next_offset: null,
    });
    render(<ReleaseQueuePanel />);

    fireEvent.click(await screen.findByRole("button", { name: "Reativar cliente" }));

    await waitFor(() => expect(mocks.control).toHaveBeenCalledWith("reactivate", { buffer_ids: ["sent-outbound"] }));
  });
});
