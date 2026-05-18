"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { Upload, X, Loader2, CheckCircle, AlertCircle } from "lucide-react";
import { api } from "@/lib/api";

interface Persona { id: string; slug: string; name: string }

interface GraphNodeLite {
  id: string;
  data: { label?: string; slug?: string; node_type?: string };
}

interface Props {
  open: boolean;
  onClose: () => void;
  onUploaded: (result: any) => void;
  personas: Persona[];
  initialPersonaId?: string;
}

const ASSET_FUNCTIONS = [
  { value: "",                  label: "(automatica)" },
  { value: "visual_reference",  label: "Referencia visual" },
  { value: "product_reference", label: "Referencia de produto" },
  { value: "campaign_reference",label: "Referencia de campanha" },
  { value: "text_reference",    label: "Referencia de texto" },
];

const SELECTABLE_PARENT_TYPES = new Set([
  "brand", "briefing", "campaign", "product", "audience", "copy", "faq", "offer", "rule", "tone",
]);

export default function AssetUploadDialog({ open, onClose, onUploaded, personas, initialPersonaId }: Props) {
  const [personaId, setPersonaId] = useState(initialPersonaId || "");
  const [parentSlug, setParentSlug] = useState("");
  const [parentQuery, setParentQuery] = useState("");
  const [assetFunction, setAssetFunction] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [parents, setParents] = useState<GraphNodeLite[]>([]);
  const [parentsLoading, setParentsLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const personaSlug = useMemo(() => personas.find((p) => p.id === personaId)?.slug || "", [personaId, personas]);

  useEffect(() => {
    if (!open) return;
    setError(null);
    if (!personaId && initialPersonaId) setPersonaId(initialPersonaId);
  }, [open, initialPersonaId, personaId]);

  useEffect(() => {
    if (!file) { setPreview(null); return; }
    if (!file.type.startsWith("image/")) { setPreview(null); return; }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    if (!personaSlug) { setParents([]); return; }
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

  if (!open) return null;

  function onPick(f: File) {
    setFile(f);
    setError(null);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    const f = e.dataTransfer.files?.[0];
    if (f) onPick(f);
  }

  async function submit() {
    setError(null);
    if (!personaId) { setError("Escolha uma persona."); return; }
    if (!parentSlug) { setError("Escolha o galho do grafo (brand, briefing, campanha, produto, copy, FAQ)."); return; }
    if (!file) { setError("Escolha um arquivo."); return; }
    setSubmitting(true);
    try {
      const result = await api.assetUpload(file, {
        persona_id: personaId,
        branch_hint: parentSlug,
        asset_function: assetFunction || undefined,
        persona_slug: personaSlug || undefined,
      });
      onUploaded(result);
      // Reset and close
      setFile(null);
      setParentSlug("");
      setParentQuery("");
      setAssetFunction("");
      onClose();
    } catch (err: any) {
      setError(err?.message || "Falha no upload.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/55 p-5 backdrop-blur-sm">
      <div className="flex max-h-[88vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl glass-raised shadow-2xl shadow-black/40">
        <div className="sticky top-0 z-10 flex items-start justify-between border-b border-white/10 bg-obs-surface/70 backdrop-blur-xl px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-obs-text tracking-tight">Novo asset</h2>
            <p className="mt-1 text-xs text-obs-subtle">O arquivo entra como card pendente, conectado ao galho escolhido e ao Gallery.</p>
          </div>
          <button onClick={onClose} className="inline-flex h-8 w-8 items-center justify-center rounded-xl border border-white/[0.06] bg-white/[0.035] text-obs-subtle hover:bg-white/[0.07] hover:text-obs-text transition-colors" aria-label="Fechar">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {/* Persona */}
          <div>
            <label className="text-[10px] font-medium uppercase tracking-wide text-obs-faint">Cliente / Persona</label>
            <select
              value={personaId}
              onChange={(e) => setPersonaId(e.target.value)}
              className="mt-1 w-full rounded-xl border border-white/10 bg-white/[0.04] backdrop-blur-md px-3 py-2 text-sm text-obs-text focus:outline-none focus:border-obs-violet/50"
            >
              <option value="">Escolha...</option>
              {personas.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>

          {/* File picker / dropzone */}
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
            className="rounded-xl border border-dashed border-white/15 bg-white/[0.03] backdrop-blur-md p-6 text-center cursor-pointer hover:border-white/25 transition-colors"
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              accept="image/*,video/*,application/pdf,text/plain,text/markdown,.md,.txt"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) onPick(f); }}
            />
            {!file && (
              <>
                <Upload size={20} className="mx-auto text-obs-subtle mb-2" />
                <p className="text-sm text-obs-text">Solte um arquivo aqui ou clique para selecionar</p>
                <p className="mt-1 text-[11px] text-obs-faint">PNG, JPG, WEBP, MP4, MOV, PDF, TXT, MD</p>
              </>
            )}
            {file && (
              <div className="space-y-2">
                <p className="text-sm text-obs-text">{file.name}</p>
                <p className="text-[11px] text-obs-faint">{(file.size / 1024).toFixed(1)} KB · {file.type || "?"}</p>
                {preview && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={preview} alt={file.name} className="mx-auto mt-2 max-h-40 rounded-lg border border-white/10" />
                )}
              </div>
            )}
          </div>

          {/* Parent picker */}
          <div>
            <label className="text-[10px] font-medium uppercase tracking-wide text-obs-faint">Galho do grafo (parent)</label>
            <input
              type="text"
              value={parentQuery}
              onChange={(e) => setParentQuery(e.target.value)}
              placeholder="Filtrar por nome ou slug (brand, briefing, campanha, produto, copy, FAQ...)"
              className="mt-1 w-full rounded-xl border border-white/10 bg-white/[0.04] backdrop-blur-md px-3 py-2 text-sm text-obs-text placeholder:text-obs-faint focus:outline-none focus:border-obs-violet/50"
            />
            <div className="mt-2 max-h-56 overflow-y-auto rounded-xl border border-white/10 bg-white/[0.03] backdrop-blur-md">
              {parentsLoading && <p className="px-3 py-2 text-xs text-obs-subtle">Carregando galhos...</p>}
              {!parentsLoading && !personaSlug && <p className="px-3 py-2 text-xs text-obs-faint">Escolha uma persona para listar os galhos.</p>}
              {!parentsLoading && personaSlug && filteredParents.length === 0 && (
                <p className="px-3 py-2 text-xs text-obs-faint">Sem galhos compativeis encontrados.</p>
              )}
              {filteredParents.map((node) => {
                const slug = node.data?.slug || node.id;
                const selected = slug === parentSlug;
                return (
                  <button
                    key={node.id}
                    type="button"
                    onClick={() => setParentSlug(slug)}
                    className={`group block w-full px-3 py-2 text-left text-xs transition-colors ${
                      selected
                        ? "bg-obs-violet/15 text-obs-text"
                        : "text-obs-subtle hover:bg-white/[0.04] hover:text-obs-text"
                    }`}
                  >
                    <span className="font-medium">{node.data?.label || slug}</span>
                    <span className="ml-2 text-[10px] uppercase text-obs-faint">{node.data?.node_type}</span>
                    <span className="ml-2 font-mono text-[10px] text-obs-faint">{slug}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Asset function */}
          <div>
            <label className="text-[10px] font-medium uppercase tracking-wide text-obs-faint">Funcao do asset (opcional)</label>
            <select
              value={assetFunction}
              onChange={(e) => setAssetFunction(e.target.value)}
              className="mt-1 w-full rounded-xl border border-white/10 bg-white/[0.04] backdrop-blur-md px-3 py-2 text-sm text-obs-text focus:outline-none focus:border-obs-violet/50"
            >
              {ASSET_FUNCTIONS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
            </select>
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded-xl border border-red-300/35 bg-red-500/[0.18] px-3 py-2 text-xs text-red-50">
              <AlertCircle size={14} /> {error}
            </div>
          )}
        </div>

        <div className="sticky bottom-0 z-10 flex items-center justify-end gap-2 border-t border-white/10 bg-obs-surface/70 backdrop-blur-xl px-6 py-4">
          <button
            onClick={onClose}
            disabled={submitting}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-xs font-medium text-obs-subtle hover:bg-white/10 hover:border-white/20 hover:text-obs-text disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Cancelar
          </button>
          <button
            onClick={submit}
            disabled={submitting}
            className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-300/30 bg-emerald-500/15 px-4 py-2 text-xs font-medium text-emerald-50 shadow-sm shadow-emerald-500/10 backdrop-blur-md hover:bg-emerald-500/25 hover:border-emerald-300/50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {submitting ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle size={12} />}
            Enviar asset
          </button>
        </div>
      </div>
    </div>
  );
}
