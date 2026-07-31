"use client";

import { useState } from "react";
import { CheckCircle2, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { useGlobalPersona } from "@/lib/useGlobalPersona";

export default function KnowledgeSyncPage() {
  const persona = useGlobalPersona();
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");

  async function synchronize() {
    if (!persona.slug) return;
    setRunning(true);
    setResult(null);
    setError("");
    try {
      const vault = await api.triggerSync(persona.slug);
      const graph = await api.syncGraphDocument({
        persona_slug: persona.slug,
        idempotency_key: `dashboard-sync:${persona.slug}:${Date.now()}`,
      });
      setResult({ vault, graph });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setRunning(false);
    }
  }

  return (
    <main className="mx-auto max-w-4xl space-y-6 p-6">
      <header>
        <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-obs-faint">
          Persona selecionada · {persona.slug || "nenhuma"}
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-obs-text">Sincronizar conhecimento</h1>
        <p className="mt-1 text-sm text-obs-subtle">
          Uma única operação importa o vault da persona e reconcilia a versão publicada com grafo, RAG e contexto do chatbot.
        </p>
      </header>

      <section className="rounded-2xl border border-white/10 bg-obs-surface p-5">
        {!persona.slug ? (
          <p className="text-sm text-amber-200">Selecione uma persona no cabeçalho.</p>
        ) : (
          <>
            <p className="text-sm text-obs-text">Escopo: <strong>{persona.slug}</strong></p>
            <p className="mt-1 text-xs leading-5 text-obs-subtle">
              Arquivos entram como candidatos de validação; somente conteúdo aprovado é publicado e refletido no grafo.
            </p>
            <button
              type="button"
              onClick={synchronize}
              disabled={running}
              className="mt-4 inline-flex items-center gap-2 rounded-xl bg-obs-violet px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50"
            >
              <RefreshCw size={15} className={running ? "animate-spin" : ""} />
              {running ? "Sincronizando..." : "Sincronizar persona"}
            </button>
          </>
        )}
      </section>

      {error && (
        <p role="alert" className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">
          {error}
        </p>
      )}
      {result && (
        <section className="rounded-2xl border border-emerald-500/25 bg-emerald-500/5 p-5">
          <h2 className="flex items-center gap-2 text-sm font-medium text-emerald-300">
            <CheckCircle2 size={16} /> Sincronização concluída
          </h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <ResultCard title="Importação do vault" value={result.vault} />
            <ResultCard title="Reconciliação do grafo" value={result.graph} />
          </div>
        </section>
      )}
    </main>
  );
}

function ResultCard({ title, value }: { title: string; value: any }) {
  return (
    <div className="rounded-xl border border-white/10 bg-obs-base/50 p-3">
      <p className="text-xs font-medium text-obs-text">{title}</p>
      <pre className="mt-2 max-h-44 overflow-auto text-[10px] leading-5 text-obs-subtle">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}
