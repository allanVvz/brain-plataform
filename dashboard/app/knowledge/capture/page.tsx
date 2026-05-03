"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  CheckCircle,
  Circle,
  ClipboardList,
  FileText,
  FolderOpen,
  Link,
  Loader2,
  Network,
  Play,
  Save,
  Send,
  Sparkles,
  Trash2,
  Upload,
  User,
} from "lucide-react";
import { api, BASE } from "@/lib/api";

const MODELS = [
  { id: "gpt-4o-mini", label: "GPT-4o Mini - rapido" },
  { id: "gpt-4o", label: "GPT-4o - balanceado" },
  { id: "gpt-3.5-turbo", label: "GPT-3.5 Turbo - legado" },
  { id: "claude-haiku-4-5-20251001", label: "Claude Haiku - fallback" },
];

const TYPE_OPTIONS = [
  { value: "brand", label: "Brand / Identidade" },
  { value: "briefing", label: "Briefing" },
  { value: "product", label: "Produto" },
  { value: "campaign", label: "Campanha" },
  { value: "copy", label: "Copy / Texto" },
  { value: "faq", label: "FAQ / KB" },
  { value: "tone", label: "Tom de Voz" },
  { value: "rule", label: "Regra / Padrao" },
  { value: "asset", label: "Asset Visual" },
  { value: "other", label: "Outro" },
];

const DEFAULT_OBJECTIVE =
  "Criar conhecimento de marketing para Tock Fatal a partir do catalogo Modal, organizar em grafo e propor copys por niveis.";

const DEFAULT_SOURCE = "https://tockfatal.com/pages/catalogo-modal";

const KNOWLEDGE_BLOCKS = [
  { id: "brand", label: "Brand", description: "Identidade, proposta, posicionamento e promessas confirmadas." },
  { id: "briefing", label: "Briefing", description: "Contexto bruto, objetivo, fonte e restricoes da captura." },
  { id: "campaign", label: "Campanha", description: "Colecoes, lancamentos, sazonalidade e angulos comerciais." },
  { id: "audience", label: "Publico", description: "Segmentos, dores, desejos, linguagem e objecoes." },
  { id: "product", label: "Produto", description: "Itens, kits, beneficios, precos, disponibilidade e atributos." },
  { id: "entity", label: "Entidades", description: "Cores, materiais, categorias, variantes e termos relacionados." },
  { id: "copy", label: "Copy", description: "Textos comerciais por canal, publico, etapa e oferta." },
  { id: "faq", label: "FAQ", description: "Perguntas e respostas recuperaveis pela KB." },
  { id: "rule", label: "Regras", description: "Politicas comerciais, limites, validacoes e padroes operacionais." },
  { id: "tone", label: "Tom de voz", description: "Estilo, delicadeza, vocabulario e restricoes de linguagem." },
  { id: "asset", label: "Assets", description: "Imagens, referencias visuais, criativos e materiais de apoio." },
];

const DEFAULT_SELECTED_BLOCKS = ["briefing", "audience", "product", "copy", "faq"];

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

interface Persona {
  id: string;
  slug: string;
  name: string;
}

interface SessionUpload {
  id: string;
  title: string;
  content_type: string;
  persona_id?: string;
  source: "text" | "file";
  file_name?: string;
  preview: string;
  knowledge_item_id?: string;
}

interface CrawlerRun {
  url: string;
  status_code?: number;
  confidence?: number;
  confidence_label?: string;
  warnings?: string[];
  stages?: Array<{ key: string; label: string; status: string }>;
  product_candidates?: Array<Record<string, any>>;
}

interface CapturePlan {
  personaSlug: string;
  objective: string;
  sourceUrl: string;
  outputFormat: string;
  selectedBlocks: string[];
  confirmed: boolean;
}

function StepDot({ done, label }: { done: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2">
      {done ? (
        <CheckCircle size={12} className="text-green-400 shrink-0" />
      ) : (
        <Circle size={12} className="text-obs-faint shrink-0" />
      )}
      <span className={`text-xs ${done ? "text-green-400" : "text-obs-subtle"}`}>{label}</span>
    </div>
  );
}

