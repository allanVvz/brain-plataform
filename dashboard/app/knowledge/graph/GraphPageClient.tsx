"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, api } from "@/lib/api";
import {
  RefreshCw,
  Search,
  Network,
  GitBranch,
  Tag as TagIcon,
  AtSign,
  Database,
  Crosshair,
  Layers3,
  Plus,
  X,
} from "lucide-react";
import NodeDrawer from "@/components/graph/NodeDrawer";
import { getVisualHierarchyRank } from "@/components/graph/knowledgeGraphLayout";
import { parseGraphJsonV2Payload } from "@/lib/graph-json-v2";
import SofiaChatPanel, { SofiaChatMessage } from "./SofiaChatPanel";
import { resolveSofiaToolFromInput, SOFIA_REACT_FLOW_TOOLS } from "./sofiaReactFlowTools";
import { chooseAddBlockParent, compatibleParentTypes, relationForParentChild } from "./graphParenting";

const GraphView = dynamic(() => import("@/components/graph/GraphView"), { ssr: false });

type ViewMode = "layered" | "semantic_tree" | "graph";

interface RegistryNodeType {
  node_type: string;
  label?: string;
  level?: number;
  importance?: number;
  color?: string;
  icon?: string;
  sort_order?: number;
}

interface FocusInfo {
  node_id: string;
  node_type?: string;
  slug?: string;
  title?: string;
}

interface FocusPathStep {
  node_id: string;
  slug?: string;
  title?: string;
  node_type?: string;
  direction?: string | null;
}

interface GraphPayload {
  nodes: any[];
  edges: any[];
  meta: {
    total_personas?: number;
    total_items?: number;
    ki_items?: number;
    kb_entries?: number;
    semantic_nodes?: number;
    semantic_edges?: number;
    focus?: FocusInfo | null;
    focus_path?: FocusPathStep[];
    applied_filters?: Record<string, unknown>;
    registry?: {
      node_types?: RegistryNodeType[];
    };
  };
}

interface GraphFilterOption {
  value: string;
  label: string;
  nodeType: string;
  level: number;
  confidence: number;
}

const MODES: { value: ViewMode; label: string; icon: React.ReactNode; help: string }[] = [
  { value: "semantic_tree", label: "Tree",       icon: <GitBranch size={11} />, help: "Hierarquia automatica por aresta principal" },
  { value: "graph",         label: "Grafo",     icon: <Network size={11} />,   help: "Rede organica estilo Obsidian/neural" },
];
function applySofiaGraphPatch(base: GraphPayload, patch: any, persisted: boolean): GraphPayload {
  const nodeById = new Map((base.nodes || []).map((node) => [node.id, node]));
  const edgeById = new Map((base.edges || []).map((edge) => [edge.id, edge]));
  const markNode = (node: any) => ({
    ...node,
    data: {
      ...(node?.data || {}),
      pending_visual: !persisted,
      metadata: { ...(node?.data?.metadata || {}), pending_visual: !persisted },
    },
  });
  const markEdge = (edge: any) => ({
    ...edge,
    data: {
      ...(edge?.data || {}),
      pending_visual: !persisted,
      metadata: { ...(edge?.data?.metadata || {}), pending_visual: !persisted },
    },
  });
  const operations = Array.isArray(patch?.operations) ? patch.operations : [];
  for (const op of operations) {
    const kind = String(op?.kind || "").toLowerCase();
    if (kind === "upsert_node" && op?.node?.id) nodeById.set(op.node.id, { ...(nodeById.get(op.node.id) || {}), ...markNode(op.node) });
    if (kind === "remove_node") nodeById.delete(String(op.node_id || ""));
    if (kind === "upsert_edge" && op?.edge?.id) edgeById.set(op.edge.id, { ...(edgeById.get(op.edge.id) || {}), ...markEdge(op.edge) });
    if (kind === "remove_edge") edgeById.delete(String(op.edge_id || ""));
  }
  for (const node of Array.isArray(patch?.nodes) ? patch.nodes : []) if (node?.id) nodeById.set(node.id, { ...(nodeById.get(node.id) || {}), ...markNode(node) });
  for (const edge of Array.isArray(patch?.edges) ? patch.edges : []) if (edge?.id) edgeById.set(edge.id, { ...(edgeById.get(edge.id) || {}), ...markEdge(edge) });
  for (const nodeId of Array.isArray(patch?.remove_node_ids) ? patch.remove_node_ids : []) nodeById.delete(String(nodeId));
  for (const edgeId of Array.isArray(patch?.remove_edge_ids) ? patch.remove_edge_ids : []) edgeById.delete(String(edgeId));
  return { ...base, nodes: Array.from(nodeById.values()), edges: Array.from(edgeById.values()) };
}

function normalizeToolName(raw: unknown): string {
  return String(raw || "").toLowerCase().replace(/-/g, "_");
}

