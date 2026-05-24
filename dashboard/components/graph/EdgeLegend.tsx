"use client";

/**
 * Legenda visual de edges do grafo fractal (Janela 5).
 *
 * Pareada com `edgeStyle()` em GraphView.tsx. Mantenha as cores em sync.
 */
export function EdgeLegend({ compact = false }: { compact?: boolean }) {
  const items: { label: string; color: string; dashed?: boolean; pulse?: boolean }[] = [
    { label: "Primária (hierarquia)", color: "var(--rf-edge)" },
    { label: "Secundária", color: "rgba(148,163,184,0.78)", dashed: true },
    { label: "Pendente curadoria", color: "rgba(251,191,36,0.95)", dashed: true, pulse: true },
    { label: "Asset pendente", color: "rgba(167,139,250,0.95)", dashed: true, pulse: true },
    { label: "Asset aprovado", color: "#d946ef" },
    { label: "Branch validado", color: "#22c55e" },
  ];

  return (
    <div
      className="rounded-lg border border-white/10 bg-black/60 backdrop-blur-sm px-3 py-2 text-[11px] text-white/85"
      style={{
        position: "absolute",
        top: 12,
        right: 12,
        zIndex: 4,
        boxShadow: "0 4px 16px rgba(0,0,0,0.35)",
        maxWidth: compact ? 180 : 240,
      }}
    >
      <div className="text-[10px] uppercase tracking-wider opacity-60 mb-1">Edges</div>
      <div className="flex flex-col gap-1">
        {items.map((it) => (
          <div key={it.label} className="flex items-center gap-2">
            <svg width="28" height="10" viewBox="0 0 28 10" aria-hidden>
              <line
                x1="2"
                y1="5"
                x2="26"
                y2="5"
                stroke={it.color}
                strokeWidth={2}
                strokeDasharray={it.dashed ? "6 4" : undefined}
                opacity={0.95}
                className={it.pulse ? "edge-legend-pulse" : undefined}
              />
            </svg>
            <span>{it.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
