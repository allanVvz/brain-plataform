import { act, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AppShell from "@/app/AppShell";

const mocks = vi.hoisted(() => ({
  pathname: "/",
  replace: vi.fn(),
  refresh: vi.fn(),
  me: vi.fn(),
  logout: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => mocks.pathname,
  useRouter: () => mocks,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...original,
    api: {
      ...original.api,
      me: mocks.me,
      logout: mocks.logout,
    },
  };
});

function Probe({ onMount }: { onMount: () => void }) {
  useEffect(onMount, [onMount]);
  return <div>admin child mounted</div>;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("AppShell session barrier", () => {
  beforeEach(() => {
    mocks.pathname = "/";
    mocks.replace.mockReset();
    mocks.refresh.mockReset();
    mocks.me.mockReset();
    mocks.logout.mockReset();
    localStorage.clear();
  });

  it("does not mount an admin page while the session is unresolved", () => {
    mocks.me.mockReturnValue(new Promise(() => {}));
    const onMount = vi.fn();
    render(<AppShell><Probe onMount={onMount} /></AppShell>);

    expect(screen.getByText("Validando acesso...")).toBeInTheDocument();
    expect(screen.queryByText("admin child mounted")).not.toBeInTheDocument();
    expect(onMount).not.toHaveBeenCalled();
  });

  it("redirects a client before mounting the requested admin page", async () => {
    const session = deferred<any>();
    mocks.me.mockReturnValue(session.promise);
    const onMount = vi.fn();
    render(<AppShell><Probe onMount={onMount} /></AppShell>);

    await act(async () => {
      session.resolve({
        account_type: "client",
        user: { account_type: "client", must_change_password: false },
        personas: [{ slug: "aurora" }],
        navigation: { home_url: "/clientes/aurora/mensagens" },
      });
      await session.promise;
    });

    expect(mocks.replace).toHaveBeenCalledWith("/clientes/aurora/mensagens");
    expect(onMount).not.toHaveBeenCalled();
  });

  it("mounts the admin page only after an internal session is validated", async () => {
    mocks.me.mockResolvedValue({
      account_type: "internal",
      user: { account_type: "internal", role: "admin" },
      personas: [],
      navigation: { home_url: "/" },
    });
    const onMount = vi.fn();
    render(<AppShell><Probe onMount={onMount} /></AppShell>);

    expect(await screen.findByText("admin child mounted")).toBeInTheDocument();
    await waitFor(() => expect(onMount).toHaveBeenCalledTimes(1));
    expect(mocks.replace).not.toHaveBeenCalled();
  });
});
