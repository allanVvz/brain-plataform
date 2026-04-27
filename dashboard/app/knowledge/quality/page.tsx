"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ExternalLink, ChevronDown, ChevronUp } from "lucide-react";

const BASE = process.env.NEXT_PUBLIC_AI_BRAIN_URL || "http://localhost:8000";

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
const ASSET_TYPES = ["background","logo","product","model","banner","story","post","video","icon","other"];
const ASSET_FUNCTIONS = ["maker_material","brand_reference","campaign_hero","copy_support","product_showcase","other"];

const STATUS_META: Record<string, { label: string; badge: string; urgent?: boolean }> = {
  attention:      { label: "Atenção",         badge: "bg-obs-amber/10 border-obs-amber/30 text-obs-amber",     urgent: true },
  needs_persona:  { label: "Sem persona",     badge: "bg-obs-amber/10 border-obs-amber/30 text-obs-amber" },
  needs_category: { label: "Sem categoria",   badge: "bg-yellow-500/10 border-yellow-500/30 text-yellow-400" },
  pending:        { label: "Pendente",         badge: "bg-white/5 border-white/10 text-obs-subtle" },
  approved:       { label: "Aprovado",         badge: "bg-green-500/10 border-green-500/30 text-green-400" },
  embedded:       { label: "Na KB",            badge: "bg-obs-violet/10 border-obs-violet/30 text-obs-violet" },
  rejected:       { label: "Rejeitado",        badge: "bg-obs-rose/10 border-obs-rose/30 text-obs-rose" },
};

const IMAGE_EXTS = new Set(["png","jpg","jpeg","svg","gif","webp"]);
const VIDEO_EXTS = new Set(["mp4","mov","webm"]);

