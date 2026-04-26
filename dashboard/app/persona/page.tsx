"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface Persona { id: string; slug: string; name: string; tone: string; products: string[]; config: any; active: boolean; created_at: string; }

const SLUGS = ["tock-fatal", "baita-conveniencia", "vz-lupas"];

export default function PersonaPage() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selected, setSelected] = useState<Persona | null>(null);
  const [brand, setBrand] = useState<any>(null);
  const [bindings, setBindings] = useState<any[]>([]);
  const [kbCount, setKbCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.personas().then((list) => {
      setPersonas(list);
      if (list.length > 0) selectPersona(list[0]);
    }).finally(() => setLoading(false));
  }, []);

  async function selectPersona(p: Persona) {
    setSelected(p);
    setBrand(null);
    setBindings([]);
    setKbCount(null);
    const [brandData, bindingsData, kbData] = await Promise.all([
      api.brandProfile(p.id).catch(() => null),
      api.workflowBindings(p.id).catch(() => []),
      api.kb(p.id).catch(() => []),
    ]);
    setBrand(brandData);
    setBindings(bindingsData);
    setKbCount(Array.isArray(kbData) ? kbData.length : 0);
  }

  if (loading) return <p className="text-brain-muted text-sm">Carregando...</p>;

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Personas / Clientes</h1>

      {/* Client tabs */}
      <div className="flex gap-2 flex-wrap">
        {personas.map((p) => (
          <button key={p.id} onClick={() => selectPersona(p)}
            className={`text-sm px-4 py-1.5 rounded-md border transition-colors ${
              selected?.id === p.id
                ? "bg-brain-accent/20 border-brain-accent text-brain-accent font-medium"
                : "border-brain-border text-brain-muted hover:text-white"
            }`}>
            {p.name}
          </button>
        ))}
      </div>

      {selected && (
        <div className="grid grid-cols-3 gap-4">
          {/* Main info */}
          <div className="col-span-2 space-y-4">
            <div className="bg-brain-surface border border-brain-border rounded-xl p-5 space-y-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-brain-accent/20 flex items-center justify-center text-brain-accent font-bold text-lg">
                  {selected.name[0]}
                </div>
                <div>
                  <p className="font-semibold text-lg">{selected.name}</p>
                  <p className="text-xs text-brain-muted font-mono">{selected.slug}</p>
                </div>
                <span className={`ml-auto text-xs px-2 py-0.5 rounded-full border ${selected.active ? "border-green-500/40 text-green-400" : "border-red-500/40 text-red-400"}`}>
                  {selected.active ? "ativo" : "inativo"}
                </span>
              </div>

              <div>
                <p className="text-xs text-brain-muted uppercase tracking-wide mb-1">Tom de voz</p>
                <p className="text-sm">{selected.tone || "—"}</p>
              </div>

              <div>
                <p className="text-xs text-brain-muted uppercase tracking-wide mb-1">Produtos</p>
                <div className="flex flex-wrap gap-1.5">
                  {(selected.products || []).map((p) => (
                    <span key={p} className="text-xs bg-brain-bg border border-brain-border rounded px-2 py-0.5">{p}</span>
                  ))}
                </div>
              </div>

              {selected.config && Object.keys(selected.config).length > 0 && (
                <div>
                  <p className="text-xs text-brain-muted uppercase tracking-wide mb-1">Config</p>
                  <pre className="text-xs bg-brain-bg border border-brain-border rounded p-3 overflow-x-auto">
                    {JSON.stringify(selected.config, null, 2)}
                  </pre>
                </div>
              )}
            </div>

            {/* Brand Profile */}
            {brand && Object.keys(brand).length > 0 && (
              <div className="bg-brain-surface border border-brain-border rounded-xl p-5 space-y-3">
                <p className="text-sm font-semibold">Brand Profile</p>
                {brand.tagline && (
                  <div>
                    <p className="text-xs text-brain-muted mb-0.5">Tagline</p>
                    <p className="text-sm italic">"{brand.tagline}"</p>
                  </div>
                )}
                {brand.positioning && (
                  <div>
                    <p className="text-xs text-brain-muted mb-0.5">Posicionamento</p>
                    <p className="text-sm">{brand.positioning}</p>
                  </div>
                )}
                {brand.tone_pillars?.length > 0 && (
                  <div>
                    <p className="text-xs text-brain-muted mb-1">Pilares de tom</p>
                    <div className="flex gap-2 flex-wrap">
                      {brand.tone_pillars.map((t: string) => (
                        <span key={t} className="text-xs bg-brain-accent/10 border border-brain-accent/30 text-brain-accent rounded px-2 py-0.5">{t}</span>
                      ))}
                    </div>
                  </div>
                )}
                {brand.differentials?.length > 0 && (
                  <div>
                    <p className="text-xs text-brain-muted mb-1">Diferenciais</p>
                    <ul className="text-sm space-y-0.5">
                      {brand.differentials.map((d: string, i: number) => (
                        <li key={i} className="flex gap-2"><span className="text-brain-accent">·</span>{d}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {brand.palette?.length > 0 && (
                  <div>
                    <p className="text-xs text-brain-muted mb-1">Paleta</p>
                    <div className="flex gap-2">
                      {brand.palette.map((c: string) => (
                        <div key={c} className="flex items-center gap-1.5">
                          <div className="w-5 h-5 rounded border border-brain-border" style={{ backgroundColor: c }} />
                          <span className="text-xs font-mono text-brain-muted">{c}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
            {!brand && (
              <div className="bg-brain-surface border border-dashed border-brain-border rounded-xl p-4 text-center text-sm text-brain-muted">
                Sem brand profile. Sincronize o vault ou adicione via{" "}
                <a href="/knowledge/upload" className="text-brain-accent hover:underline">Upload</a>.
              </div>
            )}
          </div>

          {/* Right column: stats + bindings */}
          <div className="space-y-4">
            {/* Quick stats */}
            <div className="bg-brain-surface border border-brain-border rounded-xl p-4 space-y-3">
              <p className="text-xs text-brain-muted uppercase tracking-wide">Resumo</p>
              <Stat label="Entradas na KB" value={kbCount ?? "—"} />
              <Stat label="Fluxos n8n" value={bindings.length} />
            </div>

            {/* n8n bindings */}
            <div className="bg-brain-surface border border-brain-border rounded-xl p-4 space-y-2">
              <p className="text-xs text-brain-muted uppercase tracking-wide mb-2">Fluxos n8n</p>
              {bindings.length === 0 && (
                <p className="text-xs text-brain-muted">Nenhum fluxo vinculado.</p>
              )}
              {bindings.map((b) => (
                <div key={b.id} className="flex items-center gap-2 text-xs">
                  <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${b.active ? "bg-green-400" : "bg-brain-muted"}`} />
                  <span className="text-white truncate">{b.workflow_name}</span>
                  {b.whatsapp_number && <span className="text-brain-muted shrink-0">{b.whatsapp_number}</span>}
                </div>
              ))}
            </div>

            {/* Quick links */}
            <div className="bg-brain-surface border border-brain-border rounded-xl p-4 space-y-1">
              <p className="text-xs text-brain-muted uppercase tracking-wide mb-2">Ações rápidas</p>
              <a href={`/kb?persona_id=${selected.id}`} className="block text-xs text-brain-accent hover:underline py-0.5">→ Ver KB</a>
              <a href="/knowledge/sync" className="block text-xs text-brain-accent hover:underline py-0.5">→ Sincronizar Vault</a>
              <a href={`/knowledge/validate?persona=${selected.id}`} className="block text-xs text-brain-accent hover:underline py-0.5">→ Validar itens pendentes</a>
              <a href="/knowledge/upload" className="block text-xs text-brain-accent hover:underline py-0.5">→ Upload de conhecimento</a>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-brain-muted">{label}</span>
      <span className="text-sm font-semibold text-white">{value}</span>
    </div>
  );
}
