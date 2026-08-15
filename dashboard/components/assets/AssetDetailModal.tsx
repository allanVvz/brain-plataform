"use client";
import { useEffect, useMemo, useState } from "react";
import { X, Loader2, CheckCircle2, AlertTriangle, Link2, Maximize2, Trash2, Radio } from "lucide-react";
import { api } from "@/lib/api";

// asset_readings.reading_type — see api/services/asset_pipeline/schemas.py
const READING_LABEL: Record<string, string> = {
  transcription: "Transcrição",
  ocr: "OCR",
  ai_fallback: "Leitura visual",
  pdf_text: "Texto do PDF",
  video_mock: "Vídeo",
  classification: "Classificação",
  rename: "Nomeação",
};

interface AssetConnection {
  edge_id: string;
  relation_type: string;
  slot_key: string | null;
  page_section: string | null;
  label: string | null;
  position: number | null;
  role: string | null;
  parent_node: {
    id: string;
    slug: string | null;
    node_type: string | null;
    title: string | null;
    collection_slug: string | null;
  };
  slot_options: Array<{ slot_key: string; label: string }>;
}

interface LandingTarget {
  slot_key: string;
  slot_label: string;
  parent_node_type: string;
  target_slug: string | null;
  collection_slug: string | null;
  label: string;
  node_id: string;
}

const PARENT_TYPE_LABEL: Record<string, string> = {
  brand: "Brand",
  campaign: "Campanha",
  category: "Grupo de produto",
  product: "Produto",
};

const SELECT_CLASS =
  "mt-1 w-full rounded-md border border-white/15 bg-obs-base px-2 py-2 text-[12px] text-obs-text outline-none focus:border-obs-violet/50 disabled:opacity-60";

function bindBodyFor(connection: AssetConnection, slotKey: string) {
  const parentType = connection.parent_node.node_type || "";
  if (parentType === "campaign") {
    return {
      slot: slotKey,
      collection_slug: connection.parent_node.collection_slug || undefined,
    };
  }
  return {
    slot: slotKey,
    target_slug: connection.parent_node.slug || undefined,
  };
}

function targetKey(target: LandingTarget) {
  return `${target.slot_key}:${target.node_id}`;
}

interface Props {
  assetId: string;
  initialPreviewUrl?: string | null;
  mediaType?: "image" | "video" | "audio" | "pdf" | "document";
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
  const [connections, setConnections] = useState<AssetConnection[]>([]);
  const [connectionsLoading, setConnectionsLoading] = useState(false);
  const [busyEdgeId, setBusyEdgeId] = useState<string | null>(null);
  const [slotError, setSlotError] = useState<string | null>(null);
  const [targets, setTargets] = useState<LandingTarget[]>([]);
  const [selectedSlot, setSelectedSlot] = useState("");
  const [selectedTargetKey, setSelectedTargetKey] = useState("");
  const [pathSaving, setPathSaving] = useState(false);
  const [validatingPath, setValidatingPath] = useState(false);
  const [approving, setApproving] = useState(false);
  const [pathValidation, setPathValidation] = useState<{ ok: boolean; errors: string[] } | null>(null);
  const [deleting, setDeleting] = useState(false);

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

  async function loadConnections() {
    setConnectionsLoading(true);
    setSlotError(null);
    try {
      const payload = await api.assetConnections(assetId);
      setConnections(payload.connections || []);
    } catch (exc: any) {
      // Surface as inline slot section error; main asset load is independent.
      setSlotError(exc?.message || "Falha ao carregar conexoes.");
      setConnections([]);
    } finally {
      setConnectionsLoading(false);
    }
  }

  async function loadTargets() {
    try {
      const payload = await api.assetLandingTargets(assetId);
      setTargets(payload.targets || []);
    } catch {
      setTargets([]);
    }
  }

  useEffect(() => {
    load();
    loadConnections();
    loadTargets();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetId]);

  const slotChoices = useMemo(() => {
    const bySlot = new Map<string, string>();
    for (const target of targets) {
      if (!bySlot.has(target.slot_key)) bySlot.set(target.slot_key, target.slot_label);
    }
    return Array.from(bySlot.entries()).map(([slot_key, label]) => ({ slot_key, label }));
  }, [targets]);

