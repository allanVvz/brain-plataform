"use client";

import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GitBranch, Layers3, Network, Plus, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { ApiError, api } from "@/lib/api";
import { useGraphBundleDraft } from "@/lib/GraphBundleDraftProvider";
import { useGlobalPersona } from "@/lib/useGlobalPersona";
import {
  draftSnapshotToView,
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
  const personaSlug = useGlobalPersona().slug;
  const [catalog, setCatalog] = useState<GraphBundleVersionsPayload | null>(null);
  const [view, setView] = useState<GraphBundleViewPayload | null>(null);
  const [selectedNode, setSelectedNode] = useState<any | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [newNodeOpen, setNewNodeOpen] = useState(false);
  const [newNodeType, setNewNodeType] = useState("product");
  const [newNodeTitle, setNewNodeTitle] = useState("");
  const requestId = useRef(0);
  const drafts = useGraphBundleDraft();

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
    requestId.current += 1;
    setCatalog(null); setView(null); setSelectedNode(null); setError("");
  }, [personaSlug]);

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

  const effectiveView = useMemo(
    () => drafts.draft?.persona_slug === personaSlug && drafts.draft.state !== "published" ? draftSnapshotToView(drafts.draft) : view,
    [drafts.draft, personaSlug, view],
  );
  const graph = useMemo(() => effectiveView ? graphBundleToReactFlow(effectiveView) : null, [effectiveView]);
  const selectedVersion = catalog?.versions.find((item) => item.ref === view?.ref);
  const activeVersion = catalog?.versions.find((item) => item.state === "active");
  const beginEditing = async () => {
    if (!personaSlug || !activeVersion?.checksum) return;
    try { await drafts.ensureDraft(personaSlug, activeVersion.checksum, { surface: "graph" }); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Falha ao abrir rascunho."); }
  };
  const mutate = async (operations: any[], reason: string) => drafts.mutate(operations, reason, { surface: "graph" });
  const reviewAndPublish = async () => {
    try {
      if (!drafts.review) { await drafts.reviewDraft(); return; }
      await drafts.publishDraft("Publicação confirmada no editor unificado");
      await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Falha na revisão/publicação."); }
  };
  const addNode = async () => {
    const title = newNodeTitle.trim();
    if (!title) return;
    const slug = title.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || crypto.randomUUID();
    await mutate([{ op: "add_node", node: { id: `${newNodeType}:${crypto.randomUUID()}`, node_type: newNodeType, slug, title, summary: "", status: "pending_validation", tags: [], data: { source: "operator" } } }], "Node criado no grafo");
    setNewNodeTitle(""); setNewNodeOpen(false);
  };
  const connectNodes = async (source: string, target: string) => {
    const bundleNodes = effectiveView?.document?.nodes || [];
    const sourceType = String(bundleNodes.find((node: any) => String(node.id) === source)?.node_type || "").toLowerCase();
    const targetType = String(bundleNodes.find((node: any) => String(node.id) === target)?.node_type || "").toLowerCase();
    if (["embed", "embedded", "gallery"].includes(sourceType)) throw new Error("Nodes finais só recebem conexões.");
    if (targetType === "persona") throw new Error("Persona é a raiz e não recebe conexões.");
    if (["embed", "embedded"].includes(targetType)) {
      if (sourceType !== "faq") throw new Error("Somente FAQ aprovada pode ser conectada ao Embedded.");
      await mutate([{ op: "approve_faq", node_id: source }], "FAQ aprovada e enviada ao RAG");
      return;
    }
    const relation = targetType === "gallery" ? (sourceType === "asset" ? "gallery_asset" : "publishes_to") : "contains";
    await mutate([{ op: "add_edge", edge: { id: `edge:${source}:${relation}:${target}`, source, target, relation_type: relation, weight: 1, metadata: { active: true } } }], "Conexão criada no grafo");
  };
  return (
    <div className="flex h-[calc(100vh-96px)] -mx-6 -mt-6 flex-col overflow-hidden">
      <div className="shrink-0 space-y-2 border-b border-white/06 px-6 py-2.5 glass">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-obs-text">Grafo de Conhecimento</span>
          <span className="rounded-md bg-obs-violet/20 px-2 py-1 text-[11px] text-obs-violet">GraphBundle v3</span>
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
            <span className="text-[10px] text-obs-subtle">{effectiveView?.read_only === false ? `Rascunho · revisão ${drafts.draft?.revision}` : "Publicação ativa · layout local"}</span>
            {effectiveView?.read_only !== false ? (
              <button type="button" onClick={beginEditing} disabled={!activeVersion?.checksum || drafts.busy} className="rounded-lg bg-obs-violet px-3 py-1.5 text-[11px] font-medium text-white disabled:opacity-40">Editar grafo</button>
            ) : (
              <><button type="button" onClick={() => setNewNodeOpen(true)} disabled={drafts.busy} className="flex items-center gap-1 rounded-lg border border-obs-violet/30 px-3 py-1.5 text-[11px] text-obs-violet disabled:opacity-40"><Plus size={12} />Novo node</button><button type="button" onClick={reviewAndPublish} disabled={drafts.busy} className="rounded-lg bg-emerald-600 px-3 py-1.5 text-[11px] font-medium text-white disabled:opacity-40">{drafts.review ? "Publicar revisão" : "Revisar e testar"}</button></>
            )}
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
          {effectiveView && <span className={`rounded border px-2 py-1 text-[10px] ${effectiveView.state === "blocked" ? "border-red-400/30 bg-red-500/10 text-red-200" : effectiveView.state === "active" ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-200" : "border-white/10 text-obs-subtle"}`}>{STATE_LABEL[effectiveView.state] || effectiveView.state}</span>}
          {effectiveView?.checksum && <span className="max-w-[310px] truncate font-mono text-[10px] text-obs-faint" title={effectiveView.checksum}>{effectiveView.checksum}</span>}
          {graph && <span className="ml-auto text-[10px] text-obs-subtle">{graph.nodes.length} nodes · {graph.edges.length} edges</span>}
        </div>
      </div>

      <div className="relative flex-1 overflow-hidden" id="graph-bundle-v3-canvas">
        {!personaSlug && <div className="absolute inset-0 flex items-center justify-center text-sm text-obs-subtle">Selecione uma persona para visualizar o GraphBundle v3.</div>}
        {loading && <div className="absolute inset-0 z-20 flex items-center justify-center bg-obs-base/40 text-sm text-obs-subtle">Carregando GraphBundle v3...</div>}
        {error && <div className="absolute left-1/2 top-4 z-30 -translate-x-1/2 rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-xs text-red-100">{error}</div>}
        {(drafts.error || effectiveView?.validation_errors.length) ? <div className="absolute left-3 top-3 z-20 max-w-md rounded-lg border border-red-400/25 bg-red-500/10 px-3 py-2 text-[10px] text-red-100">{drafts.error || `Draft bloqueado: ${effectiveView?.validation_errors.join(" · ")}`}</div> : null}
        {drafts.draft?.change_summary?.faq_nodes_requiring_review?.length ? <div className="absolute right-3 top-14 z-20 max-w-sm rounded-lg border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-[10px] text-amber-100">{drafts.draft.change_summary.faq_nodes_requiring_review.length} FAQ(s) derivada(s) voltaram para revisão. Ajuste e aprove no Golden Dataset antes de publicar.</div> : null}
        {drafts.review && effectiveView?.read_only === false && <div className={`absolute left-3 top-3 z-20 max-w-md rounded-lg border px-3 py-2 text-[10px] ${drafts.review.validation_errors.length ? "border-red-400/25 bg-red-500/10 text-red-100" : "border-emerald-400/25 bg-emerald-500/10 text-emerald-100"}`}>{drafts.review.validation_errors.length ? drafts.review.validation_errors.join(" · ") : `Diff e previews de agente, catálogo e site validados. ${Object.keys(drafts.review.diff || {}).length} seção(ões) alterada(s).`}</div>}
        {newNodeOpen && <div className="absolute right-3 top-3 z-40 w-80 space-y-2 rounded-xl border border-obs-violet/30 bg-obs-raised p-3 shadow-xl"><p className="text-xs font-semibold text-obs-text">Novo node</p><select value={newNodeType} onChange={(event) => setNewNodeType(event.target.value)} className="lg-input w-full text-xs">{["brand", "campaign", "product", "audience", "tone", "rule", "copy", "faq", "asset", "tag", "knowledge_item"].map((type) => <option key={type} value={type}>{type}</option>)}</select><input autoFocus value={newNodeTitle} onChange={(event) => setNewNodeTitle(event.target.value)} placeholder="Título" className="lg-input w-full text-xs" /><div className="flex gap-2"><button type="button" onClick={addNode} disabled={!newNodeTitle.trim() || drafts.busy} className="rounded-md bg-obs-violet px-3 py-1.5 text-xs text-white disabled:opacity-40">Criar</button><button type="button" onClick={() => setNewNodeOpen(false)} className="rounded-md border border-white/10 px-3 py-1.5 text-xs">Cancelar</button></div></div>}
        {graph && effectiveView && (
          <GraphView
            key={`${effectiveView.ref}:${effectiveView.checksum}:${mode}`}
            rawNodes={graph.nodes}
            rawEdges={graph.edges}
            onNodeClick={(node) => setSelectedNode(node)}
            onSelectionChange={(nodes) => setSelectedNode(nodes.length === 1 ? nodes[0] : null)}
            mode={mode}
            searchQuery={searchQuery}
            showAllEdges={mode === "graph"}
            layoutScope={graphBundleLayoutScope(effectiveView)}
            readOnly={effectiveView.read_only}
            onConnectNodes={connectNodes}
            onDeleteEdge={async (edgeId) => { await mutate([{ op: "revoke_edge", edge_id: edgeId }], "Conexão removida do grafo"); }}
          />
        )}
        <GraphBundleNodeDrawer node={selectedNode} view={effectiveView} edges={graph?.edges || []} editable={effectiveView?.read_only === false} busy={drafts.busy} onSave={(nodeId, patch) => mutate([{ op: "update_node", node_id: nodeId, patch }], "Node atualizado no grafo").then(() => undefined)} onArchive={(nodeId) => mutate([{ op: "archive_node", node_id: nodeId }], "Node arquivado no grafo").then(() => setSelectedNode(null))} onClose={() => setSelectedNode(null)} />
        {selectedVersion?.updated_at && <span className="absolute bottom-3 left-3 z-10 rounded bg-obs-base/80 px-2 py-1 text-[9px] text-obs-faint">Atualizado em {new Date(selectedVersion.updated_at).toLocaleString("pt-BR")}</span>}
      </div>
    </div>
  );
}
