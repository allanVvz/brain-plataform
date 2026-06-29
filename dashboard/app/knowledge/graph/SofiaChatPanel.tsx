"use client";

import { useEffect, useRef } from "react";
import { Loader2, MessageCircle, Send, Undo2, CheckCircle2, X } from "lucide-react";

export interface SofiaChatMessage {
  id: string;
  role: "user" | "sofia" | "system";
  text: string;
  pending?: boolean;
  createdAt: number;
}

interface SofiaChatPanelProps {
  open: boolean;
  loading: boolean;
  messages: SofiaChatMessage[];
  hasPendingVisualChanges: boolean;
  sessionId?: string | null;
  planSummary?: { persona?: string; brand?: string | null; selectedNodeId?: string | null; queueSize?: number; blockingCount?: number } | null;
  onToggle: () => void;
  onSubmit: (text: string) => void;
  onConfirmPending: () => void;
  onUndoPending: () => void;
}

export default function SofiaChatPanel({
  open,
  loading,
  messages,
  hasPendingVisualChanges,
  sessionId,
  planSummary,
  onToggle,
  onSubmit,
  onConfirmPending,
  onUndoPending,
}: SofiaChatPanelProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, loading]);

  const statusText = loading
    ? "Sofia processando..."
    : hasPendingVisualChanges
      ? "Alteracao visual pendente"
      : "Alteracao persistida";

  return (
    <div className="absolute left-0 top-0 z-40 h-full pointer-events-none">
      <button
        type="button"
        onClick={onToggle}
        className="pointer-events-auto absolute left-3 top-1/2 flex -translate-y-1/2 items-center gap-1.5 rounded-r-lg rounded-l-md border border-white/10 bg-obs-violet/25 px-2.5 py-3 text-xs font-semibold text-obs-violet shadow-lg shadow-black/20 hover:bg-obs-violet/35"
        title={open ? "Fechar Sofia" : "Abrir Sofia"}
      >
        <MessageCircle size={16} />
        {!open && <span>Sofia</span>}
      </button>

      {open && (
        <aside className="pointer-events-auto absolute left-0 top-0 h-full w-[340px] border-r border-white/10 bg-obs-surface/95 backdrop-blur">
          <header className="flex items-center justify-between border-b border-white/10 px-3 py-2">
            <div>
              <p className="text-xs font-semibold text-obs-text">Sofia no Graph</p>
              <p className="text-[10px] text-obs-subtle" aria-live="polite">
                {statusText}
              </p>
              {sessionId && (
                <p className="text-[10px] text-obs-faint font-mono">sessao {sessionId.slice(0, 8)}</p>
              )}
            </div>
            <button type="button" onClick={onToggle} className="rounded p-1 text-obs-subtle hover:text-white">
              <X size={14} />
            </button>
          </header>

          <div className="flex h-[calc(100%-110px)] flex-col">
            <div ref={scrollRef} className="flex-1 space-y-2 overflow-y-auto px-3 py-3">
              {planSummary && (
                <div className="rounded border border-white/10 bg-white/[0.03] px-2.5 py-2 text-[10px] text-obs-subtle">
                  <p>persona: <span className="text-obs-text">{planSummary.persona || "-"}</span></p>
                  <p>brand ativa: <span className="text-obs-text">{planSummary.brand || "-"}</span></p>
                  <p>node foco: <span className="text-obs-text font-mono">{planSummary.selectedNodeId || "-"}</span></p>
                  <p>fila patch: <span className="text-obs-text">{planSummary.queueSize ?? 0}</span> | bloqueios: <span className="text-obs-text">{planSummary.blockingCount ?? 0}</span></p>
                </div>
              )}
              {messages.length === 0 && (
                <p className="rounded border border-dashed border-white/15 px-3 py-2 text-[11px] text-obs-subtle">
                  Descreva uma alteracao no grafo para a Sofia executar.
                </p>
              )}
              {messages.map((m) => (
                <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`max-w-[85%] rounded-lg border px-2.5 py-2 text-[11px] ${
                      m.role === "user"
                        ? "border-obs-violet/35 bg-obs-violet/20 text-white"
                        : m.role === "system"
                          ? "border-amber-400/35 bg-amber-500/15 text-amber-100"
                          : "border-white/10 bg-white/5 text-obs-text"
                    }`}
                  >
                    {m.text}
                    {m.pending && <span className="mt-1 block text-[10px] text-amber-200">nao persistido</span>}
                  </div>
                </div>
              ))}
              {loading && (
                <div className="flex items-center gap-1 text-[11px] text-obs-subtle">
                  <Loader2 size={12} className="animate-spin" />
                  Sofia pensando...
                </div>
              )}
            </div>

            <div className="border-t border-white/10 p-2">
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  const form = new FormData(event.currentTarget);
                  const text = String(form.get("message") || "").trim();
                  if (!text) return;
                  onSubmit(text);
                  event.currentTarget.reset();
                }}
                className="flex gap-1.5"
              >
                <input
                  name="message"
                  autoComplete="off"
                  placeholder="Ex.: reencaixe VZ Lupas abaixo de AllanVvz"
                  className="flex-1 rounded border border-white/10 bg-obs-base px-2 py-1.5 text-[11px] text-obs-text outline-none focus:border-obs-violet/50"
                  disabled={loading}
                />
                <button type="submit" disabled={loading} className="rounded bg-obs-violet px-2 text-white disabled:opacity-50">
                  <Send size={12} />
                </button>
              </form>
              <div className="mt-2 flex gap-1.5">
                <button
                  type="button"
                  disabled={!hasPendingVisualChanges || loading}
                  onClick={onConfirmPending}
                  className="flex items-center gap-1 rounded border border-emerald-400/35 bg-emerald-500/15 px-2 py-1 text-[10px] text-emerald-200 disabled:opacity-40"
                >
                  <CheckCircle2 size={11} />
                  Confirmar
                </button>
                <button
                  type="button"
                  disabled={!hasPendingVisualChanges || loading}
                  onClick={onUndoPending}
                  className="flex items-center gap-1 rounded border border-red-400/35 bg-red-500/15 px-2 py-1 text-[10px] text-red-200 disabled:opacity-40"
                >
                  <Undo2 size={11} />
                  Desfazer
                </button>
              </div>
            </div>
          </div>
        </aside>
      )}
    </div>
  );
}
