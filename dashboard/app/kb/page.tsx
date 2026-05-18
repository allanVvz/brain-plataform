"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface Persona { id: string; slug: string; name: string; }

const TIPO_COLOR: Record<string, string> = {
  faq: "text-sky-400", brand: "text-purple-400", briefing: "text-blue-400",
  produto: "text-teal-400", copy: "text-yellow-400", prompt: "text-green-400",
  regra: "text-gray-400", tom: "text-indigo-400", concorrente: "text-red-400",
  audiencia: "text-violet-400", campanha: "text-orange-400", maker: "text-rose-400",
};

export default function KbPage() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selectedPersona, setSelectedPersona] = useState<string>("");
  const [entries, setEntries] = useState<any[]>([]);
  const [filter, setFilter] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.personas().then((list) => {
      setPersonas(list);
      loadKb(list[0]?.id || "");
    });
  }, []);

  function loadKb(personaId: string) {
    setSelectedPersona(personaId);
    setLoading(true);
    api.kb(personaId || undefined).then(setEntries).finally(() => setLoading(false));
  }

  async function handleSync() {
    if (!selectedPersona) return;
    setSyncing(true);
    try {
      await api.syncKb(selectedPersona);
      const data = await api.kb(selectedPersona);
      setEntries(data);
    } catch (e) { console.error(e); }
    finally { setSyncing(false); }
  }

  const visible = filter
    ? entries.filter((e) =>
        (e.titulo || "").toLowerCase().includes(filter.toLowerCase()) ||
        (e.conteudo || "").toLowerCase().includes(filter.toLowerCase()) ||
        (e.categoria || "").toLowerCase().includes(filter.toLowerCase()))
    : entries;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Golden Dataset</h1>
        <div className="flex gap-2">
          <button onClick={handleSync} disabled={syncing || !selectedPersona}
            className="text-sm border border-brain-border text-brain-muted hover:text-white disabled:opacity-40 px-4 py-1.5 rounded-md transition-colors">
            {syncing ? "Sincronizando..." : "↺ Sync Sheets"}
          </button>
          <a href="/knowledge/upload"
            className="text-sm bg-brain-accent/20 border border-brain-accent/40 text-brain-accent hover:bg-brain-accent/30 px-4 py-1.5 rounded-md transition-colors">
            + Adicionar
          </a>
        </div>
      </div>

      <div className="flex gap-2 items-center">
        <div className="flex gap-1.5 flex-wrap">
          <button onClick={() => loadKb("")}
            className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${!selectedPersona ? "bg-brain-accent/20 border-brain-accent text-brain-accent" : "border-brain-border text-brain-muted hover:text-white"}`}>
            Todos
          </button>
          {personas.map((p) => (
            <button key={p.id} onClick={() => loadKb(p.id)}
              className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${selectedPersona === p.id ? "bg-brain-accent/20 border-brain-accent text-brain-accent" : "border-brain-border text-brain-muted hover:text-white"}`}>
              {p.name}
            </button>
          ))}
        </div>
        <input
          placeholder="Buscar..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="ml-auto bg-brain-bg border border-brain-border rounded px-3 py-1.5 text-xs text-white w-48 focus:outline-none focus:border-brain-accent"
        />
      </div>

      <div className="bg-brain-surface border border-brain-border rounded-xl overflow-hidden">
        <div className="grid grid-cols-[90px_110px_1fr_80px_70px] text-xs text-brain-muted px-4 py-2 border-b border-brain-border font-medium uppercase tracking-wide">
          <span>Tipo</span><span>Categoria</span><span>Pergunta / Título</span><span>Status</span><span>Fonte</span>
        </div>
        <div className="divide-y divide-brain-border max-h-[600px] overflow-y-auto">
          {loading && <p className="text-brain-muted text-sm p-4">Carregando...</p>}
          {!loading && visible.map((e) => (
            <div key={e.id} className="grid grid-cols-[90px_110px_1fr_80px_70px] px-4 py-2.5 text-xs items-start gap-2 hover:bg-white/5">
              <span className={`font-medium ${TIPO_COLOR[e.tipo] || "text-brain-muted"}`}>{e.tipo}</span>
              <span className="text-brain-muted truncate">{e.categoria}</span>
              <div>
                <p className="text-white font-medium">{e.titulo}</p>
                <p className="text-brain-muted mt-0.5 line-clamp-2">{e.conteudo}</p>
              </div>
              <span className={e.status === "ATIVO" ? "text-green-400" : "text-brain-muted"}>{e.status}</span>
              <span className="text-brain-muted">{e.source}</span>
            </div>
          ))}
          {!loading && visible.length === 0 && (
            <div className="px-4 py-8 text-center text-brain-muted text-sm">
              Nenhuma entrada no Golden Dataset.{" "}
              <a href="/knowledge/sync" className="text-brain-accent hover:underline">Sincronizar vault</a> ou{" "}
              <a href="/knowledge/upload" className="text-brain-accent hover:underline">adicionar manualmente</a>.
            </div>
          )}
        </div>
      </div>
      <p className="text-xs text-brain-muted">{loading ? "" : `${visible.length} entrada${visible.length !== 1 ? "s" : ""} do Golden Dataset exibida${visible.length !== 1 ? "s" : ""}`}</p>
    </div>
  );
}
