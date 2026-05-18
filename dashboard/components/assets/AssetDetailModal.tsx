"use client";
import { useEffect, useState } from "react";
import { X, Loader2, CheckCircle2, AlertTriangle, Link2, Maximize2 } from "lucide-react";
import { api, API_URL } from "@/lib/api";

interface Props {
  assetId: string;
  initialPreviewUrl?: string | null;
  mediaType?: "image" | "video" | "document";
  fileExt?: string | null;
  onClose: () => void;
  onChanged?: () => void;
}

interface GraphState {
  in_graph: boolean;
  reason: "ok" | "missing_node" | "missing_gallery_edge" | string;
  knowledge_node_id: string | null;
  gallery_edge_id: string | null;
  parent_node_id: string | null;
  parent_edge_id: string | null;
}

interface AssetDetailPayload {
  asset: any;
  readings: any[];
  markdown: string;
  graph: GraphState;
}

function renderAssetMarkdown(md: string) {
  // Minimal markdown renderer scoped to the schema produced by
  // compose_markdown in api/services/asset_pipeline/__init__.py.
  const blocks: { kind: "h1" | "h2" | "p"; text: string }[] = [];
  const lines = (md || "").replace(/\r\n/g, "\n").split("\n");
  let buffer: string[] = [];
  const flush = () => {
    if (!buffer.length) return;
    const text = buffer.join("\n").trim();
    if (text) blocks.push({ kind: "p", text });
    buffer = [];
  };
  for (const raw of lines) {
    const line = raw ?? "";
    if (line.startsWith("# ")) {
      flush();
      blocks.push({ kind: "h1", text: line.slice(2).trim() });
    } else if (line.startsWith("## ")) {
      flush();
      blocks.push({ kind: "h2", text: line.slice(3).trim() });
    } else {
      buffer.push(line);
    }
  }
  flush();
  return blocks.map((b, idx) => {
    if (b.kind === "h1") {
      return (
        <h2 key={idx} className="text-sm font-semibold text-obs-text mt-1 mb-1.5 break-words">
          {b.text}
        </h2>
      );
    }
    if (b.kind === "h2") {
      return (
        <h3 key={idx} className="text-[11px] font-semibold uppercase tracking-wider text-obs-subtle mt-3 mb-1">
          {b.text}
        </h3>
      );
    }
    return (
      <pre
        key={idx}
        className="whitespace-pre-wrap font-sans text-[12px] leading-relaxed text-obs-text bg-obs-base/60 border border-white/10 rounded-lg px-3 py-2"
      >
        {b.text}
      </pre>
    );
  });
}

