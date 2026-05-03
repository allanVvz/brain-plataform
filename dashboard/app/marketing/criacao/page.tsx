"use client";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Sparkles, Send, Loader2, Copy as CopyIcon, Check, ChevronRight, MessageCircle } from "lucide-react";
import { CaptureWorkspace } from "@/app/knowledge/capture/page";

interface InputSpec {
  name: string;
  label: string;
  type: "text" | "textarea" | "select";
  placeholder?: string;
  required?: boolean;
  options?: string[];
}

interface ModeSpec {
  key: string;
  label: string;
  description: string;
  inputs: InputSpec[];
}

export default function CriacaoPage() {
  const [modes, setModes] = useState<ModeSpec[]>([]);
  const [availableModels, setAvailableModels] = useState<Record<string, string>>({});
  const [selectedKey, setSelectedKey] = useState<string>("");
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [model, setModel] = useState<string>("gpt-4o-mini");
  const [personaId, setPersonaId] = useState<string>("");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [content, setContent] = useState<string>("");
  const [copied, setCopied] = useState(false);
  const [activeTool, setActiveTool] = useState<"criar" | "gerar">("criar");

  // Load modes + persona scope
  useEffect(() => {
    api.marketingModes()
      .then((d) => {
        setModes(d.modes);
        setAvailableModels(d.available_models);
        if (d.modes[0]) setSelectedKey(d.modes[0].key);
      })
      .catch((e) => setError(e?.message || "Falha ao carregar modos"));

    setPersonaId(window.localStorage.getItem("ai-brain-persona-id") || "");
    const onPersonaChange = (event: Event) => {
      const detail = (event as CustomEvent<{ id?: string }>).detail;
      setPersonaId(detail?.id || "");
    };
    window.addEventListener("ai-brain-persona-change", onPersonaChange);
    return () => window.removeEventListener("ai-brain-persona-change", onPersonaChange);
  }, []);

  // Reset inputs when mode changes (avoid stale fields)
  useEffect(() => {
    setInputs({});
    setContent("");
    setError(null);
  }, [selectedKey]);

  const selectedMode = useMemo(() => modes.find((m) => m.key === selectedKey) || null, [modes, selectedKey]);

  const canGenerate = useMemo(() => {
    if (!selectedMode || generating) return false;
    return selectedMode.inputs.every((i) => !i.required || (inputs[i.name] || "").trim().length > 0);
  }, [selectedMode, inputs, generating]);

  const onGenerate = async () => {
    if (!canGenerate || !selectedMode) return;
    setGenerating(true);
    setError(null);
    setContent("");
    try {
      const res = await api.marketingGenerate({
        mode: selectedMode.key,
        inputs,
        persona_id: personaId || undefined,
        model,
        max_tokens: 1500,
      });
      setContent(res.content);
    } catch (e: any) {
      setError(e?.message || "Erro ao gerar");
    } finally {
      setGenerating(false);
    }
  };

  const onCopy = async () => {
    if (!content) return;
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  };

  const toolButton = (key: "criar" | "gerar", label: string, Icon: typeof Sparkles) => {
    const active = activeTool === key;
    return (
      <button
        type="button"
        onClick={() => setActiveTool(key)}
        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs transition-colors ${
          active ? "bg-obs-violet/15 text-obs-violet" : "text-obs-subtle hover:text-obs-text hover:bg-white/05"
        }`}
      >
        <Icon size={13} />
        {label}
      </button>
    );
  };

  return (
    <div className="flex flex-col h-[calc(100vh-6rem)] gap-3 overflow-hidden">
      <div
        className="shrink-0 flex items-center justify-between rounded-xl px-4 py-3"
        style={{ border: "1px solid rgba(255,255,255,0.07)", background: "rgba(14,17,24,0.80)" }}
      >
        <div>
          <p className="text-sm font-semibold text-white">Criar</p>
          <p className="text-[10px] text-obs-faint">Ferramentas de marketing e captura de conhecimento</p>
        </div>
        <div className="flex items-center gap-1 rounded-lg bg-obs-base border border-white/06 p-1">
          {toolButton("criar", "Criar", MessageCircle)}
          {toolButton("gerar", "Gerar copy", Sparkles)}
        </div>
      </div>

      {activeTool === "criar" ? (
        <div className="flex-1 min-h-0 overflow-hidden">
          <CaptureWorkspace embedded />
        </div>
      ) : (
        <div className="flex-1 min-h-0 flex gap-4 overflow-hidden">
      {/* ── Left: mode picker ─────────────────────────── */}
      <aside
        className="w-60 shrink-0 flex flex-col rounded-xl overflow-hidden"
        style={{ border: "1px solid rgba(255,255,255,0.07)", background: "rgba(14,17,24,0.80)" }}
      >
        <div className="px-4 py-3" style={{ borderBottom: "1px solid rgba(255,255,255,0.07)" }}>
          <div className="flex items-center gap-2">
            <Sparkles size={13} className="text-obs-violet" />
            <span className="text-xs font-semibold text-white">Modos de criação</span>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto py-1">
          {modes.map((m) => {
            const active = m.key === selectedKey;
            return (
              <button
                key={m.key}
                onClick={() => setSelectedKey(m.key)}
                className="w-full text-left px-3 py-2 transition flex items-start gap-2"
                style={{
                  background: active ? "rgba(124,111,255,0.10)" : "transparent",
                  borderLeft: active ? "2px solid #7c6fff" : "2px solid transparent",
                }}
              >
                <ChevronRight size={11} className={`mt-0.5 shrink-0 ${active ? "text-obs-violet" : "text-obs-faint"}`} />
                <div className="min-w-0">
                  <p className={`text-xs font-medium truncate ${active ? "text-white" : "text-obs-subtle"}`}>{m.label}</p>
                  <p className="text-[10px] text-obs-faint line-clamp-2 mt-0.5">{m.description}</p>
                </div>
              </button>
            );
          })}
        </div>
      </aside>

      {/* ── Center: form ────────────────────────────── */}
      <div
        className="w-[420px] shrink-0 flex flex-col rounded-xl overflow-hidden"
        style={{ border: "1px solid rgba(255,255,255,0.07)", background: "rgba(14,17,24,0.80)" }}
      >
        <div className="px-4 py-3 flex items-center justify-between" style={{ borderBottom: "1px solid rgba(255,255,255,0.07)" }}>
          <div className="min-w-0">
            <p className="text-xs font-semibold text-white truncate">{selectedMode?.label || "—"}</p>
            <p className="text-[10px] text-obs-faint truncate">
              {personaId ? "persona ativa" : "sem persona — selecione no topo"}
            </p>
          </div>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="text-[10px] bg-obs-base border border-white/10 rounded px-1.5 py-0.5 text-obs-subtle focus:outline-none"
            title="Modelo (OpenAI cascade + Anthropic fallback)"
          >
            {Object.entries(availableModels).map(([id, label]) => (
              <option key={id} value={id}>{label}</option>
            ))}
          </select>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {selectedMode?.inputs.map((spec) => (
            <FieldInput
              key={spec.name}
              spec={spec}
              value={inputs[spec.name] || ""}
              onChange={(v) => setInputs((prev) => ({ ...prev, [spec.name]: v }))}
            />
          ))}
          {!selectedMode && (
            <p className="text-xs text-obs-faint">Carregando modos…</p>
          )}
        </div>

        <div className="p-3" style={{ borderTop: "1px solid rgba(255,255,255,0.07)" }}>
          <button
            onClick={onGenerate}
            disabled={!canGenerate}
            className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-md text-xs font-medium bg-amber-500/85 hover:bg-amber-400 text-zinc-900 disabled:opacity-40 disabled:cursor-not-allowed transition"
          >
            {generating ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
            {generating ? "Gerando…" : "Gerar"}
          </button>
          {error && <p className="text-[10px] text-red-400 mt-2">erro: {error}</p>}
        </div>
      </div>

      {/* ── Right: result ───────────────────────────── */}
      <div
        className="flex-1 flex flex-col rounded-xl overflow-hidden"
        style={{ border: "1px solid rgba(255,255,255,0.07)", background: "rgba(14,17,24,0.80)" }}
      >
        <div className="px-4 py-3 flex items-center justify-between" style={{ borderBottom: "1px solid rgba(255,255,255,0.07)" }}>
          <span className="text-xs font-semibold text-white">Resultado</span>
          {content && (
            <button
              onClick={onCopy}
              className="flex items-center gap-1 text-[11px] text-obs-subtle hover:text-white transition"
            >
              {copied ? <Check size={11} className="text-emerald-400" /> : <CopyIcon size={11} />}
              {copied ? "copiado" : "copiar"}
            </button>
          )}
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          {!content && !generating && (
            <p className="text-xs text-obs-faint">
              Preencha os campos à esquerda e clique em <b className="text-obs-subtle">Gerar</b>. O resultado aparece aqui em markdown.
            </p>
          )}
          {generating && (
            <div className="flex items-center gap-2 text-xs text-obs-subtle">
              <Loader2 size={11} className="animate-spin" /> Pensando…
            </div>
          )}
          {content && (
            <pre className="text-xs text-obs-text whitespace-pre-wrap break-words font-mono leading-relaxed">
              {content}
            </pre>
          )}
        </div>
      </div>
        </div>
      )}
    </div>
  );
}

function FieldInput({
  spec,
  value,
  onChange,
}: {
  spec: InputSpec;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="block text-[10px] uppercase tracking-wider text-obs-faint mb-1">
        {spec.label}{spec.required && <span className="text-amber-400 ml-0.5">*</span>}
      </label>
      {spec.type === "textarea" ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={spec.placeholder}
          rows={3}
          className="w-full bg-obs-base border border-white/10 rounded px-2 py-1.5 text-xs text-obs-text placeholder-obs-faint focus:outline-none focus:border-obs-violet/50 resize-y"
        />
      ) : spec.type === "select" ? (
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full bg-obs-base border border-white/10 rounded px-2 py-1.5 text-xs text-obs-text focus:outline-none focus:border-obs-violet/50"
        >
          <option value="">— escolha —</option>
          {(spec.options || []).map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
      ) : (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={spec.placeholder}
          className="w-full bg-obs-base border border-white/10 rounded px-2 py-1.5 text-xs text-obs-text placeholder-obs-faint focus:outline-none focus:border-obs-violet/50"
        />
      )}
    </div>
  );
}
