"use client";

import { useEffect, useMemo, useState } from "react";
import { ImagePlus, X } from "lucide-react";
import { api } from "@/lib/api";

export function LinkAssetDrawer({
  open,
  personaId,
  product,
  onClose,
  onLinked,
}: {
  open: boolean;
  personaId: string;
  product: any;
  onClose: () => void;
  onLinked: () => void;
}) {
  const [assets, setAssets] = useState<any[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [linking, setLinking] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !personaId) return;
    setLoading(true);
    api.assetList({ persona_id: personaId, limit: 200 })
      .then(setAssets)
      .finally(() => setLoading(false));
  }, [open, personaId]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return assets;
    return assets.filter((asset) => `${asset.name || ""} ${asset.original_filename || ""}`.toLowerCase().includes(q));
  }, [assets, query]);

  if (!open) return null;

  async function link(asset: any) {
    setLinking(asset.id);
    try {
      await api.linkProductAsset(product.slug, { asset_id: asset.id, relation_type: "product_image" }, { persona_id: personaId });
      onLinked();
      onClose();
    } finally {
      setLinking(null);
    }
  }

  return (
    <div className="fixed inset-0 z-[85] flex justify-end bg-black/35 backdrop-blur-sm">
      <aside className="h-full w-full max-w-md overflow-hidden glass-raised">
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-obs-text">Vincular asset</h2>
            <p className="text-[11px] text-obs-faint">{product?.title}</p>
          </div>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 text-obs-subtle hover:text-obs-text" aria-label="Fechar">
            <X size={15} />
          </button>
        </div>
        <div className="p-4">
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar asset" className="lg-input w-full text-sm" />
        </div>
        <div className="h-[calc(100%-116px)] overflow-y-auto px-4 pb-4">
          {loading && <p className="text-xs text-obs-faint">Carregando...</p>}
          {!loading && filtered.map((asset) => (
            <button key={asset.id} type="button" onClick={() => link(asset)} className="mb-2 flex w-full items-center gap-3 rounded-lg border border-white/10 bg-white/[0.03] p-3 text-left hover:bg-white/[0.06]">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-md bg-obs-raised">
                {asset.url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={asset.url} alt={asset.name || "Asset"} className="h-full w-full object-cover" />
                ) : (
                  <ImagePlus size={16} className="text-obs-faint" />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-obs-text">{asset.name || asset.original_filename || "Asset"}</p>
                <p className="truncate text-[10px] text-obs-faint">{asset.status || "ready"}</p>
              </div>
              <span className="text-[10px] text-obs-violet">{linking === asset.id ? "..." : "vincular"}</span>
            </button>
          ))}
        </div>
      </aside>
    </div>
  );
}
