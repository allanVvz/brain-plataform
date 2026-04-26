"use client";
import { useState, useEffect, useRef } from "react";
import { api } from "@/lib/api";
import {
  Play, RefreshCw, Zap, MessageCircle, AlertCircle,
  CheckCircle2, Clock, ChevronDown,
} from "lucide-react";

// ── Types ──────────────────────────────────────────────────────

type Turn = { role: string; text: string; ts: string; timeout?: boolean };
type Gap = { topic: string; evidence: string; priority: "high" | "medium" | "low" };
type Insights = {
  demonstrated: string[];
  gaps: Gap[];
  recommendations: string[];
  overall_score: number;
  summary: string;
};
type Session = {
  id: string;
  persona_slug: string;
  flow_id: string;
  status: string;
  script: any;
  output: any;
  insights: Insights | null;
  created_at: string;
};

// ── Helpers ────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  ready: "text-brain-muted",
  starting: "text-yellow-400",
  running: "text-yellow-400",
  done: "text-green-400",
  interrupted: "text-orange-400",
  error: "text-red-400",
};

const PRIORITY_COLOR: Record<string, string> = {
  high: "bg-red-500/20 text-red-300 border-red-500/30",
  medium: "bg-yellow-500/20 text-yellow-300 border-yellow-500/30",
  low: "bg-brain-border/40 text-brain-muted border-brain-border",
};

function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span className={`text-[10px] font-medium px-2 py-0.5 rounded border ${color}`}>
      {label}
    </span>
  );
}

