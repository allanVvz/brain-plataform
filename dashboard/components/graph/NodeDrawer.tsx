"use client";
import { useState, useEffect } from "react";
import { X, Edit2, Save, CheckCircle, XCircle, Tag, Loader2, Crosshair } from "lucide-react";
import { api, BASE } from "@/lib/api";

const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "webp", "svg", "gif"]);
const VIDEO_EXTS = new Set(["mp4", "mov", "webm"]);

const STATUS_BADGE: Record<string, string> = {
  pending:        "bg-obs-amber/10 border-obs-amber/30 text-obs-amber",
  needs_persona:  "bg-obs-amber/10 border-obs-amber/30 text-obs-amber",
  needs_category: "bg-obs-amber/10 border-obs-amber/30 text-obs-amber",
  approved:       "bg-green-500/10 border-green-500/30 text-green-400",
  embedded:       "bg-obs-violet/10 border-obs-violet/30 text-obs-violet",
  rejected:       "bg-obs-rose/10 border-obs-rose/30 text-obs-rose",
  ATIVO:          "bg-green-500/10 border-green-500/30 text-green-400",
  INATIVO:        "bg-obs-rose/10 border-obs-rose/30 text-obs-rose",
};

const ALREADY_VALID = new Set(["ATIVO", "approved", "embedded"]);

interface NodeDrawerProps {
  node: any | null;
  onClose: () => void;
  onUpdated?: (itemId: string) => void;
  focusPath?: Array<{
    node_id: string;
    slug?: string;
    title?: string;
    node_type?: string;
    relation_type?: string | null;
    direction?: string | null;
  }>;
  onFocusHere?: () => void;
}

