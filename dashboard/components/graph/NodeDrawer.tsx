"use client";
import { useState, useEffect } from "react";
import { X, Edit2, Save, CheckCircle, XCircle, Tag, Loader2, Crosshair, Maximize2, Trash2, ExternalLink } from "lucide-react";
import { api, API_URL } from "@/lib/api";
import FaqGeneratorPanel from "./FaqGeneratorPanel";
import AudienceLeadsShortcut from "@/components/leads/AudienceLeadsShortcut";

const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "webp", "svg", "gif"]);
const VIDEO_EXTS = new Set(["mp4", "mov", "webm"]);

const STATUS_BADGE: Record<string, string> = {
  pending:        "bg-obs-amber/10 border-obs-amber/30 text-obs-amber",
  needs_persona:  "bg-obs-amber/10 border-obs-amber/30 text-obs-amber",
  needs_category: "bg-obs-amber/10 border-obs-amber/30 text-obs-amber",
  approved:       "bg-green-500/10 border-green-500/30 text-green-400",
  embedded:       "bg-obs-violet/10 border-obs-violet/30 text-obs-violet",
  rejected:       "bg-obs-rose/10 border-obs-rose/30 text-obs-rose",
  ATIVO:          "bg-green-500/10 border-green-500/30 text-green-400",
  INATIVO:        "bg-obs-rose/10 border-obs-rose/30 text-obs-rose",
};

const ALREADY_VALID = new Set(["ATIVO", "approved", "embedded"]);

function formatLastModified(value: unknown): string | null {
  if (!value) return null;
  const date = new Date(typeof value === "number" ? value : String(value));
  if (Number.isNaN(date.getTime())) return null;
  const dd = String(date.getDate()).padStart(2, "0");
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const yyyy = date.getFullYear();
  const hh = String(date.getHours()).padStart(2, "0");
  const min = String(date.getMinutes()).padStart(2, "0");
  return `${dd}/${mm}/${yyyy} ${hh}:${min}`;
}

interface NodeDrawerProps {
  node: any | null;
  selectedNodes?: any[];
  personaSlug?: string;
  sessionId?: string | null;
  onClose: () => void;
  onUpdated?: (itemId: string) => void | Promise<any>;
  directLinks?: Array<{
    id?: string;
    direction: "in" | "out";
    other_id: string;
    other_label: string;
    other_type: string;
    other_summary?: string;
    other_level?: number;
  }>;
  focusPath?: Array<{
    node_id: string;
    slug?: string;
    title?: string;
    node_type?: string;
    direction?: string | null;
  }>;
  onFocusHere?: () => void;
  onDeleteNode?: (nodeId: string) => void | Promise<void>;
  onDeleteEdge?: (edgeId: string) => void | Promise<void>;
  onSelectNode?: (nodeId: string) => void;
}

