"use client";

import { useEffect, useState } from "react";
import { Save, X } from "lucide-react";

export function ProductMdModal({
  product,
  onClose,
  onSave,
}: {
  product: any;
  onClose: () => void;
  onSave: (patch: { title: string; summary: string; tags: string[]; metadata: Record<string, any> }) => Promise<void>;
}) {
  const [title, setTitle] = useState(product?.title || "");
  const [summary, setSummary] = useState(product?.summary || "");
  const [tags, setTags] = useState((product?.tags || []).join(", "));
  const [metadata, setMetadata] = useState(JSON.stringify(product?.metadata || {}, null, 2));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTitle(product?.title || "");
    setSummary(product?.summary || "");
    setTags((product?.tags || []).join(", "));
    setMetadata(JSON.stringify(product?.metadata || {}, null, 2));
  }, [product]);

  if (!product) return null;

  async function save() {
    setSaving(true);
    setError(null);
    try {
      let parsed = {};
      try {
        parsed = metadata.trim() ? JSON.parse(metadata) : {};
      } catch {
        throw new Error("Metadata precisa ser JSON valido.");
      }
      await onSave({
        title,
        summary,
        tags: tags.split(",").map((tag: string) => tag.trim()).filter(Boolean),
        metadata: parsed,
      });
      onClose();
    } catch (err: any) {
      setError(err?.message || "Falha ao salvar.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/55 p-5 backdrop-blur-sm">
      <div className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl glass-raised">
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-obs-text">Card MD do produto</h2>
            <p className="text-[11px] text-obs-faint">{product.slug}</p>
          </div>
          <button type="button" onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 text-obs-subtle hover:text-obs-text" aria-label="Fechar">
            <X size={15} />
          </button>
        </div>
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-0 overflow-y-auto md:grid-cols-[420px_1fr]">
          <div className="space-y-3 border-b border-white/10 p-5 md:border-b-0 md:border-r">
            <label className="block text-[10px] uppercase tracking-wide text-obs-faint">Title</label>
            <input value={title} onChange={(e) => setTitle(e.target.value)} className="lg-input w-full text-sm" />
            <label className="block text-[10px] uppercase tracking-wide text-obs-faint">Summary</label>
            <textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={4} className="lg-input w-full text-sm" />
            <label className="block text-[10px] uppercase tracking-wide text-obs-faint">Tags</label>
            <input value={tags} onChange={(e) => setTags(e.target.value)} className="lg-input w-full text-sm" />
            <label className="block text-[10px] uppercase tracking-wide text-obs-faint">Metadata</label>
            <textarea value={metadata} onChange={(e) => setMetadata(e.target.value)} rows={9} className="code-surface w-full rounded-lg p-3 font-mono text-xs outline-none" />
          </div>
          <pre className="code-surface m-5 overflow-auto rounded-lg p-4 text-xs leading-relaxed whitespace-pre-wrap">{product.markdown}</pre>
        </div>
        <div className="flex items-center justify-between border-t border-white/10 px-5 py-4">
          {error ? <p className="text-xs text-red-400">{error}</p> : <span />}
          <button type="button" onClick={save} disabled={saving} className="lg-btn lg-btn-primary rounded-lg">
            <Save size={13} /> {saving ? "Salvando..." : "Salvar"}
          </button>
        </div>
      </div>
    </div>
  );
}