function buildInitialContext(plan: CapturePlan, uploads: SessionUpload[]) {
  const selectedBlockText = plan.selectedBlocks.length
    ? plan.selectedBlocks
        .map((id) => {
          const block = KNOWLEDGE_BLOCKS.find((item) => item.id === id);
          return block ? `- ${block.id}: ${block.label} - ${block.description}` : `- ${id}`;
        })
        .join("\n")
    : "- nenhum bloco selecionado; pergunte ao operador quais blocos deseja capturar.";

  const uploadBlock = uploads.length
    ? uploads
        .map((u, i) => {
          return [
            `### Upload ${i + 1}: ${u.title}`,
            `- source: ${u.source}${u.file_name ? ` (${u.file_name})` : ""}`,
            `- content_type: ${u.content_type}`,
            `- knowledge_item_id: ${u.knowledge_item_id || "pending"}`,
            "",
            u.preview,
          ].join("\n");
        })
        .join("\n\n")
    : "Nenhum upload manual nesta sessao.";

  return [
    "# Plano confirmado pelo operador",
    `persona_slug: ${plan.personaSlug}`,
    `objetivo: ${plan.objective}`,
    `fonte principal: ${plan.sourceUrl}`,
    `saida esperada: ${plan.outputFormat}`,
    "",
    "## Blocos de conhecimento solicitados",
    selectedBlockText,
    "",
    "## Uploads manuais da sessao",
    uploadBlock,
    "",
    "## Regras de execucao",
    "- Se o operador pedir para ler/coletar o site, acionar captura bruta/crawler quando disponivel e tratar resultado como evidencia com confianca, nao como verdade perfeita.",
    "- Antes de gerar ou salvar, confirmar fontes, entries e links semanticos.",
    "- Se faltar qualquer informacao, perguntar ao operador antes de propor ou salvar.",
    "- Fazer no maximo 3 perguntas objetivas por rodada.",
    "- Os blocos selecionados sao a intencao inicial; se a conversa mudar, aceitar novos blocos e perguntar lacunas especificas.",
    "- Ao gerar, produzir diversos conhecimentos: uma proposta por bloco selecionado e uma entry por produto/FAQ/copy quando houver dados suficientes.",
    "- Gerar conhecimento hierarquizado como grafo quando houver relacoes entre brand, campanha, publico, produto, entidades, copy, FAQ, regra ou tom.",
    "- Nao inventar precos, cores, disponibilidade ou URLs.",
    "- Usar Tock Fatal como persona padrao.",
  ].join("\n");
}

