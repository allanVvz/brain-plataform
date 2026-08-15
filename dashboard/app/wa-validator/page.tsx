"use client";
import { useState, useEffect, useRef } from "react";
import { api } from "@/lib/api";
import { useGlobalPersona } from "@/lib/useGlobalPersona";
import {
  Play, Zap, MessageCircle, AlertCircle,
  CheckCircle2, Clock, Bot, FlaskConical, Paperclip,
} from "lucide-react";

// ── Types ──────────────────────────────────────────────────────

type Gap = { topic: string; evidence: string; priority: "high" | "medium" | "low" };
type Insights = {
  demonstrated: string[];
  gaps: Gap[];
  recommendations: string[];
  overall_score: number;
  summary: string;
  technical_score?: number;
  conversational_quality_score?: number | null;
  technical_pass?: boolean;
  quality_pass?: boolean;
  quality_scope?: string;
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

// ── Helpers ────────────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  ready: "text-brain-muted",
  queued: "text-yellow-400",
  starting: "text-yellow-400",
  running: "text-yellow-400",
  done: "text-green-400",
  failed: "text-red-400",
  interrupted: "text-orange-400",
  error: "text-red-400",
};

const PRIORITY_COLOR: Record<string, string> = {
  high: "bg-red-500/20 text-red-300 border-red-500/30",
  medium: "bg-yellow-500/20 text-yellow-300 border-yellow-500/30",
  low: "bg-brain-border/40 text-brain-muted border-brain-border",
};

// "graph:10:sha256:abc..." -> "Grafo v10"; "evidence:<node-id>" -> a short,
// human-readable label instead of a raw UUID/hash nobody can act on.
function translateKnowledgeItem(item: string): string {
  if (item.startsWith("graph:")) {
    const version = item.split(":")[1];
    return `Grafo v${version}`;
  }
  if (item.startsWith("evidence:")) {
    const id = item.slice("evidence:".length);
    return `Evidência de conhecimento (${id.slice(0, 8)}…)`;
  }
  return item;
}

function graphVersionLabel(session: Session | null): string | null {
  const version = session?.script?.meta?.graph_version;
  return version != null ? `Grafo v${version}` : null;
}

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
// The conversation itself is NOT rendered here -- it lives in exactly one
// place, the "Conversas de validação registradas" MessagesLayout panel
// this component's parent renders below it (reading the real `messages`
// table). This component is config + status only: which agent/flow to
// test, run it, and show what the run demonstrated.

