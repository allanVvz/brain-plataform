"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Clock3, Loader2, ShieldCheck, Wrench } from "lucide-react";
import { api } from "@/lib/api";

type HarnessStep = {
  id: string;
  tool_name: string;
  agent_key: string;
  status: string;
  effect: string;
  duration_ms?: number | null;
};

type HarnessRun = {
  id: string;
  revision: number;
  assigned_agent_key: string;
  intent: string;
  status: string;
  plan?: Record<string, any>;
  response_payload?: Record<string, any>;
  artifacts?: any[];
  steps?: HarnessStep[];
};

export function AgentHarnessStatus({ sessionId, compact = false }: { sessionId?: string | null; compact?: boolean }) {
  const [run, setRun] = useState<HarnessRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    try {
      const session = await api.agentHarnessSession(sessionId);
      const latest = Array.isArray(session?.runs) ? session.runs[0] : null;
      if (latest?.id) setRun(await api.agentHarnessRun(latest.id));
    } catch {
      // Migration 088 can roll out after the compatible legacy UI. Absence is
      // intentionally silent; the chat itself remains usable.
    }
  }, [sessionId]);

  useEffect(() => {
    void refresh();
    if (!sessionId) return;
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => window.clearInterval(timer);
  }, [refresh, sessionId]);

  const awaitingApproval = run?.status === "awaiting_approval";
  const message = useMemo(
    () => String(run?.response_payload?.message || ""),
    [run],
  );

  if (!sessionId || !run) return null;

  async function mutate(kind: "approve" | "cancel") {
    if (!run) return;
    setBusy(true);
    setError(null);
    const nonce = `${kind}-${run.id}-${run.revision}-${Date.now()}`;
    try {
      if (kind === "approve") {
        await api.agentHarnessApprove(run.id, {
          expected_revision: run.revision,
          idempotency_key: nonce,
          reason: "Confirmacao pontual pelo operador no dashboard",
        });
      } else {
        await api.agentHarnessCancel(run.id, {
          expected_revision: run.revision,
          idempotency_key: nonce,
          reason: "Cancelamento solicitado pelo operador no dashboard",
        });
      }
      await refresh();
    } catch (cause: any) {
      setError(cause?.message || "Falha ao atualizar o run.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={`rounded-lg border border-white/10 bg-black/15 ${compact ? "p-2" : "p-3"}`} aria-label="Execucao da Sofia">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-[10px] uppercase tracking-[0.14em] text-obs-faint">especialista atual</p>
          <p className="truncate text-xs font-medium text-obs-text">{run.assigned_agent_key}</p>
        </div>
        <span className={`rounded px-1.5 py-0.5 text-[10px] ${awaitingApproval ? "bg-amber-500/15 text-amber-200" : "bg-emerald-500/10 text-emerald-200"}`}>
          {run.status}
        </span>
      </div>
      {message && <p className="mt-2 text-[11px] text-obs-subtle">{message}</p>}
      {!!run.steps?.length && (
        <div className="mt-2 space-y-1">
          {run.steps.map((step) => (
            <div key={step.id} className="flex items-center gap-1.5 text-[10px] text-obs-subtle">
              {step.agent_key === "qa_validator" ? <ShieldCheck size={11} /> : <Wrench size={11} />}
              <span className="min-w-0 flex-1 truncate">{step.tool_name}</span>
              <span>{step.status}</span>
              {typeof step.duration_ms === "number" && <span>{step.duration_ms} ms</span>}
            </div>
          ))}
        </div>
      )}
      {awaitingApproval && (
        <div className="mt-2 flex gap-1.5">
          <button type="button" disabled={busy} onClick={() => void mutate("approve")} className="flex items-center gap-1 rounded border border-emerald-400/30 bg-emerald-500/10 px-2 py-1 text-[10px] text-emerald-200 disabled:opacity-50">
            {busy ? <Loader2 size={10} className="animate-spin" /> : <CheckCircle2 size={10} />} Confirmar
          </button>
          <button type="button" disabled={busy} onClick={() => void mutate("cancel")} className="flex items-center gap-1 rounded border border-red-400/30 bg-red-500/10 px-2 py-1 text-[10px] text-red-200 disabled:opacity-50">
            <AlertTriangle size={10} /> Cancelar run
          </button>
        </div>
      )}
      {run.status === "running" && <p className="mt-2 flex items-center gap-1 text-[10px] text-obs-faint"><Clock3 size={10} /> polling a cada 2 s</p>}
      {error && <p className="mt-2 text-[10px] text-red-300">{error}</p>}
    </section>
  );
}
