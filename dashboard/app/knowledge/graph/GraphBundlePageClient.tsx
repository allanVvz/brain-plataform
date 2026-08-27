"use client";

import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GitBranch, Layers3, Network, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { ApiError, api } from "@/lib/api";
import {
  graphBundleLayoutScope,
  graphBundleToReactFlow,
  GraphBundleVersion,
  GraphBundleVersionsPayload,
  GraphBundleViewPayload,
} from "@/lib/graph-bundle-v3";
import GraphBundleNodeDrawer from "./GraphBundleNodeDrawer";

const GraphView = dynamic(() => import("@/components/graph/GraphView"), { ssr: false });
type ViewMode = "layered" | "semantic_tree" | "graph";

const MODES: Array<{ value: ViewMode; label: string; icon: React.ReactNode }> = [
  { value: "layered", label: "Camadas", icon: <Layers3 size={11} /> },
  { value: "semantic_tree", label: "Tree", icon: <GitBranch size={11} /> },
  { value: "graph", label: "Grafo", icon: <Network size={11} /> },
];

const STATE_LABEL: Record<string, string> = {
  draft: "Draft",
  blocked: "Draft bloqueado",
  staged: "Staged",
  active: "Ativo",
};

export default function GraphBundlePageClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [personaSlug, setPersonaSlug] = useState("");
  const [catalog, setCatalog] = useState<GraphBundleVersionsPayload | null>(null);
  const [view, setView] = useState<GraphBundleViewPayload | null>(null);
  const [selectedNode, setSelectedNode] = useState<any | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(0);

  const requestedMode = searchParams.get("mode");
  const mode: ViewMode = requestedMode === "graph" || requestedMode === "layered" ? requestedMode : "semantic_tree";
  const selectedRef = searchParams.get("ref") || "";

  const replaceParams = useCallback((patch: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    next.set("backend", "v3");
    router.replace(`/knowledge/graph?${next.toString()}`);
  }, [router, searchParams]);

  useEffect(() => {
    const syncPersona = () => {
      requestId.current += 1;
      setPersonaSlug(window.localStorage.getItem("ai-brain-persona-slug") || "");
      setCatalog(null);
      setView(null);
      setSelectedNode(null);
      setError("");
    };
    syncPersona();
    window.addEventListener("ai-brain-persona-change", syncPersona as EventListener);
    return () => window.removeEventListener("ai-brain-persona-change", syncPersona as EventListener);
  }, []);

  const load = useCallback(async () => {
    const currentRequest = ++requestId.current;
    setLoading(true);
    setError("");
    setSelectedNode(null);
    try {
      if (!personaSlug) {
        setCatalog(null);
        setView(null);
        return;
      }
      const nextCatalog = await api.graphBundleVersions(personaSlug);
      if (currentRequest !== requestId.current) return;
      setCatalog(nextCatalog);
      const chosen = nextCatalog.versions.find((item: GraphBundleVersion) => item.ref === selectedRef)
        || nextCatalog.versions.find((item: GraphBundleVersion) => item.ref === nextCatalog.default_ref)
        || nextCatalog.versions[0];
      if (!chosen) {
        setView(null);
        setError("Nenhum draft ou publicação GraphBundle v3 disponível para esta persona.");
        return;
      }
      if (chosen.ref !== selectedRef) replaceParams({ ref: chosen.ref });
      const nextView = await api.graphBundleView(personaSlug, chosen.source, chosen.ref);
      if (currentRequest !== requestId.current) return;
      setView(nextView);
    } catch (caught) {
      if (currentRequest !== requestId.current) return;
      setCatalog(null);
      setView(null);
      setError(caught instanceof ApiError && caught.status === 404
        ? "Nenhum GraphBundle v3 encontrado para esta persona."
        : caught instanceof Error ? caught.message : "Falha ao carregar o GraphBundle v3.");
    } finally {
      if (currentRequest === requestId.current) setLoading(false);
    }
  }, [personaSlug, replaceParams, selectedRef]);

  useEffect(() => { load(); }, [load]);

  const graph = useMemo(() => view ? graphBundleToReactFlow(view) : null, [view]);
  const selectedVersion = catalog?.versions.find((item) => item.ref === view?.ref);
  const v2Href = useMemo(() => {
    const next = new URLSearchParams(searchParams.toString());
    next.delete("backend");
    next.delete("ref");
    return `/knowledge/graph${next.toString() ? `?${next}` : ""}`;
  }, [searchParams]);

  return (
    <div className="flex h-[calc(100vh-96px)] -mx-6 -mt-6 flex-col overflow-hidden">
      <div className="shrink-0 space-y-2 border-b border-white/06 px-6 py-2.5 glass">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-obs-text">Grafo de Conhecimento</span>
          <div className="flex items-center rounded-lg border border-white/10 bg-white/[0.03] p-0.5 text-[11px]">
            <a href={v2Href} className="rounded-md px-2 py-1 text-obs-subtle hover:text-white">Graph JSON v2</a>
            <span className="rounded-md bg-obs-violet/20 px-2 py-1 text-obs-violet">GraphBundle v3</span>
          </div>
          <div className="flex items-center gap-1" role="tablist" aria-label="Visualização do GraphBundle">
            {MODES.map((item) => (
              <button key={item.value} type="button" onClick={() => replaceParams({ mode: item.value })} role="tab" aria-selected={mode === item.value}
                className={`flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] ${mode === item.value ? "border-obs-violet bg-obs-violet/20 text-obs-violet" : "border-white/10 text-obs-subtle"}`}>
                {item.icon}{item.label}
              </button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <ShieldCheck size={12} className="text-emerald-300" />
            <span className="text-[10px] text-obs-subtle">Somente leitura semântica · layout local</span>
            <button type="button" onClick={load} disabled={loading} className="rounded-lg border border-white/06 p-1.5 text-obs-subtle hover:text-white disabled:opacity-40" aria-label="Atualizar GraphBundle">
              <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
            </button>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <select value={view?.ref || selectedRef} onChange={(event) => replaceParams({ ref: event.target.value })} disabled={!catalog?.versions.length}
            className="min-w-[340px] rounded-lg border border-white/08 bg-obs-base px-2.5 py-1.5 text-xs text-obs-text outline-none" aria-label="Versão GraphBundle">
            {(catalog?.versions || []).map((item) => (
              <option key={item.ref} value={item.ref}>{STATE_LABEL[item.state] || item.state} · {item.label}{item.validation_error_count ? ` · ${item.validation_error_count} erro(s)` : ""}</option>
            ))}
          </select>
          <div className="flex w-72 items-center gap-1.5 rounded-lg border border-white/06 bg-obs-base px-2 py-1">
            <Search size={11} className="text-obs-faint" />
            <input value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="Buscar slug/título..." className="flex-1 bg-transparent text-xs text-obs-text outline-none" />
          </div>
          {view && <span className={`rounded border px-2 py-1 text-[10px] ${view.state === "blocked" ? "border-red-400/30 bg-red-500/10 text-red-200" : view.state === "active" ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-200" : "border-white/10 text-obs-subtle"}`}>{STATE_LABEL[view.state] || view.state}</span>}
          {view?.checksum && <span className="max-w-[310px] truncate font-mono text-[10px] text-obs-faint" title={view.checksum}>{view.checksum}</span>}
          {graph && <span className="ml-auto text-[10px] text-obs-subtle">{graph.nodes.length} nodes · {graph.edges.length} edges</span>}
        </div>
      </div>

      <div className="relative flex-1 overflow-hidden" id="graph-bundle-v3-canvas">
        {!personaSlug && <div className="absolute inset-0 flex items-center justify-center text-sm text-obs-subtle">Selecione uma persona para visualizar o GraphBundle v3.</div>}
        {loading && <div className="absolute inset-0 z-20 flex items-center justify-center bg-obs-base/40 text-sm text-obs-subtle">Carregando GraphBundle v3...</div>}
        {error && <div className="absolute left-1/2 top-4 z-30 -translate-x-1/2 rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-xs text-red-100">{error}</div>}
        {view?.validation_errors.length ? <div className="absolute left-3 top-3 z-20 max-w-md rounded-lg border border-red-400/25 bg-red-500/10 px-3 py-2 text-[10px] text-red-100">Draft visível, mas bloqueado: {view.validation_errors.join(" · ")}</div> : null}
        {graph && view && (
          <GraphView
            key={`${view.ref}:${mode}`}
            rawNodes={graph.nodes}
            rawEdges={graph.edges}
            onNodeClick={(node) => setSelectedNode(node)}
            onSelectionChange={(nodes) => setSelectedNode(nodes.length === 1 ? nodes[0] : null)}
            mode={mode}
            searchQuery={searchQuery}
            showAllEdges={mode === "graph"}
            layoutScope={graphBundleLayoutScope(view)}
            readOnly
          />
        )}
        <GraphBundleNodeDrawer node={selectedNode} view={view} edges={graph?.edges || []} onClose={() => setSelectedNode(null)} />
        {selectedVersion?.updated_at && <span className="absolute bottom-3 left-3 z-10 rounded bg-obs-base/80 px-2 py-1 text-[9px] text-obs-faint">Atualizado em {new Date(selectedVersion.updated_at).toLocaleString("pt-BR")}</span>}
      </div>
    </div>
  );
}
