export type LeadsAudience = {
  id: string;
  slug: string;
  name: string;
  persona_id?: string;
  is_system?: boolean;
  source_type?: string;
};

/**
 * Audiences that should render as filter pills in the Leads tab.
 *
 * The `import` bucket is an operational grouping for CSV/bulk imports, not a
 * semantic audience of the persona, so it must never appear as a filter. The
 * synthetic "Todos" pill is added separately by the page. Real audiences —
 * including ones created via the Graph/Sofia (source_type='graph') — flow
 * through unchanged. Backend already excludes `import`; this is a defensive
 * client-side guard so older backends behave the same.
 */
export function visibleAudienceFilters<T extends LeadsAudience>(audiences: T[] | null | undefined): T[] {
  return (audiences || []).filter((a) => {
    const slug = String(a?.slug || "").trim().toLowerCase();
    const sourceType = String(a?.source_type || "").trim().toLowerCase();
    return slug !== "import" && sourceType !== "import";
  });
}

/** Synthetic "Todos" pill key (kept in sync with the Leads page). */
export const ALL_AUDIENCE_KEY = "__all__";

export type LeadsFilter = { key: string; slug: string; name: string; isSystem: boolean; isAll: boolean };

/**
 * The full filter row for the Leads tab: a fixed "Todos" first, then each real
 * audience of the active persona (Graph/Sofia audiences included, `import`
 * excluded). Audiences appear even with zero leads.
 */
export function buildLeadsFilters(audiences: LeadsAudience[] | null | undefined): LeadsFilter[] {
  const all: LeadsFilter = { key: ALL_AUDIENCE_KEY, slug: ALL_AUDIENCE_KEY, name: "Todos", isSystem: true, isAll: true };
  const rest = visibleAudienceFilters(audiences).map((a) => ({
    key: a.slug,
    slug: a.slug,
    name: a.name,
    isSystem: Boolean(a.is_system),
    isAll: false,
  }));
  return [all, ...rest];
}

/** URL that opens the Leads tab pre-filtered by an audience (persona stays active). */
export function leadsAudienceUrl(slug: string | null | undefined): string {
  const value = String(slug || "").trim();
  return value ? `/leads?audience=${encodeURIComponent(value)}` : "/leads";
}
