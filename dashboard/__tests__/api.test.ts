import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";

describe("api.getGraphDocument", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls /graph-documents/current with persona_slug", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true }),
    } as Response);

    await api.getGraphDocument("allanvvz");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api-brain/graph-documents/current?persona_slug=allanvvz");
  });
});
