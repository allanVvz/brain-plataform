import { afterEach, describe, expect, it, vi } from "vitest";
import { API_OFFLINE_ERROR, ApiError, api } from "@/lib/api";

describe("API error taxonomy", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps a 403 as an authorization error instead of reporting an outage", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ detail: "Acesso negado." }),
      { status: 403, headers: { "Content-Type": "application/json" } },
    )));

    const error = await api.health().catch((caught) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 403,
      path: "/health/score",
      kind: "forbidden",
      detail: "Acesso negado.",
    });
    expect(error.message).toBe("403 /health/score - Acesso negado.");
    expect(error.message).not.toBe(API_OFFLINE_ERROR);
  });

  it.each([502, 503, 504])("classifies HTTP %s as backend unavailable", async (status) => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status })));
    const error = await api.health().catch((caught) => caught);
    expect(error).toMatchObject({ status, kind: "unavailable" });
    expect(error.message).toBe(API_OFFLINE_ERROR);
  });

  it("classifies a failed fetch as a network outage", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("fetch failed");
    }));
    const error = await api.health().catch((caught) => caught);
    expect(error).toMatchObject({ status: 0, kind: "network" });
    expect(error.message).toBe(API_OFFLINE_ERROR);
  });
});