export default function AssetDetailModal({
  assetId,
  initialPreviewUrl,
  mediaType,
  fileExt,
  onClose,
  onChanged,
}: Props) {
  const [data, setData] = useState<AssetDetailPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [ensuring, setEnsuring] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [imgZoom, setImgZoom] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const payload = await api.assetGet(assetId);
      setData(payload);
    } catch (exc: any) {
      setError(exc?.message || "Falha ao carregar asset.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetId]);

  async function ensureGallery() {
    if (!data) return;
    setEnsuring(true);
    setError(null);
    try {
      const result = await api.assetEnsureGallery(assetId);
      setData((prev) =>
        prev
          ? {
              ...prev,
              asset: result.asset || prev.asset,
              graph: result.graph || prev.graph,
              markdown: result.markdown || prev.markdown,
            }
          : prev,
      );
      setConfirming(false);
      onChanged?.();
    } catch (exc: any) {
      const msg = exc?.message || "";
      if (msg.includes("404") || /not found/i.test(msg)) {
        setError(
          "Endpoint /assets/{id}/ensure-gallery devolveu 404. Reinicie o backend (uvicorn) para carregar a rota nova e tente de novo.",
        );
      } else {
        setError(msg || "Falha ao conectar o asset ao grafo.");
      }
    } finally {
      setEnsuring(false);
    }
  }

  const asset = data?.asset;
  const storagePath =
    asset?.storage_bucket && asset?.storage_path
      ? `${asset.storage_bucket}:${asset.storage_path}`
      : null;
  const fileUrl = storagePath && API_URL
    ? `${API_URL}/knowledge/file?path=${encodeURIComponent(storagePath)}`
    : initialPreviewUrl || asset?.url || null;
  const mt = mediaType || (asset?.type === "video" ? "video" : asset?.type === "image" ? "image" : "document");
  const inGraph = !!data?.graph?.in_graph;
  const reasonLabel: Record<string, string> = {
    missing_node: "Sem node no grafo de conhecimento.",
    missing_gallery_edge: "Node existe, mas falta a conexao com Gallery.",
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 backdrop-blur-sm p-4">
      <div
        className="w-full max-w-5xl max-h-[92vh] flex flex-col rounded-2xl border border-white/15 shadow-xl"
        style={{ background: "rgba(255,255,255,0.97)" }}
      >
        <header className="flex items-center justify-between gap-3 border-b border-white/15 px-5 py-3">
          <div>
            <h2 className="text-sm font-semibold text-obs-text truncate max-w-[40rem]">
              {asset?.name || asset?.original_filename || "Asset"}
            </h2>
            <p className="text-[11px] text-obs-subtle">
              {asset?.type || "asset"} · {fileExt || asset?.mime_type || "?"} ·{" "}
              {asset?.created_at ? new Date(asset.created_at).toLocaleString() : ""}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-white/20 bg-obs-base px-2 py-1 text-obs-text hover:bg-white/10"
            aria-label="Fechar"
          >
            <X size={14} />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-5">
          <section className="space-y-3">
            <div
              className="relative rounded-xl border border-white/10 bg-obs-raised overflow-hidden flex items-center justify-center"
              style={{ minHeight: "20rem", maxHeight: "70vh" }}
            >
              {mt === "image" && fileUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={fileUrl}
                  alt={asset?.name || "asset"}
                  onClick={() => setImgZoom((v) => !v)}
                  className={`max-h-[70vh] w-auto h-auto cursor-zoom-in transition-transform ${
                    imgZoom ? "scale-150 cursor-zoom-out" : ""
                  }`}
                />
              ) : mt === "video" && fileUrl ? (
                <video src={fileUrl} controls className="max-h-[70vh] w-full" />
              ) : fileUrl ? (
                <a
                  href={fileUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-lg border border-obs-violet/40 bg-obs-violet/15 px-3 py-1.5 text-xs text-obs-violet"
                >
                  <Maximize2 size={12} /> Abrir arquivo
                </a>
              ) : (
                <span className="text-4xl font-mono text-obs-faint">.{(fileExt || "?").toLowerCase()}</span>
              )}
            </div>

            <div
              className={`rounded-lg border px-3 py-2 text-[12px] ${
                inGraph
                  ? "border-emerald-400/40 bg-emerald-500/8 text-emerald-700"
                  : "border-amber-400/40 bg-amber-500/10 text-amber-800"
              }`}
            >
              <div className="flex items-start gap-2">
                {inGraph ? (
                  <CheckCircle2 size={14} className="mt-0.5 shrink-0" />
                ) : (
                  <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                )}
                <div className="flex-1">
                  <p className="font-semibold">
                    {inGraph
                      ? "Está no grafo de conhecimento"
                      : "Não está no grafo de conhecimento"}
                  </p>
                  <p className="text-[11px] opacity-90 mt-0.5">
                    {inGraph
                      ? "Asset conectado a um galho do grafo e visível em Gallery."
                      : reasonLabel[data?.graph?.reason || ""] ||
                        "Asset existe no banco mas ainda não foi conectado ao grafo da Sofia."}
                  </p>
                  {!inGraph && !confirming && (
                    <button
                      type="button"
                      onClick={() => setConfirming(true)}
                      disabled={ensuring || loading}
                      className="mt-2 inline-flex items-center gap-1 rounded-md border border-amber-500/40 bg-amber-500/15 px-2.5 py-1 text-[11px] font-medium text-amber-800 hover:bg-amber-500/25 disabled:opacity-60"
                    >
                      <Link2 size={11} />
                      Criar node md e conectar ao Gallery
                    </button>
                  )}
                  {!inGraph && confirming && (
                    <div className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-amber-900">
                      <p className="text-[11px] font-medium">
                        Conectar este asset ao grafo da Sofia agora?
                      </p>
                      <p className="text-[10px] opacity-90 mt-0.5">
                        A Sofia vai criar um node md com o conteúdo deste asset e conectá-lo automaticamente na saída do Gallery da persona. Nada é apagado.
                      </p>
                      <div className="mt-2 flex gap-2">
                        <button
                          type="button"
                          onClick={ensureGallery}
                          disabled={ensuring}
                          className="inline-flex items-center gap-1 rounded-md border border-emerald-500/40 bg-emerald-500/15 px-2 py-1 text-[11px] font-semibold text-emerald-800 hover:bg-emerald-500/25 disabled:opacity-60"
                        >
                          {ensuring ? (
                            <Loader2 size={11} className="animate-spin" />
                          ) : (
                            <CheckCircle2 size={11} />
                          )}
                          Sim, conectar agora
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirming(false)}
                          disabled={ensuring}
                          className="inline-flex items-center gap-1 rounded-md border border-white/25 bg-obs-base px-2 py-1 text-[11px] text-obs-text hover:bg-white/15"
                        >
                          Cancelar
                        </button>
                      </div>
                    </div>
                  )}
                  {inGraph && data?.graph?.knowledge_node_id && (
                    <p className="text-[10px] font-mono mt-1 opacity-75">
                      node: {data.graph.knowledge_node_id.slice(0, 8)}… · edge:{" "}
                      {(data.graph.gallery_edge_id || "").slice(0, 8)}…
                    </p>
                  )}
                </div>
              </div>
            </div>

            {error && (
              <div className="rounded-md border border-red-400/40 bg-red-500/10 px-3 py-2 text-[11px] text-red-800">
                {error}
              </div>
            )}
          </section>

          <section className="space-y-2">
            <h3 className="text-[12px] font-semibold uppercase tracking-wider text-obs-text">
              Documento markdown
            </h3>
            {loading && (
              <div className="flex items-center gap-2 text-obs-subtle text-sm">
                <Loader2 size={12} className="animate-spin" /> carregando...
              </div>
            )}
            {!loading && data?.markdown && (
              <div className="space-y-0.5">{renderAssetMarkdown(data.markdown)}</div>
            )}
            {!loading && !data?.markdown && (
              <p className="text-[11px] text-obs-faint italic">
                Sem markdown associado a este asset.
              </p>
            )}
          </section>
        </div>

        <footer className="border-t border-white/15 px-5 py-3 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-white/20 px-3 py-1.5 text-[12px] text-obs-text hover:bg-white/10"
          >
            Fechar
          </button>
        </footer>
      </div>
    </div>
  );
}
