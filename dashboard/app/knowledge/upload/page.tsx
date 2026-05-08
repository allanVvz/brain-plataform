"use client";
import { useEffect, useState, useRef } from "react";
import { api } from "@/lib/api";

interface Persona { id: string; slug: string; name: string; }

const TYPE_OPTIONS = [
  { value: "brand",         label: "Brand / Identidade" },
  { value: "briefing",      label: "Briefing" },
  { value: "product",       label: "Produto" },
  { value: "campaign",      label: "Campanha" },
  { value: "copy",          label: "Copy / Texto" },
  { value: "prompt",        label: "Prompt de Agente" },
  { value: "faq",           label: "FAQ / Golden Dataset" },
  { value: "tone",          label: "Tom de Voz" },
  { value: "audience",      label: "Público-alvo" },
  { value: "competitor",    label: "Concorrente" },
  { value: "maker_material",label: "Material para Maker" },
  { value: "rule",          label: "Regra / Padrão" },
  { value: "asset",         label: "Asset Visual" },
  { value: "other",         label: "Outro" },
];

export default function UploadPage() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [mode, setMode] = useState<"text" | "file">("text");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [personaId, setPersonaId] = useState("");
  const [contentType, setContentType] = useState("other");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.personas().then(setPersonas).catch(() => {});
  }, []);

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
      setTitle("");
      setContent("");
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
    } catch (e) {
      console.error(e);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-xl font-semibold">Upload de Conhecimento</h1>
        <p className="text-sm text-brain-muted mt-0.5">Adicione textos ou arquivos para validação antes de entrar no Golden Dataset</p>
      </div>

      {success && (
        <div className="border border-green-500/40 bg-green-500/10 text-green-400 rounded-xl px-4 py-3 text-sm">
          Material enviado com sucesso! Revise em{" "}
          <a href="/knowledge/validate" className="underline">Knowledge Validation</a>.
        </div>
      )}

      <form onSubmit={submit} className="bg-brain-surface border border-brain-border rounded-xl p-5 space-y-4">
        {/* Mode toggle */}
        <div className="flex gap-2">
          <button type="button" onClick={() => setMode("text")}
            className={`text-xs px-4 py-1.5 rounded-md border transition-colors ${mode === "text" ? "bg-brain-accent/20 border-brain-accent text-brain-accent" : "border-brain-border text-brain-muted hover:text-white"}`}>
            Colar texto
          </button>
          <button type="button" onClick={() => setMode("file")}
            className={`text-xs px-4 py-1.5 rounded-md border transition-colors ${mode === "file" ? "bg-brain-accent/20 border-brain-accent text-brain-accent" : "border-brain-border text-brain-muted hover:text-white"}`}>
            Upload de arquivo
          </button>
        </div>

        {/* Title */}
        <div>
          <label className="text-xs text-brain-muted block mb-1">Título *</label>
          <input
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Ex: Briefing Baita Conveniência 2025"
            className="w-full bg-brain-bg border border-brain-border rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-brain-accent"
          />
        </div>

        {/* Content or File */}
        {mode === "text" ? (
          <div>
            <label className="text-xs text-brain-muted block mb-1">Conteúdo *</label>
            <textarea
              required
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={8}
              placeholder="Cole o conteúdo aqui..."
              className="w-full bg-brain-bg border border-brain-border rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-brain-accent resize-none"
            />
            <p className="text-xs text-brain-muted mt-1">{content.length} caracteres</p>
          </div>
        ) : (
          <div>
            <label className="text-xs text-brain-muted block mb-1">Arquivo (.md, .txt, .json)</label>
            <input
              ref={fileRef}
              type="file"
              accept=".md,.txt,.json"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="w-full bg-brain-bg border border-brain-border rounded px-3 py-2 text-sm text-white focus:outline-none"
            />
          </div>
        )}

        {/* Persona + Type */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-brain-muted block mb-1">Cliente / Persona</label>
            <select
              value={personaId}
              onChange={(e) => setPersonaId(e.target.value)}
              className="w-full bg-brain-bg border border-brain-border rounded px-2 py-2 text-sm text-white focus:outline-none focus:border-brain-accent">
              <option value="">Sem persona (global)</option>
              {personas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-brain-muted block mb-1">Tipo de conteúdo *</label>
            <select
              value={contentType}
              onChange={(e) => setContentType(e.target.value)}
              className="w-full bg-brain-bg border border-brain-border rounded px-2 py-2 text-sm text-white focus:outline-none focus:border-brain-accent">
              {TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
        </div>

        <div className="pt-2">
          <button
            type="submit"
            disabled={submitting || (mode === "text" ? !title || !content : !title || !file)}
            className="bg-brain-accent hover:bg-brain-accent/80 disabled:opacity-50 text-white text-sm px-6 py-2 rounded-md transition-colors font-medium">
            {submitting ? "Enviando..." : "Enviar para validação"}
          </button>
        </div>
      </form>

      {/* Type guide */}
      <div className="bg-brain-surface border border-brain-border rounded-xl p-5">
        <p className="text-xs text-brain-muted uppercase tracking-wide mb-3">Guia de tipos</p>
        <div className="grid grid-cols-2 gap-2">
          {TYPE_OPTIONS.map((o) => (
            <div key={o.value} className="flex gap-2 text-xs">
              <span className="text-brain-accent font-mono">{o.value}</span>
              <span className="text-brain-muted">{o.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