function ScoreMeter({ score }: { score: number }) {
  const color = score >= 70 ? "bg-green-500" : score >= 40 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-3">
      <div className="flex-1 h-2 bg-brain-border rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${score}%` }} />
      </div>
      <span className="text-sm font-bold w-10 text-right">{score}%</span>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────

export default function WaValidatorPage() {
  const [personas, setPersonas] = useState<any[]>([]);
  const [flows, setFlows] = useState<any[]>([]);
  const [models, setModels] = useState<any[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSession, setActiveSession] = useState<Session | null>(null);

  // form state
  const [personaSlug, setPersonaSlug] = useState("");
  const [flowId, setFlowId] = useState("");
  const [target, setTarget] = useState("");
  const [model, setModel] = useState("claude-haiku-4-5-20251001");
  const [analyzeModel, setAnalyzeModel] = useState("claude-haiku-4-5-20251001");

  const [generating, setGenerating] = useState(false);
  const [running, setRunning] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState("");

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Initial loads
  useEffect(() => {
    api.personas().then((p) => {
      setPersonas(p);
      if (p.length > 0) setPersonaSlug(p[0].slug);
    }).catch(() => {});
    api.waFlows().then((f) => {
      setFlows(f);
      if (f.length > 0) setFlowId(f[0].id);
    }).catch(() => {});
    api.waModels().then(setModels).catch(() => {});
    api.waSessions().then(setSessions).catch(() => {});
  }, []);

  // Poll active session while running
  useEffect(() => {
    if (activeSession && (activeSession.status === "running" || activeSession.status === "starting")) {
      pollRef.current = setInterval(async () => {
        try {
          const updated = await api.waSession(activeSession.id);
          setActiveSession(updated);
          setSessions((prev) =>
            prev.map((s) => s.id === updated.id ? updated : s)
          );
          if (updated.status !== "running" && updated.status !== "starting") {
            clearInterval(pollRef.current!);
          }
        } catch {}
      }, 3000);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [activeSession?.id, activeSession?.status]);

  async function handleGenerate() {
    setError("");
    setGenerating(true);
    try {
      const result = await api.waGenerateScript({
        persona_slug: personaSlug,
        flow_id: flowId,
        target_contact: target,
        model,
      });
      const newSession: Session = {
        id: result.session_id,
        persona_slug: personaSlug,
        flow_id: flowId,
        status: "ready",
        script: result.script,
        output: null,
        insights: null,
        created_at: new Date().toISOString(),
      };
      setSessions((prev) => [newSession, ...prev]);
      setActiveSession(newSession);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setGenerating(false);
    }
  }

  async function handleRun() {
    if (!activeSession) return;
    setRunning(true);
    try {
      const updated = await api.waRun(activeSession.id);
      setActiveSession(updated);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  }

  async function handleAnalyze() {
    if (!activeSession) return;
    setAnalyzing(true);
    try {
      const insights = await api.waAnalyze(activeSession.id, analyzeModel);
      setActiveSession((s) => s ? { ...s, insights } : s);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setAnalyzing(false);
    }
  }

  const conversation: Turn[] = activeSession?.output?.conversation || [];
  const steps: any[] = activeSession?.script?.steps || [];
  const expected: string[] = activeSession?.script?.expected_knowledge || [];
  const insights = activeSession?.insights;
  const isRunning = activeSession?.status === "running" || activeSession?.status === "starting";
  const isDone = activeSession?.status === "done";

  return (
    <div className="flex gap-6 h-[calc(100vh-96px)]">
      {/* ── Left panel ───────────────────────────────────── */}
      <div className="flex flex-col gap-4 w-72 shrink-0">
        {/* Form */}
        <div className="bg-brain-surface border border-brain-border rounded-xl p-4 space-y-3">
          <h2 className="text-sm font-semibold text-white">Configurar Validação</h2>

          <div className="space-y-1">
            <label className="text-[11px] text-brain-muted uppercase tracking-wide">Cliente / Persona</label>
            <select
              className="w-full bg-brain-bg border border-brain-border text-sm text-white rounded px-2 py-1.5"
              value={personaSlug}
              onChange={(e) => setPersonaSlug(e.target.value)}
            >
              {personas.map((p) => (
                <option key={p.slug} value={p.slug}>{p.name}</option>
              ))}
            </select>
          </div>

          <div className="space-y-1">
            <label className="text-[11px] text-brain-muted uppercase tracking-wide">Fluxo a Testar</label>
            <select
              className="w-full bg-brain-bg border border-brain-border text-sm text-white rounded px-2 py-1.5"
              value={flowId}
              onChange={(e) => setFlowId(e.target.value)}
            >
              {flows.map((f) => (
                <option key={f.id} value={f.id}>{f.label}</option>
              ))}
            </select>
          </div>

          <div className="space-y-1">
            <label className="text-[11px] text-brain-muted uppercase tracking-wide">Contato WhatsApp</label>
            <input
              className="w-full bg-brain-bg border border-brain-border text-sm text-white rounded px-2 py-1.5 placeholder:text-brain-muted"
              placeholder="5511999999999 ou nome"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            />
          </div>

          <div className="space-y-1">
            <label className="text-[11px] text-brain-muted uppercase tracking-wide">Modelo IA (geração)</label>
            <select
              className="w-full bg-brain-bg border border-brain-border text-sm text-white rounded px-2 py-1.5"
              value={model}
              onChange={(e) => setModel(e.target.value)}
            >
              {models.map((m) => (
                <option key={m.id} value={m.id}>{m.label}</option>
              ))}
            </select>
          </div>

          {error && (
            <p className="text-xs text-red-400 flex items-center gap-1">
              <AlertCircle size={12} /> {error}
            </p>
          )}

          <button
            onClick={handleGenerate}
            disabled={generating || !personaSlug || !flowId || !target}
            className="w-full py-2 text-sm font-medium rounded-lg bg-brain-accent/90 hover:bg-brain-accent text-white transition disabled:opacity-40"
          >
            {generating ? "Gerando script..." : "Gerar Script"}
          </button>
        </div>

        {/* Session list */}
        {sessions.length > 0 && (
          <div className="bg-brain-surface border border-brain-border rounded-xl p-3 flex-1 overflow-y-auto space-y-1">
            <p className="text-[10px] text-brain-muted uppercase tracking-widest mb-2">Sessões</p>
            {sessions.map((s) => (
              <button
                key={s.id}
                onClick={() => setActiveSession(s)}
                className={`w-full text-left px-3 py-2 rounded-lg text-xs transition-colors ${
                  activeSession?.id === s.id
                    ? "bg-brain-accent/20 text-brain-accent"
                    : "text-brain-muted hover:text-white hover:bg-white/5"
                }`}
              >
                <div className="font-medium truncate">{s.persona_slug} — {s.flow_id}</div>
                <div className={`mt-0.5 ${STATUS_COLOR[s.status] || "text-brain-muted"}`}>
                  {s.status}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── Center panel: script + conversation ──────────── */}
      <div className="flex-1 flex flex-col gap-4 min-w-0">
        {!activeSession ? (
          <div className="flex-1 flex items-center justify-center text-brain-muted text-sm">
            Configure e gere um script para começar a validação.
          </div>
        ) : (
          <>
            {/* Script preview */}
            <div className="bg-brain-surface border border-brain-border rounded-xl p-4">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h3 className="text-sm font-semibold text-white">
                    {activeSession.script?.meta?.persona_name || activeSession.persona_slug}
                    <span className="text-brain-muted ml-2 font-normal">— {activeSession.flow_id}</span>
                  </h3>
                  {activeSession.script?.flow_description && (
                    <p className="text-xs text-brain-muted mt-0.5">{activeSession.script.flow_description}</p>
                  )}
                </div>
                <span className={`text-xs font-medium ${STATUS_COLOR[activeSession.status] || ""}`}>
                  {activeSession.status === "running" || activeSession.status === "starting" ? (
                    <span className="flex items-center gap-1"><Clock size={11} className="animate-spin" />{activeSession.status}</span>
                  ) : activeSession.status}
                </span>
              </div>

              <div className="flex gap-2 flex-wrap text-xs text-brain-muted">
                <span>{steps.length} steps</span>
                {expected.length > 0 && <span>· {expected.length} conhecimentos esperados</span>}
              </div>

              <div className="mt-3 flex gap-2">
                <button
                  onClick={handleRun}
                  disabled={running || isRunning || activeSession.status === "done"}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-green-600/80 hover:bg-green-600 text-white transition disabled:opacity-40"
                >
                  <Play size={12} />
                  {running || isRunning ? "Executando..." : "Executar no WhatsApp"}
                </button>
                {isDone && !insights && (
                  <div className="flex items-center gap-2">
                    <select
                      className="bg-brain-bg border border-brain-border text-xs text-white rounded px-2 py-1.5"
                      value={analyzeModel}
                      onChange={(e) => setAnalyzeModel(e.target.value)}
                    >
                      {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                    </select>
                    <button
                      onClick={handleAnalyze}
                      disabled={analyzing}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-brain-accent/80 hover:bg-brain-accent text-white transition disabled:opacity-40"
                    >
                      <Zap size={12} />
                      {analyzing ? "Analisando..." : "Analisar Gaps"}
                    </button>
                  </div>
                )}
              </div>
            </div>

            {/* Conversation feed */}
            <div className="flex-1 bg-brain-surface border border-brain-border rounded-xl p-4 overflow-y-auto flex flex-col gap-2 min-h-0">
              <p className="text-[10px] text-brain-muted uppercase tracking-widest shrink-0">
                Conversa {conversation.length > 0 ? `(${conversation.length} turnos)` : ""}
              </p>

              {conversation.length === 0 && !isRunning && (
                <div className="flex-1 flex items-center justify-center text-brain-muted text-xs">
                  {activeSession.status === "ready"
                    ? "Clique em «Executar no WhatsApp» para iniciar a conversa."
                    : "Aguardando conversa..."}
                </div>
              )}

              {conversation.map((turn, i) => {
                const isBot = turn.role !== "validator";
                return (
                  <div key={i} className={`flex ${isBot ? "justify-start" : "justify-end"}`}>
                    <div className={`max-w-[80%] rounded-xl px-3 py-2 text-sm ${
                      isBot
                        ? "bg-brain-bg border border-brain-border text-white"
                        : "bg-brain-accent/20 border border-brain-accent/30 text-white"
                    } ${turn.timeout ? "opacity-50 italic" : ""}`}>
                      <div className="text-[10px] mb-1 font-medium capitalize text-brain-muted">
                        {turn.role === "validator" ? "você (validator)" : turn.role}
                      </div>
                      {turn.timeout ? "(sem resposta)" : turn.text}
                    </div>
                  </div>
                );
              })}

              {isRunning && (
                <div className="flex justify-start">
                  <div className="bg-brain-bg border border-brain-border rounded-xl px-3 py-2 text-brain-muted text-xs animate-pulse">
                    Sofia está respondendo...
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* ── Right panel: KB gaps & insights ──────────────── */}
      <div className="w-72 shrink-0 flex flex-col gap-4">
        {/* Expected knowledge */}
        {expected.length > 0 && (
          <div className="bg-brain-surface border border-brain-border rounded-xl p-4">
            <p className="text-[10px] text-brain-muted uppercase tracking-widest mb-2">Conhecimento Esperado</p>
            <ul className="space-y-1">
              {expected.map((e, i) => (
                <li key={i} className="text-xs text-brain-muted flex items-start gap-1.5">
                  <CheckCircle2 size={11} className="mt-0.5 shrink-0 text-brain-border" />
                  {e}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Gaps analysis */}
        {insights ? (
          <div className="flex-1 bg-brain-surface border border-brain-border rounded-xl p-4 overflow-y-auto space-y-4">
            <div>
              <p className="text-[10px] text-brain-muted uppercase tracking-widest mb-2">Score Geral</p>
              <ScoreMeter score={insights.overall_score} />
              <p className="text-xs text-brain-muted mt-2">{insights.summary}</p>
            </div>

            {insights.gaps.length > 0 && (
              <div>
                <p className="text-[10px] text-brain-muted uppercase tracking-widest mb-2">
                  Gaps Identificados ({insights.gaps.length})
                </p>
                <div className="space-y-2">
                  {insights.gaps.map((g, i) => (
                    <div key={i} className="bg-brain-bg rounded-lg p-3 border border-brain-border space-y-1">
                      <div className="flex items-start justify-between gap-2">
                        <span className="text-xs font-medium text-white">{g.topic}</span>
                        <Badge label={g.priority} color={PRIORITY_COLOR[g.priority]} />
                      </div>
                      <p className="text-[11px] text-brain-muted">{g.evidence}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {insights.demonstrated.length > 0 && (
              <div>
                <p className="text-[10px] text-brain-muted uppercase tracking-widest mb-2">Demonstrado</p>
                <ul className="space-y-1">
                  {insights.demonstrated.map((d, i) => (
                    <li key={i} className="text-xs text-green-400 flex items-start gap-1.5">
                      <CheckCircle2 size={11} className="mt-0.5 shrink-0" />
                      {d}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {insights.recommendations.length > 0 && (
              <div>
                <p className="text-[10px] text-brain-muted uppercase tracking-widest mb-2">Recomendações KB</p>
                <ul className="space-y-1">
                  {insights.recommendations.map((r, i) => (
                    <li key={i} className="text-xs text-brain-muted flex items-start gap-1.5">
                      <MessageCircle size={11} className="mt-0.5 shrink-0 text-brain-accent" />
                      {r}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <div className="flex-1 bg-brain-surface border border-brain-border rounded-xl p-4 flex items-center justify-center">
            <p className="text-xs text-brain-muted text-center">
              {isDone
                ? "Clique em «Analisar Gaps» para identificar lacunas na base de conhecimento."
                : "Execute uma validação para ver os insights de gaps."}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
