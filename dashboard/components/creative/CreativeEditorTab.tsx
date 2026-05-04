"use client";

import { useState } from "react";
import { CreativeCanvas } from "@/components/creative/CreativeCanvas";
import { GallerySidebar } from "@/components/creative/GallerySidebar";
import { CreativeLayer, LayersPanel } from "@/components/creative/LayersPanel";

const initialLayers: CreativeLayer[] = [
  { id: "copy", name: "Texto e logo", kind: "texto", x: 80, y: 980, visible: true },
  { id: "product", name: "Produto", kind: "produto", x: 240, y: 290, visible: true },
  { id: "background", name: "Background", kind: "background", x: 0, y: 0, visible: true },
];

export function CreativeEditorTab() {
  const [selectedItemId, setSelectedItemId] = useState("prd-01");
  const [selectedLayerId, setSelectedLayerId] = useState("product");
  const [layers, setLayers] = useState<CreativeLayer[]>(initialLayers);

  function moveLayer(id: string, direction: "up" | "down") {
    setLayers((current) => {
      const next = [...current];
      const index = next.findIndex((layer) => layer.id === id);
      if (index < 0) return current;
      const target = direction === "up" ? index - 1 : index + 1;
      if (target < 0 || target >= next.length) return current;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  function toggleVisibility(id: string) {
    setLayers((current) =>
      current.map((layer) =>
        layer.id === id ? { ...layer, visible: !layer.visible } : layer,
      ),
    );
  }

  return (
    <section className="animate-fade-in space-y-4">
      <div className="rounded-xl border border-white/06 bg-white/[0.025] p-4">
        <div className="flex flex-col gap-1">
          <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">
            Creative Studio
          </p>
          <h2 className="text-lg font-semibold text-obs-text">Editor visual de criativos</h2>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)_288px]">
        <GallerySidebar selectedItemId={selectedItemId} onSelect={setSelectedItemId} />
        <CreativeCanvas layers={layers} selectedLayerId={selectedLayerId} />
        <LayersPanel
          layers={layers}
          selectedLayerId={selectedLayerId}
          onSelect={setSelectedLayerId}
          onMove={moveLayer}
          onToggleVisibility={toggleVisibility}
        />
      </div>
    </section>
  );
}