  const targetChoices = useMemo(
    () => targets.filter((target) => target.slot_key === selectedSlot),
    [targets, selectedSlot],
  );

  useEffect(() => {
    const currentConnection = connections[0];
    if (!currentConnection || !targets.length || selectedSlot || selectedTargetKey) return;
    const currentSlot = currentConnection.slot_key || "";
    const currentTarget = targets.find(
      (target) => target.slot_key === currentSlot && target.node_id === currentConnection.parent_node.id,
    );
    if (currentSlot) setSelectedSlot(currentSlot);
    if (currentTarget) setSelectedTargetKey(targetKey(currentTarget));
  }, [connections, selectedSlot, selectedTargetKey, targets]);

  async function applyPath() {
    const target = targets.find((candidate) => targetKey(candidate) === selectedTargetKey);
    if (!target) return;
    setPathSaving(true);
    setSlotError(null);
    try {
      await api.assetRebindPath(assetId, {
        slot: target.slot_key,
        target_slug: target.target_slug,
        collection_slug: target.collection_slug,
        label: target.label,
        remove_existing: true,
      });
      await load();
      await loadConnections();
      setPathValidation(null);
      onChanged?.();
    } catch (exc: any) {
      setSlotError(exc?.message || "Falha ao alterar caminho do asset.");
    } finally {
      setPathSaving(false);
    }
  }

  async function validatePath() {
    setValidatingPath(true);
    setSlotError(null);
    try {
      const result = await api.assetValidatePath(assetId);
      setPathValidation({ ok: result.ok, errors: result.errors || [] });
      await loadConnections();
    } catch (exc: any) {
      setPathValidation({ ok: false, errors: [exc?.message || "Falha ao validar caminho."] });
    } finally {
      setValidatingPath(false);
    }
  }

  async function approveAsset() {
    setApproving(true);
    setError(null);
    setSlotError(null);
    try {
      const result = await api.assetApprove(assetId);
      setData((prev) => (prev ? { ...prev, asset: result.asset || prev.asset } : prev));
      setPathValidation({ ok: true, errors: [] });
      await load();
      await loadConnections();
      onChanged?.();
    } catch (exc: any) {
      setSlotError(exc?.message || "Falha ao aprovar asset.");
    } finally {
      setApproving(false);
    }
  }

  async function deleteAsset() {
    if (!window.confirm("Excluir este asset, o card de asset e todas as ligacoes do grafo?")) return;
    setDeleting(true);
    setError(null);
    try {
      await api.assetDelete(assetId);
      onChanged?.();
      onClose();
    } catch (exc: any) {
      setError(exc?.message || "Falha ao excluir asset.");
    } finally {
      setDeleting(false);
    }
  }

  async function changeSlot(connection: AssetConnection, nextSlotKey: string) {
    if (!nextSlotKey || nextSlotKey === connection.slot_key) return;
    setBusyEdgeId(connection.edge_id);
    setSlotError(null);
    try {
      if (connection.slot_key) {
        await api.assetUnbindSlot(
          assetId,
          connection.slot_key,
          connection.parent_node.slug,
        );
      }
      await api.assetBindSlot(assetId, bindBodyFor(connection, nextSlotKey));
      await loadConnections();
      onChanged?.();
    } catch (exc: any) {
      setSlotError(exc?.message || "Falha ao alterar slot.");
    } finally {
      setBusyEdgeId(null);
    }
  }