export default function NodeDrawer({ node, selectedNodes = [], personaSlug, sessionId, onClose, onUpdated, directLinks = [], focusPath = [], onFocusHere, onDeleteNode, onDeleteEdge, onSelectNode }: NodeDrawerProps) {
  const [editing, setEditing]     = useState(false);
  const [fullItem, setFullItem]   = useState<any>(null);
  const [fetching, setFetching]   = useState(false);
  const [saving, setSaving]       = useState(false);
  const [flash, setFlash]         = useState<"ok" | "err" | null>(null);
  const [expanded, setExpanded]   = useState(false);

  // Edit fields
  const [title,   setTitle]   = useState("");
  const [content, setContent] = useState("");
  const [tagsRaw, setTagsRaw] = useState("");
  const [tipo,    setTipo]    = useState("");

  // Persona handoff-message templates (appointment_policy.texts, published
  // graph — a different store from the vault/queue/graph-node content
  // above, see docs/sdr/aurora/rules/no-auto-confirm.md).
  const [handoffTexts, setHandoffTexts]         = useState<Record<string, string>>({});
  const [handoffLoading, setHandoffLoading]     = useState(false);
  const [handoffSaving, setHandoffSaving]       = useState(false);
  const [handoffFlash, setHandoffFlash]         = useState<"ok" | "err" | null>(null);

  useEffect(() => {
    const isPersonaNode = node?.type === "personaNode";
    if (!isPersonaNode || !personaSlug) {
      setHandoffTexts({});
      return;
    }
    setHandoffLoading(true);
    setHandoffFlash(null);
    api.getPersonaAppointmentPolicy(personaSlug)
      .then((res: any) => {
        const texts = res?.texts || {};
        setHandoffTexts({
          atendimento_humano: texts.atendimento_humano || "",
          encaminhamento_excepcional: texts.encaminhamento_excepcional || "",
          esclarecimento_duvida: texts.esclarecimento_duvida || "",
          encaminhamento_duvida_persistente: texts.encaminhamento_duvida_persistente || "",
          complemento_confirmacao: texts.complemento_confirmacao || "",
          cabecalho_servicos: texts.cabecalho_servicos || "",
          saudacao_abertura: texts.saudacao_abertura || "",
          sem_comparar_concorrentes: texts.sem_comparar_concorrentes || "",
        });
      })
      .catch(() => setHandoffTexts({}))
      .finally(() => setHandoffLoading(false));
  }, [node?.id, personaSlug]);

  async function saveHandoffTexts() {
    if (!personaSlug) return;
    setHandoffSaving(true);
    try {
      await api.updatePersonaAppointmentPolicy(personaSlug, handoffTexts);
      setHandoffFlash("ok");
    } catch {
      setHandoffFlash("err");
    } finally {
      setHandoffSaving(false);
      setTimeout(() => setHandoffFlash(null), 2500);
    }
  }

  // Fetch full item whenever the selected node changes
  useEffect(() => {
    const graphKnowledgeItem =
      node?.data?.source === "graph" &&
      node?.data?.source_table === "knowledge_items" &&
      !!node?.data?.item_id;
    if (!node || node.type === "personaNode" || !node.data?.item_id || (!["vault", "queue"].includes(node.data?.source) && !graphKnowledgeItem)) {
      setFullItem(null);
      setEditing(false);
      return;
    }

    setFetching(true);
    setEditing(false);
    setFlash(null);

    const d = node.data;
    const fetchFn = d.source === "vault"
      ? api.kbEntry(d.item_id)
      : api.queueItem(d.item_id);

    fetchFn
      .then((item: any) => {
        setFullItem(item);
        setTitle(item.titulo   ?? item.title   ?? d.label ?? "");
        setContent(item.conteudo ?? item.content ?? "");
        setTagsRaw((item.tags  ?? d.tags ?? []).join(", "));
        setTipo(item.tipo ?? item.content_type ?? "");
      })
      .catch(() => setFullItem(null))
      .finally(() => setFetching(false));
  }, [node?.id]);

  if (!node && selectedNodes.length <= 1) return null;
  if (!node && selectedNodes.length > 1) {
    return <MultiNodeDrawer nodes={selectedNodes} onClose={onClose} />;
  }

  const d          = node.data;
  const isPersona  = node.type === "personaNode";
  const isProtected = isPersona || ["persona", "embedded", "gallery"].includes(String(d.node_type || "")) || d.protected === true;
  const isVault    = d.source === "vault";
  const isQueue    = d.source === "queue" || (d.source === "graph" && d.source_table === "knowledge_items");
  const fileType   = (d.file_type || "").toLowerCase();
  const assetUrl   = d.asset_url || d.metadata?.public_url || d.metadata?.url || d.metadata?.asset_url || null;
  const fileUrl    = assetUrl || (d.file_path && API_URL
    ? `${API_URL}/knowledge/file?path=${encodeURIComponent(d.file_path)}`
    : null);
  const inferredExt = String(fileUrl || d.file_path || "").split("?")[0].split(".").pop()?.toLowerCase() || "";
  const isImage    = IMAGE_EXTS.has(fileType) || IMAGE_EXTS.has(inferredExt) || d.node_type === "asset" && Boolean(fileUrl);
  const isVideo    = VIDEO_EXTS.has(fileType) || VIDEO_EXTS.has(inferredExt);

  const currentStatus  = fullItem?.status ?? d.status;
  const tags: string[] = fullItem?.tags ?? d.tags ?? [];
  const displayContent = fullItem
    ? (fullItem.conteudo ?? fullItem.content ?? "")
    : (d.markdown ?? d.metadata?.body ?? d.content_preview ?? "");

  const isGraphNode = String(node.id || "").startsWith("gn:");
  const canEdit     = !isProtected && (isVault || isQueue || isGraphNode);
  const needsCanonicalSnapshot = isQueue && currentStatus === "approved" && !d.approved_snapshot_id;
  const canValidate = !isProtected && (!ALREADY_VALID.has(currentStatus) || needsCanonicalSnapshot);
  const canReject   = !isProtected && isQueue && currentStatus !== "rejected";
  const canDelete   = !isProtected && String(node.id || "").startsWith("gn:") && !!onDeleteNode;
  const canPublish  = !isProtected
    && d.source === "graph"
    && d.source_table === "knowledge_items"
    && d.node_type === "faq"
    && currentStatus === "approved"
    && !!d.persona_id;
  const canGenerateFaqs = !isPersona && !isProtected;
  const audiencePreview = Array.isArray(d.metadata?.preview) ? d.metadata.preview : [];
  const audienceOpenUrl = d.metadata?.open_url || (d.metadata?.lead_import_batch_id ? `/leads/import?open=${d.metadata.lead_import_batch_id}` : "");

  function showFlash(kind: "ok" | "err") {
    setFlash(kind);
    setTimeout(() => setFlash(null), 2500);
  }

  async function saveValues(vals: { title: string; content: string; tags: string[] }) {
    setSaving(true);
    try {
      if (isVault && d.item_id) {
        await api.updateKbEntry(d.item_id, { titulo: vals.title, conteudo: vals.content, tipo, tags: vals.tags });
      } else if (isGraphNode) {
        // The node body (Markdown) is the source of context. The node endpoint
        // persists metadata.markdown + the backing item, and reverts an
        // approved/embedded FAQ to draft (removing it from the Embedded body).
        const saved = await api.updateGraphNode(String(node.id), { title: vals.title, markdown: vals.content, tags: vals.tags });
        if (saved?.reverted_to_draft) {
          setFullItem((prev: any) => ({ ...(prev || {}), status: "pending" }));
        }
      } else if (d.item_id) {
        const saved = await api.updateQueueItem(d.item_id, { title: vals.title, content: vals.content, tags: vals.tags, content_type: tipo || undefined });
        if (saved?.status) {
          setFullItem((prev: any) => (prev ? { ...prev, ...saved } : saved));
        }
      } else {
        return;
      }
      setEditing(false);
      showFlash("ok");
      await onUpdated?.(d.item_id || node.id);
    } catch { showFlash("err"); }
    finally { setSaving(false); }
  }

  async function save() {
    await saveValues({
      title,
      content,
      tags: tagsRaw.split(",").map((t: string) => t.trim()).filter(Boolean),
    });
  }

  function beginEdit() {
    // Seed the edit fields from the node's real body so non-item graph nodes
    // (whose content is the node Markdown) are editable too, not just items.
    setTitle(fullItem?.titulo ?? fullItem?.title ?? d.label ?? "");
    setContent(fullItem ? (fullItem.conteudo ?? fullItem.content ?? "") : (displayContent ?? ""));
    setTagsRaw(((fullItem?.tags ?? d.tags ?? []) as string[]).join(", "));
    setTipo(fullItem?.tipo ?? fullItem?.content_type ?? d.node_type ?? "");
    setEditing(true);
  }

  async function validate() {
    if (!d.item_id) return;
    setSaving(true);
    try {
      if (isVault) {
        await api.validateKbEntry(d.item_id);
        await onUpdated?.(d.item_id);
        setFullItem((prev: any) => prev ? { ...prev, status: "ATIVO" } : prev);
      } else {
        const result = await api.approveItem(d.item_id, false);
        const evidence = result?.evidence || {};
        const contentType = String(d.node_type || d.content_type || fullItem?.content_type || "").toLowerCase();
        const snapshotId = result?.approved_snapshot_id || evidence.approved_snapshot_id;
        const ragEntryId = result?.rag_entry_id || evidence.rag_entry_id;
        const ragChunkIds = result?.rag_chunk_ids || evidence.rag_chunk_ids || [];
        if (result?.success !== true || !snapshotId || !evidence.knowledge_item_id || !evidence.knowledge_node_id) {
          throw new Error(result?.error || "Aprovacao incompleta: backend nao confirmou snapshot, item e node semantico.");
        }
        if (contentType === "faq" && (!ragEntryId || !Array.isArray(ragChunkIds) || ragChunkIds.length === 0)) {
          throw new Error("FAQ aprovada, mas o Golden Dataset RAG nao confirmou entry e chunks.");
        }
        const refreshed = await onUpdated?.(d.item_id);
        const expectedNodeId = `gn:${evidence.knowledge_node_id}`;
        const graphNodes = Array.isArray(refreshed?.nodes) ? refreshed.nodes : [];
        const refreshedNode = graphNodes.find((node: any) => node?.id === expectedNodeId);
        const nodeExists = Boolean(refreshedNode);
        if (!nodeExists) {
          throw new Error("Aprovacao parcial: o grafo nao refletiu o node FAQ aprovado.");
        }
        if (contentType === "faq") {
          const rd = refreshedNode?.data || {};
          if (!rd.approved_snapshot_id || !rd.rag_entry_id || Number(rd.rag_chunk_count || 0) <= 0) {
            throw new Error("Aprovacao parcial: graph-data nao refletiu snapshot e chunks RAG.");
          }
        }
        setFullItem((prev: any) => prev ? { ...prev, ...(result?.item || {}), status: result?.item?.status || "approved" } : result?.item || prev);
      }
      showFlash("ok");
    } catch { showFlash("err"); }
    finally { setSaving(false); }
  }

  async function publish() {
    if (!canPublish) return;
    setSaving(true);
    try {
      const result = await api.createGraphEdge({
        source_node_id: String(node.id),
        target_node_id: `embedded:${d.persona_id}`,
        relation_type: "manual",
        persona_id: d.persona_id,
        weight: 0.9,
        metadata: {
          created_from: "graph_drawer_publish",
          direction: "source_to_target",
          primary_tree: false,
        },
      });
      const evidence = result?.evidence || {};
      const ragChunkIds = evidence.rag_chunk_ids || evidence.knowledge_rag_chunk_ids || [];
      if (!result?.success || !evidence.knowledge_item_id || !evidence.approved_snapshot_id || !evidence.rag_entry_id || !Array.isArray(ragChunkIds) || ragChunkIds.length === 0 || !evidence.knowledge_node_id || !evidence.embedded_edge_id) {
        throw new Error("Publicacao incompleta no Golden Dataset.");
      }
      await onUpdated?.(d.item_id);
      setFullItem((prev: any) => prev ? { ...prev, status: "embedded" } : prev);
      showFlash("ok");
    } catch {
      showFlash("err");
    } finally {
      setSaving(false);
    }
  }

  async function reject() {
    if (!d.item_id || !isQueue) return;
    setSaving(true);
    try {
      await api.rejectItem(d.item_id);
      setFullItem((prev: any) => prev ? { ...prev, status: "rejected" } : prev);
      showFlash("ok");
      await onUpdated?.(d.item_id);
    } catch { showFlash("err"); }
    finally { setSaving(false); }
  }

  const lastModifiedRaw =
    fullItem?.updated_at ||
    fullItem?.modified_at ||
    fullItem?.last_modified_at ||
    fullItem?.created_at ||
    d.updated_at ||
    d.modified_at ||
    d.last_modified_at ||
    d.created_at ||
    null;
  const lastModifiedDisplay = lastModifiedRaw ? formatLastModified(lastModifiedRaw) : null;

  const rawSummaryItems: Array<[string, any]> = [
    ["Status", currentStatus || "active"],
    ["Tipo", d.content_type || d.node_type || "node"],
    ["Origem", d.source || "graph"],
    ["Preço", fullItem?.metadata?.price?.display || d.metadata?.price?.display],
    ["Última modificação", lastModifiedDisplay],
  ];
  const summaryItems = rawSummaryItems.filter(([, value]) => Boolean(value));

  return (
    <div className="absolute right-0 top-0 z-50 flex h-full w-[min(720px,94vw)] flex-col border-l border-white/06 glass-raised shadow-2xl animate-slide-in-r">

      {/* ── Header ── */}
      <div className="flex items-start justify-between px-5 pt-5 pb-4 sep">
        <div className="flex-1 min-w-0 space-y-1.5">

          {/* Badges row */}
          <div className="flex items-center gap-2 flex-wrap">
            {isPersona ? (
              <span className="text-[10px] px-2 py-0.5 rounded-full border border-obs-violet/40 bg-obs-violet/10 text-obs-violet uppercase tracking-wide">
                Persona
              </span>
            ) : (
              <span className={`text-[10px] px-2 py-0.5 rounded-full border ${STATUS_BADGE[currentStatus] || STATUS_BADGE.pending}`}>
                {currentStatus}
              </span>
            )}

            {!isPersona && d.content_type && (
              <span className="text-[10px] text-obs-subtle">{d.content_type}</span>
            )}

            {!isPersona && d.source && (
              <span className={`text-[9px] px-1.5 py-0.5 rounded border font-mono ${
                isVault
                  ? "border-obs-slate/30 bg-obs-slate/10 text-obs-slate"
                  : "border-white/10 text-obs-faint"
              }`}>
                {isVault ? "vault" : "queue"}
              </span>
            )}

            {typeof d.level === "number" && (
              <span
                className="text-[9px] px-1.5 py-0.5 rounded border font-mono"
                style={{
                  borderColor: `${d.color || "#94a3b8"}55`,
                  background: `${d.color || "#94a3b8"}14`,
                  color: d.color || "#94a3b8",
                }}
                title="Nivel semantico no registry"
              >
                L{d.level}
              </span>
            )}

            {typeof d.importance === "number" && (
              <span
                className="text-[9px] px-1.5 py-0.5 rounded border border-white/10 bg-white/5 text-obs-subtle font-mono"
                title="Importancia (0..1)"
              >
                imp {d.importance.toFixed(2)}
              </span>
            )}

            {typeof d.confidence === "number" && (
              <span
                className="text-[9px] px-1.5 py-0.5 rounded border border-white/10 bg-white/5 text-obs-subtle font-mono"
                title="Confianca (0..1)"
              >
                conf {d.confidence.toFixed(2)}
              </span>
            )}
          </div>

          {/* Title — editable in edit mode */}
          {editing ? (
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-obs-base border border-obs-violet/40 rounded px-2 py-1 text-sm font-semibold text-obs-text focus:outline-none focus:border-obs-violet"
            />
          ) : (
            <h3 className="text-sm font-semibold text-obs-text leading-tight">{d.label}</h3>
          )}

          {d.slug && (
            <p className="text-[11px] text-obs-subtle font-mono">{d.slug}</p>
          )}

          {lastModifiedDisplay && (
            <p className="text-[10px] text-obs-faint">Última modificação: {lastModifiedDisplay}</p>
          )}

          {typeof d.graph_distance === "number" && (
            <p className="text-[10px] text-obs-faint">distancia no grafo: {d.graph_distance}</p>
          )}
        </div>

        <div className="flex items-center gap-1 ml-3 shrink-0">
          <button
            onClick={() => setExpanded(true)}
            title="Abrir card"
            className="p-1.5 rounded-lg hover:bg-white/5 text-obs-subtle hover:text-obs-text transition-colors"
          >
            <Maximize2 size={13} />
          </button>
          {onFocusHere && !isPersona && (
            <button
              onClick={onFocusHere}
              title="Centralizar foco neste no"
              className="p-1.5 rounded-lg hover:bg-white/5 text-obs-subtle hover:text-obs-text transition-colors"
            >
              <Crosshair size={13} />
            </button>
          )}
          {canEdit && !editing && (
            <button
              onClick={beginEdit}
              title="Editar"
              className="p-1.5 rounded-lg hover:bg-white/5 text-obs-subtle hover:text-obs-text transition-colors"
            >
              <Edit2 size={13} />
            </button>
          )}
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/5 text-obs-subtle hover:text-obs-text transition-colors"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {/* ── Flash ── */}
      {flash && (
        <div className={`mx-4 mt-2 px-3 py-2 rounded-lg text-xs flex items-center gap-2 ${
          flash === "ok"
            ? "bg-green-500/10 border border-green-500/20 text-green-400"
            : "bg-obs-rose/10 border border-obs-rose/20 text-obs-rose"
        }`}>
          {flash === "ok" ? <CheckCircle size={11} /> : <XCircle size={11} />}
          {flash === "ok" ? "Salvo com sucesso" : "Erro ao salvar — tente novamente"}
        </div>
      )}

      {/* ── Body ── */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">

        {fetching && (
          <div className="flex items-center gap-2 text-xs text-obs-subtle">
            <Loader2 size={11} className="animate-spin" /> Carregando...
          </div>
        )}

        {/* Focus path breadcrumb (when this node is part of the active focus) */}
        {focusPath.length > 0 && focusPath.some((s) => s.node_id === (d?.item_id || node?.id?.replace(/^gn:/, ""))) && (
          <div>
            <p className="text-[10px] text-obs-subtle uppercase tracking-wide mb-1.5">Caminho desde a persona</p>
            <div className="flex items-center gap-1 flex-wrap text-[10px]">
              {focusPath.map((step, i) => (
                <span key={`${step.node_id}-${i}`} className="flex items-center gap-1">
                  {i > 0 && <span className="text-obs-faint">→</span>}
                  <span
                    className="px-1.5 py-0.5 rounded border truncate max-w-[140px]"
                    style={{
                      borderColor: i === focusPath.length - 1 ? "rgba(167,139,250,0.6)" : "rgba(255,255,255,0.10)",
                      color: i === focusPath.length - 1 ? "#a78bfa" : "rgba(255,255,255,0.6)",
                    }}
                    title={`${step.node_type}:${step.slug}`}
                  >
                    {step.title || step.slug || step.node_type}
                  </span>
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Persona description */}
        {isPersona && d.description && (
          <p className="text-sm text-obs-subtle leading-relaxed">{d.description}</p>
        )}

        {/* Persona handoff-message templates */}
        {isPersona && personaSlug && (
          <div className="space-y-2 border-t border-white/06 pt-4">
            <p className="text-[10px] text-obs-subtle uppercase tracking-wide">
              Mensagens de handoff
            </p>
            <p className="text-[11px] text-obs-faint leading-relaxed">
              Textos enviados quando a IA passa a conversa para um humano —
              inclusive ao ser reativada após um handoff (Retomar IA).
            </p>
            {handoffLoading ? (
              <div className="flex items-center gap-2 text-xs text-obs-subtle">
                <Loader2 size={11} className="animate-spin" /> Carregando...
              </div>
            ) : (
              <div className="space-y-3">
                {(
                  [
                    ["atendimento_humano", "Cliente pede atendimento humano"],
                    ["encaminhamento_excepcional", "Assunto excepcional (reclamação, garantia, etc.)"],
                    ["esclarecimento_duvida", "IA não entendeu a mensagem (1ª vez)"],
                    ["encaminhamento_duvida_persistente", "IA não entendeu de novo (encerra e chama humano)"],
                    ["complemento_confirmacao", "Complemento ao confirmar um agendamento/pedido completo"],
                    ["cabecalho_servicos", "Título da lista de serviços"],
                    ["saudacao_abertura", "Saudação de abertura da conversa"],
                    ["sem_comparar_concorrentes", "Regra: nunca comparar com concorrentes"],
                    ["mensagem_ausencia", "Mensagem de ausência (fora do atendimento)"],
                    ["preco_humano", "Cliente pergunta preço (quem informa valor é uma pessoa)"],
                    ["avaliacao_presencial", "Convite para avaliação presencial"],
                    ["lacuna_conhecimento", "Assunto sem resposta publicada (chama o time)"],
                  ] as const
                ).map(([key, label]) => (
                  <div key={key} className="space-y-1">
                    <label className="text-[10px] text-obs-subtle">{label}</label>
                    <textarea
                      value={handoffTexts[key] || ""}
                      onChange={(e) =>
                        setHandoffTexts((prev) => ({ ...prev, [key]: e.target.value }))
                      }
                      rows={2}
                      className="w-full bg-obs-base border border-white/10 rounded px-2 py-1.5 text-xs text-obs-text focus:outline-none focus:border-obs-violet/40 resize-none"
                    />
                  </div>
                ))}
                <div className="flex items-center gap-2">
                  <button
                    onClick={saveHandoffTexts}
                    disabled={handoffSaving}
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs bg-obs-violet/10 border border-obs-violet/30 text-obs-violet hover:bg-obs-violet/15 disabled:opacity-50 transition-colors"
                  >
                    {handoffSaving ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />}
                    Salvar mensagens
                  </button>
                  {handoffFlash && (
                    <span className={`text-[11px] flex items-center gap-1 ${handoffFlash === "ok" ? "text-green-400" : "text-obs-rose"}`}>
                      {handoffFlash === "ok" ? <CheckCircle size={11} /> : <XCircle size={11} />}
                      {handoffFlash === "ok" ? "Salvo" : "Erro ao salvar"}
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Media preview (view mode only) */}
        {!editing && isImage && fileUrl && (
          <div className="rounded-xl overflow-hidden border border-white/06 bg-obs-base">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={fileUrl}
              alt={d.label}
              className="w-full object-contain max-h-40"
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
            />
          </div>
        )}
        {!editing && isVideo && fileUrl && (
          <div className="rounded-xl overflow-hidden border border-white/06">
            <video src={fileUrl} controls className="w-full max-h-40" preload="metadata" />
          </div>
        )}

        {/* Content */}
        {!isPersona && (
          <div>
            <p className="text-[10px] text-obs-subtle uppercase tracking-wide mb-1.5">Conteúdo</p>
            {editing ? (
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                rows={9}
                className="w-full bg-obs-base border border-white/10 rounded-lg px-3 py-2.5 text-xs text-obs-text focus:outline-none focus:border-obs-violet/50 resize-y font-mono leading-relaxed"
              />
            ) : (
              <pre className="code-surface text-xs rounded-xl p-3 whitespace-pre-wrap overflow-y-auto max-h-48 font-mono leading-6">
                {displayContent || <span className="text-obs-faint italic">Sem conteúdo</span>}
                {!fullItem && (displayContent?.length ?? 0) >= 200 && "…"}
              </pre>
            )}
          </div>
        )}

        {/* Audience -> Leads shortcut */}
        {!editing && String(d.node_type || "").toLowerCase() === "audience" && d.slug && (
          <AudienceLeadsShortcut slug={d.slug} />
        )}

        {/* Sofia FAQ generator (adaptar_faqs_universais_ao_grafo) */}
        {!editing && canGenerateFaqs && (
          <FaqGeneratorPanel
            node={node}
            personaSlug={personaSlug}
            sessionId={sessionId}
            onSaved={() => onUpdated?.(d.item_id || node.id)}
          />
        )}

        {/* Focus path */}
        {!editing && focusPath.length > 0 && (
          <div>
            <p className="text-[10px] text-obs-subtle uppercase tracking-wide mb-1.5">
              Caminho semantico
            </p>
            <div className="space-y-1.5">
              {focusPath.map((step, idx) => (
                <div
                  key={`${step.node_id}-${idx}`}
                  className="rounded-lg border border-white/06 bg-white/3 px-2 py-1.5"
                >
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className="text-[10px] text-obs-faint">{idx + 1}</span>
                    <span className="text-[11px] text-obs-text truncate">
                      {step.title || step.slug || step.node_type || step.node_id}
                    </span>
                    {step.node_type && (
                      <span className="ml-auto shrink-0 rounded border border-white/10 px-1 py-0.5 text-[9px] uppercase text-obs-faint">
                        {step.node_type}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Direct links */}
        {!editing && directLinks.length > 0 && (
          <div>
            <p className="text-[10px] text-obs-subtle uppercase tracking-wide mb-1.5">
              Cards relacionados ({directLinks.length})
            </p>
            <div className="space-y-1.5">
              {directLinks.map((link) => (
                <DirectLinkCard
                  key={link.id || `${link.direction}-${link.other_id}`}
                  link={link}
                  onDelete={onDeleteEdge}
                  onSelect={onSelectNode}
                />
              ))}
            </div>
          </div>
        )}

        {/* Tags */}
        {!editing && d.node_type === "audience" && audiencePreview.length > 0 && (
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <p className="text-[10px] text-obs-subtle uppercase tracking-wide">Exemplos de leads</p>
              {audienceOpenUrl && (
                <button
                  type="button"
                  onClick={() => { window.location.href = audienceOpenUrl; }}
                  className="text-[10px] text-obs-violet hover:text-white"
                >
                  abrir importacao
                </button>
              )}
            </div>
            <LeadPreviewList rows={audiencePreview} />
          </div>
        )}

        {/* Tags */}
        {!isPersona && (
          <div>
            <p className="text-[10px] text-obs-subtle uppercase tracking-wide mb-1.5 flex items-center gap-1.5">
              <Tag size={9} /> Tags
            </p>
            {editing ? (
              <input
                value={tagsRaw}
                onChange={(e) => setTagsRaw(e.target.value)}
                placeholder="tag1, tag2, tag3"
                className="w-full bg-obs-base border border-white/10 rounded-lg px-3 py-2 text-xs text-obs-text focus:outline-none focus:border-obs-violet/50"
              />
            ) : (
              <div className="flex flex-wrap gap-1.5 min-h-[20px]">
                {tags.length > 0 ? tags.map((t) => (
                  <span key={t} className="text-[10px] px-2 py-0.5 rounded-full bg-obs-slate/10 border border-obs-slate/20 text-obs-slate font-mono">
                    {t}
                  </span>
                )) : (
                  <span className="text-[10px] text-obs-faint italic">Sem tags</span>
                )}
              </div>
            )}
          </div>
        )}

        {/* Tipo — edit mode only */}
        {editing && !isPersona && (
          <div>
            <p className="text-[10px] text-obs-subtle uppercase tracking-wide mb-1.5">Tipo</p>
            <input
              value={tipo}
              onChange={(e) => setTipo(e.target.value)}
              className="w-full bg-obs-base border border-white/10 rounded-lg px-3 py-2 text-xs text-obs-text focus:outline-none focus:border-obs-violet/50"
            />
          </div>
        )}

        {/* File path — view mode */}
        {!editing && !isPersona && d.file_path && (
          <p className="text-[10px] text-obs-faint font-mono break-all leading-relaxed">
            {d.file_path.split(/[\\/]/).slice(-2).join("/")}
          </p>
        )}
      </div>

      {/* ── Footer actions ── */}
      <div className="px-5 py-4 sep space-y-2">

        {/* Edit mode controls */}
        {editing && (
          <div className="flex gap-2">
            <button
              onClick={() => setEditing(false)}
              disabled={saving}
              className="flex-1 py-2 text-xs font-medium rounded-xl border border-white/10 bg-white/[0.04] text-obs-subtle hover:bg-white/10 hover:border-white/20 hover:text-obs-text disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Cancelar
            </button>
            <button
              onClick={save}
              disabled={saving}
              className="flex-1 py-2 text-xs font-medium rounded-xl border border-obs-violet/40 bg-obs-violet/20 text-obs-text shadow-sm backdrop-blur-md hover:bg-obs-violet/30 hover:border-obs-violet/60 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-1.5"
            >
              {saving ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />}
              Salvar
            </button>
          </div>
        )}

        {/* View mode actions */}
        {!editing && !isPersona && (
          <>
            {canValidate && (
              <button
                onClick={validate}
                disabled={saving}
                className="w-full py-2 text-xs font-medium rounded-xl border border-emerald-300/30 bg-emerald-500/15 text-emerald-50 shadow-sm shadow-emerald-500/10 backdrop-blur-md hover:bg-emerald-500/25 hover:border-emerald-300/50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-1.5"
              >
                {saving ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle size={11} />}
                {isVault ? "Validar entrada" : "Aprovar"}
              </button>
            )}

            {canPublish && (
              <button
                onClick={publish}
                disabled={saving}
                className="w-full py-2 text-xs font-medium rounded-xl border border-obs-violet/35 bg-obs-violet/15 text-obs-text shadow-sm backdrop-blur-md hover:bg-obs-violet/25 hover:border-obs-violet/55 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-1.5"
              >
                {saving ? <Loader2 size={11} className="animate-spin" /> : <Tag size={11} />}
                Publicar no Golden Dataset
              </button>
            )}

            {canReject && (
              <button
                onClick={reject}
                disabled={saving}
                className="w-full py-2 text-xs font-medium rounded-xl border border-obs-rose/35 bg-obs-rose/[0.14] text-obs-rose shadow-sm shadow-obs-rose/[0.08] backdrop-blur-md hover:bg-obs-rose/[0.20] hover:border-obs-rose/50 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-1.5"
              >
                {saving ? <Loader2 size={11} className="animate-spin" /> : <XCircle size={11} />}
                Rejeitar
              </button>
            )}

            {canDelete && (
              <button
                onClick={() => {
                  if (window.confirm("Excluir este card e suas conexoes?")) onDeleteNode?.(node.id);
                }}
                disabled={saving}
                className="w-full py-2 text-xs font-medium rounded-xl border border-red-300/35 bg-red-500/[0.18] text-red-50 shadow-sm shadow-red-500/[0.10] backdrop-blur-md hover:bg-red-500/[0.26] hover:border-red-300/55 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-1.5"
              >
                <Trash2 size={11} />
                Excluir card
              </button>
            )}
          </>
        )}

        {isPersona && (
          <button
            onClick={onClose}
            className="w-full py-2 text-xs font-medium rounded-xl border border-white/10 bg-white/[0.04] text-obs-subtle hover:bg-white/10 hover:border-white/20 hover:text-obs-text transition-colors"
          >
            Fechar
          </button>
        )}
      </div>

      {expanded && (
        <NodeExpandedModal
          node={node}
          title={title || d.label}
          content={displayContent}
          tags={tags}
          summaryItems={summaryItems}
          directLinks={directLinks}
          audiencePreview={audiencePreview}
          audienceOpenUrl={audienceOpenUrl}
          onClose={() => setExpanded(false)}
          onValidate={canValidate ? validate : undefined}
          onPublish={canPublish ? publish : undefined}
          onDelete={canDelete ? () => onDeleteNode?.(node.id) : undefined}
          onEdit={canEdit ? () => { beginEdit(); setExpanded(false); } : undefined}
          canEdit={canEdit}
          onSaveEdit={canEdit ? saveValues : undefined}
          saving={saving}
          onSelectNode={onSelectNode ? (id) => { onSelectNode(id); setExpanded(false); } : undefined}
        />
      )}
    </div>
  );
}

function DirectLinkCard({
  link,
  onDelete,
  onSelect,
}: {
  link: {
    id?: string;
    direction: "in" | "out";
    other_id: string;
    other_label: string;
    other_type: string;
    other_summary?: string;
    other_level?: number;
  };
  onDelete?: (edgeId: string) => void | Promise<void>;
  onSelect?: (nodeId: string) => void;
}) {
  const clickable = Boolean(onSelect);
  const openLinkedNode = () => onSelect?.(link.other_id);
  const body = (
    <>
      <div className="flex items-center gap-1.5 min-w-0">
        <span
          className={`shrink-0 rounded border px-1.5 py-0.5 text-[9px] uppercase ${
            link.direction === "out"
              ? "border-obs-violet/35 text-obs-violet"
              : "border-white/10 text-obs-faint"
          }`}
        >
          {link.direction === "out" ? "Sai" : "Entra"}
        </span>
        <span className="truncate text-[11px] font-medium text-obs-text">{link.other_label}</span>
        <span className="ml-auto shrink-0 rounded border border-white/10 px-1 py-0.5 text-[9px] uppercase text-obs-faint">
          {link.other_type}
        </span>
        {onDelete && link.id?.startsWith("ge:") && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onDelete(link.id!);
            }}
            onKeyDown={(e) => e.stopPropagation()}
            className="ml-1 rounded-md border border-obs-rose/35 bg-obs-rose/[0.14] px-1.5 py-0.5 text-[9px] font-medium text-obs-rose hover:bg-obs-rose/[0.20] hover:border-obs-rose/50 transition-colors"
            title="Excluir caminho"
          >
            excluir
          </button>
        )}
        {clickable && (
          <span className="ml-1 shrink-0 text-obs-faint transition-colors group-hover:text-obs-text" aria-hidden>
            →
          </span>
        )}
      </div>
      {link.other_summary ? (
        <p className="mt-1 line-clamp-2 text-[10px] leading-relaxed text-obs-subtle">
          {link.other_summary}
        </p>
      ) : (
        <p className="mt-1 text-[10px] italic text-obs-faint">Sem resumo disponível.</p>
      )}
    </>
  );

  const baseClasses = "group block w-full text-left rounded-lg border border-white/[0.04] bg-white/[0.025] backdrop-blur-md px-2 py-1.5 transition-all";

  if (clickable) {
    return (
      <div
        role="button"
        tabIndex={0}
        onClick={openLinkedNode}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            openLinkedNode();
          }
        }}
        title={`Abrir ${link.other_label}`}
        className={`${baseClasses} cursor-pointer hover:border-white/[0.09] hover:bg-white/[0.045] focus:outline-none focus:ring-2 focus:ring-white/[0.08]`}
      >
        {body}
      </div>
    );
  }
  return <div className={baseClasses}>{body}</div>;
}

function MultiNodeDrawer({ nodes, onClose }: { nodes: any[]; onClose: () => void }) {
  const counts = nodes.reduce((acc: Record<string, number>, node) => {
    const type = node?.data?.node_type || node?.data?.content_type || "node";
    acc[type] = (acc[type] || 0) + 1;
    return acc;
  }, {});
  const statuses = nodes.reduce((acc: Record<string, number>, node) => {
    const status = node?.data?.status || "active";
    acc[status] = (acc[status] || 0) + 1;
    return acc;
  }, {});
  const tags = Array.from(new Set(nodes.flatMap((node) => node?.data?.tags || []))).slice(0, 24);
  return (
    <div className="absolute top-0 right-0 z-50 flex h-full w-[340px] flex-col border-l border-white/06 glass-raised shadow-2xl">
      <div className="flex items-start justify-between px-5 py-5 sep">
        <div>
          <p className="text-[10px] uppercase tracking-[0.18em] text-obs-faint">Selecao</p>
          <h3 className="mt-1 text-sm font-semibold text-obs-text">{nodes.length} nodes selecionados</h3>
        </div>
        <button onClick={onClose} className="rounded-lg p-1.5 text-obs-subtle hover:bg-white/5 hover:text-white">
          <X size={14} />
        </button>
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
        <SummaryBlock title="Tipos" data={counts} />
        <SummaryBlock title="Status" data={statuses} />
        <div>
          <p className="mb-2 text-[10px] uppercase tracking-wide text-obs-subtle">Tags</p>
          <div className="flex flex-wrap gap-1.5">
            {tags.length ? tags.map((tag) => (
              <span key={tag} className="rounded-full border border-obs-slate/20 bg-obs-slate/10 px-2 py-0.5 text-[10px] text-obs-slate">
                {tag}
              </span>
            )) : <span className="text-xs text-obs-faint">Sem tags em comum.</span>}
          </div>
        </div>
      </div>
    </div>
  );
}

function SummaryBlock({ title, data }: { title: string; data: Record<string, number> }) {
  return (
    <div>
      <p className="mb-2 text-[10px] uppercase tracking-wide text-obs-subtle">{title}</p>
      <div className="space-y-1.5">
        {Object.entries(data).map(([key, value]) => (
          <div key={key} className="flex items-center justify-between rounded-lg border border-white/06 bg-white/3 px-2.5 py-1.5 text-xs">
            <span className="text-obs-text">{key}</span>
            <span className="text-obs-subtle">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function LeadPreviewList({ rows }: { rows: any[] }) {
  const visible = (rows || []).filter((row) => row?.status !== "invalid").slice(0, 5);
  return (
    <div className="overflow-hidden rounded-lg border border-white/06">
      <table className="w-full text-xs">
        <thead className="bg-white/[0.03] text-[9px] uppercase tracking-wide text-obs-faint">
          <tr>
            <th className="px-2 py-1.5 text-left">Nome</th>
            <th className="px-2 py-1.5 text-left">Celular</th>
            <th className="px-2 py-1.5 text-left">Email</th>
            <th className="px-2 py-1.5 text-left">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-white/06">
          {visible.map((row) => (
            <tr key={`${row.row_index}-${row.parsed?.email || row.parsed?.lead_id || ""}`}>
              <td className="px-2 py-1.5 text-obs-text">{row.parsed?.nome || "-"}</td>
              <td className="px-2 py-1.5 font-mono text-obs-subtle">{row.parsed?.lead_id || "-"}</td>
              <td className="px-2 py-1.5 text-obs-subtle">{row.parsed?.email || "-"}</td>
              <td className="px-2 py-1.5 text-obs-faint">{row.status || "-"}</td>
            </tr>
          ))}
          {!visible.length && (
            <tr>
              <td colSpan={4} className="px-2 py-4 text-center text-obs-faint">Sem exemplos validos.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function NodeExpandedModal({
  node,
  title,
  content,
  tags,
  summaryItems,
  directLinks,
  audiencePreview,
  audienceOpenUrl,
  onClose,
  onValidate,
  onPublish,
  onDelete,
  onEdit,
  canEdit,
  onSaveEdit,
  onSelectNode,
  saving,
}: {
  node: any;
  title: string;
  content: string;
  tags: string[];
  summaryItems: Array<[string, any]>;
  directLinks: NodeDrawerProps["directLinks"];
  audiencePreview?: any[];
  audienceOpenUrl?: string;
  onClose: () => void;
  onValidate?: () => void;
  onPublish?: () => void;
  onDelete?: () => void | Promise<void>;
  onEdit?: () => void;
  canEdit?: boolean;
  onSaveEdit?: (vals: { title: string; content: string; tags: string[] }) => void | Promise<void>;
  onSelectNode?: (nodeId: string) => void;
  saving: boolean;
}) {
  const d = node.data || {};
  const [editing, setEditing] = useState(false);
  const [eTitle, setETitle] = useState(title);
  const [eContent, setEContent] = useState(content);
  const [eTags, setETags] = useState((tags || []).join(", "));
  const startEdit = () => {
    setETitle(title);
    setEContent(content);
    setETags((tags || []).join(", "));
    setEditing(true);
  };
  const commitEdit = async () => {
    await onSaveEdit?.({
      title: eTitle,
      content: eContent,
      tags: eTags.split(",").map((t) => t.trim()).filter(Boolean),
    });
    setEditing(false);
  };
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/55 p-5 backdrop-blur-sm">
      <div className="flex max-h-[88vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl glass-raised shadow-2xl shadow-black/40">
        <div className="sticky top-0 z-10 border-b border-white/10 bg-obs-surface/70 backdrop-blur-xl px-6 py-5">
          <div className="mb-3 flex flex-wrap gap-1.5">
            <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium tracking-wide ${STATUS_BADGE[d.status] || STATUS_BADGE.approved}`}>
              {d.validated ? "validated" : d.status || "active"}
            </span>
            <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] text-obs-subtle">{d.content_type || d.node_type}</span>
            <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] text-obs-subtle">{d.source || "graph"}</span>
          </div>
          <div className="flex items-start gap-4">
            {editing ? (
              <input
                value={eTitle}
                onChange={(e) => setETitle(e.target.value)}
                className="min-w-0 flex-1 rounded-lg border border-obs-violet/40 bg-obs-base px-3 py-1.5 text-xl font-semibold text-obs-text focus:outline-none focus:border-obs-violet"
              />
            ) : (
              <h2 className="min-w-0 flex-1 text-2xl font-semibold leading-tight tracking-tight text-obs-text">{title}</h2>
            )}
            <div className="flex items-center gap-2 shrink-0">
              {canEdit && onSaveEdit && !editing && (
                <button
                  onClick={startEdit}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-xl border border-white/[0.06] bg-white/[0.035] text-obs-subtle transition-colors hover:bg-white/[0.07] hover:text-obs-text"
                  aria-label="Editar"
                  title="Editar"
                >
                  <Edit2 size={14} />
                </button>
              )}
              {!canEdit && onEdit && (
                <button
                  onClick={onEdit}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-xl border border-white/[0.06] bg-white/[0.035] text-obs-subtle transition-colors hover:bg-white/[0.07] hover:text-obs-text"
                  aria-label="Editar"
                  title="Editar"
                >
                  <Edit2 size={14} />
                </button>
              )}
              <button
                onClick={onClose}
                className="inline-flex h-8 w-8 items-center justify-center rounded-xl border border-white/[0.06] bg-white/[0.035] text-obs-subtle transition-colors hover:bg-white/[0.07] hover:text-obs-text"
                aria-label="Fechar"
              >
                <X size={16} />
              </button>
            </div>
          </div>
        </div>
        <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">
          <div className="grid gap-2 md:grid-cols-3">
            {summaryItems.map(([label, value]) => (
              <div key={label} className="rounded-xl border border-white/[0.05] bg-white/[0.03] backdrop-blur-md p-3 shadow-sm shadow-black/10">
                <p className="text-[10px] font-medium uppercase tracking-wide text-obs-faint">{label}</p>
                <p className="mt-1 line-clamp-3 text-sm leading-6 text-obs-text">{String(value)}</p>
              </div>
            ))}
          </div>
          <section>
            <p className="mb-2 text-[10px] font-medium uppercase tracking-wide text-obs-subtle">Conteudo</p>
            {editing ? (
              <textarea
                value={eContent}
                onChange={(e) => setEContent(e.target.value)}
                rows={12}
                className="w-full rounded-xl border border-white/10 bg-obs-base px-4 py-3 text-sm leading-6 font-mono text-obs-text focus:outline-none focus:border-obs-violet/50 resize-y"
                placeholder="Conteudo / markdown"
              />
            ) : (
              <pre className="code-surface max-h-80 overflow-y-auto whitespace-pre-wrap rounded-xl p-4 text-sm leading-6 font-mono">
                {content || "Sem conteudo."}
              </pre>
            )}
          </section>
          {!!audiencePreview?.length && (
            <section>
              <div className="mb-2 flex items-center justify-between">
                <p className="text-[10px] uppercase tracking-wide text-obs-subtle">5 exemplos validos</p>
                {audienceOpenUrl && (
                  <button
                    type="button"
                    onClick={() => { window.location.href = audienceOpenUrl; }}
                    className="inline-flex items-center gap-1 rounded-md border border-obs-violet/35 bg-obs-violet/15 px-2 py-1 text-[10px] text-obs-text hover:bg-obs-violet/25"
                  >
                    <ExternalLink size={11} />
                    Abrir importacao
                  </button>
                )}
              </div>
              <LeadPreviewList rows={audiencePreview} />
            </section>
          )}
          <section>
            <p className="mb-2 text-[10px] uppercase tracking-wide text-obs-subtle">Tags</p>
            {editing ? (
              <input
                value={eTags}
                onChange={(e) => setETags(e.target.value)}
                placeholder="tag1, tag2, tag3"
                className="w-full rounded-lg border border-white/10 bg-obs-base px-3 py-2 text-xs text-obs-text focus:outline-none focus:border-obs-violet/50"
              />
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {tags.length ? tags.map((tag) => (
                  <span key={tag} className="rounded-full border border-obs-slate/20 bg-obs-slate/10 px-2 py-0.5 text-[10px] text-obs-slate">
                    {tag}
                  </span>
                )) : <span className="text-xs text-obs-faint">Sem tags.</span>}
              </div>
            )}
          </section>
          <section>
            <p className="mb-2 text-[10px] uppercase tracking-wide text-obs-subtle">Relacoes</p>
            <div className="grid gap-2 md:grid-cols-2">
              {(directLinks || []).map((link) => (
                <DirectLinkCard
                  key={link.id || link.other_id}
                  link={link}
                  onSelect={onSelectNode}
                />
              ))}
              {!directLinks?.length && <p className="text-xs text-obs-faint">Sem relacoes diretas.</p>}
            </div>
          </section>
        </div>
        <div className="sticky bottom-0 z-10 flex items-center justify-end gap-2 border-t border-white/10 bg-obs-surface/70 backdrop-blur-xl px-6 py-4">
          {editing && (
            <>
              <button
                onClick={() => setEditing(false)}
                disabled={saving}
                className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2 text-xs font-medium text-obs-subtle hover:bg-white/10 hover:text-obs-text disabled:opacity-50 transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={commitEdit}
                disabled={saving}
                className="inline-flex items-center gap-1.5 rounded-xl border border-obs-violet/40 bg-obs-violet/20 px-4 py-2 text-xs font-medium text-obs-text hover:bg-obs-violet/30 disabled:opacity-50 transition-colors"
              >
                {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
                Salvar
              </button>
            </>
          )}
          {!editing && onValidate && (
            <button
              onClick={onValidate}
              disabled={saving}
              className="inline-flex items-center gap-1.5 rounded-xl border border-emerald-300/30 bg-emerald-500/15 px-4 py-2 text-xs font-medium text-emerald-50 shadow-sm shadow-emerald-500/10 backdrop-blur-md hover:bg-emerald-500/25 hover:border-emerald-300/50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {saving ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle size={12} />}
              Aprovar
            </button>
          )}
          {!editing && onPublish && (
            <button
              onClick={onPublish}
              disabled={saving}
              className="inline-flex items-center gap-1.5 rounded-xl border border-obs-violet/35 bg-obs-violet/15 px-4 py-2 text-xs font-medium text-obs-text shadow-sm backdrop-blur-md hover:bg-obs-violet/25 hover:border-obs-violet/55 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {saving ? <Loader2 size={12} className="animate-spin" /> : <Tag size={12} />}
              Publicar no Golden Dataset
            </button>
          )}
          {!editing && onDelete && (
            <button
              onClick={onDelete}
              disabled={saving}
              className="inline-flex items-center gap-1.5 rounded-xl border border-red-300/35 bg-red-500/[0.18] px-4 py-2 text-xs font-medium text-red-50 shadow-sm shadow-red-500/[0.10] backdrop-blur-md hover:bg-red-500/[0.26] hover:border-red-300/55 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
            >
              <Trash2 size={12} />
              Excluir
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
