"use client";

import { ArrowDown, ArrowUp, Eye, EyeOff } from "lucide-react";

export interface CreativeLayer {
  id: string;
  name: string;
  kind: "background" | "produto" | "texto";
  x: number;
  y: number;
  visible: boolean;
}

export function LayersPanel({
  layers,
  selectedLayerId,
  onSelect,
  onMove,
  onToggleVisibility,
}: {
  layers: CreativeLayer[];
  selectedLayerId: string;
  onSelect: (id: string) => void;
  onMove: (id: string, direction: "up" | "down") => void;
  onToggleVisibility: (id: string) => void;
}) {
  return (
    <aside className="rounded-xl border border-white/06 bg-white/[0.03] p-3 lg:w-72">
      <div className="mb-3">
        <h2 className="text-sm font-semibold text-obs-text">Camadas</h2>
        <p className="text-xs text-obs-subtle">Ordem, visibilidade e posicao</p>
      </div>

      <div className="space-y-2">
        {layers.map((layer, index) => {
          const active = selectedLayerId === layer.id;
          return (
            <div
              key={layer.id}
              className={`rounded-lg border p-3 transition ${
                active
                  ? "border-obs-violet/40 bg-obs-violet/10"
                  : "border-white/06 bg-white/[0.025]"
              }`}
            >
              <button type="button" onClick={() => onSelect(layer.id)} className="w-full text-left">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="text-xs font-medium text-obs-text">{layer.name}</p>
                    <p className="mt-1 text-[10px] uppercase tracking-[0.12em] text-obs-faint">
                      {layer.kind}
                    </p>
                  </div>
                  <span className="text-[10px] text-obs-faint">#{index + 1}</span>
                </div>
              </button>

              <div className="mt-3 grid grid-cols-2 gap-2">
                <label className="text-[10px] uppercase tracking-[0.12em] text-obs-faint">
                  X
                  <input
                    readOnly
                    value={layer.x}
                    className="mt-1 w-full rounded-md border border-white/06 bg-obs-base px-2 py-1 text-xs text-obs-text focus:outline-none"
                  />
                </label>
                <label className="text-[10px] uppercase tracking-[0.12em] text-obs-faint">
                  Y
                  <input
                    readOnly
                    value={layer.y}
                    className="mt-1 w-full rounded-md border border-white/06 bg-obs-base px-2 py-1 text-xs text-obs-text focus:outline-none"
                  />
                </label>
              </div>

              <div className="mt-3 flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => onMove(layer.id, "up")}
                  className="flex h-8 w-8 items-center justify-center rounded-md border border-white/06 text-obs-subtle transition hover:bg-white/5 hover:text-obs-text"
                  title="Subir camada"
                >
                  <ArrowUp size={13} />
                </button>
                <button
                  type="button"
                  onClick={() => onMove(layer.id, "down")}
                  className="flex h-8 w-8 items-center justify-center rounded-md border border-white/06 text-obs-subtle transition hover:bg-white/5 hover:text-obs-text"
                  title="Descer camada"
                >
                  <ArrowDown size={13} />
                </button>
                <button
                  type="button"
                  onClick={() => onToggleVisibility(layer.id)}
                  className="ml-auto flex h-8 w-8 items-center justify-center rounded-md border border-white/06 text-obs-subtle transition hover:bg-white/5 hover:text-obs-text"
                  title={layer.visible ? "Ocultar camada" : "Mostrar camada"}
                >
                  {layer.visible ? <Eye size={13} /> : <EyeOff size={13} />}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
