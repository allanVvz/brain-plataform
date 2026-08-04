import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CampaignsPage from "@/app/disparos/page";


const mocks = vi.hoisted(() => ({
  leadImports: vi.fn(),
  audiences: vi.fn(),
  campaigns: vi.fn(),
  health: vi.fn(),
  preview: vi.fn(),
  create: vi.fn(),
  pause: vi.fn(),
  cancel: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    leadImports: mocks.leadImports,
    audiences: mocks.audiences,
    campaigns: mocks.campaigns,
    campaignProviderHealth: mocks.health,
    campaignPreview: mocks.preview,
    createCampaign: mocks.create,
    pauseCampaign: mocks.pause,
    cancelCampaign: mocks.cancel,
  },
}));

describe("Disparos rollout one", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    localStorage.setItem("ai-brain-persona-id", "persona-1");
    mocks.leadImports.mockResolvedValue([
      { id: "batch-1", filename: "clientes.csv", status: "completed", valid_rows: 2 },
    ]);
    mocks.audiences.mockResolvedValue([
      { id: "audience-1", name: "Clientes ativos" },
    ]);
    mocks.campaigns.mockResolvedValue([]);
    mocks.health.mockResolvedValue({ provider: "meta_cloud", ready: true });
    mocks.preview.mockResolvedValue({
      counts: { selected_unique: 2, eligible: 1, blocked: 1 },
      blocked_reasons: { consent_not_granted: 1 },
      provider_ready: true,
      policy_checksum: "sha256:policy",
      preview_checksum: "sha256:preview",
    });
    mocks.create.mockResolvedValue({ campaign: { id: "campaign-1" } });
  });

  it("confirms only the previewed recipient snapshot", async () => {
    render(<CampaignsPage />);

    fireEvent.change(await screen.findByPlaceholderText("Opt-in agosto"), {
      target: { value: "Consentimento agosto" },
    });
    fireEvent.change(screen.getByLabelText("Grupo semantico"), {
      target: { value: "audience-1" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /clientes\.csv/ }));
    fireEvent.change(screen.getByPlaceholderText("Por que esta campanha esta sendo criada"), {
      target: { value: "Reativacao de clientes inativos" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Avaliar elegibilidade/i }));

    expect(await screen.findByText("1 elegiveis")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Confirmar draft congelado/i }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    expect(mocks.create.mock.calls[0][0]).toMatchObject({
      expected_revision: 0,
      expected_preview_checksum: "sha256:preview",
      persona_id: "persona-1",
      audience_id: "audience-1",
      import_batch_ids: ["batch-1"],
      reason: "Reativacao de clientes inativos",
    });
  });
});
