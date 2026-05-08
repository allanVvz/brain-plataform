"use client";
import { useEffect, useRef, useState } from "react";
import { Bot, User, Upload, Send, CheckCircle, Circle, Loader2, Save } from "lucide-react";
import { api } from "@/lib/api";

const MODELS = [
  { id: "claude-haiku-4-5-20251001", label: "Haiku 4.5 â€” RÃ¡pido" },
  { id: "claude-sonnet-4-6",         label: "Sonnet 4.6 â€” Balanceado" },
  { id: "claude-opus-4-7",           label: "Opus 4.7 â€” MÃ¡ximo" },
];

const TYPE_LABELS: Record<string, string> = {
  brand: "Brand", briefing: "Briefing", product: "Produto",
  campaign: "Campanha", copy: "Copy", faq: "FAQ", tone: "Tom de Voz",
  audience: "PÃºblico", competitor: "Concorrente", rule: "Regra",
  prompt: "Prompt", maker_material: "Maker", asset: "Asset Visual", other: "Outro",
};

function personaLabel(value: string | null) {
  if (!value) return null;
  if (value === "global") return "Global";
  return value
    .split("-")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

interface Message {
  role: "user" | "assistant" | "system";
  content: string;
}

interface Classification {
  persona_slug: string | null;
  content_type: string | null;
  asset_type: string | null;
  asset_function: string | null;
  title: string | null;
}

function ClassBadge({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-brain-border last:border-0">
      <span className="text-xs text-brain-muted">{label}</span>
      {value
        ? <span className="text-xs font-medium text-brain-accent">{value}</span>
        : <span className="text-xs text-brain-muted/50 italic">â€”</span>
      }
    </div>
  );
}

function StepDot({ done, label }: { done: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2">
      {done
        ? <CheckCircle size={13} className="text-green-400 shrink-0" />
        : <Circle size={13} className="text-brain-muted shrink-0" />
      }
      <span className={`text-xs ${done ? "text-green-400" : "text-brain-muted"}`}>{label}</span>
    </div>
  );
}

export default function IntakePage() {
  const [model, setModel] = useState("claude-sonnet-4-6");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [stage, setStage] = useState<string>("idle");
  const [cls, setCls] = useState<Classification>({
    persona_slug: null, content_type: null,
    asset_type: null, asset_function: null, title: null,
  });
  const [loading, setLoading] = useState(false);
  const [saveResult, setSaveResult] = useState<any>(null);
  const [contentText, setContentText] = useState("");
  const [showContentInput, setShowContentInput] = useState(false);
  const [resumeSummary, setResumeSummary] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const autoStartedRef = useRef(false);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (autoStartedRef.current || sessionId || stage !== "idle" || loading || file) return;
    autoStartedRef.current = true;
    void startSession();
  }, [sessionId, stage, loading, file]);

  async function startSession() {
    setLoading(true);
    try {
      const data = await api.kbIntakeStart(model);
      setSessionId(data.session_id);
      setMessages(data.bootstrap_message ? [{ role: "assistant", content: data.bootstrap_message }] : []);
      setStage(data.stage || "chatting");
      setCls(data.classification || {
        persona_slug: null, content_type: null,
        asset_type: null, asset_function: null, title: null,
      });
      setResumeSummary(data.resume_summary || null);
    } finally {
      setLoading(false);
    }
  }

  async function sendMessage() {
    if (!sessionId || (!input.trim() && !file)) return;
    setLoading(true);

    const userMsg = input.trim();
    setInput("");

    setMessages((prev) => [
      ...prev,
      { role: "user", content: file ? `ðŸ“Ž ${file.name}${userMsg ? `\n${userMsg}` : ""}` : userMsg },
    ]);

    try {
      const data = await api.kbIntakeMessage(sessionId!, userMsg, file || undefined);
      if (file) {
        setFile(null);
        if (fileRef.current) fileRef.current.value = "";
      }
      setMessages((prev) => [...prev, { role: "assistant", content: data.message }]);
      setStage(data.stage);
      setCls(data.classification);
    } finally {
      setLoading(false);
    }
  }

  async function handleSave() {
    if (!sessionId) return;
    setLoading(true);
    try {
      const data = await api.kbIntakeSave(sessionId, contentText);
      setSaveResult(data);
      setStage("done");
      setMessages((prev) => [
        ...prev,
        {
          role: "system",
          content: data.ok
            ? `âœ… Salvo com sucesso!\nðŸ“ ${data.file_path}\nðŸ”€ Git: ${data.git?.commit_ok ? "commitado" : "falhou"} | Push: ${data.git?.push_ok ? "ok" : "falhou"}\nðŸ—„ï¸ Supabase: ${data.sync?.new ?? 0} novos, ${data.sync?.updated ?? 0} atualizados`
            : `âŒ Erro: ${data.detail || data.error}`,
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    autoStartedRef.current = false;
    setSessionId(null);
    setMessages([]);
    setInput("");
    setFile(null);
    setStage("idle");
    setCls({ persona_slug: null, content_type: null, asset_type: null, asset_function: null, title: null });
    setSaveResult(null);
    setContentText("");
    setShowContentInput(false);
    setResumeSummary(null);
  }

  const allFilled =
    cls.persona_slug && cls.content_type && cls.title &&
    (cls.content_type !== "asset" || (cls.asset_type && cls.asset_function));

  return (
    <div className="flex gap-5 h-[calc(100vh-7rem)]">
      {/* â”€â”€ Chat panel â”€â”€ */}
      <div className="flex-1 flex flex-col bg-brain-surface border border-brain-border rounded-xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-brain-border">
          <div className="flex items-center gap-2">
            <Bot size={16} className="text-brain-accent" />
            <span className="text-sm font-semibold">Criar</span>
            {sessionId && (
              <span className="text-[10px] text-brain-muted font-mono">{sessionId.slice(0, 8)}</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {stage === "idle" ? (
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="bg-brain-bg border border-brain-border rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-brain-accent"
              >
                {MODELS.map((m) => (
                  <option key={m.id} value={m.id}>{m.label}</option>
                ))}
              </select>
            ) : (
              <span className="text-xs text-brain-muted">
                {MODELS.find((m) => m.id === model)?.label}
              </span>
            )}
            {stage !== "idle" && (
              <button
                onClick={reset}
                className="text-xs text-brain-muted hover:text-white border border-brain-border px-2 py-1 rounded-md transition-colors"
              >
                Nova sessÃ£o
              </button>
            )}
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
          {resumeSummary && (
            <div className="bg-brain-bg border border-brain-accent/20 rounded-xl px-3.5 py-2.5 text-xs text-white whitespace-pre-wrap">
              <p className="text-brain-accent font-medium mb-1">Retomada automatica da Sofia</p>
              {resumeSummary}
            </div>
          )}
          {stage === "idle" && (
            <div className="flex flex-col items-center justify-center h-full gap-4 text-center">
              <Bot size={40} className="text-brain-accent/50" />
              <div>
                <p className="text-white font-medium">Criar</p>
                <p className="text-sm text-brain-muted mt-1">
                  Envie textos, arquivos ou conteÃºdo. O agente classificarÃ¡ e salvarÃ¡ no vault automaticamente.
                </p>
              </div>
              <button
                onClick={startSession}
                disabled={loading}
                className="bg-brain-accent hover:bg-brain-accent/80 disabled:opacity-50 text-white text-sm px-6 py-2 rounded-md font-medium transition-colors flex items-center gap-2"
              >
                {loading ? <Loader2 size={14} className="animate-spin" /> : null}
                Iniciar sessÃ£o
              </button>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className={`flex gap-2.5 ${msg.role === "user" ? "flex-row-reverse" : ""}`}>
              <div className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center mt-0.5 ${
                msg.role === "assistant" ? "bg-brain-accent/20 text-brain-accent" :
                msg.role === "system" ? "bg-green-500/20 text-green-400" :
                "bg-white/10 text-white"
              }`}>
                {msg.role === "user" ? <User size={12} /> : <Bot size={12} />}
              </div>
              <div className={`max-w-[80%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
                msg.role === "user"
                  ? "bg-brain-accent/20 text-white"
                  : msg.role === "system"
                  ? "bg-green-500/10 border border-green-500/20 text-green-300 font-mono text-xs"
                  : "bg-brain-bg border border-brain-border text-white"
              }`}>
                {msg.content}
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex gap-2.5">
              <div className="w-6 h-6 rounded-full bg-brain-accent/20 flex items-center justify-center">
                <Bot size={12} className="text-brain-accent" />
              </div>
              <div className="bg-brain-bg border border-brain-border rounded-xl px-3.5 py-2.5">
                <Loader2 size={14} className="animate-spin text-brain-muted" />
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Content text area (shown when ready to save) */}
        {stage === "ready_to_save" && showContentInput && (
          <div className="px-4 pb-2">
            <textarea
              value={contentText}
              onChange={(e) => setContentText(e.target.value)}
              rows={4}
              placeholder="Cole o conteÃºdo completo aqui (opcional â€” se nÃ£o preenchido, salva apenas com frontmatter)..."
              className="w-full bg-brain-bg border border-brain-border rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-brain-accent resize-none"
            />
          </div>
        )}

        {/* Input area */}
        {stage !== "idle" && stage !== "done" && (
          <div className="border-t border-brain-border px-3 py-2.5 space-y-2">
            {file && (
              <div className="flex items-center gap-2 bg-brain-bg border border-brain-border rounded-lg px-3 py-1.5 text-xs text-white">
                <Upload size={12} className="text-brain-accent" />
                <span className="flex-1 truncate">{file.name}</span>
                <button onClick={() => { setFile(null); if (fileRef.current) fileRef.current.value = ""; }}
                  className="text-brain-muted hover:text-white">âœ•</button>
              </div>
            )}
            <div className="flex gap-2 items-end">
              <label className="cursor-pointer text-brain-muted hover:text-white transition-colors shrink-0" title="Anexar arquivo">
                <Upload size={16} />
                <input
                  ref={fileRef}
                  type="file"
                  className="hidden"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                />
              </label>
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                  }
                }}
                rows={1}
                placeholder="Digite uma mensagem ou arraste um arquivo..."
                className="flex-1 bg-brain-bg border border-brain-border rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-brain-accent resize-none min-h-[36px] max-h-[120px]"
                style={{ fieldSizing: "content" } as any}
              />
              <button
                onClick={sendMessage}
                disabled={loading || (!input.trim() && !file)}
                className="shrink-0 bg-brain-accent hover:bg-brain-accent/80 disabled:opacity-40 text-white p-2 rounded-lg transition-colors"
              >
                <Send size={14} />
              </button>
            </div>
          </div>
        )}

        {/* Save bar */}
        {stage === "ready_to_save" && (
          <div className="border-t border-brain-border bg-green-500/5 px-4 py-2.5 flex items-center gap-3">
            <CheckCircle size={14} className="text-green-400 shrink-0" />
            <span className="text-xs text-green-400 flex-1">ClassificaÃ§Ã£o completa â€” pronto para salvar</span>
            <button
              onClick={() => setShowContentInput((v) => !v)}
              className="text-xs text-brain-muted hover:text-white border border-brain-border px-2 py-1 rounded transition-colors"
            >
              {showContentInput ? "Ocultar conteÃºdo" : "+ ConteÃºdo"}
            </button>
            <button
              onClick={handleSave}
              disabled={loading}
              className="flex items-center gap-1.5 bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white text-xs px-4 py-1.5 rounded-md font-medium transition-colors"
            >
              {loading ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
              Salvar no vault
            </button>
          </div>
        )}
      </div>

      {/* â”€â”€ Classification panel â”€â”€ */}
      <div className="w-60 shrink-0 flex flex-col gap-4">
        {/* Classification state */}
        <div className="bg-brain-surface border border-brain-border rounded-xl p-4">
          <p className="text-[10px] uppercase tracking-widest text-brain-muted mb-3">ClassificaÃ§Ã£o</p>
          <div className="space-y-0">
            <ClassBadge label="Cliente" value={personaLabel(cls.persona_slug)} />
            <ClassBadge label="Tipo" value={cls.content_type ? TYPE_LABELS[cls.content_type] ?? cls.content_type : null} />
            {cls.content_type === "asset" && (
              <>
                <ClassBadge label="Tipo de asset" value={cls.asset_type} />
                <ClassBadge label="FunÃ§Ã£o" value={cls.asset_function} />
              </>
            )}
            <ClassBadge label="TÃ­tulo" value={cls.title} />
          </div>

          {/* Progress dots */}
          <div className="mt-4 space-y-1.5">
            <StepDot done={!!cls.persona_slug} label="Cliente definido" />
            <StepDot done={!!cls.content_type} label="Tipo classificado" />
            <StepDot done={!!cls.title} label="TÃ­tulo confirmado" />
            <StepDot done={stage === "ready_to_save" || stage === "done"} label="Pronto para salvar" />
            <StepDot done={stage === "done"} label="Salvo" />
          </div>
        </div>

        {/* Save result */}
        {saveResult?.ok && (
          <div className="bg-brain-surface border border-green-500/30 rounded-xl p-4 space-y-2">
            <p className="text-[10px] uppercase tracking-widest text-green-400 mb-2">Resultado</p>
            <div className="space-y-1">
              <StepDot done label="Vault atualizado" />
              <StepDot done={saveResult.git?.commit_ok} label="Git commitado" />
              <StepDot done={saveResult.git?.push_ok} label="Git push" />
              <StepDot done label="Supabase logado" />
            </div>
            {saveResult.file_path && (
              <p className="text-[10px] font-mono text-brain-muted mt-2 break-all leading-relaxed">
                {saveResult.file_path}
              </p>
            )}
          </div>
        )}

        {/* Tips */}
        {stage === "idle" && (
          <div className="bg-brain-surface border border-brain-border rounded-xl p-4">
            <p className="text-[10px] uppercase tracking-widest text-brain-muted mb-3">Como usar</p>
            <div className="space-y-2 text-xs text-brain-muted">
              <p>1. Escolha o modelo AI</p>
              <p>2. Inicie a sessÃ£o</p>
              <p>3. Envie texto ou faÃ§a upload de arquivo</p>
              <p>4. Responda as perguntas de classificaÃ§Ã£o</p>
              <p>5. Confirme e salve</p>
            </div>
            <div className="mt-3 pt-3 border-t border-brain-border space-y-1 text-[10px] text-brain-muted">
              <p className="text-white">Suporta:</p>
              <p>.md .txt .json .png .jpg .svg .pdf .mp4</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

