"use client";
import { useEffect, useState } from "react";
import { api, BASE } from "@/lib/api";

interface KnowledgeItem {
  id: string;
  persona_id: string | null;
  content_type: string;
  title: string;
  content: string;
  status: string;
  file_path: string | null;
  file_type: string | null;
  tags: string[] | null;
  agent_visibility: string[] | null;
  asset_type: string | null;
  asset_function: string | null;
  metadata: Record<string, any>;
  created_at: string;
}

interface Persona { id: string; slug: string; name: string; }

const TYPE_OPTIONS = [
  "brand","briefing","product","campaign","copy","asset",
  "prompt","faq","maker_material","tone","competitor","audience","rule","other",
];

const ASSET_TYPE_OPTIONS = [
  "background","logo","product","model","banner","story","post","video","icon","other",
];

const ASSET_FUNCTION_OPTIONS = [
  "maker_material","brand_reference","campaign_hero","copy_support","product_showcase","other",
];

const STATUS_COLORS: Record<string, string> = {
  pending:         "text-yellow-400 border-yellow-500/30 bg-yellow-500/5",
  needs_persona:   "text-orange-400 border-orange-500/30 bg-orange-500/5",
  needs_category:  "text-amber-400 border-amber-500/30 bg-amber-500/5",
  reviewing:       "text-blue-300 border-blue-400/30 bg-blue-400/5",
  approved:        "text-green-400 border-green-500/30 bg-green-500/5",
  rejected:        "text-red-400 border-red-500/30 bg-red-500/5",
  embedded:        "text-blue-400 border-blue-500/30 bg-blue-500/5",
};

const IMAGE_EXTS = new Set(["png","jpg","jpeg","svg","gif","webp"]);

function isImage(item: KnowledgeItem) {
  const ext = (item.file_type || "").toLowerCase();
  return IMAGE_EXTS.has(ext);
}

