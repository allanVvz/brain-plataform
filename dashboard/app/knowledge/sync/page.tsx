"use client";

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "@/lib/api";

export default function GraphSyncPage() {
  const [personas, setPersonas] = useState<any[]>([]);
  const [personaSlug, setPersonaSlug] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.personas().then((rows) => {
      setPersonas(rows || []);
      setPersonaSlug((rows || [])[0]?.slug || "");
    }).catch((reason) => setError(String(reason)));
  }, []);

  async function reconcile() {
    if (!personaSlug) return;
    setRunning(true);
    setError("");
    setResult(null);
    try {
      setResult(await api.syncGraphDocument({
        persona_slug: personaSlug,
        idempotency_key: `dashboard-sync:${personaSlug}:${Date.now()}`,
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setRunning(false);
    }
  }

  return (
    <main className="p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-white">Sync do Brain AI</h1>
        <p className="text-sm text-brain-muted mt-1">
          Reconcilia Graph JSON → Markdown → tabelas derivadas → Golden Dataset → contexto dos agentes.
        </p>
      </div>

      <section className="rounded-xl border border-brain-border bg-brain-surface p-5 space-y-4">
        <label className="block text-xs uppercase tracking-wide text-brain-muted">Persona</label>
        <select
          value={personaSlug}
          onChange={(event) => setPersonaSlug(event.target.value)}
          className="w-full rounded-lg border border-brain-border bg-black/20 px-3 py-2 text-white"
        >
          {personas.map((persona) => (
            <option key={persona.id || persona.slug} value={persona.slug}>
              {persona.name || persona.slug}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={reconcile}
          disabled={!personaSlug || running}
          className="inline-flex items-center gap-2 rounded-lg bg-brain-accent px-4 py-2 text-sm font-medium text-black disabled:opacity-50"
        >
          <RefreshCw size={15} className={running ? "animate-spin" : ""} />
          {running ? "Reconciliando…" : "Reconciliar versão publicada"}
        </button>
      </section>

      {error && <p className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">{error}</p>}
      {result && (
        <section className="rounded-xl border border-emerald-500/25 bg-emerald-500/5 p-5">
          <h2 className="text-sm font-medium text-emerald-300">Reconciliação concluída</h2>
          <pre className="mt-3 overflow-auto text-xs text-brain-muted">{JSON.stringify(result, null, 2)}</pre>
        </section>
      )}
    </main>
  );
}
