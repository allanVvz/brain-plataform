import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReleaseQueuePanel } from "@/components/disparos/ReleaseQueuePanel";
import { simplifyMessage } from "@/components/disparos/queueSimple";

const mocks = vi.hoisted(() => ({ queue: vi.fn(), control: vi.fn() }));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: { messagingQueue: mocks.queue, controlMessagingQueue: mocks.control } };
});
vi.mock("@/lib/useGlobalPersona", () => ({ useGlobalPersona: () => ({ id: "persona-1", slug: "fixture" }) }));

const demand = (queue_state: string, message: Record<string, unknown>) => ({
  id: `d-${queue_state}`, persona_id: "persona-1", lead: { nome: "Cliente" }, queue_state,
  customer_message: "Quando vocês atendem?", outbound_messages: [{ buffer_id: `m-${queue_state}`, sequence: 1, kind: "response", ...message }],
});
const keys = (state: string, message: Record<string, unknown>) =>
  simplifyMessage(state, message).actions.map((action) => `${action.key}:${action.endpoint}`);

describe("queue vocabulary", () => {
  it("maps every internal state to pausada, agendada, gerar preview or enviar", () => {
    expect(simplifyMessage("preview_ready", { status: "preview_ready", can_send: true }).state).toBe("preview");
    expect(keys("preview_ready", { status: "preview_ready", can_send: true }))
      .toEqual(["enviar:send-preview", "gerar_preview:regenerate-preview", "pausar:pause"]);
    expect(simplifyMessage("pending", { status: "pending_send" }).state).toBe("agendada");
    expect(simplifyMessage("paused", { status: "buffered" })).toEqual({ state: "pausada", actions: [expect.objectContaining({ key: "retomar", endpoint: "resume" })] });
    expect(keys("technical_failure", { status: "technical_failure" })).toEqual(["gerar_preview:reprocess"]);
    expect(keys("blocked", { status: "blocked" })).toEqual(["gerar_preview:operator-preview"]);
    expect(keys("awaiting_customer", { status: "sent" })).toEqual(["gerar_preview:reactivate"]);
  });
});

describe("queue screen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.control.mockResolvedValue({ items: [{ result: "agendado" }] });
    mocks.queue.mockResolvedValue({ items: [demand("preview_ready", { status: "preview_ready", text: "Resposta pronta", can_send: true })], next_offset: null });
  });

  it("shows the lead, the conversation, the preview and only the simple actions", async () => {
    render(<ReleaseQueuePanel />);
    expect(await screen.findByText("Resposta pronta")).toBeInTheDocument();
    expect(screen.getByText("Quando vocês atendem?")).toBeInTheDocument();
    expect(screen.getAllByText("Preview pronto").length).toBeGreaterThan(0);
    for (const label of ["Enviar", "Gerar preview", "Pausar"]) {
      expect(screen.getByRole("button", { name: `${label} mensagem 1` })).toBeEnabled();
    }
    expect(screen.queryByText(/proof/i)).not.toBeInTheDocument();
  });

  it("sends with one idempotency key per click and ignores a double click", async () => {
    let resolve: (value: unknown) => void = () => {};
    mocks.control.mockReturnValue(new Promise((done) => { resolve = done; }));
    render(<ReleaseQueuePanel />);
    const send = await screen.findByRole("button", { name: "Enviar mensagem 1" });
    fireEvent.click(send);
    fireEvent.click(send);
    resolve({ items: [{ result: "agendado" }] });
    await waitFor(() => expect(mocks.control).toHaveBeenCalledTimes(1));
    expect(mocks.control).toHaveBeenCalledWith("send-preview", { buffer_ids: ["m-preview_ready"], idempotency_key: expect.any(String) });
    expect(await screen.findByText("Agendada para envio")).toBeInTheDocument();
  });

  it("keeps Enviar visible but disabled, with the reason", async () => {
    mocks.queue.mockResolvedValue({ items: [demand("preview_ready", {
      status: "preview_ready", text: "Resposta", can_send: false, send_reason: "A mensagem 1 ainda não foi confirmada",
    })], next_offset: null });
    render(<ReleaseQueuePanel />);
    expect(await screen.findByRole("button", { name: "Enviar mensagem 1" })).toBeDisabled();
    expect(screen.getByText("A mensagem 1 ainda não foi confirmada")).toBeInTheDocument();
  });

  it("filters by state", async () => {
    mocks.queue.mockResolvedValue({ items: [
      demand("preview_ready", { status: "preview_ready", text: "Pronta", can_send: true }),
      demand("paused", { status: "buffered", text: "Parada" }),
    ], next_offset: null });
    render(<ReleaseQueuePanel />);
    await screen.findByText("Pronta");
    fireEvent.click(screen.getByRole("button", { name: "Pausadas" }));
    expect(screen.queryByText("Pronta")).not.toBeInTheDocument();
    expect(screen.getByText("Parada")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retomar mensagem 1" })).toBeEnabled();
  });
});
