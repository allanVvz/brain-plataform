"use client";
import { useEffect, useState } from "react";
import { Upload, Maximize2, X } from "lucide-react";
import { api, API_URL } from "@/lib/api";
import AssetUploadDialog from "@/components/assets/AssetUploadDialog";
import AssetDetailModal from "@/components/assets/AssetDetailModal";

const IMAGE_EXTS = new Set(["png","jpg","jpeg","svg","gif","webp"]);
const VIDEO_EXTS = new Set(["mp4","mov","webm"]);

interface KItem {
  id: string; title: string; status: string; content_type: string;
  asset_type: string | null; asset_function?: string | null; file_type: string | null; file_path: string | null;
  persona_id: string | null; created_at: string; source?: string; url?: string | null;
  approval_status?: string | null;
  landing_path?: any;
}
interface Persona { id: string; slug: string; name: string; }

const STATUS_BADGE: Record<string, string> = {
  pending:        "bg-obs-amber/10 border-obs-amber/30 text-obs-amber",
  needs_persona:  "bg-obs-amber/10 border-obs-amber/30 text-obs-amber",
  needs_category: "bg-obs-amber/10 border-obs-amber/30 text-obs-amber",
  pending_validation: "bg-obs-amber/10 border-obs-amber/30 text-obs-amber",
  approved:       "bg-green-500/10 border-green-500/30 text-green-400",
  ready:          "bg-green-500/10 border-green-500/30 text-green-400",
  reading:        "bg-obs-amber/10 border-obs-amber/30 text-obs-amber",
  embedded:       "bg-obs-violet/10 border-obs-violet/30 text-obs-violet",
  rejected:       "bg-obs-rose/10 border-obs-rose/30 text-obs-rose",
};

function effectiveStatus(row: any) {
  const approval = approvalStatus(row);
  if (approval === "approved" || approval === "rejected" || approval === "pending_validation" || approval === "context_only") {
    return approval;
  }
  return String(row?.workflow_status || row?.status || "pending_validation").toLowerCase();
}

function approvalStatus(row: any) {
  return String(row?.approval_status || row?.metadata?.validation_status || "").toLowerCase();
}

const FILTER_TYPES = [
  { value: "", label: "Todos" },
  { value: "image", label: "Imagens" },
  { value: "video", label: "Vídeos" },
  { value: "document", label: "Documentos" },
];