  async function removeConnection(connection: AssetConnection) {
    if (!connection.slot_key) return;
    setBusyEdgeId(connection.edge_id);
    setSlotError(null);
    try {
      await api.assetUnbindSlot(
        assetId,
        connection.slot_key,
        connection.parent_node.slug,
      );
      await loadConnections();
      onChanged?.();
    } catch (exc: any) {
      setSlotError(exc?.message || "Falha ao remover slot.");
    } finally {
      setBusyEdgeId(null);
    }
  }

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
  const assetMeta = asset?.metadata || {};
  // Ordered so the substantive readings (transcript, OCR, PDF text) come
  // first; classification and rename are bookkeeping.
  const readings = (data?.readings || []).filter(
    (r: any) => !["classification", "rename"].includes(r.reading_type),
  );
  const storagePath =
    assetMeta?.preview_bucket && assetMeta?.preview_path
      ? `${assetMeta.preview_bucket}:${assetMeta.preview_path}`
      : asset?.storage_bucket && asset?.storage_path
      ? `${asset.storage_bucket}:${asset.storage_path}`
      : null;
  // Private WhatsApp media goes through the persona-scoped /assets/{id}/media
  // route; public marketing assets keep using /knowledge/file.
  const fileUrl = api.assetFileUrl(asset)
    || initialPreviewUrl || assetMeta?.preview_url || asset?.url || null;
  const mt = mediaType
    || (asset?.type === "video" ? "video"
      : asset?.type === "image" ? "image"
      : asset?.type === "audio" ? "audio"
      : asset?.type === "pdf" ? "pdf"
      : "document");
  const inGraph = !!data?.graph?.in_graph;
  const primaryConnection = connections[0];
  const currentPathLabel = primaryConnection
    ? [
        PARENT_TYPE_LABEL[primaryConnection.parent_node.node_type || ""] ||
          primaryConnection.parent_node.node_type ||
          "Destino",
        primaryConnection.parent_node.title ||
          primaryConnection.parent_node.slug ||
          primaryConnection.parent_node.id.slice(0, 8),
      ].filter(Boolean).join(" - ")
    : "";
  const reasonLabel: Record<string, string> = {
    missing_node: "Sem node no grafo de conhecimento.",
    missing_gallery_edge: "Node existe, mas falta a conexao com Gallery.",
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 backdrop-blur-sm p-4">
      <div
        className="w-full max-w-5xl max-h-[92vh] flex flex-col rounded-2xl border border-white/12 shadow-xl shadow-black/40 text-obs-text"
        style={{ background: "rgba(15,18,28,0.97)" }}
      >
        <header className="flex items-center justify-between gap-3 border-b border-white/10 px-5 py-3">
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
            className="rounded-md border border-white/15 bg-white/5 px-2 py-1 text-obs-text hover:bg-white/10"
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
              ) : mt === "audio" && fileUrl ? (
                <div className="flex w-full flex-col items-center gap-3 p-6">
                  <Radio size={40} className="text-obs-teal" />
                  <audio src={fileUrl} controls preload="metadata" className="w-full max-w-md" />
                </div>
              ) : mt === "pdf" && fileUrl ? (
                <object data={fileUrl} type="application/pdf" className="h-[70vh] w-full">
                  {/* Browsers without an inline PDF viewer land here. */}
                  <div className="flex h-full flex-col items-center justify-center gap-2">
                    <span className="text-xs text-obs-subtle">Sem visualizador de PDF neste navegador.</span>
                    <a
                      href={fileUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-lg border border-obs-violet/40 bg-obs-violet/15 px-3 py-1.5 text-xs text-obs-violet"
                    >
                      <Maximize2 size={12} /> Abrir PDF
                    </a>
                  </div>
                </object>
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
                  ? "border-emerald-400/35 bg-emerald-500/10 text-emerald-100"
                  : "border-amber-400/35 bg-amber-500/10 text-amber-100"
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
                      className="mt-2 inline-flex items-center gap-1 rounded-md border border-amber-300/40 bg-amber-500/15 px-2.5 py-1 text-[11px] font-medium text-amber-100 hover:bg-amber-500/25 disabled:opacity-60"
                    >
                      <Link2 size={11} />
                      Criar node md e conectar ao Gallery
                    </button>
                  )}
                  {!inGraph && confirming && (
                    <div className="mt-2 rounded-md border border-amber-300/40 bg-amber-500/10 p-2 text-amber-100">
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
                          className="inline-flex items-center gap-1 rounded-md border border-emerald-300/40 bg-emerald-500/15 px-2 py-1 text-[11px] font-semibold text-emerald-100 hover:bg-emerald-500/25 disabled:opacity-60"
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
                          className="inline-flex items-center gap-1 rounded-md border border-white/20 bg-white/5 px-2 py-1 text-[11px] text-obs-text hover:bg-white/10"
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
              <div className="rounded-md border border-red-400/40 bg-red-500/10 px-3 py-2 text-[11px] text-red-100">
                {error}
              </div>
            )}
          </section>

          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-[12px] font-semibold uppercase tracking-wider text-obs-text">
                Classificacao e caminho
              </h3>
              {connectionsLoading && <Loader2 size={11} className="animate-spin text-obs-subtle" />}
            </div>
            <div className="rounded-xl border border-white/10 bg-white/[0.035] p-4">
              <div className="space-y-3">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-obs-subtle">Caminho ate Gallery / cardapio</p>
                    <span className={`rounded-full border px-2 py-0.5 text-[10px] ${
                      primaryConnection
                        ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-100"
                        : "border-amber-400/30 bg-amber-500/10 text-amber-100"
                    }`}>
                      {primaryConnection ? "definido" : "pendente"}
                    </span>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
                    <div>
                      <label className="block text-[10px] font-semibold uppercase tracking-wider text-obs-subtle">
                        Tipo de asset / posicao
                      </label>
                      <select
                        value={selectedSlot}
                        onChange={(e) => {
                          setSelectedSlot(e.target.value);
                          setSelectedTargetKey("");
                        }}
                        disabled={pathSaving || slotChoices.length === 0}
                        className={SELECT_CLASS}
                      >
                        <option value="">Selecionar...</option>
                        {slotChoices.map((slot) => (
                          <option key={slot.slot_key} value={slot.slot_key}>{slot.label}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-[10px] font-semibold uppercase tracking-wider text-obs-subtle">
                        Funcao / destino
                      </label>
                      <select
                        value={selectedTargetKey}
                        onChange={(e) => setSelectedTargetKey(e.target.value)}
                        disabled={pathSaving || !selectedSlot || targetChoices.length === 0}
                        className={SELECT_CLASS}
                      >
                        <option value="">Selecionar...</option>
                        {targetChoices.map((target) => (
                          <option key={targetKey(target)} value={targetKey(target)}>{target.label}</option>
                        ))}
                      </select>
                    </div>
                    <button
                      type="button"
                      onClick={applyPath}
                      disabled={!selectedTargetKey || pathSaving}
                      className="inline-flex items-center justify-center gap-1 rounded-md border border-emerald-300/35 bg-emerald-500/15 px-3 py-2 text-[12px] font-semibold text-emerald-100 hover:bg-emerald-500/25 disabled:opacity-50"
                    >
                      {pathSaving ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
                      Alterar
                    </button>
                  </div>
                  <div className="rounded-md border border-white/10 bg-black/15 px-3 py-2 text-[11px] text-obs-subtle">
                    {primaryConnection ? (
                      <>
                        Atual: <span className="text-obs-text">{currentPathLabel}</span>
                        {primaryConnection.slot_key && (
                          <span className="ml-2 font-mono text-obs-faint">{primaryConnection.slot_key}</span>
                        )}
                      </>
                    ) : (
                      "Escolha posicao e destino para criar o caminho deste asset."
                    )}
                  </div>
              </div>
            </div>
            {slotError && (
              <div className="rounded-md border border-red-400/40 bg-red-500/10 px-3 py-2 text-[11px] text-red-100">
                {slotError}
              </div>
            )}
            {pathValidation && (
              <div
                className={`rounded-md border px-3 py-2 text-[11px] ${
                  pathValidation.ok
                    ? "border-emerald-400/35 bg-emerald-500/10 text-emerald-100"
                    : "border-amber-400/35 bg-amber-500/10 text-amber-100"
                }`}
              >
                {pathValidation.ok ? (
                  "Caminho valido para catalogo/cardapio."
                ) : (
                  <span>{pathValidation.errors.join(" ")}</span>
                )}
              </div>
            )}
            {!connectionsLoading && connections.length === 0 && (
              <p className="text-[11px] text-obs-faint italic">
                Asset ainda nao esta ligado a nenhum destino de landing.
              </p>
            )}
            {false && connections.length > 0 && (
              <ul className="space-y-2">
                {connections.map((connection) => {
                  const parentType = connection.parent_node.node_type || "";
                  const typeLabel = PARENT_TYPE_LABEL[parentType] || parentType || "Parent";
                  const parentLabel =
                    connection.parent_node.title ||
                    connection.parent_node.slug ||
                    connection.parent_node.id.slice(0, 8);
                  const busy = busyEdgeId === connection.edge_id;
                  return (
                    <li
                      key={connection.edge_id}
                      className="rounded-lg border border-white/10 bg-white/[0.035] p-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3"
                    >
                      <div className="flex-1 min-w-0">
                        <p className="text-[10px] uppercase tracking-wider text-obs-subtle">
                          {typeLabel}
                        </p>
                        <p className="text-[13px] font-medium text-obs-text truncate">
                          {parentLabel}
                        </p>
                        <p className="text-[10px] font-mono text-obs-faint truncate">
                          {connection.slot_key || connection.relation_type}
                          {connection.parent_node.collection_slug ? ` · ${connection.parent_node.collection_slug}` : ""}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => removeConnection(connection)}
                        disabled={busy || !connection.slot_key}
                        className="inline-flex items-center justify-center gap-1 rounded-md border border-red-400/35 bg-red-500/10 px-2 py-1 text-[11px] text-red-100 hover:bg-red-500/20 disabled:opacity-50"
                        title="Remover este asset desta posicao"
                      >
                        {busy ? <Loader2 size={11} className="animate-spin" /> : <Trash2 size={11} />}
                        Remover
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          {/* Machine readings — transcription of a voice note, OCR of a
              photo, text pulled from a PDF. Fetched all along but never
              shown until now. */}
          {readings.length > 0 && (
            <section className="space-y-2">
              <h3 className="text-[12px] font-semibold uppercase tracking-wider text-obs-text">
                Leitura automática
              </h3>
              <div className="space-y-2">
                {readings.map((reading: any) => {
                  const body = (reading.extracted_text || reading.visual_summary || reading.summary || "").trim();
                  if (!body && !reading.metadata?.error) return null;
                  return (
                    <div
                      key={reading.id}
                      className="rounded-lg border border-white/10 bg-obs-raised p-3 space-y-1.5"
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] uppercase tracking-wide text-obs-teal">
                          {READING_LABEL[reading.reading_type] || reading.reading_type}
                        </span>
                        {reading.model_used && (
                          <span className="text-[10px] text-obs-faint">{reading.model_used}</span>
                        )}
                        {reading.metadata?.duration_seconds ? (
                          <span className="text-[10px] text-obs-faint">
                            {Math.round(reading.metadata.duration_seconds)}s
                          </span>
                        ) : null}
                        {reading.status === "failed" && (
                          <span className="text-[10px] text-obs-rose">falhou</span>
                        )}
                      </div>
                      {body ? (
                        <p className="whitespace-pre-wrap text-[12px] leading-relaxed text-obs-subtle">{body}</p>
                      ) : (
                        <p className="text-[11px] italic text-obs-faint">
                          {reading.metadata?.error || "Sem conteúdo extraído."}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          )}

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

        <footer className="border-t border-white/10 px-5 py-3 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={deleteAsset}
            disabled={deleting}
            className="mr-auto inline-flex items-center gap-1 rounded-md border border-red-400/35 bg-red-500/10 px-3 py-1.5 text-[12px] font-semibold text-red-100 hover:bg-red-500/20 disabled:opacity-60"
          >
            {deleting ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
            Excluir asset
          </button>
          <button
            type="button"
            onClick={validatePath}
            disabled={validatingPath}
            className="inline-flex items-center gap-1 rounded-md border border-white/15 px-3 py-1.5 text-[12px] text-obs-text hover:bg-white/10 disabled:opacity-60"
          >
            {validatingPath ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
            Validar caminho
          </button>
          <button
            type="button"
            onClick={approveAsset}
            disabled={approving}
            className="inline-flex items-center gap-1 rounded-md border border-emerald-300/35 bg-emerald-500/15 px-3 py-1.5 text-[12px] font-semibold text-emerald-100 hover:bg-emerald-500/25 disabled:opacity-60"
          >
            {approving ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
            Aprovar asset
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-white/15 px-3 py-1.5 text-[12px] text-obs-text hover:bg-white/10"
          >
            Fechar
          </button>
        </footer>
      </div>
    </div>
  );
}
