"use client";
import { useEffect, useRef, useState } from "react";
import { Bot, User, Upload, Send, CheckCircle, Circle, Loader2, Save, FileText, FolderOpen } from "lucide-react";
import { api, BASE } from "@/lib/api";

const MODELS = [
  { id: "claude-haiku-4-5-20251001", label: "Haiku 4.5 — Rápido" },
  { id: "claude-sonnet-4-6",         label: "Sonnet 4.6 — Balanceado" },
  { id: "claude-opus-4-7",           label: "Opus 4.7 — Máximo" },
];

const TYPE_OPTIONS = [
  { value: "brand",         label: "Brand / Identidade" },
  { value: "briefing",      label: "Briefing" },
  { value: "product",       label: "Produto" },
  { value: "campaign",      label: "Campanha" },
  { value: "copy",          label: "Copy / Texto" },
  { value: "prompt",        label: "Prompt de Agente" },
  { value: "faq",           label: "FAQ / KB" },
  { value: "tone",          label: "Tom de Voz" },
  { value: "audience",      label: "Público-alvo" },
  { value: "competitor",    label: "Concorrente" },
  { value: "maker_material",label: "Material Maker" },
  { value: "rule",          label: "Regra / Padrão" },
  { value: "asset",         label: "Asset Visual" },
  { value: "other",         label: "Outro" },
];

const TYPE_LABELS: Record<string, string> = Object.fromEntries(TYPE_OPTIONS.map((o) => [o.value, o.label]));

interface Message { role: "user" | "assistant" | "system"; content: string; }
interface Classification {
  persona_slug: string | null;
  content_type: string | null;
  asset_type: string | null;
  asset_function: string | null;
  title: string | null;
}
interface Persona { id: string; slug: string; name: string; }

function StepDot({ done, label }: { done: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2">
      {done
        ? <CheckCircle size={12} className="text-green-400 shrink-0" />
        : <Circle size={12} className="text-obs-faint shrink-0" />}
      <span className={`text-xs ${done ? "text-green-400" : "text-obs-subtle"}`}>{label}</span>
    </div>
  );
}

