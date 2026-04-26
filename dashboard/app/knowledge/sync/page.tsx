"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface SyncFile {
  path: string;
  persona: string | null;
  content_type: string;
  title: string;
  ext: string;
}

interface SyncRun {
  id: string;
  status: string;
  files_found: number;
  files_new: number;
  files_updated: number;
  files_skipped: number;
  started_at: string;
  finished_at: string | null;
  error_message: string | null;
}

interface Preview {
  files: SyncFile[];
  total: number;
  by_client: Record<string, number>;
  by_type: Record<string, number>;
  error?: string;
}

const TYPE_COLOR: Record<string, string> = {
  brand: "text-purple-400", briefing: "text-blue-400", tone: "text-indigo-400",
  product: "text-teal-400", campaign: "text-orange-400", copy: "text-yellow-400",
  asset: "text-pink-400", prompt: "text-green-400", faq: "text-sky-400",
  maker_material: "text-rose-400", competitor: "text-red-400", audience: "text-violet-400",
  rule: "text-gray-400", other: "text-brain-muted",
};

export default function SyncPage() {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [lastResult, setLastResult] = useState<any>(null);
  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState("");
  const [filterClient, setFilterClient] = useState("");

  async function loadPreview() {
    setLoading(true);
    try {
      const data = await api.knowledgePreview();
      setPreview(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  async function loadRuns() {
    try {
      const data = await api.syncRuns();
      setRuns(data);
    } catch (e) { /* ignore */ }
  }

  useEffect(() => {
    loadPreview();
    loadRuns();
  }, []);

  async function triggerSync() {
    setSyncing(true);
    setLastResult(null);
    try {
      const result = await api.triggerSync(filterClient || undefined);
      setLastResult(result);
      await loadRuns();
    } catch (e: any) {
      setLastResult({ error: e.message });
    } finally {
      setSyncing(false);
    }
  }

  const visibleFiles = (preview?.files || []).filter((f) => {
    if (filterClient && f.persona !== filterClient) return false;
    if (filterType && f.content_type !== filterType) return false;
    if (search && !f.path.toLowerCase().includes(search.toLowerCase()) &&
        !f.title.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const clients = Object.keys(preview?.by_client || {}).sort();
  const types = Object.keys(preview?.by_type || {}).sort();

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Sync AI Brain</h1>
          <p className="text-sm text-brain-muted mt-0.5">Escaneia o vault local e cria itens pendentes de validação</p>
        </div>
        <button onClick={triggerSync} disabled={syncing}
          className="text-sm bg-brain-accent hover:bg-brain-accent/80 disabled:opacity-50 px-5 py-2 rounded-md transition-colors font-medium">
          {syncing ? "Sincronizando..." : "⟳ Sincronizar AI Brain"}
        </button>
      </div>

      {/* Last sync result */}
      {lastResult && (
        <div className={`border rounded-xl p-4 text-sm ${lastResult.error ? "border-red-500/40 bg-red-500/10 text-red-400" : "border-green-500/40 bg-green-500/10 text-green-400"}`}>
          {lastResult.error ? (
            <span>Erro: {lastResult.error}</span>
          ) : (
            <span>
              Sync concluído — {lastResult.new} novos · {lastResult.updated} atualizados · {lastResult.skipped} ignorados
              {" "}(total: {lastResult.found})
            </span>
          )}
        </div>
      )}

      {/* Stats */}
      {preview && !preview.error && (
        <div className="grid grid-cols-4 gap-3">
          <Stat label="Total de arquivos" value={preview.total} />
          <Stat label="Clientes" value={Object.keys(preview.by_client).length} />
          <Stat label="Tipos de conteúdo" value={Object.keys(preview.by_type).length} />
          <Stat label="Sem persona" value={preview.by_client["unassigned"] || 0} muted />
        </div>
      )}

      {/* Distribution */}
      {preview && (
        <div className="grid grid-cols-2 gap-4">
          <DistCard title="Por cliente" data={preview.by_client} />
          <DistCard title="Por tipo" data={preview.by_type} />
        </div>
      )}

      {/* File list */}
      <div className="bg-brain-surface border border-brain-border rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-brain-border flex items-center gap-3 flex-wrap">
          <span className="text-xs text-brain-muted uppercase tracking-wide mr-auto">
            {loading ? "Carregando..." : `${visibleFiles.length} arquivo${visibleFiles.length !== 1 ? "s" : ""}`}
          </span>
          <input
            placeholder="Buscar..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="bg-brain-bg border border-brain-border rounded px-2 py-1 text-xs text-white w-40 focus:outline-none focus:border-brain-accent"
          />
          <select value={filterClient} onChange={(e) => setFilterClient(e.target.value)}
            className="bg-brain-bg border border-brain-border rounded px-2 py-1 text-xs text-white focus:outline-none">
            <option value="">Todos clientes</option>
            {clients.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select value={filterType} onChange={(e) => setFilterType(e.target.value)}
            className="bg-brain-bg border border-brain-border rounded px-2 py-1 text-xs text-white focus:outline-none">
            <option value="">Todos tipos</option>
            {types.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div className="divide-y divide-brain-border max-h-96 overflow-y-auto">
          {visibleFiles.slice(0, 300).map((f, i) => (
            <div key={i} className="px-4 py-2 flex items-center gap-3 text-xs">
              <span className={`shrink-0 font-medium ${TYPE_COLOR[f.content_type] || "text-brain-muted"}`}>
                {f.content_type}
              </span>
              <span className="text-white truncate flex-1">{f.title}</span>
              <span className="text-brain-muted shrink-0">{f.persona || "—"}</span>
              <span className="text-brain-muted font-mono shrink-0">.{f.ext}</span>
            </div>
          ))}
          {visibleFiles.length === 0 && !loading && (
            <p className="text-brain-muted text-sm p-4">Nenhum arquivo encontrado.</p>
          )}
        </div>
      </div>

      {/* Sync history */}
      {runs.length > 0 && (
        <div>
          <h2 className="text-sm font-medium text-brain-muted uppercase tracking-wide mb-3">Histórico de sincronizações</h2>
          <div className="space-y-2">
            {runs.slice(0, 5).map((r) => (
              <div key={r.id} className="bg-brain-surface border border-brain-border rounded-xl px-4 py-3 flex items-center gap-4 text-xs">
                <span className={`w-2 h-2 rounded-full shrink-0 ${r.status === "completed" ? "bg-green-400" : r.status === "running" ? "bg-yellow-400 animate-pulse" : "bg-red-400"}`} />
                <span className="text-brain-muted">{new Date(r.started_at).toLocaleString("pt-BR")}</span>
                <span className="text-white">{r.files_found} encontrados</span>
                <span className="text-green-400">{r.files_new} novos</span>
                <span className="text-blue-400">{r.files_updated} atualizados</span>
                <span className="text-brain-muted">{r.files_skipped} ignorados</span>
                {r.error_message && <span className="text-red-400 ml-auto">{r.error_message}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, muted }: { label: string; value: number; muted?: boolean }) {
  return (
    <div className="bg-brain-surface border border-brain-border rounded-xl p-4">
      <p className="text-xs text-brain-muted mb-1">{label}</p>
      <p className={`text-2xl font-bold ${muted ? "text-brain-muted" : "text-white"}`}>{value}</p>
    </div>
  );
}

function DistCard({ title, data }: { title: string; data: Record<string, number> }) {
  const total = Object.values(data).reduce((a, b) => a + b, 0);
  const sorted = Object.entries(data).sort((a, b) => b[1] - a[1]);
  return (
    <div className="bg-brain-surface border border-brain-border rounded-xl p-4">
      <p className="text-xs text-brain-muted uppercase tracking-wide mb-3">{title}</p>
      <div className="space-y-2">
        {sorted.map(([key, count]) => (
          <div key={key} className="flex items-center gap-2 text-xs">
            <span className="text-white w-40 truncate">{key}</span>
            <div className="flex-1 bg-brain-bg rounded-full h-1.5">
              <div className="h-1.5 rounded-full bg-brain-accent" style={{ width: `${(count / total) * 100}%` }} />
            </div>
            <span className="text-brain-muted w-6 text-right">{count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
