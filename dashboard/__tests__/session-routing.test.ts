import { describe, expect, it } from "vitest";
import {
  defaultSessionHome,
  mandatoryPasswordDestination,
  resolveSessionDestination,
  safeLocalTarget,
} from "@/lib/session-routing";

const clientSession = {
  account_type: "client",
  user: { account_type: "client", must_change_password: false },
  personas: [{ slug: "aurora" }, { slug: "baita-conveniencia" }],
  navigation: {
    surface: "client_portal",
    home_url: "/clientes/aurora/mensagens",
  },
};

describe("session routing", () => {
  it("rejects external and malformed next targets", () => {
    expect(safeLocalTarget("https://evil.example")).toBe("");
    expect(safeLocalTarget("//evil.example")).toBe("");
    expect(safeLocalTarget("/\\evil.example")).toBe("");
    expect(safeLocalTarget("/pipeline?view=crm")).toBe("/pipeline?view=crm");
  });

  it.each(["/", "/leads", "/insights", "/pipeline", "/knowledge/graph"])(
    "sends a client away from the internal route %s",
    (target) => {
      expect(resolveSessionDestination(clientSession, target)).toBe(
        "/clientes/aurora/mensagens",
      );
    },
  );

  it("preserves only authorized portal destinations", () => {
    expect(resolveSessionDestination(clientSession, "/clientes/baita-conveniencia/leads"))
      .toBe("/clientes/baita-conveniencia/leads");
    expect(resolveSessionDestination(clientSession, "/clientes/other/mensagens"))
      .toBe("/clientes/aurora/mensagens");
    expect(resolveSessionDestination(clientSession, "/clientes/aurora/admin"))
      .toBe("/clientes/aurora/mensagens");
  });

  it("preserves safe internal destinations for internal users", () => {
    const internal = { account_type: "internal", navigation: { home_url: "/" } };
    expect(defaultSessionHome(internal)).toBe("/");
    expect(resolveSessionDestination(internal, "/leads?stage=novo")).toBe(
      "/leads?stage=novo",
    );
  });

  it("encodes the already validated post-password destination", () => {
    expect(mandatoryPasswordDestination(clientSession, "/pipeline")).toBe(
      "/account/change-password?next=%2Fclientes%2Faurora%2Fmensagens",
    );
  });
});
