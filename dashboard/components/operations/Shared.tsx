import type { ReactNode } from "react";
import { AlertCircle, Inbox, LoaderCircle, Search } from "lucide-react";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-xl font-semibold text-obs-text">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-obs-subtle">{description}</p>}
      </div>
      {actions && <div className="shrink-0">{actions}</div>}
    </header>
  );
}

export function SearchBar({
  value,
  onChange,
  placeholder = "Buscar…",
  children,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-white/06 bg-white/[0.025] p-3 sm:flex-row sm:items-center">
      <label className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-white/06 bg-obs-base px-3 py-2">
        <Search size={14} className="text-obs-faint" />
        <input
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          className="w-full bg-transparent text-sm text-obs-text outline-none placeholder:text-obs-faint"
        />
      </label>
      {children}
    </div>
  );
}

export function StatePanel({
  state,
  title,
  description,
}: {
  state: "loading" | "error" | "empty";
  title: string;
  description?: string;
}) {
  const Icon = state === "loading" ? LoaderCircle : state === "error" ? AlertCircle : Inbox;
  return (
    <div className="flex min-h-52 flex-col items-center justify-center rounded-xl border border-dashed border-white/10 bg-white/[0.02] p-8 text-center">
      <Icon size={22} className={`text-obs-faint ${state === "loading" ? "animate-spin" : ""}`} />
      <p className="mt-3 text-sm font-medium text-obs-text">{title}</p>
      {description && <p className="mt-1 max-w-lg text-xs leading-relaxed text-obs-subtle">{description}</p>}
    </div>
  );
}

export function SafeMarkdown({ markdown }: { markdown: string }) {
  const lines = String(markdown || "").split(/\r?\n/);
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flushList = () => {
    if (!list.length) return;
    blocks.push(
      <ul key={`list-${blocks.length}`} className="my-2 list-disc space-y-1 pl-5 text-sm text-obs-subtle">
        {list.map((item, index) => <li key={index}>{item.replace(/\*\*/g, "")}</li>)}
      </ul>,
    );
    list = [];
  };
  lines.forEach((line, index) => {
    if (/^-\s+/.test(line)) {
      list.push(line.replace(/^-\s+/, ""));
      return;
    }
    flushList();
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      blocks.push(
        <h3 key={index} className="mb-1 mt-4 text-sm font-semibold text-obs-text">
          {heading[2]}
        </h3>,
      );
    } else if (line.trim()) {
      blocks.push(<p key={index} className="my-1 whitespace-pre-wrap text-sm leading-relaxed text-obs-subtle">{line}</p>);
    }
  });
  flushList();
  return <div>{blocks}</div>;
}

export function QualificationBadge({
  score,
  signals = [],
}: {
  score?: number;
  signals?: Array<{ key?: string; label?: string; points?: number }>;
}) {
  const value = Number(score || 0);
  return (
    <div
      className="rounded-lg border border-white/06 bg-white/[0.025] p-2"
      aria-label={`Qualificação: ${value} de 100`}
    >
      <div className="flex items-center justify-end">
        <span className="text-sm font-semibold text-obs-text">{value}/100</span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-white/5">
        <div className="h-full rounded-full bg-obs-violet" style={{ width: `${Math.min(100, value)}%` }} />
      </div>
      {signals.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {signals.slice(0, 5).map((signal) => (
            <span key={signal.key || signal.label} className="rounded-full bg-white/5 px-2 py-0.5 text-[9px] text-obs-subtle">
              {signal.label || signal.key} +{signal.points || 0}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