export default function WaValidatorPage({
  onRunComplete,
}: {
  /** Called after a run finishes (direct or WhatsApp), so a parent that
   * renders this alongside something else showing the same leads (e.g.
   * MessagingSettingsPanel's "Validações" tab) can refresh that sibling --
   * this component has no way to know about it on its own. Optional: every
   * other usage (the standalone /wa-validator page) simply omits it. */
  onRunComplete?: () => void;
} = {}) {
  const globalPersona = useGlobalPersona();
  const [bots, setBots] = useState<any[]>([]);
  const [flows, setFlows] = useState<any[]>([]);
  const [activeSession, setActiveSession] = useState<Session | null>(null);

  // "SDR" is the only functional agent today -- it's what the codebase
  // calls "deterministic" internally. "Closer" is listed for context (a
  // future deterministic/model closer engine is planned) but has nothing
  // to call yet, so it stays disabled rather than silently doing nothing.
  const [agentKind, setAgentKind] = useState<"sdr" | "closer">("sdr");
  const [flowId, setFlowId] = useState("");
  // "cold" (padrão de sempre: lead novo, nada conhecido), "known_name"
  // (nome do cliente já é conhecido antes do script rodar -- prova que o
  // agente não pergunta de novo) ou "random" (sorteia entre os dois a cada
  // geração). Fluxos sem etapa de nome degradam para "cold" no backend.
  const [initialState, setInitialState] = useState<"cold" | "known_name" | "random">("cold");

  const [generating, setGenerating] = useState(false);
  const [running, setRunning] = useState(false);
  const [runningDirect, setRunningDirect] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [uploadingMedia, setUploadingMedia] = useState(false);
  const [uploadedMedia, setUploadedMedia] = useState<Array<{ id: string; filename: string }>>([]);
  const [error, setError] = useState("");

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    setBots([]);
  }, []);

  // The bot/agent for a WA Validator run is whichever persona is selected
  // in the global "CLIENTE" dropdown (same source of truth every other
  // admin settings panel uses -- see components/settings/
  // MessagingSettingsPanel.tsx) -- not a separate selector duplicating it.
  const selectedBot = bots.find((b) => b.persona_slug === globalPersona.slug) || null;

  // Flows depend on the selected persona's business model; commerce flows
  // are not meaningful for an appointment-only persona.
  useEffect(() => {
    if (!globalPersona.slug) { setFlows([]); setFlowId(""); return; }
    let active = true;
    setActiveSession(null);
    api.waBootstrap(globalPersona.slug)
      .then((snapshot) => {
        if (!active) return;
        const f = snapshot.flows || [];
        setBots(snapshot.bot ? [snapshot.bot] : []);
        setFlows(f);
        setFlowId(f.length > 0 ? f[0].id : "");
        if (f.length === 0) {
          setError("A persona selecionada não possui fluxo compatível publicado.");
        } else {
          setError("");
        }
      })
      .catch((cause: any) => {
        if (!active) return;
        setFlows([]);
        setFlowId("");
        setError(cause?.message || "Não foi possível carregar os fluxos da persona selecionada.");
      });
    return () => { active = false; };
  }, [globalPersona.slug]);

  // Poll active session while running
  useEffect(() => {
    if (activeSession && (["queued", "running", "starting"].includes(activeSession.status))) {
      pollRef.current = setInterval(async () => {
        try {
          const updated = await api.waSession(activeSession.id);
          setActiveSession(updated);
          if (!["queued", "running", "starting"].includes(updated.status)) {
            clearInterval(pollRef.current!);
            onRunComplete?.();
          }
        } catch {}
      }, 2000);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [activeSession?.id, activeSession?.status]);

  async function handleGenerate() {
    if (!globalPersona.slug) {
      setError("Selecione um cliente no cabeçalho antes de gerar o script.");
      return;
    }
    const effectiveFlow = flowId || flows[0]?.id;
    if (!effectiveFlow) {
      setError("Aguarde o carregamento dos fluxos antes de gerar o script.");
      return;
    }
    setError("");
    setGenerating(true);
    try {
      const result = await api.waGenerateScript({
        persona_slug: globalPersona.slug,
        flow_id: effectiveFlow,
        target_contact: selectedBot?.bot_name || globalPersona.slug,
        model: "none",
        initial_state: initialState,
      });
      const newSession: Session = {
        id: result.session_id,
        persona_slug: globalPersona.slug,
        flow_id: effectiveFlow,
        status: "ready",
        script: result.script,
        output: null,
        insights: null,
        created_at: new Date().toISOString(),
      };
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
      const insights = await api.waAnalyze(activeSession.id, "none");
      setActiveSession((s) => s ? { ...s, insights } : s);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleMediaFiles(files: FileList | null) {
    if (!activeSession || !files?.length) return;
    setError("");
    setUploadingMedia(true);
    try {
      const uploaded: Array<{ id: string; filename: string }> = [];
      for (const file of Array.from(files)) {
        const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
        const hex = Array.from(new Uint8Array(digest))
          .map((byte) => byte.toString(16).padStart(2, "0"))
          .join("");
        const result = await api.waUploadMedia(activeSession.id, file, `media-${hex}`);
        uploaded.push({ id: result.asset.id, filename: result.asset.filename });
      }
      setUploadedMedia((current) => [
        ...current.filter((item) => !uploaded.some((next) => next.id === item.id)),
        ...uploaded,
      ]);
      onRunComplete?.();
    } catch (cause: any) {
      setError(cause?.message || "Não foi possível armazenar a mídia de teste.");
    } finally {
      setUploadingMedia(false);
    }
  }

  const expected: string[] = activeSession?.script?.expected_knowledge || [];
  const insights = activeSession?.insights;
  const isRunning = Boolean(
    activeSession && ["queued", "running", "starting"].includes(activeSession.status),
  );
  const isDone = activeSession?.status === "done";
  const isTerminal = Boolean(activeSession && ["done", "failed", "error"].includes(activeSession.status));
  const semanticAudits = (activeSession?.output?.conversation || [])
    .filter((turn: any) => turn?.role === "bot" && turn?.semantic_audit)
    .map((turn: any, index: number) => ({ index, ...turn.semantic_audit }));

  return (
    <div className="space-y-3">
      {/* ── Header bar: every test-configuration control in one place ── */}
      <div className="bg-brain-surface border border-brain-border rounded-xl p-3 space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <label className="text-[10px] text-brain-muted uppercase tracking-wide">Agente</label>
            <select
              className="bg-brain-bg border border-brain-border text-sm text-white rounded px-2 py-1.5 min-w-[9rem]"
              value={agentKind}
              onChange={(e) => setAgentKind(e.target.value as "sdr" | "closer")}
            >
              <option value="sdr">SDR</option>
              <option value="closer" disabled>Closer (em breve)</option>
            </select>
          </div>

          <div className="space-y-1">
            <label className="text-[10px] text-brain-muted uppercase tracking-wide">Fluxo a testar</label>
            <select
              className="bg-brain-bg border border-brain-border text-sm text-white rounded px-2 py-1.5 min-w-[14rem]"
              value={flowId}
              onChange={(e) => setFlowId(e.target.value)}
              disabled={flows.length === 0}
            >
              {flows.length === 0 && <option>Selecione um cliente…</option>}
              {flows.map((f) => (
                <option key={f.id} value={f.id}>{f.label}</option>
              ))}
            </select>
          </div>

          <div className="space-y-1">
            <label className="text-[10px] text-brain-muted uppercase tracking-wide">Estado inicial</label>
            <select
              className="bg-brain-bg border border-brain-border text-sm text-white rounded px-2 py-1.5 min-w-[10rem]"
              value={initialState}
              onChange={(e) => setInitialState(e.target.value as "cold" | "known_name" | "random")}
              title="Fluxos sem etapa de nome sempre rodam como 'Frio', mesmo com outra opção selecionada."
            >
              <option value="cold">Frio (padrão)</option>
              <option value="known_name">Cliente já conhecido</option>
              <option value="random">Aleatório</option>
            </select>
          </div>

          <button
            onClick={handleGenerate}
            disabled={generating || !globalPersona.slug || !flowId || flows.length === 0}
            className="py-2 px-3 text-sm font-medium rounded-lg bg-brain-accent/90 hover:bg-brain-accent text-white transition disabled:opacity-40"
          >
            {generating ? "Gerando script..." : "Gerar Script de Teste"}
          </button>

          {activeSession && (
            <div className="flex flex-wrap gap-2 ml-auto items-center">
              <button
                onClick={handleRunDirect}
                disabled={runningDirect || isRunning || isTerminal}
                title="Testa o agente diretamente via API — não precisa do WhatsApp"
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-brain-accent/80 hover:bg-brain-accent text-white transition disabled:opacity-40"
              >
                <FlaskConical size={12} />
                {runningDirect || (isRunning && !running) ? "Executando..." : "Executar Direto (sem WA)"}
              </button>
              <button
                onClick={handleRunWA}
                disabled={running || isRunning || isTerminal}
                title="Requer o runner Playwright local e um perfil autenticado do WhatsApp Web"
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-green-700/60 hover:bg-green-700 text-white transition disabled:opacity-40"
              >
                <Play size={12} />
                {running ? "Enviando WA..." : "Executar via WhatsApp"}
              </button>
              {isTerminal && activeSession.output?.conversation?.length > 0 && !insights && (
                <button
                  onClick={handleAnalyze}
                  disabled={analyzing}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-yellow-600/70 hover:bg-yellow-600 text-white transition disabled:opacity-40"
                >
                  <Zap size={12} />
                  {analyzing ? "Analisando..." : "Analisar Evidências"}
                </button>
              )}
              <span className={`text-xs font-medium ${STATUS_COLOR[activeSession.status] || ""}`}>
                {isRunning
                  ? <span className="flex items-center gap-1"><Clock size={11} className="animate-spin" />{activeSession.status}</span>
                  : activeSession.status}
              </span>
            </div>
          )}
        </div>

        {!globalPersona.slug && (
          <p className="text-xs text-brain-muted flex items-center gap-1">
            <AlertCircle size={12} /> Selecione um cliente no cabeçalho para carregar os fluxos disponíveis.
          </p>
        )}
        {error && (
          <p className="text-xs text-red-400 flex items-center gap-1">
            <AlertCircle size={12} /> {error}
          </p>
        )}
        {activeSession && isDone && (
          <div className="flex flex-wrap items-center gap-2 border-t border-brain-border pt-3">
            <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-brain-border bg-brain-bg px-3 py-1.5 text-xs font-medium text-white transition hover:border-brain-accent/60 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-40">
              <Paperclip size={12} />
              {uploadingMedia ? "Armazenando mídia…" : "Anexar mídia de teste (sem WA)"}
              <input
                data-testid="wa-validator-media-input"
                className="sr-only"
                type="file"
                multiple
                accept="image/png,image/jpeg,image/webp,application/pdf"
                disabled={uploadingMedia}
                onChange={(event) => {
                  void handleMediaFiles(event.currentTarget.files);
                  event.currentTarget.value = "";
                }}
              />
            </label>
            <span className="text-[10px] text-brain-muted">
              Persiste apenas no lead sintético; não envia ao WhatsApp e não aciona a IA.
            </span>
            {uploadedMedia.map((item) => (
              <Badge
                key={item.id}
                label={`armazenado · ${item.filename}`}
                color="bg-green-500/15 text-green-300 border-green-500/30"
              />
            ))}
          </div>
        )}
      </div>

      {/* ── Consolidated run info: who/what/graph version + demonstrated knowledge ── */}
      {activeSession && (
        <div className="bg-brain-surface border border-brain-border rounded-xl p-4 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Bot size={14} className="text-brain-accent" />
            <span className="text-sm font-semibold text-white">
              {activeSession.script?.meta?.persona_name || activeSession.persona_slug}
            </span>
            <span className="text-brain-muted text-sm">— {activeSession.flow_id}</span>
            {graphVersionLabel(activeSession) && (
              <Badge label={graphVersionLabel(activeSession)!} color="bg-brain-accent/15 text-brain-accent border-brain-accent/30" />
            )}
          </div>
          {activeSession.script?.flow_description && (
            <p className="text-xs text-brain-muted">{activeSession.script.flow_description}</p>
          )}

          {activeSession.output && (
            <div className="flex flex-wrap gap-1.5">
              <Badge
                label={activeSession.output.technical_pass === true ? "Transação aprovada" : "Transação não aprovada"}
                color={activeSession.output.technical_pass === true ? "bg-green-500/15 text-green-300 border-green-500/30" : "bg-red-500/15 text-red-300 border-red-500/30"}
              />
              <Badge
                label={activeSession.output.quality_pass === true ? "Diálogo aprovado" : activeSession.output.quality_pass === false ? "Diálogo reprovado" : "Diálogo não avaliado"}
                color={activeSession.output.quality_pass === true ? "bg-green-500/15 text-green-300 border-green-500/30" : "bg-yellow-500/15 text-yellow-300 border-yellow-500/30"}
              />
              {activeSession.output.quality_scope && (
                <Badge label={activeSession.output.quality_scope} color="bg-brain-bg text-brain-muted border-brain-border" />
              )}
            </div>
          )}

          {expected.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {expected.map((e, i) => (
                <span key={i} className="text-[11px] px-2 py-1 rounded-md bg-brain-bg border border-brain-border text-brain-muted flex items-center gap-1">
                  <CheckCircle2 size={10} className="shrink-0" /> {translateKnowledgeItem(e)}
                </span>
              ))}
            </div>
          )}

          {activeSession.status === "error" && activeSession.error && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
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

          {semanticAudits.length > 0 && (
            <details className="rounded-lg border border-brain-border bg-brain-bg/50 p-3">
              <summary className="cursor-pointer text-xs font-medium text-white">
                Critérios semânticos por turno ({semanticAudits.length})
              </summary>
              <div className="mt-3 space-y-2">
                {semanticAudits.map((audit: any) => (
                  <div key={audit.index} className="rounded border border-brain-border p-2">
                    <p className="text-[11px] font-medium text-white">Turno {audit.index + 1}</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {Object.entries(audit.criteria || {}).map(([name, passed]) => (
                        <Badge
                          key={name}
                          label={`${passed ? "✓" : "✕"} ${name}`}
                          color={passed ? "bg-green-500/10 text-green-300 border-green-500/20" : "bg-red-500/10 text-red-300 border-red-500/20"}
                        />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </details>
          )}

          {!isDone && !isRunning && expected.length === 0 && (
            <p className="text-xs text-brain-muted">
              Clique em «Executar Direto» para iniciar o teste — a conversa aparece abaixo, em
              "Conversas de validação registradas".
            </p>
          )}

          {insights && (
            <div className="pt-3 border-t border-brain-border space-y-3">
              <div>
                <p className="text-[10px] text-brain-muted uppercase tracking-widest mb-2">
                  {insights.quality_scope === "technical_only" ? "Qualidade conversacional" : "Score conversacional"}
                </p>
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
                          <span className="text-xs font-medium text-white">{translateKnowledgeItem(g.topic)}</span>
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
                        {translateKnowledgeItem(d)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {(insights.recommendations ?? []).length > 0 && (
                <div>
                  <p className="text-[10px] text-brain-muted uppercase tracking-widest mb-2">Recomendações Golden Dataset</p>
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
          )}
        </div>
      )}
    </div>
  );
}
