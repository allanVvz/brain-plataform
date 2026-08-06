import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LoginPage, { normalizeLoginError } from "@/app/login/page";
import { ApiError } from "@/lib/api";

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  login: vi.fn(),
  me: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: {
      ...original.api,
      login: mocks.login,
      me: mocks.me,
    },
  };
});

describe("login page", () => {
  beforeEach(() => {
    mocks.replace.mockReset();
    mocks.login.mockReset();
    mocks.me.mockReset();
    mocks.me.mockRejectedValue(new ApiError({
      status: 401,
      path: "/auth/me",
      detail: "Sessao obrigatoria.",
      kind: "unauthenticated",
    }));
    localStorage.clear();
    window.history.replaceState({}, "", "/login");
  });

  it("defaults to a browser-session login", () => {
    render(<LoginPage />);

    expect(screen.getByRole("checkbox", { name: /lembrar de mim/i })).not.toBeChecked();
    expect(screen.getByLabelText(/Email ou usuario/i)).toHaveFocus();
  });

  it("trims the identifier, stores the authorized persona and honors a safe next route", async () => {
    window.history.replaceState({}, "", "/login?next=%2Fpipeline%3Fview%3Dcrm");
    mocks.login.mockResolvedValue({
      account_type: "internal",
      user: { account_type: "internal", role: "operator" },
      personas: [{ id: "persona-1", slug: "aurora" }],
      navigation: { home_url: "/" },
    });
    render(<LoginPage />);

    fireEvent.change(screen.getByLabelText(/Email ou usuario/i), {
      target: { value: "  operador@example.com  " },
    });
    fireEvent.change(screen.getByLabelText(/^Senha$/i), {
      target: { value: "a-valid-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));

    await waitFor(() => expect(mocks.login).toHaveBeenCalledWith({
      identifier: "operador@example.com",
      password: "a-valid-password",
      remember: false,
    }));
    expect(localStorage.getItem("ai-brain-persona-slug")).toBe("aurora");
    expect(localStorage.getItem("ai-brain-persona-id")).toBe("persona-1");
    expect(mocks.replace).toHaveBeenCalledWith("/pipeline?view=crm");
  });

  it("shows a specific message when the auth backend is unavailable", () => {
    expect(normalizeLoginError(new ApiError({
      status: 503,
      path: "/auth/login",
      detail: "Auth backend unavailable.",
      kind: "unavailable",
    }))).toBe("O serviço de autenticação está indisponível. Tente novamente em instantes.");
  });
});