export default function QualityPage() {
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [counts, setCounts] = useState<any>({});
  const [filterStatus, setFilterStatus] = useState("attention");
  const [filterType, setFilterType] = useState("");
  const [filterPersona, setFilterPersona] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [processing, setProcessing] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      const [itemsData, personasData, countsData] = await Promise.all([
        api.knowledgeQueue(filterStatus, filterPersona || undefined, filterType || undefined),
        api.personas(),
        api.knowledgeCounts(),
      ]);
      setItems(itemsData); setPersonas(personasData); setCounts(countsData);
    } finally { setLoading(false); }
  }

  useEffect(() => { load(); }, [filterStatus, filterType, filterPersona]);

  async function approve(id: string, toKb = false) {
    setProcessing(id);
    try { await api.approveItem(id, toKb); setItems((p) => p.filter((i) => i.id !== id)); }
    finally { setProcessing(null); }
  }

  async function reject(id: string) {
    const reason = prompt("Motivo (opcional):") ?? "";
    setProcessing(id);
    try { await api.rejectItem(id, reason); setItems((p) => p.filter((i) => i.id !== id)); }
    finally { setProcessing(null); }
  }

  async function updateItem(id: string, data: Record<string, any>) {
    await api.updateQueueItem(id, data);
    setItems((p) => p.map((i) => i.id === id ? { ...i, ...data } : i));
  }

  const pName = (id: string | null) => personas.find((p) => p.id === id)?.name || "—";
  const byStatus = counts.by_status || {};

  const tabs = ["attention","needs_persona","needs_category","pending","approved","embedded","rejected"];

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-obs-text">Curadoria de Conhecimento</h1>
          <p className="text-xs text-obs-subtle mt-0.5">Revise, edite e publique materiais na KB</p>
        </div>
        <div className="flex items-center gap-2">
          <a href="/knowledge/capture"
            className="text-xs glass border border-white/06 text-obs-subtle hover:text-obs-text px-3 py-1.5 rounded-lg transition-colors">
            + Capturar
          </a>
          <button onClick={load}
            className="text-xs glass border border-white/06 text-obs-subtle hover:text-obs-text px-3 py-1.5 rounded-lg transition-colors">
            Atualizar
          </button>
        </div>
      </div>

      {/* Status tabs */}
      <div className="flex gap-1.5 flex-wrap">
        {tabs.map((key) => {
          const meta = STATUS_META[key] || { label: key, badge: "" };
          const count = byStatus[key] ?? 0;
          return (
            <button key={key} onClick={() => setFilterStatus(key)}
              className={`text-xs px-3 py-1.5 rounded-lg border transition-colors flex items-center gap-1.5 ${
                filterStatus === key ? "bg-obs-violet/15 border-obs-violet/50 text-obs-violet" : "glass border-white/06 text-obs-subtle hover:text-obs-text"}`}>
              {meta.urgent && count > 0 && <span className="w-1.5 h-1.5 rounded-full bg-obs-amber shrink-0" />}
              {meta.label}
              {count > 0 && (
                <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold border ${
                  meta.urgent && count > 0 ? "bg-obs-amber/15 text-obs-amber border-obs-amber/30" : "bg-white/5 text-obs-subtle border-white/06"}`}>
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

      {loading && <p className="text-obs-subtle text-sm">Carregando...</p>}
      {!loading && items.length === 0 && (
        <div className="glass border border-white/06 rounded-2xl px-6 py-12 text-center">
          <p className="text-obs-subtle text-sm">Nenhum item neste filtro.</p>
        </div>
      )}

      <div className="space-y-2">
        {items.map((item) => {
          const ft = (item.file_type || "").toLowerCase();
          const isImg = IMAGE_EXTS.has(ft);
          const isVid = VIDEO_EXTS.has(ft);
          const fileUrl = item.file_path ? `${BASE}/knowledge/file?path=${encodeURIComponent(item.file_path)}` : null;
          const isOpen = expanded === item.id;
          const statusMeta = STATUS_META[item.status] || { badge: "border-white/10 text-obs-subtle" };

          return (
            <div key={item.id} className={`glass border rounded-2xl overflow-hidden transition-all ${isOpen ? "border-obs-violet/30" : "border-white/06"}`}>
              {/* Row */}
              <div className="px-4 py-3 flex items-center gap-3 cursor-pointer hover:bg-white/3 transition-colors"
                onClick={() => setExpanded(isOpen ? null : item.id)}>
                <span className={`text-[10px] px-2 py-0.5 rounded-full border font-medium shrink-0 ${statusMeta.badge}`}>
                  {item.status}
                </span>
                <span className="text-[10px] text-obs-violet font-mono shrink-0">{item.content_type}</span>
                <span className="text-sm text-obs-text font-medium flex-1 truncate">{item.title}</span>
                <span className="text-xs text-obs-subtle shrink-0">{pName(item.persona_id)}</span>
                {item.file_path && (
                  <span className="text-xs text-obs-faint font-mono hidden lg:block shrink-0">
                    {item.file_path.split(/[\\/]/).slice(-2).join("/")}
                  </span>
                )}
                {isOpen ? <ChevronUp size={13} className="text-obs-subtle shrink-0" /> : <ChevronDown size={13} className="text-obs-subtle shrink-0" />}
              </div>

              {/* Expanded */}
              {isOpen && (
                <div className="sep bg-obs-base/60 p-4 space-y-4 animate-fade-in">
                  {/* Media preview */}
                  {isImg && fileUrl && (
                    <div className="flex justify-center bg-obs-raised border border-white/06 rounded-xl p-2">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={fileUrl} alt={item.title}
                        className="max-h-56 max-w-full object-contain rounded-lg"
                        onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
                    </div>
                  )}
                  {isVid && fileUrl && (
                    <div className="rounded-xl overflow-hidden border border-white/06">
                      <video src={fileUrl} controls className="w-full max-h-56" preload="metadata" />
                    </div>
                  )}

                  {/* Editable fields */}
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-[10px] text-obs-subtle block mb-1 uppercase tracking-wide">Cliente</label>
                      <select value={item.persona_id || ""} onChange={(e) => updateItem(item.id, { persona_id: e.target.value || null })}
                        className="w-full bg-obs-raised border border-white/06 rounded-lg px-2 py-1.5 text-sm text-obs-text focus:outline-none focus:border-obs-violet/40">
                        <option value="">Sem persona</option>
                        {personas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="text-[10px] text-obs-subtle block mb-1 uppercase tracking-wide">Tipo</label>
                      <select value={item.content_type} onChange={(e) => updateItem(item.id, { content_type: e.target.value })}
                        className="w-full bg-obs-raised border border-white/06 rounded-lg px-2 py-1.5 text-sm text-obs-text focus:outline-none focus:border-obs-violet/40">
                        {TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
                      </select>
                    </div>
                  </div>

                  {item.content_type === "asset" && (
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-[10px] text-obs-subtle block mb-1 uppercase tracking-wide">Tipo de asset</label>
                        <select value={item.asset_type || ""} onChange={(e) => updateItem(item.id, { asset_type: e.target.value || null })}
                          className="w-full bg-obs-raised border border-white/06 rounded-lg px-2 py-1.5 text-sm text-obs-text focus:outline-none focus:border-obs-violet/40">
                          <option value="">—</option>
                          {ASSET_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                        </select>
                      </div>
                      <div>
                        <label className="text-[10px] text-obs-subtle block mb-1 uppercase tracking-wide">Função</label>
                        <select value={item.asset_function || ""} onChange={(e) => updateItem(item.id, { asset_function: e.target.value || null })}
                          className="w-full bg-obs-raised border border-white/06 rounded-lg px-2 py-1.5 text-sm text-obs-text focus:outline-none focus:border-obs-violet/40">
                          <option value="">—</option>
                          {ASSET_FUNCTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
                        </select>
                      </div>
                    </div>
                  )}

                  {/* Agent visibility */}
                  <div>
                    <label className="text-[10px] text-obs-subtle block mb-2 uppercase tracking-wide">Visibilidade para agentes</label>
                    <div className="flex gap-2 flex-wrap">
                      {["SDR", "Closer", "Classifier", "Maker"].map((agent) => {
                        const active = (item.agent_visibility || []).includes(agent);
                        return (
                          <button key={agent}
                            onClick={() => {
                              const current = item.agent_visibility || [];
                              updateItem(item.id, { agent_visibility: active ? current.filter((a) => a !== agent) : [...current, agent] });
                            }}
                            className={`text-xs px-3 py-1 rounded-full border transition-colors ${
                              active ? "bg-obs-violet/15 border-obs-violet/50 text-obs-violet" : "border-white/06 text-obs-subtle hover:text-obs-text"}`}>
                            {agent}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Content preview */}
                  {!isImg && !isVid && item.content && (
                    <pre className="bg-obs-raised border border-white/06 rounded-xl p-3 text-xs text-obs-text/80 overflow-y-auto max-h-48 whitespace-pre-wrap font-mono leading-relaxed">
                      {item.content}
                    </pre>
                  )}

                  {/* Actions */}
                  <div className="flex gap-2 pt-1 flex-wrap">
                    {["pending","needs_persona","needs_category"].includes(item.status) && (
                      <>
                        <button disabled={processing === item.id || !item.persona_id}
                          onClick={() => approve(item.id, true)}
                          className="text-xs bg-green-500/15 border border-green-500/30 text-green-400 hover:bg-green-500/25 px-4 py-1.5 rounded-lg disabled:opacity-40 transition-colors">
                          ✓ Aprovar + KB
                        </button>
                        <button disabled={processing === item.id || !item.persona_id}
                          onClick={() => approve(item.id, false)}
                          className="text-xs bg-obs-violet/10 border border-obs-violet/30 text-obs-violet hover:bg-obs-violet/20 px-4 py-1.5 rounded-lg disabled:opacity-40 transition-colors">
                          ✓ Aprovar
                        </button>
                        <button disabled={processing === item.id}
                          onClick={() => reject(item.id)}
                          className="text-xs bg-obs-rose/10 border border-obs-rose/30 text-obs-rose hover:bg-obs-rose/20 px-4 py-1.5 rounded-lg disabled:opacity-40 transition-colors">
                          ✗ Rejeitar
                        </button>
                      </>
                    )}
                    {item.status === "approved" && (
                      <button disabled={processing === item.id}
                        onClick={async () => { setProcessing(item.id); try { await api.promoteToKb(item.id); setItems((p) => p.map((i) => i.id === item.id ? { ...i, status: "embedded" } : i)); } finally { setProcessing(null); } }}
                        className="text-xs bg-obs-violet/10 border border-obs-violet/30 text-obs-violet hover:bg-obs-violet/20 px-4 py-1.5 rounded-lg disabled:opacity-40 transition-colors">
                        → Enviar à KB
                      </button>
                    )}
                  </div>

                  {(item.status === "needs_persona" || !item.persona_id) && (
                    <p className="text-xs text-obs-amber bg-obs-amber/5 border border-obs-amber/20 rounded-lg px-3 py-2">
                      ⚠ Atribua uma persona para liberar a aprovação.
                    </p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
