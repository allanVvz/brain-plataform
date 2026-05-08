"use client";
import { useState, useEffect, useRef } from "react";
import { api } from "@/lib/api";
import {
  Play, Zap, MessageCircle, AlertCircle,
  CheckCircle2, Clock, Bot, FlaskConical,
} from "lucide-react";

// â”€â”€ Types â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

type Turn = { role: string; text: string; ts: string; timeout?: boolean; agent?: string; latency_ms?: number };
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
  error?: string;
};

// â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

// â”€â”€ Main Page â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export default function WaValidatorPage() {
  const [bots, setBots] = useState<any[]>([]);
  const [flows, setFlows] = useState<any[]>([]);
  const [models, setModels] = useState<any[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSession, setActiveSession] = useState<Session | null>(null);

  // form state â€” bot is the primary selector (replaces persona + contact)
  const [selectedBotId, setSelectedBotId] = useState("");
  const [flowId, setFlowId] = useState("");
  // default to gpt-4o-mini so generate works before models endpoint resolves
  const [model, setModel] = useState("gpt-4o-mini");
  const [analyzeModel, setAnalyzeModel] = useState("gpt-4o-mini");

  const [generating, setGenerating] = useState(false);
  const [running, setRunning] = useState(false);
  const [runningDirect, setRunningDirect] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState("");

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const convBottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.waBots().then((bs) => {
      setBots(bs);
      if (bs.length > 0) {
        setSelectedBotId(bs[0].id);
      }
    }).catch(() => {});
    api.waFlows().then((f) => {
      setFlows(f);
      if (f.length > 0) setFlowId(f[0].id);
    }).catch(() => {});
    api.waModels().then((ms) => {
      setModels(ms);
      if (ms.length > 0) { setModel(ms[0].id); setAnalyzeModel(ms[0].id); }
    }).catch(() => {});
    api.waSessions().then((ss) => {
      setSessions(ss);
      // Auto-select most recent running session, or simply the latest one
      if (ss.length > 0) {
        const live = ss.find((s: any) => s.status === "running" || s.status === "starting");
        setActiveSession(live || ss[0]);
      }
    }).catch(() => {});
  }, []);

  // Auto-scroll conversation
  useEffect(() => {
    convBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeSession?.output?.conversation?.length]);

  // Poll active session while running
  useEffect(() => {
    if (activeSession && (activeSession.status === "running" || activeSession.status === "starting")) {
      pollRef.current = setInterval(async () => {
        try {
          const updated = await api.waSession(activeSession.id);
          setActiveSession(updated);
          setSessions((prev) => prev.map((s) => s.id === updated.id ? updated : s));
          if (updated.status !== "running" && updated.status !== "starting") {
            clearInterval(pollRef.current!);
          }
        } catch {}
      }, 2000);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [activeSession?.id, activeSession?.status]);

  const selectedBot = bots.find((b) => b.id === selectedBotId) || {
    id: "",
    bot_name: "Bot",
    label: "Bot dinamico",
    persona_slug: "global",
    description: "Selecione um bot carregado do banco.",
  };

  async function handleGenerate() {
    setError("");
    setGenerating(true);
    try {
      const effectiveFlow = flowId || flows[0]?.id || "compra_simples";
      const effectiveModel = model || "gpt-4o-mini";
      const result = await api.waGenerateScript({
        persona_slug: selectedBot.persona_slug,
        flow_id: effectiveFlow,
        target_contact: selectedBot.bot_name,
        model: effectiveModel,
      });
      const newSession: Session = {
        id: result.session_id,
        persona_slug: selectedBot.persona_slug,
        flow_id: effectiveFlow,
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

  async function handleRunDirect() {
    if (!activeSession) return;
    setRunningDirect(true);
    try {
      const updated = await api.waRunDirect(activeSession.id);
      setActiveSession(updated);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setRunningDirect(false);
    }
  }

  async function handleRunWA() {
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
      {/* â”€â”€ Left panel â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      <div className="flex flex-col gap-4 w-72 shrink-0">

        {/* Form */}
        <div className="bg-brain-surface border border-brain-border rounded-xl p-4 space-y-3">
          <h2 className="text-sm font-semibold text-white flex items-center gap-2">
            <FlaskConical size={14} className="text-brain-accent" />
            Configurar Teste
          </h2>

          {/* Bot selector */}
          <div className="space-y-1">
            <label className="text-[11px] text-brain-muted uppercase tracking-wide">Bot / Agente</label>
            <div className="space-y-1.5">
              {bots.length === 0 ? (
                // Placeholder card while bots load
                <button
                  className="w-full text-left px-3 py-2 rounded-lg border text-xs bg-brain-accent/15 border-brain-accent/40 text-brain-accent"
                >
                  <div className="font-semibold flex items-center gap-1.5">
                    <Bot size={11} /> Carregando bots
                  </div>
                  <div className="text-[10px] mt-0.5 opacity-70">Aguardando configuracao dinamica</div>
                </button>
              ) : (
                bots.map((b) => {
                  const active = b.id === selectedBotId;
                  return (
                    <button
                      key={b.id}
                      onClick={() => setSelectedBotId(b.id)}
                      className={`w-full text-left px-3 py-2 rounded-lg border text-xs transition-colors ${
                        active
                          ? "bg-brain-accent/15 border-brain-accent/40 text-brain-accent"
                          : "bg-brain-bg border-brain-border text-brain-muted hover:text-white hover:border-brain-border"
                      }`}
                    >
                      <div className="font-semibold flex items-center gap-1.5">
                        <Bot size={11} /> {b.label}
                      </div>
                      {b.description && (
                        <div className="text-[10px] mt-0.5 opacity-70 truncate">{b.description}</div>
                      )}
                    </button>
                  );
                })
              )}
            </div>
          </div>

          {/* Flow selector */}
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

          {/* Model selector */}
          <div className="space-y-1">
            <label className="text-[11px] text-brain-muted uppercase tracking-wide">Modelo (geraÃ§Ã£o do script)</label>
            <select
              className="w-full bg-brain-bg border border-brain-border text-sm text-white rounded px-2 py-1.5"
              value={model}
              onChange={(e) => setModel(e.target.value)}
            >
              {models.length === 0
                ? <option value="gpt-4o-mini">GPT-4o Mini</option>
                : models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </div>

          {error && (
            <p className="text-xs text-red-400 flex items-center gap-1">
              <AlertCircle size={12} /> {error}
            </p>
          )}

          <button
            onClick={handleGenerate}
            disabled={generating}
            className="w-full py-2 text-sm font-medium rounded-lg bg-brain-accent/90 hover:bg-brain-accent text-white transition disabled:opacity-40"
          >
            {generating ? "Gerando script..." : "Gerar Script de Teste"}
          </button>
        </div>

        {/* Session list */}
        {sessions.length > 0 && (
          <div className="bg-brain-surface border border-brain-border rounded-xl p-3 flex-1 overflow-y-auto space-y-1">
            <p className="text-[10px] text-brain-muted uppercase tracking-widest mb-2">SessÃµes anteriores</p>
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
                <div className="font-medium truncate">{s.persona_slug} â€” {s.flow_id}</div>
                <div className={`mt-0.5 ${STATUS_COLOR[s.status] || "text-brain-muted"}`}>
                  {s.status}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* â”€â”€ Center panel: script + conversation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      <div className="flex-1 flex flex-col gap-4 min-w-0">
        {!activeSession ? (
          <div className="flex-1 flex flex-col items-center justify-center gap-3 text-brain-muted">
            <FlaskConical size={36} className="opacity-20" />
            <p className="text-sm">Selecione um bot, escolha o fluxo e gere um script para comeÃ§ar.</p>
          </div>
        ) : (
          <>
            {/* Script header */}
            <div className="bg-brain-surface border border-brain-border rounded-xl p-4">
              <div className="flex items-start justify-between gap-3 mb-3">
                <div>
                  <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                    <Bot size={14} className="text-brain-accent" />
                    {activeSession.script?.meta?.persona_name || activeSession.persona_slug}
                    <span className="text-brain-muted font-normal">â€” {activeSession.flow_id}</span>
                  </h3>
                  {activeSession.script?.flow_description && (
                    <p className="text-xs text-brain-muted mt-0.5 pl-5">{activeSession.script.flow_description}</p>
                  )}
                </div>
                <span className={`text-xs font-medium shrink-0 ${STATUS_COLOR[activeSession.status] || ""}`}>
                  {isRunning
                    ? <span className="flex items-center gap-1"><Clock size={11} className="animate-spin" />{activeSession.status}</span>
                    : activeSession.status}
                </span>
              </div>

              <div className="text-xs text-brain-muted pl-5 mb-3">
                {steps.length} perguntas Â· {expected.length} conhecimentos esperados
              </div>

              {activeSession.status === "error" && activeSession.error && (
                <div className="mb-3 bg-red-500/10 border border-red-500/30 rounded-lg p-3">
                  <p className="text-xs font-semibold text-red-400 mb-1">Erro</p>
                  <pre className="text-[11px] text-red-300/80 whitespace-pre-wrap break-all max-h-32 overflow-y-auto">
                    {activeSession.error}
                  </pre>
                  {(activeSession as any).log && (
                    <details className="mt-2">
                      <summary className="text-[10px] text-red-400/60 cursor-pointer select-none">Log do processo</summary>
                      <pre className="mt-1 text-[10px] text-brain-muted whitespace-pre-wrap break-all max-h-40 overflow-y-auto">
                        {(activeSession as any).log}
                      </pre>
                    </details>
                  )}
                </div>
              )}

              {/* Action buttons */}
              <div className="flex flex-wrap gap-2">
                {/* PRIMARY: direct test (internal pipeline) */}
                <button
                  onClick={handleRunDirect}
                  disabled={runningDirect || isRunning || isDone}
                  title="Testa o agente diretamente via API â€” nÃ£o precisa do WhatsApp"
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-brain-accent/80 hover:bg-brain-accent text-white transition disabled:opacity-40"
                >
                  <FlaskConical size={12} />
                  {runningDirect || (isRunning && !running)
                    ? "Executando..."
                    : "Executar Direto (sem WA)"}
                </button>

                {/* SECONDARY: WhatsApp subprocess */}
                <button
                  onClick={handleRunWA}
                  disabled={running || isRunning || isDone}
                  title="Requer wa-wscrap-bot rodando e Sofia conectada ao WhatsApp via n8n"
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-green-700/60 hover:bg-green-700 text-white transition disabled:opacity-40"
                >
                  <Play size={12} />
                  {running ? "Enviando WA..." : "Executar via WhatsApp"}
                </button>

                {/* Analyze gaps */}
                {isDone && !insights && (
                  <div className="flex items-center gap-2 ml-auto">
                    <select
                      className="bg-brain-bg border border-brain-border text-xs text-white rounded px-2 py-1.5"
                      value={analyzeModel}
                      onChange={(e) => setAnalyzeModel(e.target.value)}
                    >
                      {models.length === 0
                        ? <option value="gpt-4o-mini">GPT-4o Mini</option>
                        : models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                    </select>
                    <button
                      onClick={handleAnalyze}
                      disabled={analyzing}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-yellow-600/70 hover:bg-yellow-600 text-white transition disabled:opacity-40"
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
                Conversa {conversation.length > 0 ? `Â· ${conversation.length} turnos` : ""}
              </p>

              {conversation.length === 0 && !isRunning && (
                <div className="flex-1 flex items-center justify-center text-brain-muted text-xs">
                  {activeSession.status === "ready"
                    ? "Clique em Â«Executar DiretoÂ» para iniciar o teste interno."
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
                      <div className="text-[10px] mb-1 font-medium text-brain-muted flex items-center gap-1.5">
                        {isBot
                          ? <><Bot size={9} /> {turn.agent || selectedBot.bot_name}</>
                          : "Validador IA"}
                        {turn.latency_ms && (
                          <span className="ml-auto text-[9px] opacity-60">{turn.latency_ms}ms</span>
                        )}
                      </div>
                      {turn.timeout ? "(sem resposta)" : turn.text}
                    </div>
                  </div>
                );
              })}

              {isRunning && conversation.length > 0 && (
                <div className="flex justify-start">
                  <div className="bg-brain-bg border border-brain-border rounded-xl px-3 py-2 text-brain-muted text-xs animate-pulse">
                    {selectedBot.bot_name} estÃ¡ respondendo...
                  </div>
                </div>
              )}

              <div ref={convBottomRef} />
            </div>
          </>
        )}
      </div>

      {/* â”€â”€ Right panel: Golden Dataset gaps & insights â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */}
      <div className="w-72 shrink-0 flex flex-col gap-4">
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

        {insights ? (
          <div className="flex-1 bg-brain-surface border border-brain-border rounded-xl p-4 overflow-y-auto space-y-4">
            <div>
              <p className="text-[10px] text-brain-muted uppercase tracking-widest mb-2">Score Geral</p>
              <ScoreMeter score={insights.overall_score ?? 0} />
              <p className="text-xs text-brain-muted mt-2">{insights.summary ?? ""}</p>
            </div>

            {(insights.gaps ?? []).length > 0 && (
              <div>
                <p className="text-[10px] text-brain-muted uppercase tracking-widest mb-2">
                  Gaps ({insights.gaps.length})
                </p>
                <div className="space-y-2">
                  {insights.gaps.map((g, i) => (
                    <div key={i} className="bg-brain-bg rounded-lg p-3 border border-brain-border space-y-1">
                      <div className="flex items-start justify-between gap-2">
                        <span className="text-xs font-medium text-white">{g.topic}</span>
                        <Badge label={g.priority} color={PRIORITY_COLOR[g.priority] ?? ""} />
                      </div>
                      <p className="text-[11px] text-brain-muted">{g.evidence}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {(insights.demonstrated ?? []).length > 0 && (
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

            {(insights.recommendations ?? []).length > 0 && (
              <div>
                <p className="text-[10px] text-brain-muted uppercase tracking-widest mb-2">RecomendaÃ§Ãµes Golden Dataset</p>
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
                ? "Clique em Â«Analisar GapsÂ» para identificar lacunas no Golden Dataset."
                : "Execute um teste para ver os insights."}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

