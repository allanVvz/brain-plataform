import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ personaRouting: vi.fn(), updatePersonaRouting: vi.fn(), personaIntegrations: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: mocks }));
vi.mock("@/lib/useGlobalPersona", () => ({ useGlobalPersona: () => ({ persona: null }) }));
vi.mock("next/dynamic", () => ({ default: () => () => null }));
vi.mock("next/image", () => ({ default: () => null }));

import { AgentesSubPanel } from "@/components/settings/MessagingSettingsPanel";

const routing = (business_hours: Record<string, unknown>) => ({
  slug: "tock-fatal", conversation_mode: "n8n_agents", migration_applied: true,
  readiness: { operational: true, operational_state: "ready", blocked_reasons: [] }, business_hours,
});

describe("agent hours", () => {
  it("switches the hours off and saves new times through the routing API", async () => {
    mocks.personaIntegrations.mockResolvedValue([]);
    mocks.personaRouting.mockResolvedValue(routing({ enabled: true, start: "08:00", end: "20:00", timezone: "America/Sao_Paulo" }));
    mocks.updatePersonaRouting.mockResolvedValue(routing({ enabled: true, start: "08:00", end: "22:00", timezone: "America/Sao_Paulo" }));
    render(<AgentesSubPanel personaSlug="tock-fatal" />);

    fireEvent.change(await screen.findByLabelText("Fecha"), { target: { value: "22:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));
    await waitFor(() => expect(mocks.updatePersonaRouting).toHaveBeenCalledWith("tock-fatal", {
      business_hours: { timezone: "America/Sao_Paulo", enabled: true, start: "08:00", end: "22:00" },
    }));
    expect(await screen.findByText("Horário do agente: 08:00–22:00.")).toBeInTheDocument();

    mocks.updatePersonaRouting.mockResolvedValue(routing({ enabled: false, start: "08:00", end: "22:00", timezone: "America/Sao_Paulo" }));
    fireEvent.click(screen.getByRole("switch", { name: "Horário do agente" }));
    expect(await screen.findByText("Agente atende a qualquer hora.")).toBeInTheDocument();
  });
});
