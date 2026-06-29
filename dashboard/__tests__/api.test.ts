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

describe("api public site endpoints", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("lists public site formats", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => [],
    } as Response);

    await api.publicSiteFormats();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api-brain/api/public-site-formats");
  });

  it("updates persona public site config", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true }),
    } as Response);

    await api.updatePersonaPublicSite("vz-lupas", {
      site_slug: "vitrine-vz",
      site_name: "Vitrine VZ",
      format_key: "landing_page",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, opts] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api-brain/personas/vz-lupas/public-site");
    expect(opts?.method).toBe("PATCH");
    expect(String(opts?.body)).toContain("landing_page");
  });
});