export default function ValidatePage() {
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
      setItems(itemsData);
      setPersonas(personasData);
      setCounts(countsData);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [filterStatus, filterType, filterPersona]);

  async function approve(id: string, toKb = false) {
    setProcessing(id);
    try {
      await api.approveItem(id, toKb);
      setItems((prev) => prev.filter((i) => i.id !== id));
    } finally {
      setProcessing(null);
    }
  }

  async function reject(id: string) {
    const reason = prompt("Motivo da rejeição (opcional):") ?? "";
    setProcessing(id);
    try {
      await api.rejectItem(id, reason);
      setItems((prev) => prev.filter((i) => i.id !== id));
    } finally {
      setProcessing(null);
    }
  }

  async function updateItem(id: string, data: Record<string, any>) {
    await api.updateQueueItem(id, data);
    setItems((prev) => prev.map((i) => i.id === id ? { ...i, ...data } : i));
  }

  const personaName = (id: string | null) => personas.find((p) => p.id === id)?.name || "—";

  const byStatus = counts.by_status || {};

  const tabs = [
    { key: "attention",      label: "Atenção",    urgent: true },
    { key: "needs_persona",  label: "Sem persona" },
    { key: "needs_category", label: "Sem categoria" },
    { key: "pending",        label: "Pendente" },
    { key: "approved",       label: "Aprovado" },
    { key: "embedded",       label: "Na KB" },
    { key: "rejected",       label: "Rejeitado" },
  ];

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Validação de Conhecimento</h1>
          <p className="text-sm text-brain-muted mt-0.5">Revise, aprove ou rejeite materiais sincronizados</p>
        </div>
        <button onClick={load} className="text-xs text-brain-muted hover:text-white border border-brain-border px-3 py-1.5 rounded-md">
          Atualizar
        </button>
      </div>

      {/* Status tabs */}
      <div className="flex gap-2 flex-wrap">
        {tabs.map(({ key, label, urgent }) => {
          const count = byStatus[key] ?? 0;
          return (
            <button key={key} onClick={() => setFilterStatus(key)}
              className={`text-xs px-3 py-1.5 rounded-md border transition-colors flex items-center gap-1.5 ${
                filterStatus === key
                  ? "bg-brain-accent/20 border-brain-accent text-brain-accent"
                  : "border-brain-border text-brain-muted hover:text-white"
              }`}>
              {urgent && count > 0 && (
                <span className="w-1.5 h-1.5 rounded-full bg-orange-400 shrink-0" />
              )}
              {label}
              {count > 0 && (
                <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
                  urgent && count > 0
                    ? "bg-orange-500/20 text-orange-300"
                    : "bg-brain-border text-white"
                }`}>
                  {count}
                </span>
              )}
            </button>
          );
        })}

        <div className="ml-auto flex gap-2">
          <select value={filterPersona} onChange={(e) => setFilterPersona(e.target.value)}
            className="bg-brain-bg border border-brain-border rounded px-2 py-1 text-xs text-white focus:outline-none">
            <option value="">Todos clientes</option>
            {personas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <select value={filterType} onChange={(e) => setFilterType(e.target.value)}
            className="bg-brain-bg border border-brain-border rounded px-2 py-1 text-xs text-white focus:outline-none">
            <option value="">Todos tipos</option>
            {TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
      </div>

      {loading && <p className="text-brain-muted text-sm">Carregando...</p>}
      {!loading && items.length === 0 && (
        <p className="text-brain-muted text-sm">Nenhum item neste filtro.</p>
      )}

      <div className="space-y-3">
        {items.map((item) => (
          <div key={item.id}
            className={`border rounded-xl overflow-hidden ${expanded === item.id ? "border-brain-accent/60" : "border-brain-border"}`}>
            {/* Header row */}
            <div
              className="px-4 py-3 flex items-center gap-3 cursor-pointer hover:bg-white/5"
              onClick={() => setExpanded(expanded === item.id ? null : item.id)}>
              <span className={`text-xs px-2 py-0.5 rounded border font-medium shrink-0 ${STATUS_COLORS[item.status] ?? "text-brain-muted border-brain-border"}`}>
                {item.status}
              </span>
              <span className="text-xs text-brain-accent font-medium shrink-0">{item.content_type}</span>
              <span className="text-sm text-white font-medium flex-1 truncate">{item.title}</span>
              <span className="text-xs text-brain-muted shrink-0">{personaName(item.persona_id)}</span>
              {item.file_path && (
                <span className="text-xs text-brain-muted font-mono truncate max-w-[200px] shrink-0 hidden lg:block">
                  {item.file_path.split(/[\\/]/).slice(-2).join("/")}
                </span>
              )}
              <span className="text-brain-muted text-xs shrink-0">{expanded === item.id ? "▲" : "▼"}</span>
            </div>

            {/* Expanded panel */}
            {expanded === item.id && (
              <div className="border-t border-brain-border bg-brain-bg/50 p-4 space-y-4">
                {/* Asset image preview */}
                {isImage(item) && item.file_path && (
                  <div className="flex justify-center bg-brain-surface border border-brain-border rounded-lg p-2">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={`${BASE}/knowledge/file?path=${encodeURIComponent(item.file_path)}`}
                      alt={item.title}
                      className="max-h-64 max-w-full object-contain rounded"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                    />
                  </div>
                )}

                {/* Core fields */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs text-brain-muted block mb-1">Cliente</label>
                    <select
                      value={item.persona_id || ""}
                      onChange={(e) => updateItem(item.id, { persona_id: e.target.value || null })}
                      className="w-full bg-brain-surface border border-brain-border rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-brain-accent">
                      <option value="">Sem persona</option>
                      {personas.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-brain-muted block mb-1">Tipo de conteúdo</label>
                    <select
                      value={item.content_type}
                      onChange={(e) => updateItem(item.id, { content_type: e.target.value })}
                      className="w-full bg-brain-surface border border-brain-border rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-brain-accent">
                      {TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
                    </select>
                  </div>
                </div>

                {/* Asset-specific fields */}
                {item.content_type === "asset" && (
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs text-brain-muted block mb-1">Tipo de asset</label>
                      <select
                        value={item.asset_type || ""}
                        onChange={(e) => updateItem(item.id, { asset_type: e.target.value || null })}
                        className="w-full bg-brain-surface border border-brain-border rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-brain-accent">
                        <option value="">—</option>
                        {ASSET_TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="text-xs text-brain-muted block mb-1">Função do asset</label>
                      <select
                        value={item.asset_function || ""}
                        onChange={(e) => updateItem(item.id, { asset_function: e.target.value || null })}
                        className="w-full bg-brain-surface border border-brain-border rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-brain-accent">
                        <option value="">—</option>
                        {ASSET_FUNCTION_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
                      </select>
                    </div>
                  </div>
                )}

                {/* Agent visibility */}
                <div>
                  <label className="text-xs text-brain-muted block mb-2">Visibilidade para agentes</label>
                  <div className="flex gap-2 flex-wrap">
                    {["SDR", "Closer", "Classifier", "Maker"].map((agent) => {
                      const active = (item.agent_visibility || []).includes(agent);
                      return (
                        <button
                          key={agent}
                          onClick={() => {
                            const current = item.agent_visibility || [];
                            const next = active
                              ? current.filter((a) => a !== agent)
                              : [...current, agent];
                            updateItem(item.id, { agent_visibility: next });
                          }}
                          className={`text-xs px-3 py-1 rounded-full border transition-colors ${
                            active
                              ? "bg-brain-accent/20 border-brain-accent text-brain-accent"
                              : "border-brain-border text-brain-muted hover:text-white"
                          }`}>
                          {agent}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Content preview (text only) */}
                {!isImage(item) && item.content && (
                  <div>
                    <label className="text-xs text-brain-muted block mb-1">Conteúdo</label>
                    <pre className="bg-brain-surface border border-brain-border rounded p-3 text-xs text-white overflow-y-auto max-h-64 whitespace-pre-wrap">
                      {item.content}
                    </pre>
                  </div>
                )}

                {/* Metadata */}
                {item.metadata && Object.keys(item.metadata).length > 0 && (
                  <div>
                    <label className="text-xs text-brain-muted block mb-1">Metadados</label>
                    <pre className="bg-brain-surface border border-brain-border rounded p-2 text-xs text-brain-muted overflow-y-auto max-h-24">
                      {JSON.stringify(item.metadata, null, 2)}
                    </pre>
                  </div>
                )}

                {/* Action buttons */}
                <div className="flex gap-2 pt-1 flex-wrap">
                  {(item.status === "pending" || item.status === "needs_persona" || item.status === "needs_category") && (
                    <>
                      <button
                        disabled={processing === item.id || !item.persona_id}
                        onClick={() => approve(item.id, true)}
                        title={!item.persona_id ? "Atribua uma persona primeiro" : ""}
                        className="text-xs bg-green-500/20 border border-green-500/40 text-green-400 hover:bg-green-500/30 px-4 py-1.5 rounded-md disabled:opacity-50 transition-colors">
                        ✓ Aprovar + Enviar à KB
                      </button>
                      <button
                        disabled={processing === item.id || !item.persona_id}
                        onClick={() => approve(item.id, false)}
                        title={!item.persona_id ? "Atribua uma persona primeiro" : ""}
                        className="text-xs bg-blue-500/20 border border-blue-500/40 text-blue-400 hover:bg-blue-500/30 px-4 py-1.5 rounded-md disabled:opacity-50 transition-colors">
                        ✓ Aprovar
                      </button>
                      <button
                        disabled={processing === item.id}
                        onClick={() => reject(item.id)}
                        className="text-xs bg-red-500/10 border border-red-500/30 text-red-400 hover:bg-red-500/20 px-4 py-1.5 rounded-md disabled:opacity-50 transition-colors">
                        ✗ Rejeitar
                      </button>
                    </>
                  )}
                  {item.status === "approved" && (
                    <button
                      disabled={processing === item.id}
                      onClick={async () => {
                        setProcessing(item.id);
                        try {
                          await api.promoteToKb(item.id);
                          setItems((prev) => prev.map((i) => i.id === item.id ? { ...i, status: "embedded" } : i));
                        } finally {
                          setProcessing(null);
                        }
                      }}
                      className="text-xs bg-brain-accent/20 border border-brain-accent/40 text-brain-accent hover:bg-brain-accent/30 px-4 py-1.5 rounded-md disabled:opacity-50 transition-colors">
                      → Enviar à KB
                    </button>
                  )}
                </div>

                {/* Missing persona warning */}
                {(item.status === "needs_persona" || !item.persona_id) && (
                  <p className="text-xs text-orange-400 bg-orange-500/10 border border-orange-500/20 rounded-lg px-3 py-2">
                    ⚠ Atribua uma persona para liberar a aprovação.
                  </p>
                )}
                {item.status === "needs_category" && (
                  <p className="text-xs text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
                    ⚠ Selecione um tipo de conteúdo diferente de "other" para liberar a aprovação.
                  </p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