export default function AssetsPage() {
  const [items, setItems] = useState<KItem[]>([]);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [filterPersona, setFilterPersona] = useState("");
  const [filterMedia, setFilterMedia] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [detail, setDetail] = useState<{
    assetId: string;
    previewUrl: string | null;
    mediaType: "image" | "video" | "document";
    fileExt: string | null;
  } | null>(null);

  async function load() {
    setLoading(true);
    try {
      const [assetRows, personasData] = await Promise.all([
        api.assetList({ persona_id: filterPersona || undefined, limit: 200 }),
        api.personas(),
      ]);
      const merged = new Map<string, KItem>();
      for (const asset of assetRows || []) {
        const status = effectiveStatus(asset);
        const original = asset.original_filename || asset.name || "";
        const ext = original.includes(".") ? original.split(".").pop()?.toLowerCase() || "" : "";
        const mimeExt = typeof asset.mime_type === "string" && asset.mime_type.includes("/")
          ? asset.mime_type.split("/").pop()?.toLowerCase() || ""
          : "";
        const storagePath = asset.metadata?.preview_bucket && asset.metadata?.preview_path
          ? `${asset.metadata.preview_bucket}:${asset.metadata.preview_path}`
          : asset.storage_bucket && asset.storage_path
          ? `${asset.storage_bucket}:${asset.storage_path}`
          : null;
        merged.set(`asset:${asset.id}`, {
          id: asset.id,
          title: asset.name || original || "Asset",
          status,
          content_type: "asset",
          asset_type: asset.type || asset.metadata?.asset_type || asset.metadata?.kind || null,
          asset_function: asset.metadata?.asset_function || asset.landing_path?.asset_function || null,
          file_type: ext || mimeExt || null,
          file_path: storagePath,
          persona_id: asset.persona_id || null,
          created_at: asset.created_at || "",
          source: "asset",
          url: asset.metadata?.preview_url || asset.display_url || asset.url || null,
          landing_path: asset.landing_path || null,
          approval_status: approvalStatus(asset),
        });
      }
      setItems(Array.from(merged.values()));
      setPersonas(personasData || []);
    } finally { setLoading(false); }
  }

  async function deleteAsset(assetId: string) {
    if (!window.confirm("Excluir este asset, o card de asset e todas as ligacoes do grafo?")) return;
    await api.assetDelete(assetId);
    await load();
  }

  useEffect(() => { load(); }, [filterPersona]);

  const pName = (id: string | null) => personas.find((p) => p.id === id)?.name;

  function mediaType(item: KItem): "image" | "video" | "document" {
    const ft = (item.file_type || "").toLowerCase();
    if (IMAGE_EXTS.has(ft)) return "image";
    if (VIDEO_EXTS.has(ft)) return "video";
    return "document";
  }

  const filtered = items.filter((item) => {
    if (filterStatus === "pending" && !["pending_validation","pending","ready","reading"].includes(item.status)) return false;
    if (filterStatus && filterStatus !== "pending" && item.status !== filterStatus) return false;
    if (filterMedia === "image" && mediaType(item) !== "image") return false;
    if (filterMedia === "video" && mediaType(item) !== "video") return false;
    if (filterMedia === "document" && mediaType(item) !== "document") return false;
    return true;
  });

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-obs-text">Assets Visuais</h1>
          <p className="text-xs text-obs-subtle mt-0.5">Imagens, vídeos e documentos da base de conhecimento</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setUploadOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-obs-violet/35 bg-obs-violet/15 px-3 py-1.5 text-xs font-medium text-obs-text shadow-sm backdrop-blur-md hover:bg-obs-violet/25 hover:border-obs-violet/55 transition-colors"
          >
            <Upload size={12} /> Upload
          </button>
          <a href="/marketing/criacao"
            className="text-xs glass border border-white/06 text-obs-subtle hover:text-obs-text px-3 py-1.5 rounded-lg transition-colors">
            + Criar
          </a>
        </div>
      </div>

      <AssetUploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onUploaded={() => { load(); }}
        personas={personas}
        initialPersonaId={filterPersona || undefined}
      />

      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        {FILTER_TYPES.map(({ value, label }) => (
          <button key={value} onClick={() => setFilterMedia(value)}
            className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
              filterMedia === value ? "bg-obs-violet/15 border-obs-violet/50 text-obs-violet" : "glass border-white/06 text-obs-subtle hover:text-obs-text"}`}>
            {label}
          </button>
        ))}

        <div className="ml-auto flex gap-2">
          <select value={filterPersona} onChange={(e) => setFilterPersona(e.target.value)}
            className="bg-obs-base border border-white/06 rounded-lg px-2 py-1 text-xs text-obs-text focus:outline-none">
            <option value="">Todos clientes</option>
            {personas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}
            className="bg-obs-base border border-white/06 rounded-lg px-2 py-1 text-xs text-obs-text focus:outline-none">
            <option value="">Todos status</option>
            <option value="pending">Pendentes</option>
            <option value="pending_validation">Validacao pendente</option>
            <option value="ready">Ready</option>
            <option value="reading">Lendo</option>
            <option value="approved">Aprovado</option>
            <option value="embedded">No Golden Dataset</option>
            <option value="rejected">Rejeitado</option>
          </select>
        </div>
      </div>

      {loading && <p className="text-obs-subtle text-sm">Carregando...</p>}

      {!loading && filtered.length === 0 && (
        <div className="glass border border-white/06 rounded-2xl px-6 py-16 text-center space-y-3">
          <p className="text-obs-subtle text-sm">Nenhum asset encontrado.</p>
          <a href="/marketing/criacao"
            className="inline-block text-xs bg-obs-violet/10 border border-obs-violet/30 text-obs-violet px-4 py-2 rounded-lg transition-colors hover:bg-obs-violet/20">
            Criar material →
          </a>
        </div>
      )}

      {detail && (
        <AssetDetailModal
          assetId={detail.assetId}
          initialPreviewUrl={detail.previewUrl}
          mediaType={detail.mediaType}
          fileExt={detail.fileExt}
          onClose={() => setDetail(null)}
          onChanged={() => { load(); }}
        />
      )}

      {/* Grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-4">
        {filtered.map((item) => {
          const mt = mediaType(item);
          const ft = (item.file_type || "").toLowerCase();
          const fileUrl = item.file_path && API_URL
            ? `${API_URL}/knowledge/file?path=${encodeURIComponent(item.file_path)}`
            : item.url || null;
          const statusBadge = STATUS_BADGE[item.status] || "border-white/10 text-obs-subtle";
          const isPending = ["pending","pending_validation","ready","reading","needs_persona","needs_category"].includes(item.status);

          return (
            <div key={`${item.source || "item"}:${item.id}`} className="glass border border-white/06 rounded-2xl overflow-hidden group hover:border-white/12 transition-all">
              {/* Thumbnail */}
              <div className="aspect-square bg-obs-raised relative overflow-hidden">
                {mt === "image" && fileUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={fileUrl} alt={item.title}
                    className="w-full h-full object-cover"
                    onError={(e) => { (e.target as HTMLImageElement).src = ""; (e.target as HTMLImageElement).parentElement!.classList.add("bg-obs-raised"); }} />
                ) : mt === "video" && fileUrl ? (
                  <video src={fileUrl} className="w-full h-full object-cover" preload="metadata" muted playsInline />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <span className="text-4xl font-mono text-obs-faint">.{ft || "?"}</span>
                  </div>
                )}

                {/* Overlay badges */}
                <div className="absolute top-2 left-2 right-2 flex items-start justify-between">
                  <div className="flex items-center gap-1">
                    {item.source !== "queue" && (
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          deleteAsset(item.id).catch(() => {});
                        }}
                        title="Excluir asset"
                        className="inline-flex h-6 w-6 items-center justify-center rounded-md border border-red-400/50 bg-black/80 text-red-100 transition-colors hover:bg-red-600 hover:text-white"
                      >
                        <X size={12} />
                      </button>
                    )}
                    <span className={`text-[9px] px-2 py-0.5 rounded-full border font-medium ${statusBadge}`}>
                      {item.status}
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    {mt === "video" && (
                      <span className="text-[9px] bg-obs-amber/80 text-obs-base px-2 py-0.5 rounded-full font-bold">▶ VIDEO</span>
                    )}
                    <button
                      type="button"
                      onClick={() =>
                        setDetail({
                          assetId: item.id,
                          previewUrl: fileUrl,
                          mediaType: mt,
                          fileExt: ft || null,
                        })
                      }
                      title="Expandir e ver markdown"
                      className="inline-flex items-center justify-center rounded-md border border-black/70 px-1.5 py-0.5 transition-colors"
                      style={{ background: "rgba(0,0,0,0.85)", color: "#fff" }}
                    >
                      <Maximize2 size={11} />
                    </button>
                  </div>
                </div>

                {/* Pending shortcut */}
                {isPending && (
                  <div className="absolute bottom-2 left-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <a href="/knowledge/quality"
                      className="block text-center text-[10px] bg-obs-amber/80 text-obs-base font-semibold py-1.5 rounded-lg">
                      Revisar agora →
                    </a>
                  </div>
                )}
              </div>

              {/* Info */}
              <div className="px-3 py-2.5 space-y-1">
                <p className="text-xs font-medium text-obs-text truncate">{item.title}</p>
                <div className="flex items-center gap-1.5">
                  {item.asset_type && (
                    <span className="text-[9px] text-obs-subtle bg-white/5 px-1.5 py-0.5 rounded">{item.asset_type}</span>
                  )}
                  {item.asset_function && (
                    <span className="text-[9px] text-obs-subtle bg-white/5 px-1.5 py-0.5 rounded">{item.asset_function}</span>
                  )}
                  {pName(item.persona_id) && (
                    <span className="text-[9px] text-obs-violet bg-obs-violet/10 px-1.5 py-0.5 rounded">{pName(item.persona_id)}</span>
                  )}
                </div>
                <p className="text-[9px] text-obs-faint truncate">
                  {item.landing_path
                    ? `${item.landing_path.slot_label || item.landing_path.slot_key} -> ${item.landing_path.label || item.landing_path.target_slug || "destino"}`
                    : "sem caminho de catalogo"}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
