import { describe, expect, it } from "vitest";
import { ALL_AUDIENCE_KEY, buildLeadsFilters, leadsAudienceUrl, visibleAudienceFilters, type LeadsAudience } from "@/lib/leads";

const A = (slug: string, source_type?: string): LeadsAudience => ({
  id: slug,
  slug,
  name: slug,
  source_type,
});

describe("visibleAudienceFilters", () => {
  it("drops the import bucket (by slug and by source_type)", () => {
    const out = visibleAudienceFilters([
      A("import", "import"),
      A("audience-padrao-vz-lupas", "manual"),
      A("tecnicos", "graph"),
    ]);
    expect(out.map((a) => a.slug)).toEqual(["audience-padrao-vz-lupas", "tecnicos"]);
  });

  it("keeps audiences created in the Graph (source_type=graph)", () => {
    const out = visibleAudienceFilters([A("tecnicos", "graph")]);
    expect(out.map((a) => a.slug)).toEqual(["tecnicos"]);
  });

  it("handles null/empty input", () => {
    expect(visibleAudienceFilters(null)).toEqual([]);
    expect(visibleAudienceFilters(undefined)).toEqual([]);
    expect(visibleAudienceFilters([])).toEqual([]);
  });
});

describe("buildLeadsFilters", () => {
  it("puts Todos first, then each persona audience, dropping import", () => {
    const filters = buildLeadsFilters([
      A("import", "import"),
      A("audience-padrao-vz-lupas", "manual"),
      A("tecnicos", "graph"),
    ]);
    expect(filters[0]).toMatchObject({ slug: ALL_AUDIENCE_KEY, name: "Todos", isAll: true });
    expect(filters.map((f) => f.slug)).toEqual([ALL_AUDIENCE_KEY, "audience-padrao-vz-lupas", "tecnicos"]);
  });

  it("shows audiences even with no leads (filters are independent of leads)", () => {
    const filters = buildLeadsFilters([A("tecnicos", "graph")]);
    expect(filters.some((f) => f.slug === "tecnicos")).toBe(true);
  });

  it("always has Todos even with no audiences", () => {
    expect(buildLeadsFilters([]).map((f) => f.slug)).toEqual([ALL_AUDIENCE_KEY]);
  });
});

describe("leadsAudienceUrl", () => {
  it("builds a filtered Leads URL from an audience slug", () => {
    expect(leadsAudienceUrl("tecnicos")).toBe("/leads?audience=tecnicos");
    expect(leadsAudienceUrl("audience-padrao-vz-lupas")).toBe("/leads?audience=audience-padrao-vz-lupas");
  });
  it("falls back to /leads when slug is missing", () => {
    expect(leadsAudienceUrl(null)).toBe("/leads");
    expect(leadsAudienceUrl("")).toBe("/leads");
  });
});
