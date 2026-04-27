"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

const BASE = process.env.NEXT_PUBLIC_AI_BRAIN_URL || "http://localhost:8000";

const IMAGE_EXTS = new Set(["png","jpg","jpeg","svg","gif","webp"]);
const VIDEO_EXTS = new Set(["mp4","mov","webm"]);

interface KItem {
  id: string; title: string; status: string; content_type: string;
  asset_type: string | null; file_type: string | null; file_path: string | null;
  persona_id: string | null; created_at: string;
}
interface Persona { id: string; slug: string; name: string; }

const STATUS_BADGE: Record<string, string> = {
  pending:        "bg-obs-amber/10 border-obs-amber/30 text-obs-amber",
  needs_persona:  "bg-obs-amber/10 border-obs-amber/30 text-obs-amber",
  needs_category: "bg-obs-amber/10 border-obs-amber/30 text-obs-amber",
  approved:       "bg-green-500/10 border-green-500/30 text-green-400",
  embedded:       "bg-obs-violet/10 border-obs-violet/30 text-obs-violet",
  rejected:       "bg-obs-rose/10 border-obs-rose/30 text-obs-rose",
};

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

  async function load() {
    setLoading(true);
    try {
      const [data, personasData] = await Promise.all([
        api.knowledgeQueue("all" as any, filterPersona || undefined, "asset"),
        api.personas(),
      ]);
      setItems(data); setPersonas(personasData);
    } finally { setLoading(false); }
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
    if (filterStatus && item.status !== filterStatus) return false;
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
        <a href="/knowledge/capture"
          className="text-xs glass border border-white/06 text-obs-subtle hover:text-obs-text px-3 py-1.5 rounded-lg transition-colors">
          + Capturar
        </a>
      </div>

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
            <option value="pending">Pendente</option>
            <option value="approved">Aprovado</option>
            <option value="embedded">Na KB</option>
            <option value="rejected">Rejeitado</option>
          </select>
        </div>
      </div>

      {loading && <p className="text-obs-subtle text-sm">Carregando...</p>}

      {!loading && filtered.length === 0 && (
        <div className="glass border border-white/06 rounded-2xl px-6 py-16 text-center space-y-3">
          <p className="text-obs-subtle text-sm">Nenhum asset encontrado.</p>
          <a href="/knowledge/capture"
            className="inline-block text-xs bg-obs-violet/10 border border-obs-violet/30 text-obs-violet px-4 py-2 rounded-lg transition-colors hover:bg-obs-violet/20">
            Capturar material →
          </a>
        </div>
      )}

      {/* Grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-4">
        {filtered.map((item) => {
          const mt = mediaType(item);
          const ft = (item.file_type || "").toLowerCase();
          const fileUrl = item.file_path
            ? `${BASE}/knowledge/file?path=${encodeURIComponent(item.file_path)}`
            : null;
          const statusBadge = STATUS_BADGE[item.status] || "border-white/10 text-obs-subtle";
          const isPending = ["pending","needs_persona","needs_category"].includes(item.status);

          return (
            <div key={item.id} className="glass border border-white/06 rounded-2xl overflow-hidden group hover:border-white/12 transition-all">
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
                  <span className={`text-[9px] px-2 py-0.5 rounded-full border font-medium ${statusBadge}`}>
                    {item.status}
                  </span>
                  {mt === "video" && (
                    <span className="text-[9px] bg-obs-amber/80 text-obs-base px-2 py-0.5 rounded-full font-bold">▶ VIDEO</span>
                  )}
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
                  {pName(item.persona_id) && (
                    <span className="text-[9px] text-obs-violet bg-obs-violet/10 px-1.5 py-0.5 rounded">{pName(item.persona_id)}</span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
