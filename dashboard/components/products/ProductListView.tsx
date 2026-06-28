"use client";

import { Check, FileText, ImageOff, Link2 } from "lucide-react";
import { productGroupLabel } from "./productGrouping";

function fmtDate(value?: string): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString();
}

export function ProductListView({
  products,
  onOpenMd,
  onApprove,
  onLinkAsset,
}: {
  products: any[];
  onOpenMd: (product: any) => void;
  onApprove: (product: any) => void;
  onLinkAsset: (product: any) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-white/06">
      <table className="w-full min-w-[760px] text-left text-xs">
        <thead className="border-b border-white/08 text-[10px] uppercase tracking-wide text-obs-faint">
          <tr>
            <th className="px-3 py-2">Imagem</th>
            <th className="px-3 py-2">Produto</th>
            <th className="px-3 py-2">Grupo</th>
            <th className="px-3 py-2">Categoria</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Fonte</th>
            <th className="px-3 py-2">Atualizado</th>
            <th className="px-3 py-2 text-right">Ações</th>
          </tr>
        </thead>
        <tbody>
          {products.map((product) => {
            const validated = product.status === "validated";
            return (
              <tr key={product.id} className="border-b border-white/04 hover:bg-white/[0.02]">
                <td className="px-3 py-2">
                  {product.thumbnail ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={product.thumbnail} alt="" className="h-9 w-9 rounded object-cover" />
                  ) : (
                    <span className="flex h-9 w-9 items-center justify-center rounded bg-white/[0.04] text-obs-faint"><ImageOff size={14} /></span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <p className="font-medium text-obs-text">{product.title}</p>
                  <p className="text-[10px] text-obs-faint">{product.slug}</p>
                </td>
                <td className="px-3 py-2 text-obs-subtle">{productGroupLabel(product)}</td>
                <td className="px-3 py-2 text-obs-subtle">{product.category?.title || product.category_slug || "—"}</td>
                <td className="px-3 py-2">
                  <span className={validated ? "text-green-400" : "text-obs-amber"}>{product.status}</span>
                </td>
                <td className="px-3 py-2 text-obs-subtle">{product.metadata?.source || "—"}</td>
                <td className="px-3 py-2 text-obs-faint">{fmtDate(product.updated_at)}</td>
                <td className="px-3 py-2">
                  <div className="flex justify-end gap-1">
                    <button type="button" onClick={() => onOpenMd(product)} title="Card MD" className="rounded-md border border-white/08 p-1.5 text-obs-subtle hover:text-obs-text"><FileText size={13} /></button>
                    <button type="button" onClick={() => onLinkAsset(product)} title="Vincular asset" className="rounded-md border border-white/08 p-1.5 text-obs-subtle hover:text-obs-text"><Link2 size={13} /></button>
                    {!validated && (
                      <button type="button" onClick={() => onApprove(product)} title="Aprovar" className="rounded-md border border-green-400/30 p-1.5 text-green-400 hover:bg-green-400/10"><Check size={13} /></button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
