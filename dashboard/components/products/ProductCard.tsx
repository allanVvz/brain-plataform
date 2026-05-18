"use client";

import { CheckCircle, FileText, ImagePlus, Sparkles } from "lucide-react";
import { API_URL } from "@/lib/api";

export function ProductCard({
  product,
  onOpenMd,
  onApprove,
  onLinkAsset,
  onSofia,
}: {
  product: any;
  onOpenMd: () => void;
  onApprove: () => void;
  onLinkAsset: () => void;
  onSofia: () => void;
}) {
  const status = product.status || "pending_validation";
  const tags = product.tags || [];
  const thumbnail = product.thumbnail;
  const thumbnailUrl = typeof thumbnail === "string" && thumbnail.includes(":")
    ? `${API_URL}/knowledge/file?path=${encodeURIComponent(thumbnail)}`
    : thumbnail;
  return (
    <article className="lg-card flex min-h-[280px] flex-col gap-3">
      <div className="flex gap-3">
        <div className="flex h-20 w-20 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-obs-raised">
          {thumbnailUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={thumbnailUrl} alt={product.title} className="h-full w-full object-cover" />
          ) : (
            <ImagePlus size={18} className="text-obs-faint" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h2 className="line-clamp-2 text-sm font-semibold text-obs-text">{product.title}</h2>
            <span className={`lg-badge shrink-0 ${status === "validated" ? "lg-badge-success" : "lg-badge-warning"}`}>
              {status === "validated" ? "validated" : "pending"}
            </span>
          </div>
          <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-obs-subtle">{product.summary || "Sem resumo."}</p>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {tags.slice(0, 6).map((tag: string) => (
          <span key={tag} className="rounded-md border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] text-obs-subtle">
            {tag}
          </span>
        ))}
        {tags.length === 0 && <span className="text-[10px] text-obs-faint">sem tags</span>}
      </div>

      <div className="mt-auto grid grid-cols-2 gap-2">
        <button type="button" onClick={onOpenMd} className="lg-btn lg-btn-secondary justify-center rounded-lg text-xs">
          <FileText size={12} /> Abrir MD
        </button>
        <button type="button" onClick={onApprove} className="lg-btn lg-btn-primary justify-center rounded-lg text-xs">
          <CheckCircle size={12} /> Aprovar
        </button>
        <button type="button" onClick={onLinkAsset} className="lg-btn lg-btn-secondary justify-center rounded-lg text-xs">
          <ImagePlus size={12} /> Vincular
        </button>
        <button type="button" onClick={onSofia} className="lg-btn lg-btn-secondary justify-center rounded-lg text-xs">
          <Sparkles size={12} /> Sofia
        </button>
      </div>
    </article>
  );
}
