"use client";
import { api } from "@/lib/api";

const SEVERITY_STYLE: Record<string, string> = {
  critical: "border-red-500/40 bg-red-500/5",
  warning: "border-yellow-500/40 bg-yellow-500/5",
  info: "border-blue-500/40 bg-blue-500/5",
};

const SEVERITY_ICON: Record<string, string> = {
  critical: "⛔",
  warning: "⚠️",
  info: "ℹ️",
};

interface Props {
  insight: {
    id: string;
    severity: string;
    category: string;
    title: string;
    description?: string;
    recommendation?: string;
    affected_component?: string;
    score_impact?: number;
    status: string;
  };
  onUpdate?: () => void;
}

export function InsightCard({ insight, onUpdate }: Props) {
  const borderCls = SEVERITY_STYLE[insight.severity] || "border-brain-border";
  const icon = SEVERITY_ICON[insight.severity] || "•";

  async function acknowledge() {
    await api.updateInsight(insight.id, "acknowledged");
    onUpdate?.();
  }

  async function resolve() {
    await api.updateInsight(insight.id, "resolved");
    onUpdate?.();
  }

  return (
    <div className={`border rounded-lg p-4 space-y-2 ${borderCls}`}>
      <div className="flex items-start gap-2">
        <span className="text-base">{icon}</span>
        <div className="flex-1">
          <p className="text-sm font-medium text-white leading-snug">{insight.title}</p>
          <p className="text-xs text-brain-muted mt-0.5 uppercase tracking-wide">{insight.category}</p>
        </div>
        {insight.score_impact !== 0 && (
          <span className="text-xs text-red-400 shrink-0">{insight.score_impact}</span>
        )}
      </div>

      {insight.description && (
        <p className="text-xs text-brain-muted">{insight.description}</p>
      )}

      {insight.recommendation && (
        <p className="text-xs text-brain-accent">→ {insight.recommendation}</p>
      )}

      {insight.affected_component && (
        <p className="text-xs text-brain-muted font-mono">{insight.affected_component}</p>
      )}

      {insight.status === "open" && (
        <div className="flex gap-2 pt-1">
          <button onClick={acknowledge} className="text-xs px-2 py-1 bg-brain-border hover:bg-white/10 rounded transition-colors">
            Reconhecer
          </button>
          <button onClick={resolve} className="text-xs px-2 py-1 bg-green-600/20 hover:bg-green-600/30 text-green-400 rounded transition-colors">
            Resolver
          </button>
        </div>
      )}
    </div>
  );
}