function PreflightPanel({
  plan,
  setPlan,
  model,
  setModel,
  onStart,
  loading,
  uploads,
}: {
  plan: CapturePlan;
  setPlan: (next: CapturePlan) => void;
  model: string;
  setModel: (value: string) => void;
  onStart: () => void;
  loading: boolean;
  uploads: SessionUpload[];
}) {
  const selectedBlocks = new Set(plan.selectedBlocks);
  const toggleBlock = (blockId: string) => {
    const next = selectedBlocks.has(blockId)
      ? plan.selectedBlocks.filter((id) => id !== blockId)
      : [...plan.selectedBlocks, blockId];
    setPlan({ ...plan, selectedBlocks: next });
  };

  return (
    <div className="flex flex-col h-full glass border border-white/06 rounded-2xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 sep">
        <div className="flex items-center gap-2">
          <ClipboardList size={15} className="text-obs-violet" />
          <span className="text-sm font-semibold">Pre-confirmacao</span>
        </div>
        <select
          value={model}
          onChange={(e) => setModel(e.target.value)}
          className="bg-obs-base border border-white/06 rounded px-2 py-1 text-xs text-obs-text focus:outline-none"
        >
          {MODELS.map((m) => (
            <option key={m.id} value={m.id}>{m.label}</option>
          ))}
        </select>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-obs-faint mb-1">Persona</label>
          <input
            value={plan.personaSlug}
            onChange={(e) => setPlan({ ...plan, personaSlug: e.target.value })}
            className="w-full bg-obs-base border border-white/06 rounded-lg px-3 py-2 text-sm text-obs-text focus:outline-none focus:border-obs-violet/50"
          />
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-obs-faint mb-1">Objetivo</label>
          <textarea
            value={plan.objective}
            onChange={(e) => setPlan({ ...plan, objective: e.target.value })}
            rows={3}
            className="w-full bg-obs-base border border-white/06 rounded-lg px-3 py-2 text-sm text-obs-text focus:outline-none focus:border-obs-violet/50 resize-none"
          />
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-obs-faint mb-1">Fonte principal</label>
          <input
            value={plan.sourceUrl}
            onChange={(e) => setPlan({ ...plan, sourceUrl: e.target.value })}
            className="w-full bg-obs-base border border-white/06 rounded-lg px-3 py-2 text-sm text-obs-text focus:outline-none focus:border-obs-violet/50"
          />
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-obs-faint mb-2">Blocos de conhecimento</label>
          <div className="grid grid-cols-2 gap-2">
            {KNOWLEDGE_BLOCKS.map((block) => {
              const selected = selectedBlocks.has(block.id);
              return (
                <button
                  key={block.id}
                  type="button"
                  onClick={() => toggleBlock(block.id)}
                  className={`text-left border rounded-lg px-3 py-2 transition-colors ${
                    selected
                      ? "border-obs-violet/70 bg-obs-violet/12 text-obs-text"
                      : "border-white/06 bg-obs-base text-obs-subtle hover:border-white/12"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    {selected ? <CheckCircle size={12} className="text-obs-violet shrink-0" /> : <Circle size={12} className="text-obs-faint shrink-0" />}
                    <span className="text-xs font-semibold">{block.label}</span>
                  </div>
                  <p className="text-[10px] text-obs-faint mt-1 leading-snug">{block.description}</p>
                </button>
              );
            })}
          </div>
          <p className="text-[10px] text-obs-faint mt-2">
            A selecao e ponto de partida. Durante a conversa o agente pode adicionar, remover ou trocar blocos conforme o pedido mudar.
          </p>
        </div>
        <label className="flex items-start gap-2 text-xs text-obs-subtle border border-white/06 rounded-lg px-3 py-2 bg-obs-base">
          <input
            type="checkbox"
            checked={plan.confirmed}
            onChange={(e) => setPlan({ ...plan, confirmed: e.target.checked })}
            className="mt-0.5 accent-obs-violet"
          />
          <span>
            Confirmo que o modelo deve usar este plano e os {uploads.length} upload(s) da sessao como contexto. Se faltar dado, ele deve me perguntar antes de propor entradas, copys, links ou salvar.
          </span>
        </label>
      </div>

      <div className="sep p-3">
        <button
          onClick={onStart}
          disabled={loading || !plan.confirmed || plan.selectedBlocks.length === 0}
          className="w-full bg-obs-violet hover:bg-obs-violet/80 disabled:opacity-40 text-white text-sm px-4 py-2.5 rounded-lg font-medium transition-colors flex items-center justify-center gap-2"
        >
          {loading ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
          Iniciar modelo com plano
        </button>
      </div>
    </div>
  );
}

function ChatPanel({
  plan,
  setPlan,
  uploads,
  onCrawlerRun,
}: {
  plan: CapturePlan;
  setPlan: (next: CapturePlan) => void;
  uploads: SessionUpload[];
  onCrawlerRun: (run: CrawlerRun) => void;
}) {
  const [model, setModel] = useState("gpt-4o-mini");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [stage, setStage] = useState("idle");
  const [cls, setCls] = useState<Classification>({ persona_slug: null, content_type: null, asset_type: null, asset_function: null, title: null });
  const [loading, setLoading] = useState(false);
  const [contentText, setContentText] = useState("");
  const [showContent, setShowContent] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function start() {
    setLoading(true);
    try {
      const d = await api.kbIntakeStart(model, buildInitialContext(plan, uploads));
      setSessionId(d.session_id);
      setMessages([{ role: "assistant", content: d.welcome }]);
      setStage("chatting");
    } catch (e: any) {
      setMessages((p) => [...p, { role: "system", content: `Erro: ${e?.message || "falha desconhecida"}` }]);
    } finally {
      setLoading(false);
    }
  }

  async function send() {
    if (!sessionId || (!input.trim() && !file)) return;
    setLoading(true);
    const userMsg = input.trim();
    setInput("");
    setMessages((p) => [...p, { role: "user", content: file ? `[arquivo] ${file.name}${userMsg ? `\n${userMsg}` : ""}` : userMsg }]);
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
      if (d.crawler) onCrawlerRun(d.crawler);
      setMessages((p) => [...p, { role: "assistant", content: d.message }]);
      setStage(d.stage);
      setCls(d.classification);
    } catch (e: any) {
      setMessages((p) => [...p, { role: "system", content: `Erro: ${e?.message || "falha ao enviar"}` }]);
    } finally {
      setLoading(false);
    }
  }

  async function save() {
    if (!sessionId) return;
    setLoading(true);
    try {
      const d = await api.kbIntakeSave(sessionId, contentText);
      setStage("done");
      setMessages((p) => [...p, {
        role: "system",
        content: d.ok
          ? `Salvo.\nArquivo: ${d.file_path}\nGit: ${d.git?.commit_ok ? "ok" : "falhou"} | Push: ${d.git?.push_ok ? "ok" : "falhou"}\nSupabase: ${d.sync?.new ?? 0} novos`
          : `Erro: ${d.detail || d.error}`,
      }]);
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    setSessionId(null);
    setMessages([]);
    setInput("");
    setFile(null);
    setStage("idle");
    setCls({ persona_slug: null, content_type: null, asset_type: null, asset_function: null, title: null });
    setContentText("");
    setShowContent(false);
  }

  if (stage === "idle") {
    return (
      <PreflightPanel
        plan={plan}
        setPlan={setPlan}
        model={model}
        setModel={setModel}
        onStart={start}
        loading={loading}
        uploads={uploads}
      />
    );
  }

  return (
    <div className="flex flex-col h-full glass border border-white/06 rounded-2xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 sep">
        <div className="flex items-center gap-2">
          <Bot size={15} className="text-obs-violet" />
          <span className="text-sm font-semibold">Criar</span>
          {sessionId && <span className="text-[10px] text-obs-subtle font-mono">{sessionId.slice(0, 8)}</span>}
        </div>
        <button onClick={reset} className="text-xs text-obs-subtle hover:text-obs-text border border-white/06 px-2 py-1 rounded-md transition-colors">
          Nova sessao
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-2.5 ${msg.role === "user" ? "flex-row-reverse" : ""}`}>
            <div className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center mt-0.5 ${
              msg.role === "assistant" ? "bg-obs-violet/20 text-obs-violet"
              : msg.role === "system" ? "bg-green-500/20 text-green-400"
              : "bg-white/10 text-obs-text"}`}>
              {msg.role === "user" ? <User size={11} /> : <Bot size={11} />}
            </div>
            <div className={`max-w-[82%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
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

      {stage === "ready_to_save" && showContent && (
        <div className="px-4 pb-2">
          <textarea
            value={contentText}
            onChange={(e) => setContentText(e.target.value)}
            rows={4}
            placeholder="Conteudo completo para salvar no vault..."
            className="w-full bg-obs-base border border-white/06 rounded-lg px-3 py-2 text-xs text-obs-text focus:outline-none focus:border-obs-violet/50 resize-none"
          />
        </div>
      )}

      {stage !== "done" && (
        <div className="sep px-3 py-2.5 space-y-2">
          {file && (
            <div className="flex items-center gap-2 bg-obs-base border border-white/06 rounded-lg px-3 py-1.5 text-xs text-obs-text">
              <Upload size={11} className="text-obs-violet" />
              <span className="flex-1 truncate">{file.name}</span>
              <button onClick={() => { setFile(null); if (fileRef.current) fileRef.current.value = ""; }} className="text-obs-subtle hover:text-obs-text">
                remover
              </button>
            </div>
          )}
          <div className="flex gap-2 items-end">
            <label className="cursor-pointer text-obs-subtle hover:text-obs-text transition-colors shrink-0">
              <Upload size={15} />
              <input ref={fileRef} type="file" className="hidden" onChange={(e) => setFile(e.target.files?.[0] || null)} />
            </label>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              rows={1}
              placeholder="Mensagem..."
              className="flex-1 bg-obs-base border border-white/06 rounded-lg px-3 py-2 text-sm text-obs-text focus:outline-none focus:border-obs-violet/50 resize-none min-h-[36px] max-h-[100px]"
            />
            <button onClick={send} disabled={loading || (!input.trim() && !file)} className="shrink-0 bg-obs-violet hover:bg-obs-violet/80 disabled:opacity-40 text-white p-2 rounded-lg transition-colors">
              <Send size={13} />
            </button>
          </div>
        </div>
      )}

      {stage === "ready_to_save" && (
        <div className="sep bg-green-500/5 px-4 py-2.5 flex items-center gap-3">
          <CheckCircle size={13} className="text-green-400 shrink-0" />
          <span className="text-xs text-green-400 flex-1">Classificacao completa</span>
          <button onClick={() => setShowContent((v) => !v)} className="text-xs text-obs-subtle hover:text-obs-text border border-white/06 px-2 py-1 rounded transition-colors">
            {showContent ? "Ocultar" : "+ Conteudo"}
          </button>
          <button onClick={save} disabled={loading} className="flex items-center gap-1.5 bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white text-xs px-4 py-1.5 rounded-lg font-medium transition-colors">
            {loading ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />}
            Salvar
          </button>
        </div>
      )}

      <div className="sep px-4 py-3 shrink-0">
        <div className="flex gap-4 flex-wrap">
          <StepDot done={!!cls.persona_slug} label="Cliente" />
          <StepDot done={!!cls.content_type} label="Tipo" />
          <StepDot done={!!cls.title} label="Titulo" />
          <StepDot done={stage === "ready_to_save" || stage === "done"} label="Pronto" />
        </div>
      </div>
    </div>
  );
}

function UploadPanel({
  uploads,
  onUploaded,
  onRemoveUpload,
}: {
  uploads: SessionUpload[];
  onUploaded: (upload: SessionUpload) => void;
  onRemoveUpload: (id: string) => void;
}) {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [mode, setMode] = useState<"text" | "file">("file");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [personaId, setPersonaId] = useState("");
  const [contentType, setContentType] = useState("other");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.personas()
      .then((rows) => {
        setPersonas(rows);
        const tock = rows.find((p: Persona) => p.slug === "tock-fatal");
        if (tock) setPersonaId(tock.id);
      })
      .catch(() => {});
  }, []);

  function chooseFile(f: File | null) {
    setFile(f);
    if (f && !title) setTitle(f.name.replace(/\.[^.]+$/, ""));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      let row: any;
      let preview = "";
      if (mode === "text") {
        row = await api.uploadText({ title, content, persona_id: personaId || undefined, content_type: contentType });
        preview = content.slice(0, 1200);
      } else if (file) {
        preview = await file.text().catch(() => `[arquivo ${file.name}]`);
        row = await api.uploadFile(file, personaId || undefined, contentType);
      }
      if (row) {
        onUploaded({
          id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
          title: row.title || row.titulo || title || file?.name || "upload",
          content_type: row.content_type || contentType,
          persona_id: personaId || undefined,
          source: mode,
          file_name: file?.name,
          preview: preview.slice(0, 1600),
          knowledge_item_id: row.id,
        });
      }
      setTitle("");
      setContent("");
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col h-full glass border border-white/06 rounded-2xl overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 sep">
        <FolderOpen size={15} className="text-obs-amber" />
        <span className="text-sm font-semibold">Upload manual</span>
      </div>

      <div className="overflow-y-auto p-4">
        <form onSubmit={submit} className="space-y-3">
          <div className="flex gap-1.5">
            {(["file", "text"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                  mode === m ? "bg-obs-violet/15 border-obs-violet/50 text-obs-violet" : "border-white/06 text-obs-subtle hover:text-obs-text"
                }`}
              >
                {m === "file" ? "Arquivo" : "Texto"}
              </button>
            ))}
          </div>

          {mode === "file" ? (
            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); chooseFile(e.dataTransfer.files[0] || null); }}
              onClick={() => fileRef.current?.click()}
              className={`border-2 border-dashed rounded-xl p-5 text-center transition-colors cursor-pointer ${
                file ? "border-obs-violet/50 bg-obs-violet/5" : "border-white/10 hover:border-white/20"
              }`}
            >
              <FileText size={20} className="mx-auto text-obs-violet mb-2" />
              <p className="text-xs text-obs-subtle truncate">{file ? file.name : "Arraste ou clique"}</p>
              <input ref={fileRef} type="file" className="hidden" accept=".md,.txt,.json" onChange={(e) => chooseFile(e.target.files?.[0] || null)} />
            </div>
          ) : (
            <textarea
              required
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={6}
              placeholder="Cole o conhecimento aqui..."
              className="w-full bg-obs-base border border-white/06 rounded-xl px-3 py-2.5 text-sm text-obs-text focus:outline-none focus:border-obs-violet/40 resize-none"
            />
          )}

          <input
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Titulo"
            className="w-full bg-obs-base border border-white/06 rounded-xl px-3 py-2.5 text-sm text-obs-text focus:outline-none focus:border-obs-violet/40"
          />
          <div className="grid grid-cols-2 gap-2">
            <select value={personaId} onChange={(e) => setPersonaId(e.target.value)} className="bg-obs-base border border-white/06 rounded-xl px-3 py-2.5 text-xs text-obs-text focus:outline-none">
              <option value="">Sem persona</option>
              {personas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <select value={contentType} onChange={(e) => setContentType(e.target.value)} className="bg-obs-base border border-white/06 rounded-xl px-3 py-2.5 text-xs text-obs-text focus:outline-none">
              {TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          <button
            type="submit"
            disabled={submitting || (mode === "text" ? !title || !content : !title || !file)}
            className="w-full bg-obs-amber/90 hover:bg-obs-amber disabled:opacity-40 text-obs-base text-sm font-semibold py-2.5 rounded-xl transition-colors"
          >
            {submitting ? "Enviando..." : "Enviar para validacao"}
          </button>
        </form>

        <div className="mt-4 pt-4 border-t border-white/06">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-obs-text">Uploads da sessao</span>
            <span className="text-[10px] text-obs-faint">{uploads.length}</span>
          </div>
          <div className="space-y-2">
            {uploads.length === 0 && <p className="text-xs text-obs-faint">Uploads feitos aqui aparecem nesta lista e entram no contexto do agente.</p>}
            {uploads.map((u) => (
              <div key={u.id} className="border border-white/06 bg-obs-base rounded-lg p-2">
                <div className="flex items-start gap-2">
                  <FileText size={13} className="text-obs-violet mt-0.5 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="text-xs text-obs-text truncate">{u.title}</p>
                    <p className="text-[10px] text-obs-faint truncate">{u.content_type} | {u.knowledge_item_id || "sem id"}</p>
                  </div>
                  <button onClick={() => onRemoveUpload(u.id)} className="text-obs-faint hover:text-obs-text">
                    <Trash2 size={12} />
                  </button>
                </div>
                {u.preview && <p className="text-[10px] text-obs-subtle mt-1 line-clamp-2">{u.preview}</p>}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function CaptureSidebar({ plan, uploads, crawlerRuns }: { plan: CapturePlan; uploads: SessionUpload[]; crawlerRuns: CrawlerRun[] }) {
  const selectedBlocks = useMemo(
    () => KNOWLEDGE_BLOCKS.filter((block) => plan.selectedBlocks.includes(block.id)),
    [plan.selectedBlocks],
  );
  const latestCrawler = crawlerRuns[0];

  return (
    <aside className="w-80 shrink-0 flex flex-col glass border border-white/06 rounded-2xl overflow-hidden">
      <div className="px-4 py-3 sep flex items-center gap-2">
        <Network size={15} className="text-obs-violet" />
        <span className="text-sm font-semibold">Contexto do agente</span>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <section>
          <div className="flex items-center gap-2 mb-2">
            <Link size={12} className="text-obs-amber" />
            <span className="text-xs font-semibold text-obs-text">Fonte</span>
          </div>
          <p className="text-[11px] text-obs-violet break-all">{plan.sourceUrl}</p>
        </section>
        <section>
          <div className="flex items-center gap-2 mb-2">
            <Sparkles size={12} className="text-obs-amber" />
            <span className="text-xs font-semibold text-obs-text">Pipeline</span>
          </div>
          <div className="space-y-1.5">
            {["crawler bruto", "parsing + confianca", "perguntar lacunas", "propor arvore", "gerar conhecimentos", "validacao humana", "salvar draft"].map((step, i) => (
              <div key={step} className="flex items-center gap-2 text-xs text-obs-subtle">
                <span className="w-5 h-5 rounded-full border border-white/08 bg-obs-base flex items-center justify-center text-[10px]">{i + 1}</span>
                {step}
              </div>
            ))}
          </div>
        </section>
        <section>
          <p className="text-xs font-semibold text-obs-text mb-2">Crawler da fonte</p>
          {!latestCrawler && (
            <div className="border border-white/06 bg-obs-base rounded-lg p-2">
              <p className="text-[11px] text-obs-subtle">Aguardando pedido para ler/coletar a fonte.</p>
              <p className="text-[10px] text-obs-faint mt-1">O resultado sera tratado como captura bruta com validacao humana.</p>
            </div>
          )}
          {latestCrawler && (
            <div className="border border-white/06 bg-obs-base rounded-lg p-2 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-obs-subtle">Confianca</span>
                <span className="text-[11px] text-obs-violet">
                  {latestCrawler.confidence_label || "pendente"} {typeof latestCrawler.confidence === "number" ? `(${latestCrawler.confidence})` : ""}
                </span>
              </div>
              <div className="space-y-1">
                {(latestCrawler.stages || []).map((stage) => (
                  <div key={stage.key || stage.label} className="flex items-center justify-between gap-2 text-[10px]">
                    <span className="text-obs-faint truncate">{stage.label}</span>
                    <span className={
                      stage.status === "done" ? "text-green-400" :
                      stage.status === "error" ? "text-red-400" :
                      stage.status === "warning" ? "text-obs-amber" :
                      "text-obs-subtle"
                    }>
                      {stage.status}
                    </span>
                  </div>
                ))}
              </div>
              <p className="text-[10px] text-obs-faint">
                {(latestCrawler.product_candidates || []).length} candidato(s) de produto. Nao salva como ativo sem validacao.
              </p>
              {(latestCrawler.warnings || []).slice(0, 2).map((warning) => (
                <p key={warning} className="text-[10px] text-obs-amber line-clamp-2">{warning}</p>
              ))}
            </div>
          )}
        </section>
        <section>
          <p className="text-xs font-semibold text-obs-text mb-2">Blocos selecionados</p>
          <div className="space-y-1.5">
            {selectedBlocks.map((block) => (
              <div key={block.id} className="border border-white/06 bg-obs-base rounded px-2 py-1.5">
                <p className="text-[11px] font-semibold text-obs-subtle">{block.label}</p>
                <p className="text-[10px] text-obs-faint line-clamp-2">{block.description}</p>
              </div>
            ))}
            {selectedBlocks.length === 0 && <p className="text-xs text-obs-faint">Selecione ao menos um bloco para iniciar.</p>}
          </div>
        </section>
        <section>
          <p className="text-xs font-semibold text-obs-text mb-2">Uploads legiveis pelo agente</p>
          <div className="space-y-1">
            {uploads.map((u) => (
              <div key={u.id} className="text-[11px] border border-white/06 bg-obs-base rounded px-2 py-1 text-obs-subtle truncate">
                {u.title}
              </div>
            ))}
            {uploads.length === 0 && <p className="text-xs text-obs-faint">Nenhum upload na sessao.</p>}
          </div>
        </section>
      </div>
    </aside>
  );
}

export function CaptureWorkspace({ embedded = false }: { embedded?: boolean }) {
  const [uploads, setUploads] = useState<SessionUpload[]>([]);
  const [crawlerRuns, setCrawlerRuns] = useState<CrawlerRun[]>([]);
  const [plan, setPlan] = useState<CapturePlan>({
    personaSlug: "tock-fatal",
    objective: DEFAULT_OBJECTIVE,
    sourceUrl: DEFAULT_SOURCE,
    outputFormat: "raw markdown com copys em niveis de marketing hierarquizados como grafo",
    selectedBlocks: DEFAULT_SELECTED_BLOCKS,
    confirmed: false,
  });

  return (
    <div className={`flex gap-5 min-h-0 ${embedded ? "h-full" : "h-[calc(100vh-7rem)]"}`}>
      <div className="w-80 shrink-0">
        <UploadPanel
          uploads={uploads}
          onUploaded={(upload) => setUploads((prev) => [upload, ...prev])}
          onRemoveUpload={(id) => setUploads((prev) => prev.filter((u) => u.id !== id))}
        />
      </div>
      <div className="flex-1 min-w-0">
        <ChatPanel
          plan={plan}
          setPlan={setPlan}
          uploads={uploads}
          onCrawlerRun={(run) => setCrawlerRuns((prev) => [run, ...prev].slice(0, 5))}
        />
      </div>
      <CaptureSidebar plan={plan} uploads={uploads} crawlerRuns={crawlerRuns} />
    </div>
  );
}

export default function CapturePage() {
  return <CaptureWorkspace />;
}