function parseToolArgs(call: any): Record<string, any> {
  const raw = call?.args ?? call?.arguments ?? call?.input ?? {};
  if (raw && typeof raw === "object") return raw;
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  }
  return {};
}
export default function GraphPageClient() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [personas, setPersonas] = useState<any[]>([]);
  const [data, setData] = useState<GraphPayload | null>(null);
  // Raw canonical graph_json document. Edits are applied to this document and
  // re-published, which triggers the backend reindex of derived tables.
  const [docGraph, setDocGraph] = useState<any | null>(null);
  const [docVersion, setDocVersion] = useState(0);
  const [loading, setLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState<any>(null);
  const [selectedNodes, setSelectedNodes] = useState<any[]>([]);
  const [addPanelOpen, setAddPanelOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [headerPersonaSlug, setHeaderPersonaSlug] = useState("");
  const [personaSummaries, setPersonaSummaries] = useState<any[]>([]);
  const [graphNotice, setGraphNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [sofiaOpen, setSofiaOpen] = useState(true);
  const [sofiaLoading, setSofiaLoading] = useState(false);
  const [sofiaMessages, setSofiaMessages] = useState<SofiaChatMessage[]>([]);
  const [hasPendingVisualChanges, setHasPendingVisualChanges] = useState(false);
  const [pendingGraphSnapshot, setPendingGraphSnapshot] = useState<GraphPayload | null>(null);
  const [sharedSessionId, setSharedSessionId] = useState<string | null>(null);
  const [sharedPlanJson, setSharedPlanJson] = useState<any | null>(null);
  const graphLoadRequestId = useRef(0);

  // ── URL-driven state ──────────────────────────────────────────
  const focus = searchParams.get("focus") || "";
  const requestedMode = searchParams.get("mode");
  const mode: ViewMode =
    requestedMode === "graph" || requestedMode === "layered"
      ? requestedMode
      : "semantic_tree";
  const includeTags = searchParams.get("tags") === "1";
  const includeMentions = searchParams.get("mentions") === "1";
  const includeTechnical = searchParams.get("tech") === "1";
  const includeEmbedded = searchParams.get("embedded") !== "0";
  const showAllEdges = searchParams.get("all_edges") === "1" || searchParams.get("primary_edges") === "0";
  const branchDistance = Number(searchParams.get("distance") || 48);

  const updateParam = useCallback(
    (patch: Record<string, string | number | boolean | null>) => {
      const next = new URLSearchParams(searchParams.toString());
      for (const [k, v] of Object.entries(patch)) {
        if (v === null || v === false || v === "") next.delete(k);
        else next.set(k, String(v));
      }
      router.replace(`/knowledge/graph${next.toString() ? `?${next}` : ""}`);
    },
    [router, searchParams],
  );

  const viewModeHref = useCallback(
    (nextMode: ViewMode) => {
      const next = new URLSearchParams(searchParams.toString());
      next.set("mode", nextMode);
      next.delete("focus");
      return `/knowledge/graph?${next.toString()}`;
    },
    [searchParams],
  );

  useEffect(() => {
    const syncFromHeader = () => {
      const stored = window.localStorage.getItem("ai-brain-persona-slug") || "";
      // Clear tenant-owned state synchronously with the global persona event.
      // Waiting for the next effect/fetch leaves the previous graph visible
      // while the new persona document is in flight.
      graphLoadRequestId.current += 1;
      setDocGraph(null);
      setDocVersion(0);
      setData({ nodes: [], edges: [], meta: {} } as GraphPayload);
      setSelectedNode(null);
      setSelectedNodes([]);
      setGraphNotice(null);
      setHeaderPersonaSlug(stored);
    };
    syncFromHeader();
    window.addEventListener("ai-brain-persona-change", syncFromHeader as EventListener);
    return () => window.removeEventListener("ai-brain-persona-change", syncFromHeader as EventListener);
  }, []);

  useEffect(() => {
    const sessionId = window.localStorage.getItem("active_criar_session_id");
    if (!sessionId) return;
    setSharedSessionId(sessionId);
    api.kbIntakeSession(sessionId)
      .then((session: any) => {
        const planJson = session?.plan_json || session?.state?.plan_json || null;
        if (planJson) setSharedPlanJson(planJson);
      })
      .catch(() => {
        // Graph sidebar keeps working even if no active CRIAR session exists.
      });
  }, []);

  const load = useCallback(async () => {
    const requestId = ++graphLoadRequestId.current;
    setLoading(true);
    const emptyPayload = { nodes: [], edges: [], meta: {} } as GraphPayload;
    // Clear tenant-owned state before awaiting the next persona document. This
    // prevents even a transient render of the previous client's graph.
    setDocGraph(null);
    setDocVersion(0);
    setData(emptyPayload);
    setSelectedNode(null);
    setSelectedNodes([]);
    setGraphNotice(null);
    try {
      if (!headerPersonaSlug) {
        const catalog = await api.knowledgeCatalog().catch(() => ({ catalogs: [] }));
        if (requestId !== graphLoadRequestId.current) return emptyPayload;
        setPersonaSummaries(catalog?.catalogs || []);
        return emptyPayload;
      }
      setPersonaSummaries([]);
      const currentDoc = await api.getGraphDocument(headerPersonaSlug);
      if (requestId !== graphLoadRequestId.current) return emptyPayload;
      const parsed = parseGraphJsonV2Payload(currentDoc);
      if (parsed) {
        const v2Payload = parsed as GraphPayload;
        setGraphNotice(null);
        setDocGraph(currentDoc?.graph_json || currentDoc?.document?.graph_json || null);
        setDocVersion(Number(currentDoc?.version || currentDoc?.document?.version || 0));
        setData(v2Payload);
        return v2Payload;
      }
      setGraphNotice({ tone: "error", text: "Nenhum Graph JSON v2 publicado para esta persona." });
      return emptyPayload;
    } catch (error) {
      if (requestId !== graphLoadRequestId.current) return emptyPayload;
      // A persona pode existir sem um documento canônico publicado. Sempre
      // descarte o payload anterior para não exibir o grafo de outro cliente.
      setPersonaSummaries([]);
      setGraphNotice({
        tone: "error",
        text: error instanceof ApiError && error.status === 404
          ? "Nenhum Graph JSON v2 publicado para esta persona."
          : error instanceof Error
            ? error.message
            : "Falha ao carregar o Graph JSON desta persona.",
      });
      return emptyPayload;
    } finally {
      if (requestId === graphLoadRequestId.current) setLoading(false);
    }
  }, [headerPersonaSlug]);

  // Write-through: apply an edit to the canonical graph_json and re-publish it.
  // The backend validates the whole document and reindexes the derived tables.
  const publishEditedGraph = useCallback(
    async (mutate: (graph: any) => void, successText: string): Promise<boolean> => {
      if (!docGraph || !headerPersonaSlug) {
        setGraphNotice({ tone: "error", text: "Documento canônico do grafo indisponível para edição." });
        return false;
      }
      const next = JSON.parse(JSON.stringify(docGraph));
      mutate(next);
      try {
        await api.commitGraphDocument({
          persona_slug: headerPersonaSlug,
          brand_slug: next.brand_slug ?? null,
          graph_json: next,
          source: "graph_ui",
          reason: successText,
          expected_version: docVersion,
          idempotency_key: `graph-ui:${headerPersonaSlug}:${crypto.randomUUID()}`,
        });
        await load();
        setGraphNotice({ tone: "success", text: successText });
        window.setTimeout(() => setGraphNotice(null), 2200);
        return true;
      } catch (error) {
        setGraphNotice({
          tone: "error",
          text: error instanceof Error ? error.message : "Falha ao publicar a alteração no grafo.",
        });
        return false;
      }
    },
    [docGraph, docVersion, headerPersonaSlug, load],
  );

  useEffect(() => {
    api.personas().then((p: any) => setPersonas(p));
  }, []);

  useEffect(() => { load(); }, [load]);

  // Refresh node selection when payload changes (so drawer shows fresh data).
  useEffect(() => {
    if (!selectedNode || !data) return;
    const fresh = data.nodes.find((n) => n.id === selectedNode.id);
    if (fresh) setSelectedNode(fresh);
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  const focusNode = data?.meta?.focus || null;
  const focusPath = data?.meta?.focus_path || [];
  const effectivePersonaSlug = headerPersonaSlug;
  const effectivePersona = useMemo(
    () => personas.find((p) => p.slug === effectivePersonaSlug) || null,
    [personas, effectivePersonaSlug],
  );

  const graphFilterOptions = useMemo<GraphFilterOption[]>(() => {
    if (!data) return [];
    const unique = new Map<string, GraphFilterOption>();
    for (const node of data.nodes || []) {
      const d = node?.data || {};
      const nodeType = String(d.node_type || "").toLowerCase();
      if (!nodeType || ["persona", "tag", "mention", "knowledge_item", "kb_entry"].includes(nodeType)) continue;
      const slug = String(d.slug || "");
      if (!slug) continue;
      const key = `${nodeType}:${slug}`;
      if (unique.has(key)) continue;
      unique.set(key, {
        value: key,
        label: String(d.label || slug),
        nodeType,
        level: getVisualHierarchyRank(nodeType),
        confidence: typeof d.confidence === "number" ? d.confidence : 0,
      });
    }
    return Array.from(unique.values()).sort((a, b) => {
      if (a.level !== b.level) return a.level - b.level;
      if (b.confidence !== a.confidence) return b.confidence - a.confidence;
      if (a.nodeType !== b.nodeType) return a.nodeType.localeCompare(b.nodeType);
      return a.label.localeCompare(b.label);
    });
  }, [data]);

  const selectedDirectLinks = useMemo(() => {
    if (!data || !selectedNode) return [];
    const byId = new Map((data.nodes || []).map((node) => [node.id, node]));
    return (data.edges || [])
      .filter((edge) => edge.source === selectedNode.id || edge.target === selectedNode.id)
      .map((edge) => {
        const outbound = edge.source === selectedNode.id;
        const otherId = outbound ? edge.target : edge.source;
        const other = byId.get(otherId);
        return {
          id: edge.id,
          direction: (outbound ? "out" : "in") as "out" | "in",
          other_id: otherId,
          other_label: other?.data?.label || otherId,
          other_type: other?.data?.node_type || other?.data?.content_type || "node",
          other_summary: other?.data?.content_preview || other?.data?.description || "",
          other_level: getVisualHierarchyRank(String(other?.data?.node_type || other?.data?.content_type || "node")),
        };
      })
      .sort((a, b) => {
        if (a.other_level !== b.other_level) return a.other_level - b.other_level;
        if (a.other_type !== b.other_type) return String(a.other_type).localeCompare(String(b.other_type));
        return String(a.other_label).localeCompare(String(b.other_label));
      });
  }, [data, selectedNode]);

  const onFocusNode = useCallback(
    (node: any) => {
      const data = node.data || {};
      const slug = data.slug;
      const ntype = data.node_type;
      if (slug && ntype) {
        updateParam({ focus: `${ntype}:${slug}` });
      } else if (node.id?.startsWith("gn:")) {
        updateParam({ focus: node.id.slice(3) });
      }
    },
    [updateParam],
  );

  const onClearFocus = useCallback(() => {
    updateParam({ focus: null });
  }, [updateParam]);

  const handleConnectNodes = useCallback(
    async (sourceId: string, targetId: string) => {
      const byId = new Map((data?.nodes || []).map((node) => [node.id, node]));
      const targetNode = byId.get(targetId);
      const targetType = String(targetNode?.data?.node_type || targetNode?.data?.content_type || "");

      // V2 write-through: add the edge to the canonical graph_json and re-publish.
      // The backend validator enforces the graph law (FAQ->Embedded, etc.) and the
      // publish reindex updates the derived tables.
      if (docGraph) {
        const relation =
          ["gallery", "embedded", "marketing_workspace"].includes(targetType)
            ? "publishes_to"
            : targetType === "faq" ? "answers" : "contains";
        const finalReceiver = ["gallery", "embedded", "marketing_workspace"].includes(targetType);
        await publishEditedGraph((graph) => {
          graph.edges = Array.isArray(graph.edges) ? graph.edges : [];
          graph.edges.push({
            id: `edge:ui:${Date.now()}`,
            source: sourceId,
            target: targetId,
            relation,
            relation_type: relation,
            relation_class: relation === "publishes_to" ? "publication" : relation === "contains" ? "hierarchy" : "semantic",
            primary_tree: !finalReceiver,
            lifecycle: { status: "active" },
            ...(relation === "publishes_to" ? {
              grant: {
                mode: "manual",
                reason: "Publicação manual pela interface do grafo",
              },
            } : {}),
            metadata: { created_from: "graph_ui", active: true },
          });
        }, targetType === "embedded" ? "FAQ publicado no Golden Dataset." : "Conexão criada.");
        return;
      }
      setGraphNotice({ tone: "error", text: "Edicao do Graph requer documento Graph JSON v2 publicado." });
      return;
    },
    [data?.nodes, docGraph, publishEditedGraph],
  );

  const handleDeleteEdge = useCallback(
    async (edgeId: string) => {
      const rawEdgeId = String(edgeId || "");

      // V2 write-through: drop the edge from the canonical graph_json and re-publish.
      if (docGraph) {
        await publishEditedGraph((graph) => {
          const edge = (Array.isArray(graph.edges) ? graph.edges : []).find(
            (item: any) => String(item?.id) === rawEdgeId,
          );
          if (edge) edge.lifecycle = { ...(edge.lifecycle || {}), status: "revoked" };
        }, "Conexão apagada.");
        return;
      }
      setGraphNotice({ tone: "error", text: "Exclusao de aresta requer documento Graph JSON v2 publicado." });
      return;
    },
    [docGraph, publishEditedGraph],
  );

  const handleDeleteNode = useCallback(
    async (nodeId: string) => {
      if (!docGraph) {
        setGraphNotice({ tone: "error", text: "Exclusao de node requer documento Graph JSON v2 publicado." });
        return;
      }
      const node = data?.nodes?.find((item) => item.id === nodeId);
      if (!node) {
        setGraphNotice({ tone: "error", text: "Este card nao pode ser apagado pela UI." });
        return;
      }
      const nodeType = String(node?.data?.node_type || "");
      if (["persona", "embedded", "gallery", "marketing_workspace"].includes(nodeType) || node?.data?.protected) {
        setGraphNotice({ tone: "error", text: "Este node e protegido e nao pode ser excluido." });
        return;
      }
      try {
        await publishEditedGraph((graph) => {
          const item = (Array.isArray(graph.nodes) ? graph.nodes : []).find(
            (candidate: any) => String(candidate?.id) === nodeId,
          );
          if (item) item.lifecycle = { ...(item.lifecycle || {}), status: "archived" };
          for (const edge of Array.isArray(graph.edges) ? graph.edges : []) {
            if (String(edge?.source) === nodeId || String(edge?.target) === nodeId) {
              edge.lifecycle = { ...(edge.lifecycle || {}), status: "revoked" };
            }
          }
        }, "Card apagado.");
        if (selectedNode?.id === nodeId) setSelectedNode(null);
      } catch (error) {
        setGraphNotice({
          tone: "error",
          text: error instanceof Error ? error.message : "Nao foi possivel apagar o card.",
        });
      }
    },
    [data?.nodes, docGraph, publishEditedGraph, selectedNode?.id],
  );

  const appendSofiaMessage = useCallback((role: SofiaChatMessage["role"], text: string, pending = false) => {
    setSofiaMessages((current) => [
      ...current,
      { id: `${Date.now()}-${Math.random()}`, role, text, pending, createdAt: Date.now() },
    ]);
  }, []);

  const handleSofiaSubmit = useCallback(async (text: string) => {
    if (!data) return;
    appendSofiaMessage("user", text);
    setSofiaLoading(true);
    try {
      const resolvedTool = resolveSofiaToolFromInput(text);
      const command = resolvedTool
        ? SOFIA_REACT_FLOW_TOOLS[resolvedTool.tool].command({
            message: text,
            personaSlug: effectivePersonaSlug || undefined,
            value: resolvedTool.value,
          })
        : SOFIA_REACT_FLOW_TOOLS.apply_patch_visual.command({
            message: text,
            personaSlug: effectivePersonaSlug || undefined,
          });
      const response = await api.sofiaGraphCommand({
        action: "command",
        message: command,
        persona_slug: effectivePersonaSlug || undefined,
        active_persona_slug: effectivePersonaSlug || undefined,
        selected_node_id: selectedNode?.id || null,
        selected_node_ids: selectedNodes.map((node) => String(node.id)).filter(Boolean),
        session_id: sharedSessionId || undefined,
        plan_json: sharedPlanJson || undefined,
      });
      if (response?.session_id && response.session_id !== sharedSessionId) {
        setSharedSessionId(String(response.session_id));
        window.localStorage.setItem("active_criar_session_id", String(response.session_id));
      }
      if (response?.plan_json) setSharedPlanJson(response.plan_json);
      const persisted = Boolean(response?.persisted);
      const replyText = String(response?.sofia_message || response?.text || response?.message || response?.reply || "Comando processado.");
      const toolCalls = Array.isArray(response?.tool_calls) ? response.tool_calls : [];
      let patch = response?.patch || response?.graph_patch || null;
      let shouldHighlight = false;
      let shouldSelect: string | null = null;
      let shouldFocus: string | null = null;
      let shouldSwitchToTree = false;
      for (const call of toolCalls) {
        const tool = normalizeToolName(call?.tool || call?.name);
        const args = parseToolArgs(call);
        if (tool === "apply_patch_visual" && !patch && args?.patch) patch = args.patch;
        if (tool === "highlight_edges") shouldHighlight = true;
        if (tool === "select_node" && !shouldSelect) shouldSelect = String(args?.slug_or_id || args?.node_id || args?.id || "").trim() || null;
        if (tool === "focus_node" && !shouldFocus) shouldFocus = String(args?.slug_or_id || args?.node_id || args?.id || "").trim() || null;
        if (tool === "update_layout") shouldSwitchToTree = true;
      }
      if (patch) {
        if (!persisted && !pendingGraphSnapshot) setPendingGraphSnapshot(data);
        setData((current) => (current ? applySofiaGraphPatch(current, patch, persisted) : current));
        setHasPendingVisualChanges(!persisted);
        if (!persisted) {
          appendSofiaMessage("system", SOFIA_REACT_FLOW_TOOLS.mark_pending.command({ personaSlug: effectivePersonaSlug || undefined }));
        }
      }
      if (shouldSwitchToTree) updateParam({ mode: "semantic_tree" });
      if (shouldHighlight) setGraphNotice({ tone: "success", text: "Arestas destacadas para revisao." });
      if (shouldSelect && data) {
        const lookup = shouldSelect.toLowerCase();
        const found = (data.nodes || []).find((n) => {
          const id = String(n?.id || "").toLowerCase();
          const slug = String(n?.data?.slug || "").toLowerCase();
          return id === lookup || slug === lookup || id.endsWith(`:${lookup}`);
        });
        if (found) {
          setSelectedNodes([found]);
          setSelectedNode(found);
        }
      }
      if (shouldFocus) {
        const lookup = shouldFocus.toLowerCase();
        const found = (data?.nodes || []).find((n) => {
          const id = String(n?.id || "").toLowerCase();
          const slug = String(n?.data?.slug || "").toLowerCase();
          return id === lookup || slug === lookup || id.endsWith(`:${lookup}`);
        });
        if (found) onFocusNode(found);
      }
      appendSofiaMessage("sofia", replyText, !persisted);
      if (persisted) {
        setPendingGraphSnapshot(null);
        setHasPendingVisualChanges(false);
        await load();
      }
    } catch (error) {
      appendSofiaMessage("system", error instanceof Error ? error.message : "Falha ao enviar comando.");
    } finally {
      setSofiaLoading(false);
    }
  }, [appendSofiaMessage, data, effectivePersonaSlug, load, onFocusNode, pendingGraphSnapshot, selectedNode?.id, selectedNodes, sharedPlanJson, sharedSessionId, updateParam]);

  const handleConfirmPending = useCallback(async () => {
    setSofiaLoading(true);
    try {
      const response = await api.sofiaGraphCommand({
        action: "confirm_pending",
        message: SOFIA_REACT_FLOW_TOOLS.confirm_pending.command({ personaSlug: effectivePersonaSlug || undefined }),
        persona_slug: effectivePersonaSlug || undefined,
        session_id: sharedSessionId || undefined,
        plan_json: sharedPlanJson || undefined,
      });
      if (response?.plan_json) setSharedPlanJson(response.plan_json);
      appendSofiaMessage("sofia", String(response?.text || response?.message || "Alteracoes confirmadas."));
      setPendingGraphSnapshot(null);
      setHasPendingVisualChanges(false);
      await load();
    } catch (error) {
      appendSofiaMessage("system", error instanceof Error ? error.message : "Falha ao confirmar pendencias.");
    } finally {
      setSofiaLoading(false);
    }
  }, [appendSofiaMessage, effectivePersonaSlug, load, sharedPlanJson, sharedSessionId]);

  const handleUndoPending = useCallback(async () => {
    try {
      await api.sofiaGraphCommand({
        action: "undo_pending",
        message: SOFIA_REACT_FLOW_TOOLS.undo_pending.command({ personaSlug: effectivePersonaSlug || undefined }),
        persona_slug: effectivePersonaSlug || undefined,
        session_id: sharedSessionId || undefined,
        plan_json: sharedPlanJson || undefined,
      });
    } catch {
      // rollback local mantido mesmo sem suporte backend.
    }
    if (pendingGraphSnapshot) setData(pendingGraphSnapshot);
    setPendingGraphSnapshot(null);
    setHasPendingVisualChanges(false);
    appendSofiaMessage("system", "Alteracoes visuais pendentes desfeitas.");
  }, [appendSofiaMessage, effectivePersonaSlug, pendingGraphSnapshot, sharedPlanJson, sharedSessionId]);

  const sharedPlanSummary = useMemo(() => {
    if (!sharedPlanJson || typeof sharedPlanJson !== "object") return null;
    const ctx = sharedPlanJson.active_context || {};
    const blocking = Array.isArray(sharedPlanJson.blocking_issues) ? sharedPlanJson.blocking_issues.length : 0;
    const queue = Array.isArray(sharedPlanJson.graph_patch_queue) ? sharedPlanJson.graph_patch_queue.length : 0;
    return {
      persona: String(sharedPlanJson.persona_slug || effectivePersonaSlug || ""),
      brand: ctx.brand_slug ? String(ctx.brand_slug) : null,
      selectedNodeId: ctx.selected_node_id ? String(ctx.selected_node_id) : null,
      queueSize: queue,
      blockingCount: blocking,
    };
  }, [effectivePersonaSlug, sharedPlanJson]);

  if (!headerPersonaSlug) {
    return (
      <div className="space-y-5">
        <div>
          <h1 className="text-xl font-semibold text-obs-text">Grafos de conhecimento</h1>
          <p className="mt-1 text-sm text-obs-subtle">
            Visão agregada das personas autorizadas. Selecione uma persona no topo para abrir e editar seu grafo.
          </p>
        </div>
        {loading && <div className="rounded-xl border border-white/06 p-8 text-center text-sm text-obs-subtle">Carregando grafos…</div>}
        {!loading && personaSummaries.length === 0 && (
          <div className="rounded-xl border border-dashed border-white/10 p-8 text-center text-sm text-obs-subtle">
            Nenhum Graph JSON v2 publicado no escopo autorizado.
          </div>
        )}
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {personaSummaries.map((catalog) => (
            <button
              key={catalog.persona.slug}
              type="button"
              onClick={() => window.dispatchEvent(new CustomEvent("ai-brain-persona-change", { detail: { id: catalog.persona.id, slug: catalog.persona.slug } }))}
              className="rounded-xl border border-white/06 bg-white/[0.025] p-4 text-left transition hover:border-obs-violet/35 hover:bg-obs-violet/[0.04]"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-obs-text">{catalog.persona.name}</p>
                  <p className="mt-0.5 text-[10px] uppercase tracking-[0.12em] text-obs-faint">{catalog.persona.slug}</p>
                </div>
                <span className="rounded-full bg-emerald-400/10 px-2 py-1 text-[10px] text-emerald-300">{catalog.graph.status}</span>
              </div>
              <div className="mt-4 grid grid-cols-3 gap-2 text-center">
                <div className="rounded-lg bg-white/[0.03] p-2"><p className="text-lg font-semibold text-obs-text">{catalog.graph.node_count}</p><p className="text-[9px] text-obs-faint">nodes</p></div>
                <div className="rounded-lg bg-white/[0.03] p-2"><p className="text-lg font-semibold text-obs-text">{catalog.graph.edge_count}</p><p className="text-[9px] text-obs-faint">edges</p></div>
                <div className="rounded-lg bg-white/[0.03] p-2"><p className="text-lg font-semibold text-obs-text">{catalog.embedded.faq_count}</p><p className="text-[9px] text-obs-faint">FAQs</p></div>
              </div>
              <p className="mt-3 truncate font-mono text-[10px] text-obs-faint">v{catalog.graph.version} · {catalog.graph.checksum}</p>
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100vh-96px)] -mx-6 -mt-6 overflow-hidden">
      {/* ── Top bar (3 rows) ──────────────────────────────────── */}
      <div className="px-6 py-2.5 border-b border-white/06 glass shrink-0 space-y-2">
        {/* Row 1: persona + mode + meta */}
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-obs-text">Grafo de Conhecimento</span>

          <div className="flex min-w-[320px] items-center gap-2 rounded-lg border border-white/08 bg-white/[0.04] px-2.5 py-1.5 shadow-sm">
            <Layers3 size={11} className="text-obs-subtle" />
            <select
              value={focus}
              onChange={(e) => updateParam({ focus: e.target.value || null })}
              aria-label="filtro-semantico-grafo"
              className="w-full bg-transparent text-xs font-medium text-obs-text outline-none"
              disabled={!effectivePersonaSlug || graphFilterOptions.length === 0}
            >
              <option className="bg-obs-raised text-obs-text" value="">
                {effectivePersona?.name ? `${effectivePersona.name} no centro` : "Centro: persona"}
              </option>
              {graphFilterOptions.map((option) => (
                <option className="bg-obs-raised text-obs-text" key={option.value} value={option.value}>
                  {`L${option.level} · ${option.nodeType} · ${option.label}${option.confidence > 0 ? ` · conf ${option.confidence.toFixed(2)}` : ""}`}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-1" role="tablist" aria-label="Visualização do grafo">
            {MODES.map((m) => (
              <a
                key={m.value}
                href={viewModeHref(m.value)}
                role="tab"
                aria-selected={mode === m.value}
                aria-controls="knowledge-graph-canvas"
                title={m.help}
                className={`flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border transition ${
                  mode === m.value
                    ? "bg-obs-violet/20 border-obs-violet text-obs-violet"
                    : "glass border-white/10 text-obs-subtle hover:text-obs-text"
                }`}
              >
                {m.icon}
                <span>{m.label}</span>
              </a>
            ))}
          </div>

          <div className="ml-auto flex items-center gap-3">
            {data?.meta && (
              <span className="text-[11px] text-obs-subtle">
                {data.nodes.length} nodes · {data.edges.length} edges
                {data.meta.semantic_nodes !== undefined && ` · ${data.meta.semantic_nodes} semânticos`}
              </span>
            )}
            <button
              onClick={load}
              disabled={loading}
              className="p-1.5 rounded-lg glass border border-white/06 text-obs-subtle hover:text-obs-text transition disabled:opacity-40"
            >
              <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
            </button>
          </div>
        </div>

        {/* Row 2: visual spacing + visibility toggles */}
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex min-w-[320px] items-center gap-3 rounded-lg border border-white/06 bg-obs-base/80 px-3 py-2">
            <span className="whitespace-nowrap text-[10px] uppercase tracking-wider text-obs-faint">Forca gravitacional</span>
            <input
              type="range"
              min={0}
              max={100}
              value={branchDistance}
              onChange={(e) => updateParam({ distance: Number(e.target.value) === 48 ? null : e.target.value })}
              className="h-1 flex-1 accent-obs-violet"
              aria-label="forca-gravitacional"
            />
            <span className="w-8 text-right text-[10px] text-obs-subtle">{branchDistance}</span>
          </div>

          <div className="flex items-center gap-1.5">
            <ToggleChip
              active={includeTags}
              onClick={() => updateParam({ tags: !includeTags ? "1" : null })}
              icon={<TagIcon size={10} />}
              label="Tags"
            />
            <ToggleChip
              active={includeMentions}
              onClick={() => updateParam({ mentions: !includeMentions ? "1" : null })}
              icon={<AtSign size={10} />}
              label="Mentions"
            />
            <ToggleChip
              active={includeTechnical}
              onClick={() => updateParam({ tech: !includeTechnical ? "1" : null })}
              icon={<Database size={10} />}
              label="Técnicos"
            />
          </div>

          <ToggleChip
            active={showAllEdges}
            onClick={() => updateParam({ all_edges: !showAllEdges ? "1" : null, primary_edges: null })}
            icon={<GitBranch size={10} />}
            label="Mostrar todas"
          />

          <ToggleChip
            active={includeEmbedded}
            onClick={() => updateParam({ embedded: includeEmbedded ? "0" : null })}
            icon={<Database size={10} />}
            label="Embedded"
          />

          {focusNode && (
            <div className="ml-auto flex items-center gap-2 px-2.5 py-1 rounded-md bg-obs-violet/10 border border-obs-violet/30">
              <Crosshair size={11} className="text-obs-violet" />
              <span className="text-[11px] text-obs-violet truncate max-w-[300px]">
                Foco: {focusNode.title || focusNode.slug || focusNode.node_type}
              </span>
              <button
                onClick={onClearFocus}
                className="text-[11px] text-obs-subtle hover:text-white"
                title="Limpar foco"
              >
                ✕
              </button>
            </div>
          )}
        </div>

        {/* Row 3: search + focus path breadcrumb */}
        <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 bg-obs-base border border-white/06 rounded-lg px-2 py-1 w-72">
            <Search size={11} className="text-obs-faint" />
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Buscar slug/título..."
              className="flex-1 bg-transparent text-xs text-obs-text placeholder-obs-faint focus:outline-none"
            />
          </div>

          {focusPath.length > 0 && (
            <div className="flex items-center gap-1 text-[11px] text-obs-subtle min-w-0 overflow-x-auto">
              {focusPath.map((step, i) => (
                <span key={`${step.node_id}-${i}`} className="flex items-center gap-1 shrink-0">
                  {i > 0 && <span className="text-obs-faint">→</span>}
                  <span
                    className="px-1.5 py-0.5 rounded border truncate max-w-[140px]"
                    style={{
                      borderColor: i === focusPath.length - 1 ? "rgba(167,139,250,0.6)" : "rgba(255,255,255,0.10)",
                      color: i === focusPath.length - 1 ? "#a78bfa" : undefined,
                    }}
                    title={`${step.node_type}:${step.slug}`}
                  >
                    {step.title || step.slug || step.node_type}
                  </span>
                </span>
              ))}
            </div>
          )}
        </div>

        {effectivePersona && (
          <div className="flex items-center gap-2 text-[11px] text-obs-subtle">
            <span className="rounded border border-obs-violet/30 bg-obs-violet/10 px-2 py-0.5 text-obs-violet">
              Persona central: {effectivePersona.name}
            </span>
            <span>Filtro semantico por nivel, tipo e confianca dentro da persona ativa.</span>
          </div>
        )}
      </div>

      {/* ── Graph canvas ─────────────────────────────────────── */}
      <div
        id="knowledge-graph-canvas"
        className="flex-1 relative overflow-hidden"
        role="tabpanel"
        aria-label={mode === "semantic_tree" ? "Visualização Tree" : "Visualização Grafo"}
      >
        <SofiaChatPanel
          open={sofiaOpen}
          loading={sofiaLoading}
          messages={sofiaMessages}
          hasPendingVisualChanges={hasPendingVisualChanges}
          sessionId={sharedSessionId}
          planSummary={sharedPlanSummary}
          onToggle={() => setSofiaOpen((v) => !v)}
          onSubmit={handleSofiaSubmit}
          onConfirmPending={handleConfirmPending}
          onUndoPending={handleUndoPending}
        />
        {loading && !data && (
          <div className="absolute inset-0 flex items-center justify-center text-obs-subtle text-sm">
            Carregando grafo...
          </div>
        )}

        {data && (
          <GraphView
            key={`${effectivePersonaSlug || "global"}:${mode}:${docGraph?.graph_id || data.nodes[0]?.id || "empty"}`}
            rawNodes={data.nodes}
            rawEdges={data.edges}
            onNodeClick={(node) => {
              setSelectedNode(node);
              setSelectedNodes([node]);
            }}
            onSelectionChange={(nodes) => {
              setSelectedNodes(nodes);
              if (nodes.length > 1) setSelectedNode(null);
            }}
            onConnectNodes={handleConnectNodes}
            onDeleteEdge={handleDeleteEdge}
            mode={mode}
            searchQuery={searchQuery}
            focusNodeId={focusNode?.node_id || null}
            showAllEdges={showAllEdges}
            branchDistance={branchDistance}
          />
        )}

        {graphNotice && (
          <div
            className={`absolute right-4 top-4 z-50 rounded-lg border px-3 py-2 text-xs shadow-lg ${
              graphNotice.tone === "success"
                ? "border-emerald-400/30 bg-emerald-500/12 text-emerald-200"
                : "border-red-400/35 bg-red-500/15 text-red-100"
            }`}
          >
            {graphNotice.text}
          </div>
        )}

        {/* Legend */}
        {data?.meta?.registry?.node_types && data.meta.registry.node_types.length > 0 && (
          <div className="absolute bottom-3 left-3 max-w-[280px] rounded-lg glass border border-white/06 p-2 text-[10px]">
            <div className="text-[9px] uppercase tracking-wider text-obs-faint mb-1">Tipos</div>
            <div className="flex flex-wrap gap-1">
              {data.meta.registry.node_types
                .filter((t) => !["tag", "mention", "knowledge_item", "kb_entry"].includes(t.node_type) || includeTags || includeMentions || includeTechnical)
                .sort((a, b) => getVisualHierarchyRank(a.node_type) - getVisualHierarchyRank(b.node_type))
                .map((t) => (
                  <span
                    key={t.node_type}
                    className="flex items-center gap-1 px-1.5 py-0.5 rounded border"
                    style={{ borderColor: `${t.color}40`, background: `${t.color}10`, color: t.color }}
                  >
                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: t.color }} />
                    {t.label || t.node_type}
                  </span>
                ))}
            </div>
          </div>
        )}

        {/* Drawer overlay */}
        <NodeDrawer
          node={selectedNode}
          selectedNodes={selectedNodes}
          personaSlug={effectivePersonaSlug || undefined}
          sessionId={sharedSessionId || undefined}
          onClose={() => {
            setSelectedNode(null);
            setSelectedNodes([]);
          }}
          onUpdated={load}
          focusPath={focusPath}
          directLinks={selectedDirectLinks}
          onFocusHere={() => selectedNode && onFocusNode(selectedNode)}
          onDeleteNode={handleDeleteNode}
          onDeleteEdge={handleDeleteEdge}
          onSelectNode={(nodeId) => {
            const next = (data?.nodes || []).find((n) => n.id === nodeId);
            if (next) {
              setSelectedNode(next);
              setSelectedNodes([next]);
            }
          }}
        />

        <button
          type="button"
          onClick={() => setAddPanelOpen(true)}
          className="absolute bottom-5 left-1/2 z-40 flex h-12 w-12 -translate-x-1/2 items-center justify-center rounded-full border border-obs-violet/45 bg-obs-violet/20 text-obs-violet shadow-obs-node transition hover:bg-obs-violet/30 hover:text-white"
          title="Adicionar bloco"
        >
          <Plus size={22} />
        </button>

        {addPanelOpen && (
          <AddBlockPanel
            nodes={data?.nodes || []}
            edges={data?.edges || []}
            persona={effectivePersona}
            selectedNode={selectedNode}
            onClose={() => setAddPanelOpen(false)}
            onCreated={async (created) => {
              setAddPanelOpen(false);
              await load();
              const graphNode = created?.graph_node;
              if (graphNode?.slug && graphNode?.node_type) {
                updateParam({ focus: `${graphNode.node_type}:${graphNode.slug}` });
              }
              setGraphNotice({ tone: "success", text: "Bloco criado e conectado." });
              window.setTimeout(() => setGraphNotice(null), 2200);
            }}
          />
        )}
      </div>
    </div>
  );
}

function AddBlockPanel({
  nodes,
  edges,
  persona,
  selectedNode,
  onClose,
  onCreated,
}: {
  nodes: any[];
  edges: any[];
  persona?: any;
  selectedNode?: any;
  onClose: () => void;
  onCreated: (created?: any) => void | Promise<void>;
}) {
  const nodeTypeOptions = [
    { value: "brand", label: "Brand" },
    { value: "campaign", label: "Campanha" },
    { value: "product", label: "Produto" },
    { value: "briefing", label: "Briefing" },
    { value: "audience", label: "Audiencia" },
    { value: "entity", label: "Entidade" },
    { value: "tone", label: "Tom" },
    { value: "rule", label: "Regra" },
    { value: "copy", label: "Copy" },
    { value: "faq", label: "FAQ" },
    { value: "asset", label: "Asset" },
  ];
  const parentOptions = useMemo(
    () => nodes
      .filter((node) => node.id?.startsWith("gn:"))
      .filter((node) => !["tag", "mention"].includes(node.data?.node_type))
      .map((node) => ({
        id: node.id.slice(3),
        graphId: node.id,
        label: node.data?.label || node.data?.slug || node.id,
        slug: node.data?.slug,
        type: node.data?.node_type || "node",
      }))
      .sort((a, b) => {
        const ar = getVisualHierarchyRank(a.type);
        const br = getVisualHierarchyRank(b.type);
        if (ar !== br) return ar - br;
        return a.label.localeCompare(b.label);
      })
      .slice(0, 120),
    [nodes],
  );
  const graphNodesById = useMemo(() => new Map(parentOptions.map((node) => [node.graphId, node])), [parentOptions]);
  const childOptionsByParent = useMemo(() => {
    const structural = new Set([
      "manual",
      "contains",
      "part_of_campaign",
      "about_product",
      "briefed_by",
      "answers_question",
      "supports_copy",
      "uses_asset",
      "belongs_to_persona",
      "persona_has_brand",
      "brand_has_briefing",
      "briefing_has_campaign",
      "campaign_has_audience",
      "audience_has_product_group",
      "product_group_has_product",
      "product_has_copy",
      "product_has_faq",
      "copy_has_faq",
    ]);
    const out = new Map<string, typeof parentOptions>();
    for (const edge of edges || []) {
      const relation = String(edge?.data?.relation_type || "").toLowerCase();
      if (!structural.has(relation)) continue;
      const source = edge?.source;
      const target = edge?.target;
      const child = graphNodesById.get(target);
      if (!source || !child || source === target) continue;
      const list = out.get(source) || [];
      if (!list.some((item) => item.graphId === child.graphId)) list.push(child);
      out.set(source, list);
    }
    for (const [key, list] of out) {
      out.set(key, [...list].sort((a, b) => {
        const ar = getVisualHierarchyRank(a.type);
        const br = getVisualHierarchyRank(b.type);
        if (ar !== br) return ar - br;
        return a.label.localeCompare(b.label);
      }));
    }
    return out;
  }, [edges, graphNodesById]);
  const [contentType, setContentType] = useState("product");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [pathIds, setPathIds] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const selectedParent = useMemo(() => {
    const last = pathIds[pathIds.length - 1];
    return parentOptions.find((node) => node.graphId === last);
  }, [parentOptions, pathIds]);
  const parentNodeId = selectedParent?.id || "";

  useEffect(() => {
    if (pathIds.length) return;
    const chosen = chooseAddBlockParent(contentType, parentOptions, selectedNode?.id);
    if (chosen?.graphId) setPathIds([chosen.graphId]);
  }, [contentType, parentOptions, pathIds.length, selectedNode?.id]);

  useEffect(() => {
    if (!pathIds.length) return;
    const selected = parentOptions.find((node) => node.graphId === pathIds[pathIds.length - 1]);
    if (selected && compatibleParentTypes(contentType).includes(selected.type)) return;
    const chosen = chooseAddBlockParent(contentType, parentOptions, selectedNode?.id);
    setPathIds(chosen?.graphId ? [chosen.graphId] : []);
  }, [contentType, parentOptions, pathIds, selectedNode?.id]);

  const selectPathNode = (level: number, graphId: string) => {
    setPathIds((current) => [...current.slice(0, level), graphId]);
  };

  const pathColumns = useMemo(() => {
    const allowedRootTypes = new Set(compatibleParentTypes(contentType));
    const rootOptions = parentOptions.filter((node) => allowedRootTypes.has(node.type));
    const columns: Array<{ title: string; helper: string; options: typeof parentOptions; selected?: string }> = [
      {
        title: "Parent compativel",
        helper: "Escolha onde o novo bloco deve entrar.",
        options: rootOptions,
        selected: pathIds[0],
      },
    ];
    const firstChildren = pathIds[0] ? childOptionsByParent.get(pathIds[0]) || [] : [];
    columns.push({
      title: "Alguma outra conexao?",
      helper: "Somente filhos imediatos da campanha.",
      options: firstChildren,
      selected: pathIds[1],
    });
    if (pathIds[1]) {
      columns.push({
        title: "Terceiro nivel",
        helper: "Refine com o proximo nivel hierarquico.",
        options: childOptionsByParent.get(pathIds[1]) || [],
        selected: pathIds[2],
      });
    }
    return columns;
  }, [contentType, parentOptions, childOptionsByParent, pathIds]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!persona?.id) {
      setError("Selecione uma persona antes de criar o bloco.");
      return;
    }
    if (!title.trim() || !content.trim()) {
      setError("Titulo e conteudo sao obrigatorios.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const created = await api.intakeKnowledge({
        raw_text: content,
        persona_id: persona.id,
        source: "graph_ui_add_block",
        source_ref: title,
        title,
        content_type: contentType,
        tags: [contentType, persona.slug].filter(Boolean),
        metadata: {
          slug: title,
          markdown_document: true,
          parent_node_id: parentNodeId || undefined,
          parent_relation_type: selectedParent ? relationForParentChild(selectedParent.type, contentType) : "contains",
        },
        submitted_by: "graph_ui",
        validate: true,
        parent_node_id: parentNodeId || undefined,
        parent_relation_type: selectedParent ? relationForParentChild(selectedParent.type, contentType) : "contains",
      });
      await onCreated(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nao foi possivel criar o bloco.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="absolute inset-0 z-50 flex items-end justify-center bg-black/30 p-3">
      <form onSubmit={submit} className="w-full max-w-4xl rounded-xl border border-white/08 bg-obs-surface shadow-2xl">
        <div className="flex items-center justify-between border-b border-white/06 px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-obs-text">Adicionar bloco ao grafo</h2>
            <p className="mt-0.5 text-[11px] text-obs-subtle">Defina o tipo, conteudo e galho principal.</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-obs-subtle transition hover:bg-white/5 hover:text-white"
          >
            <X size={16} />
          </button>
        </div>

        <div className="max-h-[76vh] overflow-y-auto p-4">
          <section>
            <p className="mb-2 text-[9px] font-semibold uppercase tracking-[0.16em] text-obs-faint">Tipo</p>
            <div className="flex flex-wrap gap-1.5">
              {nodeTypeOptions.map((type) => (
                <button
                  key={type.value}
                  type="button"
                  onClick={() => setContentType(type.value)}
                  className={`rounded-md border px-2.5 py-1.5 text-left text-[11px] leading-none transition ${
                    contentType === type.value
                      ? "border-obs-violet/50 bg-obs-violet/15 text-white"
                      : "border-white/06 bg-white/[0.03] text-obs-subtle hover:border-obs-violet/35 hover:text-white"
                  }`}
                >
                  {type.label}
                </button>
              ))}
            </div>
            <input
              required
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Titulo do bloco"
              className="mt-3 w-full rounded-md border border-white/06 bg-obs-base px-3 py-2 text-sm text-obs-text outline-none focus:border-obs-violet/50"
            />
            <textarea
              required
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={4}
              placeholder="Conteudo markdown do novo conhecimento..."
              className="mt-2.5 w-full resize-none rounded-md border border-white/06 bg-obs-base px-3 py-2 text-sm text-obs-text outline-none focus:border-obs-violet/50"
            />
            <div className="mt-3 grid gap-2 md:grid-cols-3">
              {pathColumns.map((column, index) => (
                <div key={`${column.title}-${index}`} className="min-h-[104px] rounded-md border border-white/06 bg-obs-base/70 p-2.5">
                  <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-obs-faint">{column.title}</p>
                  <p className="mt-0.5 truncate text-[10px] text-obs-subtle">{column.helper}</p>
                  <div className="mt-2 max-h-28 space-y-1.5 overflow-y-auto pr-1">
                    {column.options.length ? column.options.map((node) => (
                      <button
                        key={node.graphId}
                        type="button"
                        onClick={() => selectPathNode(index, node.graphId)}
                        className={`w-full rounded-md border px-2 py-1.5 text-left transition ${
                          column.selected === node.graphId
                            ? "border-obs-violet/60 bg-obs-violet/18 text-white"
                            : "border-white/06 bg-white/[0.03] text-obs-subtle hover:border-obs-violet/35 hover:text-white"
                        }`}
                      >
                        <span className="block text-[8px] uppercase tracking-[0.12em] text-obs-faint">{node.type}</span>
                        <span className="mt-0.5 block truncate text-[11px] font-medium leading-tight">{node.label}</span>
                      </button>
                    )) : (
                      <p className="rounded-md border border-dashed border-white/08 px-2 py-3 text-[11px] text-obs-faint">
                        Nenhum filho imediato nesse nivel.
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <p className="mt-2 truncate text-[11px] text-obs-subtle">
              Conexao principal selecionada: {selectedParent ? `${selectedParent.type} - ${selectedParent.label}` : "Persona ativa"}
            </p>
            {error && <p className="mt-3 text-xs text-red-200">{error}</p>}
          </section>
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-white/06 px-4 py-3">
          <button type="button" onClick={onClose} className="rounded-md border border-white/06 px-3 py-2 text-xs text-obs-subtle hover:text-white">
            Cancelar
          </button>
          <button type="submit" disabled={saving} className="rounded-md bg-obs-violet px-4 py-2 text-xs font-medium text-white disabled:opacity-50">
            {saving ? "Criando..." : "Criar node"}
          </button>
        </div>
      </form>
    </div>
  );
}

function ToggleChip({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1 text-[10px] px-2 py-1 rounded-md border transition ${
        active
          ? "bg-obs-violet/15 border-obs-violet/50 text-obs-violet"
          : "glass border-white/10 text-obs-subtle hover:text-obs-text"
      }`}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}
