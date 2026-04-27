"use client";
import { X, ExternalLink, Tag, User, Calendar } from "lucide-react";

const BASE = process.env.NEXT_PUBLIC_AI_BRAIN_URL || "http://localhost:8000";

const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "webp", "svg", "gif"]);
const VIDEO_EXTS = new Set(["mp4", "mov", "webm"]);

const STATUS_BADGE: Record<string, string> = {
  pending:        "bg-obs-amber/10 border-obs-amber/30 text-obs-amber",
  needs_persona:  "bg-obs-amber/10 border-obs-amber/30 text-obs-amber",
  needs_category: "bg-obs-amber/10 border-obs-amber/30 text-obs-amber",
  approved:       "bg-green-500/10 border-green-500/30 text-green-400",
  embedded:       "bg-obs-violet/10 border-obs-violet/30 text-obs-violet",
  rejected:       "bg-obs-rose/10 border-obs-rose/30 text-obs-rose",
};

interface NodeDrawerProps {
  node: any | null;
  onClose: () => void;
}

export default function NodeDrawer({ node, onClose }: NodeDrawerProps) {
  if (!node) return null;

  const d = node.data;
  const isPersona = node.type === "personaNode";
  const fileType = (d.file_type || "").toLowerCase();
  const isImage = IMAGE_EXTS.has(fileType);
  const isVideo = VIDEO_EXTS.has(fileType);
  const fileUrl = d.file_path
    ? `${BASE}/knowledge/file?path=${encodeURIComponent(d.file_path)}`
    : null;

  return (
    <div className="absolute top-0 right-0 h-full w-80 glass-raised border-l border-white/06 flex flex-col z-50 animate-slide-in-r shadow-2xl">
      {/* Header */}
      <div className="flex items-start justify-between px-5 pt-5 pb-4 sep">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            {isPersona ? (
              <span className="text-[10px] px-2 py-0.5 rounded-full border border-obs-violet/40 bg-obs-violet/10 text-obs-violet uppercase tracking-wide">
                Persona
              </span>
            ) : (
              <span className={`text-[10px] px-2 py-0.5 rounded-full border ${STATUS_BADGE[d.status] || STATUS_BADGE.pending}`}>
                {d.status}
              </span>
            )}
            {d.content_type && (
              <span className="text-[10px] text-obs-subtle">{d.content_type}</span>
            )}
          </div>
          <h3 className="text-sm font-semibold text-obs-text leading-tight">{d.label}</h3>
          {d.slug && (
            <p className="text-[11px] text-obs-subtle mt-0.5 font-mono">{d.slug}</p>
          )}
        </div>
        <button
          onClick={onClose}
          className="shrink-0 ml-2 p-1.5 rounded-lg hover:bg-white/5 text-obs-subtle hover:text-obs-text transition-colors"
        >
          <X size={14} />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {/* Persona description */}
        {isPersona && d.description && (
          <p className="text-sm text-obs-subtle leading-relaxed">{d.description}</p>
        )}

        {/* Media preview */}
        {isImage && fileUrl && (
          <div className="rounded-xl overflow-hidden border border-white/06 bg-obs-base">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={fileUrl}
              alt={d.label}
              className="w-full object-contain max-h-48"
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
            />
          </div>
        )}

        {isVideo && fileUrl && (
          <div className="rounded-xl overflow-hidden border border-white/06">
            <video
              src={fileUrl}
              controls
              className="w-full max-h-48"
              preload="metadata"
            />
          </div>
        )}

        {/* Content preview */}
        {d.content_preview && (
          <div>
            <p className="text-[10px] text-obs-subtle uppercase tracking-wide mb-1.5">Conteúdo</p>
            <pre className="text-xs text-obs-text/70 bg-obs-base rounded-lg p-3 border border-white/06 whitespace-pre-wrap overflow-y-auto max-h-40 font-mono leading-relaxed">
              {d.content_preview}
              {d.content_preview.length >= 200 && "…"}
            </pre>
          </div>
        )}

        {/* Metadata */}
        {!isPersona && (
          <div className="space-y-2">
            {d.status && (
              <div className="flex items-center gap-2 text-xs">
                <Tag size={11} className="text-obs-subtle shrink-0" />
                <span className="text-obs-subtle">Status:</span>
                <span className="text-obs-text">{d.status}</span>
              </div>
            )}
            {d.file_path && (
              <div className="flex items-start gap-2 text-xs">
                <ExternalLink size={11} className="text-obs-subtle shrink-0 mt-0.5" />
                <span className="text-obs-subtle font-mono break-all leading-relaxed">{d.file_path.split(/[\\/]/).slice(-2).join("/")}</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer actions */}
      <div className="px-5 py-4 sep space-y-2">
        {!isPersona && d.status === "pending" && (
          <a
            href="/knowledge/quality"
            className="flex items-center justify-center gap-2 w-full py-2 text-xs font-medium rounded-lg bg-obs-amber/10 border border-obs-amber/30 text-obs-amber hover:bg-obs-amber/20 transition-colors"
          >
            Revisar na Quality →
          </a>
        )}
        {isPersona && (
          <a
            href="/knowledge/graph"
            onClick={onClose}
            className="flex items-center justify-center gap-2 w-full py-2 text-xs font-medium rounded-lg glass border border-white/08 text-obs-subtle hover:text-obs-text transition-colors"
          >
            Fechar
          </a>
        )}
      </div>
    </div>
  );
}
