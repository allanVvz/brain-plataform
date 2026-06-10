"use client";

import { GripVertical, ImageOff } from "lucide-react";
import { groupByProductGroup } from "./productGrouping";

/**
 * Kanban grouped by product_group. Columns come from groupByProductGroup, with
 * a trailing "Sem grupo" column for ungrouped products. Drag-and-drop is mocked
 * (cards carry draggable affordance but reclassification has no backend yet).
 */
export function ProductKanbanView({
  products,
  onOpenMd,
}: {
  products: any[];
  onOpenMd: (product: any) => void;
}) {
  const columns = groupByProductGroup(products);

  return (
    <div className="flex gap-3 overflow-x-auto pb-2">
      {columns.map((column) => (
        <div key={column.group} className="flex w-64 shrink-0 flex-col rounded-xl border border-white/06 bg-white/[0.02]" data-kanban-column={column.group}>
          <div className="flex items-center justify-between border-b border-white/08 px-3 py-2">
            <p className="truncate text-xs font-semibold text-obs-text">{column.group}</p>
            <span className="rounded-full bg-white/[0.06] px-2 py-0.5 text-[10px] text-obs-subtle">{column.products.length}</span>
          </div>
          <div className="flex flex-col gap-2 p-2">
            {column.products.map((product) => (
              <button
                key={product.id}
                type="button"
                draggable
                onClick={() => onOpenMd(product)}
                data-kanban-card={product.slug}
                className="flex items-center gap-2 rounded-lg border border-white/08 bg-white/[0.03] p-2 text-left transition hover:border-white/15"
              >
                <GripVertical size={13} className="shrink-0 text-obs-faint" />
                {product.thumbnail ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={product.thumbnail} alt="" className="h-8 w-8 rounded object-cover" />
                ) : (
                  <span className="flex h-8 w-8 items-center justify-center rounded bg-white/[0.04] text-obs-faint"><ImageOff size={13} /></span>
                )}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-medium text-obs-text">{product.title}</p>
                  <p className={`text-[10px] ${product.status === "validated" ? "text-green-400" : "text-obs-amber"}`}>{product.status}</p>
                </div>
              </button>
            ))}
            {column.products.length === 0 && <p className="px-1 py-3 text-center text-[11px] text-obs-faint">Vazio</p>}
          </div>
        </div>
      ))}
    </div>
  );
}
