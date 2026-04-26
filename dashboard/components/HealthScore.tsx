"use client";

interface Props {
  data: {
    score_total: number;
    score_performance: number;
    score_reliability: number;
    score_architecture: number;
    score_business: number;
    open_critical?: number;
    open_warnings?: number;
  };
}

function Bar({ value, max = 25, color }: { value: number; max?: number; color: string }) {
  const pct = Math.min((value / max) * 100, 100);
  return (
    <div className="w-full bg-brain-border rounded-full h-1.5">
      <div className={`h-1.5 rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function HealthScore({ data }: Props) {
  const score = data.score_total ?? 0;
  const color = score >= 80 ? "text-green-400" : score >= 60 ? "text-yellow-400" : "text-red-400";
  const barColor = score >= 80 ? "bg-green-400" : score >= 60 ? "bg-yellow-400" : "bg-red-400";

  const dimensions = [
    { label: "Performance", value: data.score_performance, bar: "bg-blue-400" },
    { label: "Reliability", value: data.score_reliability, bar: "bg-purple-400" },
    { label: "Architecture", value: data.score_architecture, bar: "bg-indigo-400" },
    { label: "Business", value: data.score_business, bar: "bg-teal-400" },
  ];

  return (
    <div className="bg-brain-surface border border-brain-border rounded-xl p-5">
      <div className="flex items-start gap-8">
        {/* Score principal */}
        <div className="text-center min-w-[100px]">
          <div className={`text-5xl font-bold ${color}`}>{score}</div>
          <div className="text-brain-muted text-xs mt-1">/ 100</div>
          <div className="mt-2">
            <Bar value={score} max={100} color={barColor} />
          </div>
        </div>

        {/* Dimensões */}
        <div className="flex-1 grid grid-cols-2 gap-4">
          {dimensions.map(({ label, value, bar }) => (
            <div key={label}>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-brain-muted">{label}</span>
                <span className="text-white font-medium">{value}/25</span>
              </div>
              <Bar value={value} color={bar} />
            </div>
          ))}
        </div>

        {/* Alertas */}
        {(data.open_critical || data.open_warnings) ? (
          <div className="flex flex-col gap-2 min-w-[120px]">
            {(data.open_critical ?? 0) > 0 && (
              <div className="flex items-center gap-2 bg-red-500/10 border border-red-500/30 rounded px-3 py-1.5">
                <span className="text-red-400 text-lg">⛔</span>
                <span className="text-red-400 text-sm font-medium">{data.open_critical} crítico{data.open_critical! > 1 ? "s" : ""}</span>
              </div>
            )}
            {(data.open_warnings ?? 0) > 0 && (
              <div className="flex items-center gap-2 bg-yellow-500/10 border border-yellow-500/30 rounded px-3 py-1.5">
                <span className="text-yellow-400 text-lg">⚠️</span>
                <span className="text-yellow-400 text-sm font-medium">{data.open_warnings} aviso{data.open_warnings! > 1 ? "s" : ""}</span>
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
