import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReleaseQueuePanel } from "@/components/disparos/ReleaseQueuePanel";

const mocks = vi.hoisted(() => ({ queue: vi.fn(), control: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { messagingQueue: mocks.queue, controlMessagingQueue: mocks.control } }));
vi.mock("@/lib/useGlobalPersona", () => ({ useGlobalPersona: () => ({ id: "persona-1", slug: "fixture" }) }));

const base = {
  id: "demand-1", demand_id: "group-1", persona_id: "persona-1", lead_ref: 7,
  customer_message: "Preciso saber quando vocês atendem", customer_message_at: "2026-09-18T10:00:00Z",
  last_agent_message: "Como posso ajudar?", lead: { nome: "Cliente real" }, persona: { name: "Loja" },
  origin: "proactive", queue_state: "preview_ready", recent_context: [
    { id: "i1", direction: "inbound", content: "Preciso saber quando vocês atendem", created_at: "2026-09-18T10:00:00Z" },
    { id: "o1", direction: "outbound", content: "Como posso ajudar?", created_at: "2026-09-18T09:59:00Z" },
  ],
};

describe("operational demand queue", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.control.mockResolvedValue({ items: [{ result: "agendado" }] });
    mocks.queue.mockResolvedValue({ items: [{ ...base, outbound_messages: [{
      buffer_id: "message-1", sequence: 1, kind: "response", text: "Resposta pronta",
      proof_id: "proof-1", status: "preview_ready", can_retry: true, can_send: true,
    }] }], next_offset: null });
  });

  it("renders customer context and one outbound without ever using inbound as preview", async () => {
    render(<ReleaseQueuePanel />);
    expect(await screen.findByText("Contexto da conversa")).toBeInTheDocument();
    expect(screen.getAllByText("Preciso saber quando vocês atendem").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Como posso ajudar?").length).toBeGreaterThan(0);
    expect(screen.getByText("Resposta pronta")).toBeInTheDocument();
    expect(screen.getByText("Mensagem 1 de 1")).toBeInTheDocument();
    expect(screen.queryByText("Mensagem anterior")).not.toBeInTheDocument();
  });

  it("shows Retry and Enviar even when a capability is blocked", async () => {
    mocks.queue.mockResolvedValue({ items: [{ ...base, outbound_messages: [{
      buffer_id: "message-1", sequence: 1, kind: "response", text: "Resposta pronta",
      status: "processing", can_retry: false, retry_reason: "Envio em andamento",
      can_send: false, send_reason: "Mensagem não está pronta para envio",
    }] }], next_offset: null });
    render(<ReleaseQueuePanel />);
    expect(await screen.findByRole("button", { name: "Retry mensagem 1" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Enviar mensagem 1" })).toBeDisabled();
    expect(screen.getByText(/Retry: Envio em andamento/)).toBeInTheDocument();
  });

  it("retries one ordinary outbound without sending it", async () => {
    render(<ReleaseQueuePanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry mensagem 1" }));
    await waitFor(() => expect(mocks.control).toHaveBeenCalledWith(
      "regenerate-preview", { buffer_ids: ["message-1"] },
    ));
    expect(mocks.control).not.toHaveBeenCalledWith("send-preview", expect.anything());
  });

  it("explicitly generates an inert preview from a blocked inbound", async () => {
    mocks.queue.mockResolvedValue({ items: [{ ...base, queue_state: "blocked", outbound_messages: [{
      buffer_id: "canonical-inbound", sequence: 1, kind: "response", status: "blocked",
      can_retry: false, retry_reason: "Demanda sem falha técnica recuperável",
      can_generate_preview: true, can_send: false, send_reason: "Gere uma resposta válida antes de enviar",
    }] }], next_offset: null });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ReleaseQueuePanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Gerar prévia da mensagem 1" }));
    await waitFor(() => expect(mocks.control).toHaveBeenCalledWith(
      "operator-preview", { buffer_ids: ["canonical-inbound"] },
    ));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("mensagem original"));
    expect(mocks.control).not.toHaveBeenCalledWith("send-preview", expect.anything());
  });

  it("renders two messages in one demand and blocks message 2 until message 1 is confirmed", async () => {
    mocks.queue.mockResolvedValue({ items: [{ ...base, outbound_messages: [
      { buffer_id: "first", sequence: 1, kind: "apology", text: "Aviso de horário", proof_id: "proof-1", status: "preview_ready", can_retry: true, can_send: true },
      { buffer_id: "second", sequence: 2, kind: "context", text: "Resposta contextual", proof_id: "proof-2", status: "preview_ready", can_retry: true, can_send: false, send_reason: "A mensagem 1 ainda não foi confirmada" },
    ] }], next_offset: null });
    render(<ReleaseQueuePanel />);
    expect(await screen.findByText("Mensagem 1 de 2")).toBeInTheDocument();
    expect(screen.getByText("Mensagem 2 de 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enviar mensagem 2" })).toBeDisabled();
    expect(screen.getByText(/A mensagem 1 ainda não foi confirmada/)).toBeInTheDocument();
  });

  it("retries only the selected second message and does not send in the same click", async () => {
    mocks.queue.mockResolvedValue({ items: [{ ...base, outbound_messages: [
      { buffer_id: "first-sent", sequence: 1, kind: "apology", text: "Aviso", status: "sent", can_retry: false, retry_reason: "Mensagem já confirmada", can_send: false, send_reason: "Mensagem já confirmada" },
      { buffer_id: "second-failed", sequence: 2, kind: "context", text: "Contexto", status: "failed", can_retry: true, can_send: false, send_reason: "Mensagem não está pronta para envio" },
    ] }], next_offset: null });
    render(<ReleaseQueuePanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry mensagem 2" }));
    await waitFor(() => expect(mocks.control).toHaveBeenCalledTimes(1));
    expect(mocks.control).toHaveBeenCalledWith("regenerate-preview", { buffer_ids: ["second-failed"] });
    expect(mocks.control).not.toHaveBeenCalledWith("send-preview", expect.anything());
  });

  it("sends one selected message and suppresses a double click while the request is pending", async () => {
    let resolve!: (value: unknown) => void;
    mocks.control.mockReturnValue(new Promise((done) => { resolve = done; }));
    render(<ReleaseQueuePanel />);
    const button = await screen.findByRole("button", { name: "Enviar mensagem 1" });
    fireEvent.click(button); fireEvent.click(button);
    expect(mocks.control).toHaveBeenCalledTimes(1);
    expect(mocks.control).toHaveBeenCalledWith("send-preview", { buffer_ids: ["message-1"] });
    resolve({ items: [{ result: "agendado" }] });
  });

  it("shows three API demands for one lead without a local two-row limit", async () => {
    mocks.queue.mockResolvedValue({ items: [1, 2, 3].map((value) => ({
      ...base, id: `d-${value}`, demand_id: `g-${value}`, customer_message: `Demanda ${value}`,
      outbound_messages: [{ buffer_id: `b-${value}`, sequence: 1, kind: "response", text: `Resposta ${value}`, status: "blocked", can_retry: false, can_send: false }],
    })), next_offset: null });
    render(<ReleaseQueuePanel />);
    expect(await screen.findByText("Demanda 1")).toBeInTheDocument();
    expect(screen.getByText("Demanda 2")).toBeInTheDocument();
    expect(screen.getByText("Demanda 3")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Retry mensagem 1/ })).toHaveLength(3);
  });

  it("uses the explicit empty-agent fallback and expands directional history", async () => {
    mocks.queue.mockResolvedValue({ items: [{ ...base, last_agent_message: null, outbound_messages: [{ buffer_id: "blocked", sequence: 1, kind: "response", status: "blocked", can_retry: false, can_send: false }] }], next_offset: null });
    render(<ReleaseQueuePanel />);
    expect(await screen.findByText("Ainda sem resposta do agente")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Histórico recente (2)"));
    const history = screen.getByText("Histórico recente (2)").parentElement!;
    expect(within(history).getByText(/Cliente ·/)).toBeInTheDocument();
    expect(within(history).getByText(/Agente ·/)).toBeInTheDocument();
  });
});
