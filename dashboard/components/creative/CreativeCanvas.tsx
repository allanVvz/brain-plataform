"use client";

import { Eye, EyeOff } from "lucide-react";
import type { CreativeLayer } from "@/components/creative/LayersPanel";

export function CreativeCanvas({
  layers,
  selectedLayerId,
}: {
  layers: CreativeLayer[];
  selectedLayerId: string;
}) {
  const visible = (id: string) => layers.find((layer) => layer.id === id)?.visible !== false;

  return (
    <section className="flex min-h-[560px] flex-1 flex-col rounded-xl border border-white/06 bg-white/[0.025]">
      <div className="flex items-center justify-between border-b border-white/06 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-obs-text">Canvas</h2>
          <p className="text-xs text-obs-subtle">Preview 1080 x 1350</p>
        </div>
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.14em] text-obs-faint">
          {layers.every((layer) => layer.visible) ? <Eye size={12} /> : <EyeOff size={12} />}
          {layers.filter((layer) => layer.visible).length} camadas
        </div>
      </div>

      <div className="flex flex-1 items-center justify-center p-5">
        <div className="relative aspect-[4/5] w-full max-w-[440px] overflow-hidden rounded-xl border border-white/10 bg-obs-deep shadow-obs-node">
          {visible("background") && (
            <div
              className={`absolute inset-0 ${
                selectedLayerId === "background" ? "ring-2 ring-inset ring-obs-violet/60" : ""
              }`}
            >
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_15%,rgba(124,111,255,0.24),transparent_32%),linear-gradient(135deg,#111827,#050709_62%,#172033)]" />
              <div className="absolute inset-x-8 bottom-12 h-24 rounded-full bg-white/8 blur-2xl" />
            </div>
          )}

          {visible("product") && (
            <div
              className={`absolute left-[22%] top-[24%] h-[42%] w-[56%] rounded-2xl border border-white/20 bg-gradient-to-br from-emerald-200 via-cyan-300 to-obs-violet shadow-obs-glow ${
                selectedLayerId === "product" ? "ring-2 ring-obs-violet/80" : ""
              }`}
            >
              <div className="absolute left-1/2 top-8 h-20 w-20 -translate-x-1/2 rounded-full bg-white/35 blur-xl" />
              <div className="absolute inset-x-8 bottom-8 h-14 rounded-lg border border-white/35 bg-white/20" />
            </div>
          )}

          {visible("copy") && (
            <div
              className={`absolute inset-x-8 bottom-8 rounded-xl border border-white/10 bg-black/40 p-5 backdrop-blur ${
                selectedLayerId === "copy" ? "ring-2 ring-obs-violet/80" : ""
              }`}
            >
              <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-amber-200">
                Nova campanha
              </p>
              <p className="mt-2 text-2xl font-semibold leading-tight text-white">
                Modal premium para vender mais
              </p>
              <p className="mt-2 text-xs leading-relaxed text-zinc-300">
                Conforto, giro rapido e visual de alto valor.
              </p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
