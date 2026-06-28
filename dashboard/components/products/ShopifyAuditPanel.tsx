"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, ImageOff } from "lucide-react";

export type AuditProduct = {
  external_id: string;
  title: string;
  thumbnail?: string | null;
  price?: string | null;
  currency?: string | null;
  product_group?: string;
  has_image?: boolean;
  item: any;
};

export type AuditCollection = {
  key: string;
  label: string;
  count: number;
  products: AuditProduct[];
};

/**
 * Audit tree for the Shopify import: collections are collapsible with a
 * tri-state checkbox; each product is minimized (thumbnail + title + checkbox).
 * Everything starts enabled; `onSelectionChange` reports the selected raw items
 * so the parent can import only the chosen products.
 */
export function ShopifyAuditPanel({
  collections,
  onSelectionChange,
}: {
  collections: AuditCollection[];
  onSelectionChange: (items: any[]) => void;
}) {
  const allIds = useMemo(
    () => collections.flatMap((c) => c.products.map((p) => p.external_id)),
    [collections],
  );
  const [enabled, setEnabled] = useState<Set<string>>(() => new Set(allIds));
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());

  // Re-seed selection whenever a fresh preview arrives.
  useEffect(() => {
    setEnabled(new Set(allIds));
    setCollapsed(new Set());
  }, [allIds]);

  useEffect(() => {
    const byId = new Map<string, any>();
    for (const c of collections) for (const p of c.products) byId.set(p.external_id, p.item);
    onSelectionChange([...enabled].map((id) => byId.get(id)).filter(Boolean));
  }, [enabled, collections, onSelectionChange]);

  function toggleProduct(id: string) {
    setEnabled((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function toggleCollection(col: AuditCollection, on: boolean) {
    setEnabled((prev) => {
      const next = new Set(prev);
      for (const p of col.products) (on ? next.add(p.external_id) : next.delete(p.external_id));
      return next;
    });
  }

  function toggleCollapse(key: string) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }

  return (
    <div className="space-y-2" data-testid="shopify-audit">
      {collections.map((col) => {
        const enabledInCol = col.products.filter((p) => enabled.has(p.external_id)).length;
        const allOn = enabledInCol === col.products.length && col.products.length > 0;
        const isCollapsed = collapsed.has(col.key);
        return (
          <div key={col.key} className="overflow-hidden rounded-lg border border-white/08 bg-white/[0.02]" data-audit-collection={col.key}>
            <div className="flex items-center gap-2 px-3 py-2">
              <input
                type="checkbox"
                checked={allOn}
                ref={(el) => {
                  if (el) el.indeterminate = enabledInCol > 0 && !allOn;
                }}
                onChange={(e) => toggleCollection(col, e.target.checked)}
                aria-label={`Coleção ${col.label}`}
                className="h-4 w-4 accent-obs-violet"
              />
              <button type="button" onClick={() => toggleCollapse(col.key)} className="flex flex-1 items-center gap-1 text-left">
                {isCollapsed ? <ChevronRight size={14} className="text-obs-faint" /> : <ChevronDown size={14} className="text-obs-faint" />}
                <span className="text-sm font-medium text-obs-text">{col.label}</span>
              </button>
              <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-[10px] text-obs-subtle">
                {enabledInCol}/{col.count}
              </span>
            </div>
            {!isCollapsed && (
              <div className="space-y-1 border-t border-white/06 p-2">
                {col.products.map((p) => (
                  <label
                    key={p.external_id}
                    data-audit-product={p.external_id}
                    className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 hover:bg-white/[0.03]"
                  >
                    <input
                      type="checkbox"
                      checked={enabled.has(p.external_id)}
                      onChange={() => toggleProduct(p.external_id)}
                      aria-label={p.title}
                      className="h-4 w-4 accent-obs-violet"
                    />
                    {p.thumbnail ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={p.thumbnail} alt="" className="h-8 w-8 rounded object-cover" />
                    ) : (
                      <span className="flex h-8 w-8 items-center justify-center rounded bg-white/[0.04] text-obs-faint"><ImageOff size={13} /></span>
                    )}
                    <span className="min-w-0 flex-1 truncate text-xs text-obs-text">{p.title}</span>
                    {p.price && <span className="text-[11px] text-obs-subtle">{p.currency || "R$"} {p.price}</span>}
                  </label>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