export default function NodeDrawer({ node, onClose, onUpdated, focusPath = [], onFocusHere }: NodeDrawerProps) {
  const [editing, setEditing]     = useState(false);
  const [fullItem, setFullItem]   = useState<any>(null);
  const [fetching, setFetching]   = useState(false);
  const [saving, setSaving]       = useState(false);
  const [flash, setFlash]         = useState<"ok" | "err" | null>(null);

  // Edit fields
  const [title,   setTitle]   = useState("");
  const [content, setContent] = useState("");
  const [tagsRaw, setTagsRaw] = useState("");
  const [tipo,    setTipo]    = useState("");

  // Fetch full item whenever the selected node changes
  useEffect(() => {
    if (!node || node.type === "personaNode" || !node.data?.item_id) {
      setFullItem(null);
      setEditing(false);
      return;
    }

    setFetching(true);
    setEditing(false);
    setFlash(null);

    const d = node.data;
    const fetchFn = d.source === "vault"
      ? api.kbEntry(d.item_id)
      : api.queueItem(d.item_id);

    fetchFn
      .then((item: any) => {
        setFullItem(item);
        setTitle(item.titulo   ?? item.title   ?? d.label ?? "");
        setContent(item.conteudo ?? item.content ?? "");
        setTagsRaw((item.tags  ?? d.tags ?? []).join(", "));
        setTipo(item.tipo ?? item.content_type ?? "");
      })
      .catch(() => setFullItem(null))
      .finally(() => setFetching(false));
  }, [node?.id]);

  if (!node) return null;

  const d          = node.data;
  const isPersona  = node.type === "personaNode";
  const isVault    = d.source === "vault";
  const isQueue    = d.source === "queue";
  const fileType   = (d.file_type || "").toLowerCase();
  const isImage    = IMAGE_EXTS.has(fileType);
  const isVideo    = VIDEO_EXTS.has(fileType);
  const fileUrl    = d.file_path
    ? `${BASE}/knowledge/file?path=${encodeURIComponent(d.file_path)}`
    : null;

  const currentStatus  = fullItem?.status ?? d.status;
  const tags: string[] = fullItem?.tags ?? d.tags ?? [];
  const displayContent = fullItem
    ? (fullItem.conteudo ?? fullItem.content ?? "")
    : (d.content_preview ?? "");

  const canEdit     = !isPersona && (isVault || isQueue);
  const canValidate = !isPersona && !ALREADY_VALID.has(currentStatus);
  const canReject   = !isPersona && isQueue && currentStatus !== "rejected";

  function showFlash(kind: "ok" | "err") {
    setFlash(kind);
    setTimeout(() => setFlash(null), 2500);
  }

  async function save() {
    if (!d.item_id) return;
    setSaving(true);
    try {
      const tagsArr = tagsRaw.split(",").map((t: string) => t.trim()).filter(Boolean);
      if (isVault) {
        await api.updateKbEntry(d.item_id, { titulo: title, conteudo: content, tipo, tags: tagsArr });
      } else {
        await api.updateQueueItem(d.item_id, { title, content, tags: tagsArr, content_type: tipo || undefined });
      }
      setEditing(false);
      showFlash("ok");
      onUpdated?.(d.item_id);
    } catch { showFlash("err"); }
    finally { setSaving(false); }
  }

  async function validate() {
    if (!d.item_id) return;
    setSaving(true);
    try {
      if (isVault) {
        await api.validateKbEntry(d.item_id);
      } else {
        await api.approveItem(d.item_id, true);
      }
      setFullItem((prev: any) => prev ? { ...prev, status: isVault ? "ATIVO" : "embedded" } : prev);
      showFlash("ok");
      onUpdated?.(d.item_id);
    } catch { showFlash("err"); }
    finally { setSaving(false); }
  }

  async function reject() {
    if (!d.item_id || !isQueue) return;
    setSaving(true);
    try {
      await api.rejectItem(d.item_id);
      setFullItem((prev: any) => prev ? { ...prev, status: "rejected" } : prev);
      showFlash("ok");
      onUpdated?.(d.item_id);
    } catch { showFlash("err"); }
    finally { setSaving(false); }
  }

  return (
    <div className="absolute top-0 right-0 h-full w-[340px] glass-raised border-l border-white/06 flex flex-col z-50 animate-slide-in-r shadow-2xl">

      {/* ── Header ── */}
      <div className="flex items-start justify-between px-5 pt-5 pb-4 sep">
        <div className="flex-1 min-w-0 space-y-1.5">

          {/* Badges row */}
          <div className="flex items-center gap-2 flex-wrap">
            {isPersona ? (
              <span className="text-[10px] px-2 py-0.5 rounded-full border border-obs-violet/40 bg-obs-violet/10 text-obs-violet uppercase tracking-wide">
                Persona
              </span>
            ) : (
              <span className={`text-[10px] px-2 py-0.5 rounded-full border ${STATUS_BADGE[currentStatus] || STATUS_BADGE.pending}`}>
                {currentStatus}
              </span>
            )}

            {!isPersona && d.content_type && (
              <span className="text-[10px] text-obs-subtle">{d.content_type}</span>
            )}

            {!isPersona && d.source && (
              <span className={`text-[9px] px-1.5 py-0.5 rounded border font-mono ${
                isVault
                  ? "border-obs-slate/30 bg-obs-slate/10 text-obs-slate"
                  : "border-white/10 text-obs-faint"
              }`}>
                {isVault ? "vault" : "queue"}
              </span>
            )}

            {typeof d.level === "number" && (
              <span
                className="text-[9px] px-1.5 py-0.5 rounded border font-mono"
                style={{
                  borderColor: `${d.color || "#94a3b8"}55`,
                  background: `${d.color || "#94a3b8"}14`,
                  color: d.color || "#94a3b8",
                }}
                title="Nivel semantico no registry"
              >
                L{d.level}
              </span>
            )}

            {typeof d.importance === "number" && (
              <span
                className="text-[9px] px-1.5 py-0.5 rounded border border-white/10 bg-white/5 text-obs-subtle font-mono"
                title="Importancia (0..1)"
              >
                imp {d.importance.toFixed(2)}
              </span>
            )}

            {typeof d.confidence === "number" && (
              <span
                className="text-[9px] px-1.5 py-0.5 rounded border border-white/10 bg-white/5 text-obs-subtle font-mono"
                title="Confianca (0..1)"
              >
                conf {d.confidence.toFixed(2)}
              </span>
            )}
          </div>

          {/* Title — editable in edit mode */}
          {editing ? (
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-obs-base border border-obs-violet/40 rounded px-2 py-1 text-sm font-semibold text-obs-text focus:outline-none focus:border-obs-violet"
            />
          ) : (
            <h3 className="text-sm font-semibold text-obs-text leading-tight">{d.label}</h3>
          )}

          {d.slug && (
            <p className="text-[11px] text-obs-subtle font-mono">{d.slug}</p>
          )}

          {typeof d.graph_distance === "number" && (
            <p className="text-[10px] text-obs-faint">distancia no grafo: {d.graph_distance}</p>
          )}
        </div>

        <div className="flex items-center gap-1 ml-3 shrink-0">
          {onFocusHere && !isPersona && (
            <button
              onClick={onFocusHere}
              title="Centralizar foco neste no"
              className="p-1.5 rounded-lg hover:bg-white/5 text-obs-subtle hover:text-obs-text transition-colors"
            >
              <Crosshair size={13} />
            </button>
          )}
          {canEdit && !editing && (
            <button
              onClick={() => setEditing(true)}
              title="Editar"
              className="p-1.5 rounded-lg hover:bg-white/5 text-obs-subtle hover:text-obs-text transition-colors"
            >
              <Edit2 size={13} />
            </button>
          )}
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/5 text-obs-subtle hover:text-obs-text transition-colors"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {/* ── Flash ── */}
      {flash && (
        <div className={`mx-4 mt-2 px-3 py-2 rounded-lg text-xs flex items-center gap-2 ${
          flash === "ok"
            ? "bg-green-500/10 border border-green-500/20 text-green-400"
            : "bg-obs-rose/10 border border-obs-rose/20 text-obs-rose"
        }`}>
          {flash === "ok" ? <CheckCircle size={11} /> : <XCircle size={11} />}
          {flash === "ok" ? "Salvo com sucesso" : "Erro ao salvar — tente novamente"}
        </div>
      )}

      {/* ── Body ── */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">

        {fetching && (
          <div className="flex items-center gap-2 text-xs text-obs-subtle">
            <Loader2 size={11} className="animate-spin" /> Carregando...
          </div>
        )}

        {/* Focus path breadcrumb (when this node is part of the active focus) */}
        {focusPath.length > 0 && focusPath.some((s) => s.node_id === (d?.item_id || node?.id?.replace(/^gn:/, ""))) && (
          <div>
            <p className="text-[10px] text-obs-subtle uppercase tracking-wide mb-1.5">Caminho desde a persona</p>
            <div className="flex items-center gap-1 flex-wrap text-[10px]">
              {focusPath.map((step, i) => (
                <span key={`${step.node_id}-${i}`} className="flex items-center gap-1">
                  {i > 0 && <span className="text-obs-faint">→</span>}
                  <span
                    className="px-1.5 py-0.5 rounded border truncate max-w-[140px]"
                    style={{
                      borderColor: i === focusPath.length - 1 ? "rgba(167,139,250,0.6)" : "rgba(255,255,255,0.10)",
                      color: i === focusPath.length - 1 ? "#a78bfa" : "rgba(255,255,255,0.6)",
                    }}
                    title={`${step.node_type}:${step.slug}${step.relation_type ? ` (${step.relation_type})` : ""}`}
                  >
                    {step.title || step.slug || step.node_type}
                  </span>
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Persona description */}
        {isPersona && d.description && (
          <p className="text-sm text-obs-subtle leading-relaxed">{d.description}</p>
        )}

        {/* Media preview (view mode only) */}
        {!editing && isImage && fileUrl && (
          <div className="rounded-xl overflow-hidden border border-white/06 bg-obs-base">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={fileUrl}
              alt={d.label}
              className="w-full object-contain max-h-40"
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
            />
          </div>
        )}
        {!editing && isVideo && fileUrl && (
          <div className="rounded-xl overflow-hidden border border-white/06">
            <video src={fileUrl} controls className="w-full max-h-40" preload="metadata" />
          </div>
        )}

        {/* Content */}
        {!isPersona && (
          <div>
            <p className="text-[10px] text-obs-subtle uppercase tracking-wide mb-1.5">Conteúdo</p>
            {editing ? (
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                rows={9}
                className="w-full bg-obs-base border border-white/10 rounded-lg px-3 py-2.5 text-xs text-obs-text focus:outline-none focus:border-obs-violet/50 resize-y font-mono leading-relaxed"
              />
            ) : (
              <pre className="text-xs text-obs-text/70 bg-obs-base rounded-lg p-3 border border-white/06 whitespace-pre-wrap overflow-y-auto max-h-48 font-mono leading-relaxed">
                {displayContent || <span className="text-obs-faint italic">Sem conteúdo</span>}
                {!fullItem && (displayContent?.length ?? 0) >= 200 && "…"}
              </pre>
            )}
          </div>
        )}

        {/* Focus path */}
        {!editing && focusPath.length > 0 && (
          <div>
            <p className="text-[10px] text-obs-subtle uppercase tracking-wide mb-1.5">
              Caminho semantico
            </p>
            <div className="space-y-1.5">
              {focusPath.map((step, idx) => (
                <div
                  key={`${step.node_id}-${idx}`}
                  className="rounded-lg border border-white/06 bg-white/3 px-2 py-1.5"
                >
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className="text-[10px] text-obs-faint">{idx + 1}</span>
                    <span className="text-[11px] text-obs-text truncate">
                      {step.title || step.slug || step.node_type || step.node_id}
                    </span>
                    {step.node_type && (
                      <span className="ml-auto shrink-0 rounded border border-white/10 px-1 py-0.5 text-[9px] uppercase text-obs-faint">
                        {step.node_type}
                      </span>
                    )}
                  </div>
                  {step.relation_type && (
                    <p className="mt-0.5 text-[10px] text-obs-faint truncate">
                      {step.relation_type}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Tags */}
        {!isPersona && (
          <div>
            <p className="text-[10px] text-obs-subtle uppercase tracking-wide mb-1.5 flex items-center gap-1.5">
              <Tag size={9} /> Tags
            </p>
            {editing ? (
              <input
                value={tagsRaw}
                onChange={(e) => setTagsRaw(e.target.value)}
                placeholder="tag1, tag2, tag3"
                className="w-full bg-obs-base border border-white/10 rounded-lg px-3 py-2 text-xs text-obs-text focus:outline-none focus:border-obs-violet/50"
              />
            ) : (
              <div className="flex flex-wrap gap-1.5 min-h-[20px]">
                {tags.length > 0 ? tags.map((t) => (
                  <span key={t} className="text-[10px] px-2 py-0.5 rounded-full bg-obs-slate/10 border border-obs-slate/20 text-obs-slate font-mono">
                    {t}
                  </span>
                )) : (
                  <span className="text-[10px] text-obs-faint italic">Sem tags</span>
                )}
              </div>
            )}
          </div>
        )}

        {/* Tipo — edit mode only */}
        {editing && !isPersona && (
          <div>
            <p className="text-[10px] text-obs-subtle uppercase tracking-wide mb-1.5">Tipo</p>
            <input
              value={tipo}
              onChange={(e) => setTipo(e.target.value)}
              className="w-full bg-obs-base border border-white/10 rounded-lg px-3 py-2 text-xs text-obs-text focus:outline-none focus:border-obs-violet/50"
            />
          </div>
        )}

        {/* File path — view mode */}
        {!editing && !isPersona && d.file_path && (
          <p className="text-[10px] text-obs-faint font-mono break-all leading-relaxed">
            {d.file_path.split(/[\\/]/).slice(-2).join("/")}
          </p>
        )}
      </div>

      {/* ── Footer actions ── */}
      <div className="px-5 py-4 sep space-y-2">

        {/* Edit mode controls */}
        {editing && (
          <div className="flex gap-2">
            <button
              onClick={() => setEditing(false)}
              disabled={saving}
              className="flex-1 py-2 text-xs rounded-lg glass border border-white/08 text-obs-subtle hover:text-obs-text transition-colors"
            >
              Cancelar
            </button>
            <button
              onClick={save}
              disabled={saving}
              className="flex-1 py-2 text-xs font-medium rounded-lg bg-obs-violet/80 hover:bg-obs-violet disabled:opacity-50 text-white transition-colors flex items-center justify-center gap-1.5"
            >
              {saving ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />}
              Salvar
            </button>
          </div>
        )}

        {/* View mode actions */}
        {!editing && !isPersona && (
          <>
            {canValidate && (
              <button
                onClick={validate}
                disabled={saving}
                className="w-full py-2 text-xs font-medium rounded-lg bg-green-600/80 hover:bg-green-500 disabled:opacity-50 text-white transition-colors flex items-center justify-center gap-1.5"
              >
                {saving ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle size={11} />}
                {isVault ? "Validar → ATIVO" : "Aprovar e promover à KB"}
              </button>
            )}

            {canReject && (
              <button
                onClick={reject}
                disabled={saving}
                className="w-full py-2 text-xs font-medium rounded-lg bg-obs-rose/10 border border-obs-rose/30 text-obs-rose hover:bg-obs-rose/20 disabled:opacity-50 transition-colors flex items-center justify-center gap-1.5"
              >
                {saving ? <Loader2 size={11} className="animate-spin" /> : <XCircle size={11} />}
                Rejeitar
              </button>
            )}
          </>
        )}

        {isPersona && (
          <button
            onClick={onClose}
            className="w-full py-2 text-xs rounded-lg glass border border-white/08 text-obs-subtle hover:text-obs-text transition-colors"
          >
            Fechar
          </button>
        )}
      </div>
    </div>
  );
}
