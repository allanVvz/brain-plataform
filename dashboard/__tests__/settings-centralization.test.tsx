import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SettingsPage from "@/app/settings/page";

const mocks = vi.hoisted(() => ({
  me: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: {
      ...original.api,
      me: mocks.me,
    },
  };
});

describe("settings central", () => {
  beforeEach(() => {
    mocks.me.mockReset();
    mocks.me.mockResolvedValue({
      user: {
        account_type: "internal",
        role: "admin",
        email: "admin@example.com",
        must_change_password: true,
      },
      personas: [],
    });
  });

  it("opens the requested internal tab from the URL", async () => {
    window.history.replaceState({}, "", "/settings?tab=security");
    const { container } = render(<SettingsPage />);

    await waitFor(() => {
      expect(container.querySelector("[data-settings-tab='security']")).toBeInTheDocument();
    });
    expect(container.textContent).toContain("Este é um aviso; o acesso não é bloqueado.");
  });

  it("declares every consolidated settings tab", () => {
    window.history.replaceState({}, "", "/settings?tab=security");
    const { getByRole } = render(<SettingsPage />);

    for (const label of [
      "Geral",
      "Mensageria",
      "ChatBot",
      "Ferramentas",
      "Logs",
      "Acessos",
      "Segurança",
    ]) {
      expect(getByRole("button", { name: label })).toBeInTheDocument();
    }
  });
});
