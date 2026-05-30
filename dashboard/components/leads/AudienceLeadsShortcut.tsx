"use client";
import { Users } from "lucide-react";
import { leadsAudienceUrl } from "@/lib/leads";

/**
 * Shortcut shown on an Audience node's sidebar/modal: jumps to the Leads tab
 * pre-filtered by that audience. Persona stays active (Leads reads it from
 * localStorage), so only the audience filter is applied via the URL.
 */
export default function AudienceLeadsShortcut({ slug }: { slug?: string | null }) {
  if (!slug) return null;
  return (
    <a
      href={leadsAudienceUrl(slug)}
      data-testid="audience-leads-shortcut"
      className="flex items-center gap-1.5 rounded-lg border border-obs-violet/30 bg-obs-violet/10 px-2.5 py-1.5 text-[11px] font-medium text-obs-violet transition-colors hover:bg-obs-violet/20"
    >
      <Users size={12} />
      Atalho: Ver leads desta audience
    </a>
  );
}
