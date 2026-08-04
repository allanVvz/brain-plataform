import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ClientDisparosPage from "@/app/clientes/[personaSlug]/disparos/page";

const mocks = vi.hoisted(() => ({
  capabilitiesEdit: true,
  health: { provider: "meta_cloud", ready: true, rollout_one_enabled: true } as any,
  imports: [{ id: "batch-1", filename: "lista.csv", status: "completed", valid_rows: 2 }] as any[],
  groups: [{ id: "audience-1", name: "Clientes ativos" }] as any[],
  campaigns: [] as any[],
  preview: { counts: { selected_unique: 2, eligible: 2, blocked: 0 }, preview_checksum: "sha256:test" } as any,
  campaignProviderHealth: vi.fn(),
  leadImports: vi.fn(),
  audiences: vi.fn(),
  campaigns_: vi.fn(),
  campaignPreview: vi.fn(),
  createCampaign: vi.fn(),
  pauseCampaign: vi.fn(),
  cancelCampaign: vi.fn(),
}));

vi.mock("@/app/clientes/[personaSlug]/PortalContext", () => ({
  usePortal: () => ({
    personaSlug: "aurora",
    capabilities: { view: true, edit: mocks.capabilitiesEdit, manage: false, manage_members: false },
  }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: {
      ...original.api,
      portalCampaignProviderHealth: mocks.campaignProviderHealth,
      portalLeadImports: mocks.leadImports,
      portalAudiences: mocks.audiences,
      portalCampaigns: mocks.campaigns_,
      portalCampaignPreview: mocks.campaignPreview,
      portalCreateCampaign: mocks.createCampaign,
      portalPauseCampaign: mocks.pauseCampaign,
      portalCancelCampaign: mocks.cancelCampaign,
    },
  };
});

describe("client disparos page", () => {
  beforeEach(() => {
    mocks.capabilitiesEdit = true;
    mocks.health = { provider: "meta_cloud", ready: true, rollout_one_enabled: true };
    mocks.campaigns = [];
    mocks.campaignProviderHealth.mockReset();
    mocks.campaignProviderHealth.mockImplementation(async () => mocks.health);
    mocks.leadImports.mockReset();
    mocks.leadImports.mockImplementation(async () => mocks.imports);
    mocks.audiences.mockReset();
    mocks.audiences.mockImplementation(async () => mocks.groups);
    mocks.campaigns_.mockReset();
    mocks.campaigns_.mockImplementation(async () => mocks.campaigns);
    mocks.campaignPreview.mockReset();
    mocks.campaignPreview.mockResolvedValue(mocks.preview);
    mocks.createCampaign.mockReset();
    mocks.createCampaign.mockResolvedValue({ ok: true });
    mocks.pauseCampaign.mockReset();
    mocks.cancelCampaign.mockReset();
  });

  it("shows a friendly empty state when the rollout flag is disabled for the persona", async () => {
    mocks.health = { provider: null, ready: false, rollout_one_enabled: false };
    render(<ClientDisparosPage />);
    expect(await screen.findByText("Disparos ainda não disponíveis")).toBeInTheDocument();
    expect(screen.queryByText("Nova campanha")).not.toBeInTheDocument();
  });

  it("disables write actions for a view-only client", async () => {
    mocks.capabilitiesEdit = false;
    render(<ClientDisparosPage />);
    const previewButton = await screen.findByRole("button", { name: /Avaliar elegibilidade/i });
    expect(previewButton).toBeDisabled();
  });

  it("runs preview then creates a draft when the client can edit", async () => {
    render(<ClientDisparosPage />);
    fireEvent.change(await screen.findByPlaceholderText("Opt-in agosto"), { target: { value: "Campanha teste" } });
    fireEvent.change(screen.getByPlaceholderText("Reativar clientes"), { target: { value: "Reengajar" } });
    fireEvent.change(screen.getByDisplayValue("Selecione"), { target: { value: "audience-1" } });
    fireEvent.click(screen.getByText("lista.csv"));
    fireEvent.change(screen.getByPlaceholderText("Por que esta campanha está sendo criada"), {
      target: { value: "Reengajar clientes inativos" },
    });

    const previewButton = screen.getByRole("button", { name: /Avaliar elegibilidade/i });
    expect(previewButton).not.toBeDisabled();
    fireEvent.click(previewButton);

    await waitFor(() => expect(mocks.campaignPreview).toHaveBeenCalledWith(
      "aurora",
      expect.objectContaining({ audience_id: "audience-1", import_batch_ids: ["batch-1"] }),
    ));

    const confirmButton = await screen.findByRole("button", { name: /Confirmar draft congelado/i });
    fireEvent.click(confirmButton);

    await waitFor(() => expect(mocks.createCampaign).toHaveBeenCalledWith(
      "aurora",
      expect.objectContaining({ expected_preview_checksum: "sha256:test" }),
    ));
  });
});