// ── Left panel: Chat Classifier ────────────────────────────────
function ChatPanel() {
  const [model, setModel] = useState("claude-sonnet-4-6");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [stage, setStage] = useState("idle");
  const [cls, setCls] = useState<Classification>({ persona_slug: null, content_type: null, asset_type: null, asset_function: null, title: null });
  const [loading, setLoading] = useState(false);
  const [saveResult, setSaveResult] = useState<any>(null);
  const [contentText, setContentText] = useState("");
  const [showContent, setShowContent] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  async function start() {
    setLoading(true);
    try {
      const d = await api.kbIntakeStart(model);
      setSessionId(d.session_id);
      setMessages([{ role: "assistant", content: d.welcome }]);
      setStage("chatting");
    } catch (e: any) {
      setMessages((p) => [...p, {
        role: "system",
        content: `Erro ao salvar: ${e?.message || "falha desconhecida"}`,
      }]);
    } finally { setLoading(false); }
  }

  async function send() {
    if (!sessionId || (!input.trim() && !file)) return;
    setLoading(true);
    const userMsg = input.trim();
    setInput("");
    setMessages((p) => [...p, { role: "user", content: file ? `📎 ${file.name}${userMsg ? `\n${userMsg}` : ""}` : userMsg }]);
    try {
      let d: any;
      if (file) {
        const form = new FormData();
        form.append("session_id", sessionId);
        form.append("message", userMsg);
        form.append("file", file);
        const res = await fetch(`${BASE}/kb-intake/upload`, { method: "POST", body: form });
        d = await res.json();
        setFile(null);
        if (fileRef.current) fileRef.current.value = "";
      } else {
        d = await api.kbIntakeMessage(sessionId, userMsg);
      }
      setMessages((p) => [...p, { role: "assistant", content: d.message }]);
      setStage(d.stage);
      setCls(d.classification);
    } finally { setLoading(false); }
  }

  async function save() {
    if (!sessionId) return;
    setLoading(true);
    try {
      const d = await api.kbIntakeSave(sessionId, contentText);
      setSaveResult(d);
      setStage("done");
      setMessages((p) => [...p, {
        role: "system",
        content: d.ok
          ? `✅ Salvo!\n📁 ${d.file_path}\n🔀 Git: ${d.git?.commit_ok ? "ok" : "falhou"} | Push: ${d.git?.push_ok ? "ok" : "falhou"}\n🗄 Supabase: ${d.sync?.new ?? 0} novos`
          : `❌ Erro: ${d.detail || d.error}`,
      }]);
    } finally { setLoading(false); }
  }

  function reset() {
    setSessionId(null); setMessages([]); setInput(""); setFile(null);
    setStage("idle"); setCls({ persona_slug: null, content_type: null, asset_type: null, asset_function: null, title: null });
    setSaveResult(null); setContentText(""); setShowContent(false);
  }

  return (
    <div className="flex flex-col h-full glass border border-white/06 rounded-2xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 sep">
        <div className="flex items-center gap-2">
          <Bot size={15} className="text-obs-violet" />
          <span className="text-sm font-semibold">KB Classifier</span>
          {sessionId && <span className="text-[10px] text-obs-subtle font-mono">{sessionId.slice(0, 8)}</span>}
        </div>
        <div className="flex items-center gap-2">
          {stage === "idle" ? (
            <select value={model} onChange={(e) => setModel(e.target.value)}
              className="bg-obs-base border border-white/06 rounded px-2 py-1 text-xs text-obs-text focus:outline-none">
              {MODELS.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          ) : (
            <button onClick={reset} className="text-xs text-obs-subtle hover:text-obs-text border border-white/06 px-2 py-1 rounded-md transition-colors">
              Nova sessão
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {stage === "idle" && (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-center">
            <Bot size={36} className="text-obs-violet/40" />
            <div>
              <p className="text-obs-text font-medium">KB Classifier</p>
              <p className="text-xs text-obs-subtle mt-1 max-w-xs">Envie textos ou arquivos. O agente classifica e salva no vault automaticamente.</p>
            </div>
            <button onClick={start} disabled={loading}
              className="bg-obs-violet hover:bg-obs-violet/80 disabled:opacity-50 text-white text-sm px-5 py-2 rounded-lg font-medium transition-colors flex items-center gap-2">
              {loading && <Loader2 size={13} className="animate-spin" />}
              Iniciar sessão
            </button>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-2.5 ${msg.role === "user" ? "flex-row-reverse" : ""}`}>
            <div className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center mt-0.5 ${
              msg.role === "assistant" ? "bg-obs-violet/20 text-obs-violet"
              : msg.role === "system" ? "bg-green-500/20 text-green-400"
              : "bg-white/10 text-obs-text"}`}>
              {msg.role === "user" ? <User size={11} /> : <Bot size={11} />}
            </div>
            <div className={`max-w-[80%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
              msg.role === "user" ? "bg-obs-violet/15 text-obs-text"
              : msg.role === "system" ? "bg-green-500/8 border border-green-500/20 text-green-300 font-mono text-xs"
              : "bg-obs-raised border border-white/06 text-obs-text"}`}>
              {msg.content}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex gap-2.5">
            <div className="w-6 h-6 rounded-full bg-obs-violet/20 flex items-center justify-center">
              <Bot size={11} className="text-obs-violet" />
            </div>
            <div className="glass border border-white/06 rounded-xl px-3.5 py-2.5">
              <Loader2 size={13} className="animate-spin text-obs-subtle" />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Content input */}
      {stage === "ready_to_save" && showContent && (
        <div className="px-4 pb-2">
          <textarea value={contentText} onChange={(e) => setContentText(e.target.value)}
            rows={3} placeholder="Conteúdo completo (opcional)..."
            className="w-full bg-obs-base border border-white/06 rounded-lg px-3 py-2 text-xs text-obs-text focus:outline-none focus:border-obs-violet/50 resize-none" />
        </div>
      )}

      {/* Input bar */}
      {stage !== "idle" && stage !== "done" && (
        <div className="sep px-3 py-2.5 space-y-2">
          {file && (
            <div className="flex items-center gap-2 bg-obs-base border border-white/06 rounded-lg px-3 py-1.5 text-xs text-obs-text">
              <Upload size={11} className="text-obs-violet" />
              <span className="flex-1 truncate">{file.name}</span>
              <button onClick={() => { setFile(null); if (fileRef.current) fileRef.current.value = ""; }}
                className="text-obs-subtle hover:text-obs-text">✕</button>
            </div>
          )}
          <div className="flex gap-2 items-end">
            <label className="cursor-pointer text-obs-subtle hover:text-obs-text transition-colors shrink-0">
              <Upload size={15} />
              <input ref={fileRef} type="file" className="hidden" onChange={(e) => setFile(e.target.files?.[0] || null)} />
            </label>
            <textarea value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              rows={1} placeholder="Mensagem..." style={{ fieldSizing: "content" } as any}
              className="flex-1 bg-obs-base border border-white/06 rounded-lg px-3 py-2 text-sm text-obs-text focus:outline-none focus:border-obs-violet/50 resize-none min-h-[36px] max-h-[100px]" />
            <button onClick={send} disabled={loading || (!input.trim() && !file)}
              className="shrink-0 bg-obs-violet hover:bg-obs-violet/80 disabled:opacity-40 text-white p-2 rounded-lg transition-colors">
              <Send size={13} />
            </button>
          </div>
        </div>
      )}

      {/* Save bar */}
      {stage === "ready_to_save" && (
        <div className="sep bg-green-500/5 px-4 py-2.5 flex items-center gap-3">
          <CheckCircle size={13} className="text-green-400 shrink-0" />
          <span className="text-xs text-green-400 flex-1">Classificação completa</span>
          <button onClick={() => setShowContent((v) => !v)}
            className="text-xs text-obs-subtle hover:text-obs-text border border-white/06 px-2 py-1 rounded transition-colors">
            {showContent ? "Ocultar" : "+ Conteúdo"}
          </button>
          <button onClick={save} disabled={loading}
            className="flex items-center gap-1.5 bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white text-xs px-4 py-1.5 rounded-lg font-medium transition-colors">
            {loading ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />}
            Salvar
          </button>
        </div>
      )}

      {/* Classification sidebar (inline for compact layout) */}
      {stage !== "idle" && (
        <div className="sep px-4 py-3 space-y-2 shrink-0">
          <div className="flex gap-4 flex-wrap">
            <StepDot done={!!cls.persona_slug} label="Cliente" />
            <StepDot done={!!cls.content_type} label="Tipo" />
            <StepDot done={!!cls.title} label="Título" />
            <StepDot done={stage === "ready_to_save" || stage === "done"} label="Pronto" />
          </div>
        </div>
      )}
    </div>
  );
}

// ── Right panel: Quick Upload ──────────────────────────────────
function UploadPanel() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [mode, setMode] = useState<"text" | "file">("file");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [personaId, setPersonaId] = useState("");
  const [contentType, setContentType] = useState("other");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const dropRef = useRef<HTMLDivElement>(null);

  useEffect(() => { api.personas().then(setPersonas).catch(() => {}); }, []);

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f) { setFile(f); if (!title) setTitle(f.name.replace(/\.[^.]+$/, "")); }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setSuccess(false);
    try {
      if (mode === "text") {
        await api.uploadText({ title, content, persona_id: personaId || undefined, content_type: contentType });
      } else if (file) {
        await api.uploadFile(file, personaId || undefined, contentType);
      }
      setSuccess(true);
      setTitle(""); setContent(""); setFile(null);
      if (fileRef.current) fileRef.current.value = "";
    } catch (e) { console.error(e); } finally { setSubmitting(false); }
  }

  return (
    <div className="flex flex-col h-full glass border border-white/06 rounded-2xl overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 sep">
        <FolderOpen size={15} className="text-obs-amber" />
        <span className="text-sm font-semibold">Upload Direto</span>
        <span className="text-[10px] text-obs-subtle ml-1">→ queue de validação</span>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {success && (
          <div className="mb-4 border border-green-500/30 bg-green-500/8 text-green-400 rounded-xl px-4 py-3 text-xs">
            Enviado! Revise em{" "}
            <a href="/knowledge/quality" className="underline">Quality →</a>
          </div>
        )}

        <form onSubmit={submit} className="space-y-4">
          {/* Mode toggle */}
          <div className="flex gap-1.5">
            {(["file", "text"] as const).map((m) => (
              <button key={m} type="button" onClick={() => setMode(m)}
                className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                  mode === m ? "bg-obs-violet/15 border-obs-violet/50 text-obs-violet" : "border-white/06 text-obs-subtle hover:text-obs-text"}`}>
                {m === "file" ? "📎 Arquivo" : "📝 Texto"}
              </button>
            ))}
          </div>

          {/* Dropzone */}
          {mode === "file" && (
            <div ref={dropRef} onDragOver={(e) => e.preventDefault()} onDrop={onDrop}
              className={`border-2 border-dashed rounded-xl p-6 text-center transition-colors cursor-pointer ${
                file ? "border-obs-violet/50 bg-obs-violet/5" : "border-white/10 hover:border-white/20"}`}
              onClick={() => fileRef.current?.click()}>
              {file ? (
                <div className="space-y-1">
                  <FileText size={20} className="mx-auto text-obs-violet" />
                  <p className="text-sm text-obs-text font-medium">{file.name}</p>
                  <p className="text-xs text-obs-subtle">{(file.size / 1024).toFixed(1)} KB</p>
                  <button type="button" onClick={(e) => { e.stopPropagation(); setFile(null); if (fileRef.current) fileRef.current.value = ""; }}
                    className="text-xs text-obs-subtle hover:text-obs-rose transition-colors">remover</button>
                </div>
              ) : (
                <>
                  <Upload size={20} className="mx-auto text-obs-subtle mb-2" />
                  <p className="text-xs text-obs-subtle">Arraste ou clique</p>
                  <p className="text-[10px] text-obs-faint mt-1">.md .txt .json .png .jpg .svg .mp4</p>
                </>
              )}
              <input ref={fileRef} type="file" className="hidden"
                accept=".md,.txt,.json,.png,.jpg,.jpeg,.svg,.mp4,.mov"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) { setFile(f); if (!title) setTitle(f.name.replace(/\.[^.]+$/, "")); } }} />
            </div>
          )}

          {mode === "text" && (
            <textarea required value={content} onChange={(e) => setContent(e.target.value)}
              rows={6} placeholder="Cole o conteúdo aqui..."
              className="w-full bg-obs-base border border-white/06 rounded-xl px-3 py-2.5 text-sm text-obs-text focus:outline-none focus:border-obs-violet/40 resize-none" />
          )}

          {/* Title */}
          <input required value={title} onChange={(e) => setTitle(e.target.value)}
            placeholder="Título *"
            className="w-full bg-obs-base border border-white/06 rounded-xl px-3 py-2.5 text-sm text-obs-text focus:outline-none focus:border-obs-violet/40" />

          {/* Persona + Type */}
          <div className="grid grid-cols-2 gap-2">
            <select value={personaId} onChange={(e) => setPersonaId(e.target.value)}
              className="bg-obs-base border border-white/06 rounded-xl px-3 py-2.5 text-sm text-obs-text focus:outline-none">
              <option value="">Sem persona</option>
              {personas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <select value={contentType} onChange={(e) => setContentType(e.target.value)}
              className="bg-obs-base border border-white/06 rounded-xl px-3 py-2.5 text-sm text-obs-text focus:outline-none">
              {TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>

          <button type="submit" disabled={submitting || (mode === "text" ? !title || !content : !title || !file)}
            className="w-full bg-obs-amber/90 hover:bg-obs-amber disabled:opacity-40 text-obs-base text-sm font-semibold py-2.5 rounded-xl transition-colors">
            {submitting ? "Enviando..." : "Enviar para validação"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────
export default function CapturePage() {
  return (
    <div className="flex gap-5 h-[calc(100vh-7rem)]">
      <div className="flex-1 min-w-0"><ChatPanel /></div>
      <div className="w-80 shrink-0"><UploadPanel /></div>
    </div>
  );
}
