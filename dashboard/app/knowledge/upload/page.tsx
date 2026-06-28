"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, CheckCircle, Image as ImageIcon, Loader2, Upload as UploadIcon } from "lucide-react";
import { api } from "@/lib/api";

interface Persona { id: string; slug: string; name: string; }

interface GraphNodeLite {
  id: string;
  data: { label?: string; slug?: string; node_type?: string };
}

// "Asset visual" and "Outro" both go through /assets/upload (binary pipeline).
// "Texto" covers every other content_type and goes through the legacy text route.
const TEXT_TYPES = [
  { value: "brand",          label: "Brand / Identidade" },
  { value: "briefing",       label: "Briefing" },
  { value: "product",        label: "Produto" },
  { value: "campaign",       label: "Campanha" },
  { value: "copy",           label: "Copy / Texto" },
  { value: "prompt",         label: "Prompt de Agente" },
  { value: "faq",            label: "FAQ / Golden Dataset" },
  { value: "tone",           label: "Tom de Voz" },
  { value: "audience",       label: "Publico-alvo" },
  { value: "competitor",     label: "Concorrente" },
  { value: "maker_material", label: "Material para Maker" },
  { value: "rule",           label: "Regra / Padrao" },
];

const ASSET_INTENT = [
  { value: "asset", label: "Asset visual" },
  { value: "other", label: "Outro" },
];

const SELECTABLE_PARENT_TYPES = new Set([
  "brand", "briefing", "campaign", "product", "audience", "copy", "faq", "offer", "rule", "tone",
]);

const ASSET_FUNCTIONS = [
  { value: "",                  label: "(automatica)" },
  { value: "visual_reference",  label: "Referencia visual" },
  { value: "product_reference", label: "Referencia de produto" },
  { value: "campaign_reference",label: "Referencia de campanha" },
  { value: "text_reference",    label: "Referencia de texto" },
];

type Tab = "asset" | "text";

export default function UploadPage() {
  const [tab, setTab] = useState<Tab>("asset");
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.personas().then(setPersonas).catch(() => {});
  }, []);

  function clearBanners() {
    setSuccess(null);
    setError(null);
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-xl font-semibold">Upload de Conhecimento</h1>
        <p className="text-sm text-brain-muted mt-0.5">
          Asset visual e Outro (binarios) entram pelo pipeline de assets e ficam ligados ao galho do grafo + Gallery.
          Textos seguem o fluxo legacy para validacao.
        </p>
      </div>

      <div className="flex gap-2" role="tablist" aria-label="Tipo de upload">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "asset"}
          onClick={() => { setTab("asset"); clearBanners(); }}
          className={`inline-flex items-center gap-1.5 text-xs px-4 py-1.5 rounded-md border transition-colors ${
            tab === "asset"
              ? "bg-brain-accent/20 border-brain-accent text-brain-accent"
              : "border-brain-border text-brain-muted hover:text-white"
          }`}
        >
          <ImageIcon size={12} /> Asset visual / Outro
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "text"}
          onClick={() => { setTab("text"); clearBanners(); }}
          className={`inline-flex items-center gap-1.5 text-xs px-4 py-1.5 rounded-md border transition-colors ${
            tab === "text"
              ? "bg-brain-accent/20 border-brain-accent text-brain-accent"
              : "border-brain-border text-brain-muted hover:text-white"
          }`}
        >
          <UploadIcon size={12} /> Texto
        </button>
      </div>

      {success && (
        <div className="border border-green-500/40 bg-green-500/10 text-green-400 rounded-xl px-4 py-3 text-sm">
          {success}
        </div>
      )}
      {error && (
        <div className="border border-red-500/40 bg-red-500/10 text-red-300 rounded-xl px-4 py-3 text-sm flex items-start gap-2">
          <AlertCircle size={14} className="mt-0.5 shrink-0" /> <span>{error}</span>
        </div>
      )}

      {tab === "asset" && (
        <AssetUploadForm
          personas={personas}
          onSuccess={(msg) => { setSuccess(msg); setError(null); }}
          onError={(msg) => { setError(msg); setSuccess(null); }}
        />
      )}
      {tab === "text" && (
        <TextUploadForm
          personas={personas}
          onSuccess={(msg) => { setSuccess(msg); setError(null); }}
          onError={(msg) => { setError(msg); setSuccess(null); }}
        />
      )}
    </div>
  );
}

