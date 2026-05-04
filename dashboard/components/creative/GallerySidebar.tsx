"use client";

import { ImageIcon, Shapes, Type } from "lucide-react";

export interface GalleryItem {
  id: string;
  name: string;
  type: "imagem" | "asset" | "logo" | "background" | "produto" | "texto" | "forma";
  swatch: string;
}

const iconByType: Record<GalleryItem["type"], any> = {
  imagem: ImageIcon,
  asset: ImageIcon,
  logo: Shapes,
  background: ImageIcon,
  produto: ImageIcon,
  texto: Type,
  forma: Shapes,
};

export const galleryItems: GalleryItem[] = [
  { id: "bg-01", name: "Fundo editorial", type: "background", swatch: "from-zinc-800 via-slate-700 to-zinc-950" },
  { id: "prd-01", name: "Produto principal", type: "produto", swatch: "from-emerald-300 via-teal-400 to-cyan-500" },
  { id: "logo-01", name: "Logo branco", type: "logo", swatch: "from-white via-zinc-200 to-zinc-400" },
  { id: "txt-01", name: "Headline", type: "texto", swatch: "from-amber-200 via-orange-300 to-rose-300" },
  { id: "shape-01", name: "Selo oferta", type: "forma", swatch: "from-obs-violet via-fuchsia-400 to-rose-400" },
  { id: "asset-01", name: "Textura premium", type: "asset", swatch: "from-slate-500 via-zinc-600 to-stone-700" },
];

export function GallerySidebar({
  selectedItemId,
  onSelect,
}: {
  selectedItemId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <aside className="min-h-0 rounded-xl border border-white/06 bg-white/[0.03] p-3 lg:w-64">
      <div className="mb-3">
        <h2 className="text-sm font-semibold text-obs-text">Galeria</h2>
        <p className="text-xs text-obs-subtle">Itens para composicao visual</p>
      </div>

      <div className="grid max-h-[520px] gap-2 overflow-y-auto sm:grid-cols-2 lg:grid-cols-1">
        {galleryItems.map((item) => {
          const Icon = iconByType[item.type];
          const active = selectedItemId === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onSelect(item.id)}
              className={`flex items-center gap-3 rounded-lg border p-2 text-left transition ${
                active
                  ? "border-obs-violet/40 bg-obs-violet/10"
                  : "border-white/06 bg-white/[0.025] hover:border-white/12 hover:bg-white/[0.05]"
              }`}
            >
              <span className={`h-12 w-12 shrink-0 rounded-md bg-gradient-to-br ${item.swatch}`} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium text-obs-text">{item.name}</span>
                <span className="mt-1 flex items-center gap-1 text-[10px] uppercase tracking-[0.12em] text-obs-faint">
                  <Icon size={10} />
                  {item.type}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
