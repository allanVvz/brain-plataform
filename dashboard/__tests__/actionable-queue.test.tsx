import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReleaseQueuePanel } from "@/components/disparos/ReleaseQueuePanel";

const mocks = vi.hoisted(() => ({ queue: vi.fn(), control: vi.fn() }));

vi.mock("@/lib/api", () => ({
  api: { messagingQueue: mocks.queue, controlMessagingQueue: mocks.control },
}));

describe("actionable message queue", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.queue.mockResolvedValue({
      items: [{
        id: "technical-inbound", preview: "oi", queue_state: "technical_failure",
        origin: "conversation", available_at: "2026-09-18T12:00:00.000Z",
        lead: { nome: "Teste" }, persona: { name: "Tock Fatal" }, actions: ["reprocess"],
      }], next_offset: null,
    });
    mocks.control.mockResolvedValue({ items: [{ result: "preview_gerado" }] });
  });

  it("keeps global scope and generates a preview without asking for a reason", async () => {
    render(<ReleaseQueuePanel />);

    expect(await screen.findByText("Global")).toBeInTheDocument();
    expect(screen.queryByLabelText("Lead")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Selecionar mensagem"));
    fireEvent.change(screen.getByLabelText("Ação para selecionadas"), { target: { value: "reprocess" } });

    await waitFor(() => expect(mocks.control).toHaveBeenCalledWith("reprocess", { buffer_ids: ["technical-inbound"] }));
  });
});