function AssetUploadForm({
  personas,
  onSuccess,
  onError,
}: {
  personas: Persona[];
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [intent, setIntent] = useState<"asset" | "other">("asset");
  const [personaId, setPersonaId] = useState("");
  const [parentSlug, setParentSlug] = useState("");
  const [parentQuery, setParentQuery] = useState("");
  const [assetFunction, setAssetFunction] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [parents, setParents] = useState<GraphNodeLite[]>([]);
  const [parentsLoading, setParentsLoading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const personaSlug = useMemo(
    () => personas.find((p) => p.id === personaId)?.slug || "",
    [personaId, personas],
  );

  useEffect(() => {
    if (!file || !file.type.startsWith("image/")) { setPreview(null); return; }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    if (!personaSlug) { setParents([]); setParentSlug(""); return; }
    let cancelled = false;
    setParentsLoading(true);
    api
      .graphData(personaSlug, { mode: "tree", include_tags: false, include_mentions: false })
      .then((data: any) => {
        if (cancelled) return;
        const nodes: GraphNodeLite[] = (data?.nodes || []).filter((n: GraphNodeLite) => {
          const t = (n?.data?.node_type || "").toLowerCase();
          return SELECTABLE_PARENT_TYPES.has(t);
        });
        setParents(nodes);
      })
      .catch(() => { if (!cancelled) setParents([]); })
      .finally(() => { if (!cancelled) setParentsLoading(false); });
    return () => { cancelled = true; };
  }, [personaSlug]);

  const filteredParents = useMemo(() => {
    const q = parentQuery.trim().toLowerCase();
    const base = q
      ? parents.filter((n) => (n.data?.label || "").toLowerCase().includes(q) || (n.data?.slug || "").toLowerCase().includes(q))
      : parents;
    return base.slice(0, 80);
  }, [parents, parentQuery]);

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    const f = e.dataTransfer.files?.[0];
    if (f) setFile(f);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!personaId) { onError("Escolha uma persona antes de enviar."); return; }
    if (!parentSlug) {
      onError("Escolha o galho do grafo (brand, briefing, campanha, produto, copy, FAQ...). Asset/Outro nao pode ficar sozinho na arvore.");
      return;
    }
    if (!file) { onError("Selecione um arquivo."); return; }

    setSubmitting(true);
    try {
      const result = await api.assetUpload(file, {
        persona_id: personaId,
        branch_hint: parentSlug,
        asset_function: assetFunction || undefined,
        persona_slug: personaSlug || undefined,
      });
      const titleHint = (result?.knowledge_item?.title || result?.asset?.name || file.name);
      const intentLabel = intent === "asset" ? "Asset visual" : "Outro";
      onSuccess(`${intentLabel} "${titleHint}" enviado. Ligado a ${parentSlug} e ao Gallery automaticamente.`);
      setFile(null);
      setPreview(null);
      setParentSlug("");
      setParentQuery("");
      setAssetFunction("");
      if (fileRef.current) fileRef.current.value = "";
    } catch (err: any) {
      onError(err?.message || "Falha no upload.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={submit} className="bg-brain-surface border border-brain-border rounded-xl p-5 space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-brain-muted block mb-1">Cliente / Persona *</label>
          <select
            required
            value={personaId}
            onChange={(e) => setPersonaId(e.target.value)}
            className="w-full bg-brain-bg border border-brain-border rounded px-2 py-2 text-sm text-white focus:outline-none focus:border-brain-accent"
          >
            <option value="">Escolha...</option>
            {personas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-brain-muted block mb-1">Tipo *</label>
          <select
            value={intent}
            onChange={(e) => setIntent(e.target.value as "asset" | "other")}
            className="w-full bg-brain-bg border border-brain-border rounded px-2 py-2 text-sm text-white focus:outline-none focus:border-brain-accent"
          >
            {ASSET_INTENT.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
      </div>

      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        className="rounded-xl border border-dashed border-brain-border p-6 text-center cursor-pointer hover:border-brain-accent/50 transition-colors"
        onClick={() => fileRef.current?.click()}
      >
        <input
          ref={fileRef}
          type="file"
          className="hidden"
          accept="image/*,video/*,application/pdf,text/plain,text/markdown,.md,.txt"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />
        {!file && (
          <>
            <UploadIcon size={20} className="mx-auto text-brain-muted mb-2" />
            <p className="text-sm text-white">Solte o arquivo aqui ou clique para selecionar</p>
            <p className="text-xs text-brain-muted mt-1">PNG, JPG, WEBP, MP4, MOV, PDF, TXT, MD</p>
          </>
        )}
        {file && (
          <div className="space-y-2">
            <p className="text-sm text-white">{file.name}</p>
            <p className="text-xs text-brain-muted">{(file.size / 1024).toFixed(1)} KB · {file.type || "?"}</p>
            {preview && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={preview} alt={file.name} className="mx-auto mt-2 max-h-40 rounded border border-brain-border" />
            )}
          </div>
        )}
      </div>

      <div>
        <label className="text-xs text-brain-muted block mb-1">
          Galho do grafo (parent) *
          <span className="ml-2 text-[10px] text-brain-muted/80">obrigatorio — asset nao pode ficar sozinho na arvore</span>
        </label>
        <input
          type="text"
          value={parentQuery}
          onChange={(e) => setParentQuery(e.target.value)}
          placeholder="Filtrar por nome ou slug (brand, briefing, campanha, produto, copy, FAQ...)"
          className="w-full bg-brain-bg border border-brain-border rounded px-3 py-2 text-sm text-white placeholder:text-brain-muted focus:outline-none focus:border-brain-accent"
        />
        <div className="mt-2 max-h-56 overflow-y-auto rounded border border-brain-border bg-brain-bg">
          {parentsLoading && <p className="px-3 py-2 text-xs text-brain-muted">Carregando galhos...</p>}
          {!parentsLoading && !personaSlug && <p className="px-3 py-2 text-xs text-brain-muted">Escolha uma persona para listar os galhos.</p>}
          {!parentsLoading && personaSlug && filteredParents.length === 0 && (
            <p className="px-3 py-2 text-xs text-brain-muted">Sem galhos compativeis para essa persona.</p>
          )}
          {filteredParents.map((node) => {
            const slug = node.data?.slug || node.id;
            const selected = slug === parentSlug;
            return (
              <button
                key={node.id}
                type="button"
                onClick={() => setParentSlug(slug)}
                className={`block w-full px-3 py-2 text-left text-xs transition-colors ${
                  selected ? "bg-brain-accent/20 text-white" : "text-brain-muted hover:bg-white/[0.04] hover:text-white"
                }`}
              >
                <span className="font-medium">{node.data?.label || slug}</span>
                <span className="ml-2 text-[10px] uppercase text-brain-muted/80">{node.data?.node_type}</span>
                <span className="ml-2 font-mono text-[10px] text-brain-muted/80">{slug}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <label className="text-xs text-brain-muted block mb-1">Funcao do asset (opcional)</label>
        <select
          value={assetFunction}
          onChange={(e) => setAssetFunction(e.target.value)}
          className="w-full bg-brain-bg border border-brain-border rounded px-2 py-2 text-sm text-white focus:outline-none focus:border-brain-accent"
        >
          {ASSET_FUNCTIONS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
        </select>
      </div>

      <div className="pt-2 flex items-center justify-between">
        <p className="text-[11px] text-brain-muted">
          Ao enviar, o arquivo passa pelo pipeline (classifier + OCR), vira card pendente e fica ligado ao galho escolhido + Gallery.
        </p>
        <button
          type="submit"
          disabled={submitting || !personaId || !parentSlug || !file}
          className="inline-flex items-center gap-1.5 bg-brain-accent hover:bg-brain-accent/80 disabled:opacity-50 text-white text-sm px-6 py-2 rounded-md transition-colors font-medium"
        >
          {submitting ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle size={12} />}
          {submitting ? "Enviando..." : "Enviar para validacao"}
        </button>
      </div>
    </form>
  );
}

function TextUploadForm({
  personas,
  onSuccess,
  onError,
}: {
  personas: Persona[];
  onSuccess: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [mode, setMode] = useState<"text" | "file">("text");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [personaId, setPersonaId] = useState("");
  const [contentType, setContentType] = useState(TEXT_TYPES[0].value);
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!title) { onError("Adicione um titulo."); return; }
    setSubmitting(true);
    try {
      if (mode === "text") {
        if (!content.trim()) { onError("Cole o conteudo do material."); setSubmitting(false); return; }
        await api.uploadText({ title, content, persona_id: personaId || undefined, content_type: contentType });
      } else {
        if (!file) { onError("Selecione um arquivo de texto (.md/.txt/.json)."); setSubmitting(false); return; }
        await api.uploadFile(file, personaId || undefined, contentType);
      }
      onSuccess(`Material "${title}" enviado para validacao.`);
      setTitle("");
      setContent("");
      setFile(null);
      if (fileRef.current) fileRef.current.value = "";
    } catch (err: any) {
      onError(parseUploadError(err) || "Falha no envio.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={submit} className="bg-brain-surface border border-brain-border rounded-xl p-5 space-y-4">
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setMode("text")}
          className={`text-xs px-4 py-1.5 rounded-md border transition-colors ${mode === "text" ? "bg-brain-accent/20 border-brain-accent text-brain-accent" : "border-brain-border text-brain-muted hover:text-white"}`}
        >
          Colar texto
        </button>
        <button
          type="button"
          onClick={() => setMode("file")}
          className={`text-xs px-4 py-1.5 rounded-md border transition-colors ${mode === "file" ? "bg-brain-accent/20 border-brain-accent text-brain-accent" : "border-brain-border text-brain-muted hover:text-white"}`}
        >
          Arquivo de texto
        </button>
      </div>

      <div>
        <label className="text-xs text-brain-muted block mb-1">Titulo *</label>
        <input
          required
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Ex: Briefing da persona ativa"
          className="w-full bg-brain-bg border border-brain-border rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-brain-accent"
        />
      </div>

      {mode === "text" ? (
        <div>
          <label className="text-xs text-brain-muted block mb-1">Conteudo *</label>
          <textarea
            required
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={8}
            placeholder="Cole o conteudo aqui..."
            className="w-full bg-brain-bg border border-brain-border rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-brain-accent resize-none"
          />
          <p className="text-xs text-brain-muted mt-1">{content.length} caracteres</p>
        </div>
      ) : (
        <div>
          <label className="text-xs text-brain-muted block mb-1">Arquivo de texto (.md, .txt, .json)</label>
          <input
            ref={fileRef}
            type="file"
            accept=".md,.txt,.json,text/plain,text/markdown,application/json"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="w-full bg-brain-bg border border-brain-border rounded px-3 py-2 text-sm text-white focus:outline-none"
          />
          <p className="text-xs text-brain-muted mt-1">
            Imagem, PDF ou video? Use a aba <strong>Asset visual / Outro</strong>.
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-brain-muted block mb-1">Cliente / Persona</label>
          <select
            value={personaId}
            onChange={(e) => setPersonaId(e.target.value)}
            className="w-full bg-brain-bg border border-brain-border rounded px-2 py-2 text-sm text-white focus:outline-none focus:border-brain-accent"
          >
            <option value="">Sem persona (global)</option>
            {personas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-brain-muted block mb-1">Tipo de conteudo *</label>
          <select
            value={contentType}
            onChange={(e) => setContentType(e.target.value)}
            className="w-full bg-brain-bg border border-brain-border rounded px-2 py-2 text-sm text-white focus:outline-none focus:border-brain-accent"
          >
            {TEXT_TYPES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
      </div>

      <div className="pt-2">
        <button
          type="submit"
          disabled={submitting || !title || (mode === "text" ? !content.trim() : !file)}
          className="inline-flex items-center gap-1.5 bg-brain-accent hover:bg-brain-accent/80 disabled:opacity-50 text-white text-sm px-6 py-2 rounded-md transition-colors font-medium"
        >
          {submitting ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle size={12} />}
          {submitting ? "Enviando..." : "Enviar para validacao"}
        </button>
      </div>
    </form>
  );
}

function parseUploadError(err: any): string {
  const message = err?.message || "";
  if (message.includes("415")) {
    return "Arquivo binario nao e aceito nesta aba. Use 'Asset visual / Outro' para imagens, PDFs e videos.";
  }
  if (message.toLowerCase().includes("utf-8")) {
    return "Arquivo precisa ser texto UTF-8. Para imagens/PDFs/videos use 'Asset visual / Outro'.";
  }
  return message;
}
