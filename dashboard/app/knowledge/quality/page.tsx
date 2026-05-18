"use client";
import { useEffect, useState } from "react";
import { api, API_URL, BASE } from "@/lib/api";
import {
  ChevronLeft, ChevronRight,
  CheckCircle, XCircle, Loader2,
} from "lucide-react";

interface KnowledgeItem {
  id: string; persona_id: string | null; content_type: string; title: string;
  content: string; status: string; file_path: string | null; file_type: string | null;
  tags: string[] | null; agent_visibility: string[] | null;
  asset_type: string | null; asset_function: string | null;
  metadata: Record<string, any>; created_at: string;
}
interface Persona { id: string; slug: string; name: string; }

const TYPE_OPTIONS = [
  "brand","briefing","product","campaign","copy","asset",
  "prompt","faq","maker_material","tone","competitor","audience","rule","other",
];
const ASSET_TYPES = [
  "background","foreground","logo","product","model",
  "banner","story","post","video","icon","other",
];
const ASSET_FUNCTIONS = [
  "maker_material","brand_reference","campaign_hero","copy_support","product_showcase","other",
];

const STATUS_META: Record<string, { label: string; badge: string; urgent?: boolean }> = {
  attention:      { label: "Atenção",       badge: "bg-obs-amber/10 border-obs-amber/30 text-obs-amber", urgent: true },
  needs_persona:  { label: "Sem persona",   badge: "bg-obs-amber/10 border-obs-amber/30 text-obs-amber" },
  needs_category: { label: "Sem categoria", badge: "bg-yellow-500/10 border-yellow-500/30 text-yellow-400" },
  pending:        { label: "Pendente",       badge: "bg-white/5 border-white/10 text-obs-subtle" },
  approved:       { label: "Aprovado",       badge: "bg-green-500/10 border-green-500/30 text-green-400" },
  embedded:       { label: "No Golden Dataset", badge: "bg-obs-violet/10 border-obs-violet/30 text-obs-violet" },
  rejected:       { label: "Rejeitado",      badge: "bg-obs-rose/10 border-obs-rose/30 text-obs-rose" },
};

const TABS = ["attention","needs_persona","needs_category","pending","approved","embedded","rejected"];
const IMAGE_EXTS = new Set(["png","jpg","jpeg","svg","gif","webp"]);
const VIDEO_EXTS = new Set(["mp4","mov","webm"]);

// ── helpers ────────────────────────────────────────────────────
function itemFileUrl(it: KnowledgeItem) {
  return it.file_path ? `${BASE}/knowledge/file?path=${encodeURIComponent(it.file_path)}` : null;
}
function itemIsImg(it: KnowledgeItem) { return IMAGE_EXTS.has((it.file_type || "").toLowerCase()); }
function itemIsVid(it: KnowledgeItem) { return VIDEO_EXTS.has((it.file_type || "").toLowerCase()); }

const SEL_INPUT = "bg-obs-raised border border-white/06 rounded-lg px-2.5 py-2 text-sm text-obs-text focus:outline-none focus:border-obs-violet/40 w-full";

