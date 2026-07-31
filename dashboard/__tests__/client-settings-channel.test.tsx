import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ClientSettingsPage from "@/app/clientes/[personaSlug]/configuracoes/page";

const mocks = vi.hoisted(() => ({
  channel: { configured: true, provider: "meta_cloud", status: "connected" } as any,
  whatsappChannel: vi.fn(),
  connectEvolution: vi.fn(),
}));

vi.mock("@/app/clientes/[personaSlug]/PortalContext", () => ({
  usePortal: () => ({
    personaSlug: "aurora",
    capabilities: { view: true, edit: true, manage: true, manage_members: false },
    user: {
      email: "cliente@example.com",
      must_change_password: false,
    },
  }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: {
      ...original.api,
      whatsappChannel: mocks.whatsappChannel,
      connectEvolution: mocks.connectEvolution,
    },
  };
});

describe("client channel settings", () => {
  beforeEach(() => {
    mocks.channel = {
      configured: true,
      provider: "meta_cloud",
      status: "connected",
    };
    mocks.whatsappChannel.mockReset();
    mocks.whatsappChannel.mockImplementation(async () => mocks.channel);
    mocks.connectEvolution.mockReset();
    mocks.connectEvolution.mockResolvedValue({
      status: "qr_ready",
      qr: { base64: "data:image/png;base64,iVBORw0KGgo=" },
    });
  });

  it("never exposes provider selection or switching to the client", async () => {
    render(<ClientSettingsPage />);
    expect(await screen.findByText("Canal conectado e disponível.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Provider")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Trocar provider/i })).not.toBeInTheDocument();
    expect(screen.getByText("Segurança")).toBeInTheDocument();
  });

  it("shows QR onboarding only for a pending Evolution channel", async () => {
    mocks.channel = {
      configured: true,
      provider: "evolution_baileys",
      status: "qr_ready",
    };
    render(<ClientSettingsPage />);

    const button = await screen.findByRole("button", {
      name: /Gerar ou atualizar QR Code/i,
    });
    fireEvent.click(button);

    await waitFor(() => expect(mocks.connectEvolution).toHaveBeenCalledWith("aurora"));
    expect(await screen.findByAltText("QR Code temporário para conectar WhatsApp")).toBeInTheDocument();
  });
});
