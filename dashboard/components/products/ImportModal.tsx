"use client";

import { useEffect, useState } from "react";
import { Loader2, Search, UploadCloud, X } from "lucide-react";
import { api } from "@/lib/api";
import { ShopifyAuditPanel, type AuditCollection } from "./ShopifyAuditPanel";

export type ImportProvider = "meta" | "csv" | "shopify" | "scraper";

const PROVIDERS: { key: ImportProvider; label: string; subtitle: string; primary?: boolean }[] = [
  { key: "meta", label: "Meta", subtitle: "Catalogo WhatsApp Business", primary: true },
  { key: "csv", label: "CSV", subtitle: "Arquivo CSV ou Excel", primary: true },
  { key: "shopify", label: "Shopify", subtitle: "Usar integracao ja existente" },
  { key: "scraper", label: "Scraper (Mock)", subtitle: "Importacao por scraping mockada" },
];

export function ImportModal({
  open,
  initialProvider,
  personaId,
  personaSlug,
  onClose,
  onImported,
}: {
  open: boolean;
  initialProvider: ImportProvider;
  personaId?: string;
  personaSlug?: string;
  onClose: () => void;
  onImported: () => void;
}) {
  const [provider, setProvider] = useState<ImportProvider>(initialProvider);
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [downloadImages, setDownloadImages] = useState(true);
  const [running, setRunning] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<any | null>(null);
  // Audit step (Shopify)
  const [collections, setCollections] = useState<AuditCollection[] | null>(null);
  const [selectedItems, setSelectedItems] = useState<any[]>([]);

  useEffect(() => {
    if (open) {
      setProvider(initialProvider);
      setFile(null);
      setUrl("");
      setDownloadImages(true);
      setError(null);
      setResult(null);
      setCollections(null);
      setSelectedItems([]);
    }
  }, [open, initialProvider]);

  if (!open) return null;

  const opts = { persona_id: personaId, persona_slug: personaSlug };

  async function preview() {
    setPreviewing(true);
    setError(null);
    try {
      if (!url.trim()) throw new Error("Informe a URL do catalogo Shopify.");
      const res = await api.previewImport("shopify", { ...opts, config: { url: url.trim() } });
      setCollections(res.collections || []);
    } catch (err: any) {
      setError(err?.message || "Falha ao pre-visualizar.");
    } finally {
      setPreviewing(false);
    }
  }

  async function runImport() {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      let res: any;
      if (provider === "csv") {
        if (!file) throw new Error("Selecione um arquivo CSV ou Excel.");
        res = await api.importProductsCsv(file, opts);
      } else if (provider === "shopify") {
        if (!collections) {
          await preview();
          return;
        }
        if (selectedItems.length === 0) throw new Error("Selecione ao menos um produto.");
        res = await api.importProducts("shopify", { ...opts, items: selectedItems, download_images: downloadImages });
      } else if (provider === "meta") {
        res = await api.importProducts("meta", { ...opts, config: {}, download_images: downloadImages });
      } else {
        res = await api.importProducts("scraper", { ...opts, config: {}, download_images: downloadImages });
      }
      if (res) {
        setResult(res);
        onImported();
      }
    } catch (err: any) {
      setError(err?.message || "Falha na importacao.");
    } finally {
      setRunning(false);
    }
  }

  const inAudit = provider === "shopify" && collections !== null;

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/55 p-5 backdrop-blur-sm" role="dialog" aria-label="Importar produtos">
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl glass-raised">
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-obs-text">Importar produtos</h2>
            <p className="text-[11px] text-obs-faint">Escolha a modalidade. Itens entram como pending ate aprovacao.</p>
          </div>
          <button type="button" onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 text-obs-subtle hover:text-obs-text" aria-label="Fechar">
            <X size={15} />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
          {!inAudit && (
            <div className="grid grid-cols-2 gap-2">
              {PROVIDERS.map((p) => (
                <button
                  key={p.key}
                  type="button"
                  aria-pressed={provider === p.key}
                  onClick={() => { setProvider(p.key); setCollections(null); setResult(null); }}
                  className={`rounded-lg border p-3 text-left transition ${
                    provider === p.key ? "border-obs-violet/45 bg-obs-violet/10" : "border-white/08 bg-white/[0.02] hover:border-white/15"
                  }`}
                >
                  <p className="text-sm font-medium text-obs-text">
                    {p.label}
                    {p.primary && <span className="ml-2 rounded-full bg-obs-violet/15 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-obs-violet">principal</span>}
                  </p>
                  <p className="mt-0.5 text-[11px] text-obs-subtle">{p.subtitle}</p>
                </button>
              ))}
            </div>
          )}

          {!inAudit && (
            <div className="rounded-lg border border-white/08 bg-white/[0.02] p-4">
              {provider === "meta" && (
                <p className="text-xs text-obs-subtle">
                  Usa a integracao <strong className="text-obs-text">Meta</strong> salva em Tools (Business ID, Catalog ID e Access Token).
                  Configure-a antes em <span className="font-mono">Tools → Meta</span>.
                </p>
              )}
              {provider === "csv" && (
                <div className="space-y-2">
                  <label className="block text-[10px] uppercase tracking-wide text-obs-faint">Arquivo CSV / Excel</label>
                  <input type="file" accept=".csv,.tsv,.xlsx,.xls,text/csv" onChange={(e) => setFile(e.target.files?.[0] || null)} className="lg-input w-full text-xs" aria-label="Arquivo CSV" />
                  <p className="text-[11px] text-obs-faint">Colunas suportadas: name, description, price, external_id, product_group, image_url, category.</p>
                </div>
              )}
              {provider === "shopify" && (
                <div className="space-y-2">
                  <label className="block text-[10px] uppercase tracking-wide text-obs-faint">URL do catalogo Shopify</label>
                  <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://loja.com/collections/all" className="lg-input w-full text-sm" />
                  <p className="text-[11px] text-obs-faint">Pre-visualize para auditar colecoes e produtos antes de importar.</p>
                </div>
              )}
              {provider === "scraper" && (
                <p className="text-xs text-obs-subtle">Scraper mockado: gera um conjunto fixo de produtos de exemplo para validar o fluxo.</p>
              )}
            </div>
          )}

          {inAudit && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-xs text-obs-subtle">
                  Encontramos <strong className="text-obs-text">{collections!.reduce((n, c) => n + c.count, 0)}</strong> produtos em{" "}
                  <strong className="text-obs-text">{collections!.length}</strong> colecoes. Selecione o que importar.
                </p>
                <button type="button" onClick={() => setCollections(null)} className="text-[11px] text-obs-violet hover:underline">trocar URL</button>
              </div>
              <ShopifyAuditPanel collections={collections!} onSelectionChange={setSelectedItems} />
            </div>
          )}

          {(provider === "shopify" || provider === "meta" || provider === "scraper") && (
            <label className="flex items-center gap-2 text-xs text-obs-subtle">
              <input type="checkbox" checked={downloadImages} onChange={(e) => setDownloadImages(e.target.checked)} className="h-4 w-4 accent-obs-violet" aria-label="Baixar imagens dos produtos" />
              Baixar imagens dos produtos (armazenar no Brain, alem da referencia de origem)
            </label>
          )}

          {error && <div className="rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">{error}</div>}
          {result && (
            <div className="rounded-lg border border-green-400/25 bg-green-400/05 px-3 py-2 text-xs text-green-300">
              Importacao concluida — criados: {result.created}, atualizados: {result.updated}, ignorados: {result.skipped}
              {typeof result.images_downloaded === "number" ? `, imagens baixadas: ${result.images_downloaded}` : ""} (total {result.total}).
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-white/10 px-5 py-4">
          <button type="button" onClick={onClose} className="lg-btn rounded-lg text-xs">Fechar</button>
          {provider === "shopify" && !inAudit ? (
            <button type="button" onClick={preview} disabled={previewing} className="lg-btn lg-btn-primary rounded-lg">
              {previewing ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />} Pre-visualizar
            </button>
          ) : (
            <button type="button" onClick={runImport} disabled={running} className="lg-btn lg-btn-primary rounded-lg">
              {running ? <Loader2 size={13} className="animate-spin" /> : <UploadCloud size={13} />}
              {inAudit ? ` Importar selecionados (${selectedItems.length})` : " Importar"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