export default function QualityPage() {
  const [items,         setItems]         = useState<KnowledgeItem[]>([]);
  const [personas,      setPersonas]      = useState<Persona[]>([]);
  const [counts,        setCounts]        = useState<any>({});
  const [filterStatus,  setFilterStatus]  = useState("attention");
  const [filterType,    setFilterType]    = useState("");
  const [filterPersona, setFilterPersona] = useState("");
  const [cursor,        setCursor]        = useState(0);
  const [loading,       setLoading]       = useState(false);
  const [processing,    setProcessing]    = useState(false);
  const [done,          setDone]          = useState(0);

  // ── multi-select ───────────────────────────────────────────
  const [selected,    setSelected]    = useState<Set<string>>(new Set());
  const [bulkPersona, setBulkPersona] = useState("");
  const [bulkType,    setBulkType]    = useState("");

  async function load() {
    setLoading(true);
    setCursor(0);
    setDone(0);
    setSelected(new Set());
    try {
      const [itemsData, personasData, countsData] = await Promise.all([
        api.knowledgeQueue(filterStatus, filterPersona || undefined, filterType || undefined),
        api.personas(),
        api.knowledgeCounts(),
      ]);
      setItems(itemsData);
      setPersonas(personasData);
      setCounts(countsData);
    } finally { setLoading(false); }
  }

  useEffect(() => { load(); }, [filterStatus, filterType, filterPersona]);

  // ── single-item navigation ─────────────────────────────────
  const safeIdx    = Math.min(cursor, Math.max(0, items.length - 1));
  const item       = items.length > 0 ? items[safeIdx] : null;
  const total      = items.length;
  const hasPrev    = safeIdx > 0;
  const hasNext    = safeIdx < total - 1;

  function advance() {
    setDone((d) => d + 1);
    setItems((prev) => prev.filter((_, i) => i !== safeIdx));
  }

  async function approveSingle() {
    if (!item) return;
    setProcessing(true);
    try { await api.approveItem(item.id, false); advance(); }
    catch (e) { console.error(e); }
    finally { setProcessing(false); }
  }

  async function rejectSingle() {
    if (!item) return;
    setProcessing(true);
    try { await api.rejectItem(item.id, ""); advance(); }
    catch (e) { console.error(e); }
    finally { setProcessing(false); }
  }

  async function updateSingle(data: Record<string, any>) {
    if (!item) return;
    await api.updateQueueItem(item.id, data);
    setItems((prev) => prev.map((it, i) => i === safeIdx ? { ...it, ...data } : it));
  }

  // ── multi-select actions ───────────────────────────────────
  const isMultiMode   = selected.size > 0;
  const selectedItems = items.filter((i) => selected.has(i.id));

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function selectAll() { setSelected(new Set(items.map((i) => i.id))); }
  function clearSelect() { setSelected(new Set()); setBulkPersona(""); setBulkType(""); }

  async function bulkApprove() {
    if (!selectedItems.length) return;
    setProcessing(true);
    try {
      const fields: Record<string, any> = {};
      if (bulkPersona) fields.persona_id = bulkPersona;
      if (bulkType)    fields.content_type = bulkType;
      if (Object.keys(fields).length) {
        await Promise.all(selectedItems.map((i) => api.updateQueueItem(i.id, fields)));
        setItems((prev) => prev.map((i) => selected.has(i.id) ? { ...i, ...fields } : i));
      }
      const approvable = selectedItems.filter((i) => i.persona_id || bulkPersona);
      for (const item of approvable) {
        await api.approveItem(item.id, false);
      }
      setItems((prev) => prev.filter((i) => !approvable.some((a) => a.id === i.id)));
      setDone((d) => d + approvable.length);
      clearSelect();
    } catch (e) { console.error(e); }
    finally { setProcessing(false); }
  }

  async function bulkReject() {
    if (!selectedItems.length) return;
    setProcessing(true);
    try {
      await Promise.all(selectedItems.map((i) => api.rejectItem(i.id, "")));
      setItems((prev) => prev.filter((i) => !selected.has(i.id)));
      setDone((d) => d + selectedItems.length);
      clearSelect();
    } catch (e) { console.error(e); }
    finally { setProcessing(false); }
  }

  // ── keyboard shortcuts (single mode only) ─────────────────
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (isMultiMode) {
        if (e.key === "Escape") clearSelect();
        return;
      }
      const tag = (e.target as HTMLElement)?.tagName ?? "";
      if (["INPUT","SELECT","TEXTAREA"].includes(tag)) return;
      if (e.key === "ArrowRight") { if (hasNext) setCursor((c) => c + 1); }
      if (e.key === "ArrowLeft")  { if (hasPrev) setCursor((c) => c - 1); }
      if (e.key === "Enter" && item?.persona_id) approveSingle();
      if (e.key === "r" && item)  rejectSingle();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [safeIdx, total, item, hasNext, hasPrev, isMultiMode]);

  // ── derived (single mode) ──────────────────────────────────
  const pName         = (id: string | null) => personas.find((p) => p.id === id)?.name ?? "—";
  const byStatus      = counts.by_status || {};
  const sessionTotal  = done + total;
  const progressPct   = sessionTotal > 0 ? (done / sessionTotal) * 100 : 0;
  const ft            = (item?.file_type || "").toLowerCase();
  const isImg         = IMAGE_EXTS.has(ft);
  const isVid         = VIDEO_EXTS.has(ft);
  const fileUrl       = item?.file_path && API_URL ? `${API_URL}/knowledge/file?path=${encodeURIComponent(item.file_path)}` : null;
  const statusMeta    = item ? (STATUS_META[item.status] ?? { badge: "border-white/10 text-obs-subtle", label: item.status }) : null;
  const needsAction   = ["pending","needs_persona","needs_category"].includes(item?.status ?? "");
  const canApprove    = needsAction && !!item?.persona_id;
  const canReject     = needsAction;
  const showPublishHint = item?.status === "approved" && item?.content_type === "faq";

  // ── bulk canApprove ────────────────────────────────────────
  const bulkCanApprove = selectedItems.some((i) => i.persona_id || bulkPersona);
  const bulkNeedsPersona = selectedItems.some((i) => !i.persona_id && !bulkPersona);

  return (
    <div className="space-y-4">

      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-obs-text">Curadoria em Série</h1>
          <p className="text-xs text-obs-subtle mt-0.5">
            {isMultiMode
              ? `${selected.size} item${selected.size > 1 ? "s" : ""} selecionado${selected.size > 1 ? "s" : ""} — ações aplicadas em lote`
              : "Revise um item por vez — aprovação e rejeição rápidas"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {done > 0 && (
            <span className="text-xs text-green-400 bg-green-500/8 border border-green-500/20 px-2.5 py-1 rounded-full">
              {done} revisado{done > 1 ? "s" : ""}
            </span>
          )}
          {isMultiMode && (
            <button onClick={clearSelect}
              className="text-xs glass border border-white/06 text-obs-subtle hover:text-obs-text px-3 py-1.5 rounded-lg transition-colors">
              × Limpar seleção
            </button>
          )}
          {!isMultiMode && total > 0 && (
            <button onClick={selectAll}
              className="text-xs glass border border-white/06 text-obs-subtle hover:text-obs-text px-3 py-1.5 rounded-lg transition-colors">
              Selecionar todos
            </button>
          )}
          <button onClick={load}
            className="text-xs glass border border-white/06 text-obs-subtle hover:text-obs-text px-3 py-1.5 rounded-lg transition-colors">
            Recarregar
          </button>
        </div>
      </div>

      {/* ── Status tabs + filters ── */}
      <div className="flex gap-1.5 flex-wrap items-center">
        {TABS.map((key) => {
          const meta  = STATUS_META[key] ?? { label: key, badge: "" };
          const count = byStatus[key] ?? 0;
          return (
            <button key={key} onClick={() => setFilterStatus(key)}
              className={`text-xs px-3 py-1.5 rounded-lg border transition-colors flex items-center gap-1.5 ${
                filterStatus === key
                  ? "bg-obs-violet/15 border-obs-violet/50 text-obs-violet"
                  : "glass border-white/06 text-obs-subtle hover:text-obs-text"}`}>
              {meta.urgent && count > 0 && <span className="w-1.5 h-1.5 rounded-full bg-obs-amber shrink-0" />}
              {meta.label}
              {count > 0 && (
                <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold border ${
                  meta.urgent && count > 0
                    ? "bg-obs-amber/15 text-obs-amber border-obs-amber/30"
                    : "bg-white/5 text-obs-subtle border-white/06"}`}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
        <div className="ml-auto flex gap-2">
          <select value={filterPersona} onChange={(e) => setFilterPersona(e.target.value)}
            className="bg-obs-base border border-white/06 rounded-lg px-2 py-1 text-xs text-obs-text focus:outline-none">
            <option value="">Todos</option>
            {personas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <select value={filterType} onChange={(e) => setFilterType(e.target.value)}
            className="bg-obs-base border border-white/06 rounded-lg px-2 py-1 text-xs text-obs-text focus:outline-none">
            <option value="">Todos tipos</option>
            {TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
      </div>

      {/* ── Loading ── */}
      {loading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 size={18} className="animate-spin text-obs-subtle" />
        </div>
      )}

      {/* ── Empty ── */}
      {!loading && total === 0 && (
        <div className="glass border border-white/06 rounded-2xl px-6 py-16 text-center space-y-2">
          {done > 0
            ? <><p className="text-obs-text font-medium">Fila concluída</p>
                <p className="text-obs-subtle text-sm">{done} item{done > 1 ? "s" : ""} revisado{done > 1 ? "s" : ""} nesta sessão.</p></>
            : <p className="text-obs-subtle text-sm">Nenhum item neste filtro.</p>}
        </div>
      )}

      {!loading && total > 0 && (
        <>
          {/* ── Progress ── */}
          <div className="flex items-center gap-3">
            <div className="flex-1 bg-obs-raised rounded-full h-1 overflow-hidden">
              <div className="h-full bg-obs-violet/50 rounded-full transition-all duration-500"
                style={{ width: `${Math.max(2, progressPct)}%` }} />
            </div>
            <span className="text-[10px] text-obs-faint font-mono shrink-0">
              {isMultiMode ? `${selected.size} sel · ${total} total` : `${safeIdx + 1} / ${total}`}
            </span>
          </div>

          {/* ══════════════════════════════════════════════════
              MULTI-SELECT CENTER — shown when items checked
          ══════════════════════════════════════════════════ */}
          {isMultiMode && (
            <div className="glass border border-obs-violet/20 rounded-2xl overflow-hidden">

              {/* Multi-header */}
              <div className="flex items-center gap-3 px-5 py-3.5 sep">
                <span className="text-sm font-semibold text-obs-text">
                  {selected.size} item{selected.size > 1 ? "s" : ""} selecionado{selected.size > 1 ? "s" : ""}
                </span>
                {bulkNeedsPersona && (
                  <span className="text-[10px] text-obs-amber bg-obs-amber/5 border border-obs-amber/15 rounded-full px-2 py-0.5">
                    Alguns sem persona — defina abaixo
                  </span>
                )}
              </div>

              <div className="grid grid-cols-5 divide-x divide-white/06">

                {/* Left — selected items horizontal scroll */}
                <div className="col-span-3 p-4">
                  <div
                    className="flex gap-3 overflow-x-auto pb-3"
                    style={{ scrollbarWidth: "thin", scrollbarColor: "rgba(255,255,255,0.12) transparent" }}
                  >
                    {selectedItems.map((it) => {
                      const itUrl = itemFileUrl(it);
                      const itImg = itemIsImg(it);
                      const itVid = itemIsVid(it);
                      const itMeta = STATUS_META[it.status] ?? { badge: "border-white/10 text-obs-subtle" };
                      return (
                        <div key={it.id}
                          className="shrink-0 glass border border-white/08 rounded-xl overflow-hidden flex flex-col"
                          style={{ width: 200 }}>

                          {/* Preview */}
                          <div className="bg-obs-raised flex items-center justify-center overflow-hidden"
                            style={{ height: 120 }}>
                            {itImg && itUrl
                              ? (/* eslint-disable-next-line @next/next/no-img-element */
                                <img src={itUrl} alt={it.title}
                                  className="w-full h-full object-cover"
                                  onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />)
                              : itVid && itUrl
                                ? <video src={itUrl} className="w-full h-full object-cover" preload="none" />
                                : <pre className="text-[9px] text-obs-text/50 p-2.5 w-full h-full overflow-hidden font-mono leading-relaxed">
                                    {(it.content || "").slice(0, 220)}
                                  </pre>
                            }
                          </div>

                          {/* Info + deselect */}
                          <div className="p-2.5 flex flex-col gap-1 flex-1">
                            <div className="flex items-center justify-between gap-1">
                              <span className={`text-[8px] px-1.5 py-0.5 rounded-full border font-medium ${itMeta.badge}`}>
                                {it.status}
                              </span>
                              <button
                                onClick={() => toggleSelect(it.id)}
                                className="text-[9px] text-obs-faint hover:text-obs-rose transition-colors leading-none"
                                title="Remover da seleção"
                              >×</button>
                            </div>
                            <p className="text-[10px] text-obs-violet font-mono">{it.content_type}</p>
                            <p className="text-xs text-obs-text font-medium truncate leading-snug">{it.title}</p>
                            <p className="text-[9px] text-obs-faint truncate">{pName(it.persona_id)}</p>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Right — bulk controls */}
                <div className="col-span-2 p-5 space-y-4">
                  <p className="text-[10px] text-obs-subtle uppercase tracking-wide">Aplicar a todos selecionados</p>

                  <div>
                    <label className="text-[10px] text-obs-faint block mb-1.5">Cliente</label>
                    <select value={bulkPersona} onChange={(e) => setBulkPersona(e.target.value)} className={SEL_INPUT}>
                      <option value="">— Manter atual —</option>
                      {personas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                  </div>

                  <div>
                    <label className="text-[10px] text-obs-faint block mb-1.5">Tipo</label>
                    <select value={bulkType} onChange={(e) => setBulkType(e.target.value)} className={SEL_INPUT}>
                      <option value="">— Manter atual —</option>
                      {TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
                    </select>
                  </div>

                  <div className="pt-2 space-y-2">
                    <button disabled={processing} onClick={bulkReject}
                      className="w-full flex items-center justify-center gap-1.5 text-xs bg-obs-rose/8 border border-obs-rose/30 text-obs-rose hover:bg-obs-rose/15 px-4 py-2 rounded-lg disabled:opacity-40 transition-colors">
                      {processing ? <Loader2 size={11} className="animate-spin" /> : <XCircle size={11} />}
                      Rejeitar {selected.size}
                    </button>

                    <button disabled={processing || !bulkCanApprove} onClick={bulkApprove}
                      title={!bulkCanApprove ? "Defina um cliente para os itens sem persona" : ""}
                      className="w-full flex items-center justify-center gap-1.5 text-xs bg-obs-violet/8 border border-obs-violet/30 text-obs-violet hover:bg-obs-violet/15 px-4 py-2 rounded-lg disabled:opacity-40 transition-colors">
                      {processing ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle size={11} />}
                      Aprovar {selected.size}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════
              SINGLE-ITEM CENTER — hidden in multi-select mode
          ══════════════════════════════════════════════════ */}
          {!isMultiMode && item && (
            <div className="glass border border-white/08 rounded-2xl overflow-hidden">

              {/* Card header */}
              <div className="flex items-center gap-3 px-5 py-3.5 sep">
                {statusMeta && (
                  <span className={`text-[10px] px-2 py-0.5 rounded-full border font-medium shrink-0 ${statusMeta.badge}`}>
                    {statusMeta.label}
                  </span>
                )}
                <span className="text-[10px] text-obs-violet font-mono shrink-0">{item.content_type}</span>
                <span className="text-sm font-semibold text-obs-text flex-1 truncate">{item.title}</span>
                <span className="text-xs text-obs-subtle shrink-0">{pName(item.persona_id)}</span>
                {item.file_path && (
                  <span className="text-[10px] text-obs-faint font-mono hidden lg:block shrink-0 max-w-[200px] truncate">
                    …/{item.file_path.split(/[\\/]/).slice(-1)[0]}
                  </span>
                )}
              </div>

              {/* Body: preview | controls */}
              <div className="grid grid-cols-5 divide-x divide-white/06 min-h-[280px]">

                {/* Left — content preview */}
                <div className="col-span-3 p-5 flex flex-col gap-3">
                  {isImg && fileUrl && (
                    <div className="flex justify-center bg-obs-raised border border-white/06 rounded-xl p-3 flex-1">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={fileUrl} alt={item.title}
                        className="max-h-64 max-w-full object-contain rounded-lg"
                        onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
                    </div>
                  )}
                  {isVid && fileUrl && (
                    <div className="rounded-xl overflow-hidden border border-white/06">
                      <video src={fileUrl} controls className="w-full max-h-64" preload="metadata" />
                    </div>
                  )}
                  {!isImg && !isVid && item.content && (
                    <pre className="flex-1 bg-obs-raised border border-white/06 rounded-xl p-4 text-xs text-obs-text/80 overflow-y-auto max-h-72 whitespace-pre-wrap font-mono leading-relaxed">
                      {item.content}
                    </pre>
                  )}
                  {!isImg && !isVid && !item.content && (
                    <div className="flex-1 flex items-center justify-center text-obs-faint text-xs">
                      Sem conteúdo de texto
                    </div>
                  )}
                </div>

                {/* Right — controls */}
                <div className="col-span-2 p-5 space-y-4">
                  <div>
                    <label className="text-[10px] text-obs-subtle block mb-1.5 uppercase tracking-wide">Cliente</label>
                    <select value={item.persona_id || ""} onChange={(e) => updateSingle({ persona_id: e.target.value || null })} className={SEL_INPUT}>
                      <option value="">Sem persona</option>
                      {personas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                  </div>

                  <div>
                    <label className="text-[10px] text-obs-subtle block mb-1.5 uppercase tracking-wide">Tipo</label>
                    <select value={item.content_type} onChange={(e) => updateSingle({ content_type: e.target.value })} className={SEL_INPUT}>
                      {TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
                    </select>
                  </div>

                  {item.content_type === "asset" && (
                    <>
                      <div>
                        <label className="text-[10px] text-obs-subtle block mb-1.5 uppercase tracking-wide">Tipo de asset</label>
                        <select value={item.asset_type || ""} onChange={(e) => updateSingle({ asset_type: e.target.value || null })} className={SEL_INPUT}>
                          <option value="">—</option>
                          {ASSET_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="text-[10px] text-obs-subtle block mb-1.5 uppercase tracking-wide">Função</label>
                        <select value={item.asset_function || ""} onChange={(e) => updateSingle({ asset_function: e.target.value || null })} className={SEL_INPUT}>
                          <option value="">—</option>
                          {ASSET_FUNCTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
                        </select>
                      </div>
                    </>
                  )}

                  <div>
                    <label className="text-[10px] text-obs-subtle block mb-1.5 uppercase tracking-wide">Agentes</label>
                    <div className="flex gap-1.5 flex-wrap">
                      {["SDR","Closer","Classifier","Maker"].map((agent) => {
                        const active = (item.agent_visibility || []).includes(agent);
                        return (
                          <button key={agent}
                            onClick={() => {
                              const cur = item.agent_visibility || [];
                              updateSingle({ agent_visibility: active ? cur.filter((a) => a !== agent) : [...cur, agent] });
                            }}
                            className={`text-[10px] px-2 py-0.5 rounded-full border transition-colors ${
                              active ? "bg-obs-violet/15 border-obs-violet/50 text-obs-violet" : "border-white/06 text-obs-faint hover:text-obs-subtle"}`}>
                            {agent}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {!item.persona_id && needsAction && (
                    <p className="text-[10px] text-obs-amber bg-obs-amber/5 border border-obs-amber/15 rounded-lg px-3 py-2">
                      Atribua um cliente para aprovar
                    </p>
                  )}
                </div>
              </div>

              {/* Actions footer */}
              <div className="sep px-5 py-4 flex items-center gap-2">
                <button onClick={() => setCursor((c) => c - 1)} disabled={!hasPrev} title="Anterior (←)"
                  className="p-2 rounded-lg glass border border-white/06 text-obs-subtle hover:text-obs-text disabled:opacity-25 transition-colors">
                  <ChevronLeft size={14} />
                </button>
                <button onClick={() => setCursor((c) => c + 1)} disabled={!hasNext} title="Próximo (→)"
                  className="p-2 rounded-lg glass border border-white/06 text-obs-subtle hover:text-obs-text disabled:opacity-25 transition-colors">
                  <ChevronRight size={14} />
                </button>
                <div className="flex-1" />
                {canReject && (
                  <button disabled={processing} onClick={rejectSingle} title="Rejeitar (R)"
                    className="flex items-center gap-1.5 text-xs bg-obs-rose/8 border border-obs-rose/30 text-obs-rose hover:bg-obs-rose/15 px-4 py-2 rounded-lg disabled:opacity-40 transition-colors">
                    {processing ? <Loader2 size={11} className="animate-spin" /> : <XCircle size={11} />} Rejeitar
                  </button>
                )}
                {canApprove && (
                  <button disabled={processing} onClick={approveSingle}
                    className="flex items-center gap-1.5 text-xs bg-obs-violet/8 border border-obs-violet/30 text-obs-violet hover:bg-obs-violet/15 px-4 py-2 rounded-lg disabled:opacity-40 transition-colors">
                    {processing ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle size={11} />} Aprovar
                  </button>
                )}
                {showPublishHint && (
                  <p className="text-[11px] text-obs-subtle">
                    Publique no Golden Dataset pelo grafo, conectando o FAQ aprovado ao node Embedded.
                  </p>
                )}
              </div>
            </div>
          )}

          {/* ── Queue strip with checkboxes + scrollbar ── */}
          {total > 0 && (
            <div
              className="flex gap-2 overflow-x-auto pb-2"
              style={{ scrollbarWidth: "thin", scrollbarColor: "rgba(255,255,255,0.14) transparent" }}
            >
              {items.map((it, idx) => {
                const isCurrent = !isMultiMode && idx === safeIdx;
                const isChecked = selected.has(it.id);
                return (
                  <div
                    key={it.id}
                    className={`shrink-0 rounded-xl border transition-colors overflow-hidden ${
                      isChecked
                        ? "border-obs-violet/50 bg-obs-violet/8"
                        : isCurrent
                          ? "border-obs-violet/30 bg-obs-violet/5"
                          : "glass border-white/06 hover:border-white/12"
                    }`}
                    style={{ minWidth: 148, maxWidth: 164 }}
                  >
                    {/* Checkbox row */}
                    <label
                      className="flex items-center gap-1.5 px-2.5 pt-2 pb-1 cursor-pointer select-none"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => toggleSelect(it.id)}
                        className="w-3 h-3 accent-obs-violet cursor-pointer shrink-0"
                      />
                      <span className="text-[8px] text-obs-violet font-mono truncate">{it.content_type}</span>
                    </label>

                    {/* Card body — click to navigate */}
                    <button
                      className="w-full text-left px-2.5 pb-2.5 space-y-0.5"
                      onClick={() => { setCursor(idx); if (isMultiMode) clearSelect(); }}
                    >
                      <div className="text-xs text-obs-text font-medium truncate">{it.title}</div>
                      <div className="text-[9px] text-obs-faint truncate">{pName(it.persona_id)}</div>
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          {/* Keyboard hints */}
          {!isMultiMode && (
            <div className="flex gap-5 text-[9px] text-obs-faint font-mono justify-center pb-1">
              <span>← → navegar</span>
              <span>R rejeitar</span>
              <span>Enter aprovar</span>
              <span>☐ selecionar para bulk</span>
            </div>
          )}
          {isMultiMode && (
            <div className="flex gap-5 text-[9px] text-obs-faint font-mono justify-center pb-1">
              <span>Esc limpar seleção</span>
            </div>
          )}
        </>
      )}
    </div>
  );
}
