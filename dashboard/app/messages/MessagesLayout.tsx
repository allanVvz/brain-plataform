"use client";
import { useEffect, useState, useCallback, useRef, useMemo, memo } from "react";
import { api } from "@/lib/api";
import { formatDistanceToNow, format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { MessageSquare, User, RefreshCw, Search, Phone, Radio, AlertCircle, UserCheck, Send, Boxes, Megaphone, FileQuestion, FileText, Palette, Image as ImageIcon, FileVideo, FileType, ExternalLink, Database, PanelRightClose, PanelRightOpen, ArrowLeft, ChevronLeft, ChevronRight, Tag } from "lucide-react";
import { LeadInfoModal } from "@/components/leads/LeadInfoModal";
import Link from "next/link";
import { usePathname } from "next/navigation";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Lead {
  id: number;
  lead_id: string | null;
  nome: string | null;
  telefone: string | null;
  stage: string | null;
  ai_enabled: boolean | null;
  ai_paused: boolean | null;
  handoff_level?: "none" | "partial" | "full" | null;
  ultima_mensagem: string | null;
  last_update: string | null;
  updated_at: string | null;
  persona_id: string | null;
  interesse_produto: string | null;
  metadata?: {
    // Field set is dynamic — v3 leads derive this straight from whichever
    // facts the active branch's graph contract declares (not a fixed list
    // of legacy field names).
    commercial_note?: Record<string, string> | null;
    [key: string]: any;
  } | null;
  qualification_score?: number;
  qualification_signals?: Array<{ key?: string; label?: string; points?: number }>;
  validation?: {
    is_validation?: boolean;
    source?: string | null;
    run_id?: string | null;
    scenario?: string | null;
    session_id?: string | null;
  };
}

interface ConversationSummary {
  key: string;
  nome: string;
  lead_id: string | null;
  lead_ref: number | null;
  persona_id: string | null;
  interesse_produto: string | null;
  Lead_Stage: string | null;
  last_message: string;
  last_direction: string;
  last_sender_type: string;
  last_at: string;
  qualification_score?: number;
  qualification_signals?: Array<{ key?: string; label?: string; points?: number }>;
  validation?: { is_validation?: boolean; scenario?: string | null; session_id?: string | null };
}

type AttentionState = "ok" | "human_replying" | "awaiting_bot";

const AWAITING_BOT_THRESHOLD_MS = 5 * 60 * 1000; // 5min sem resposta do bot

// ── Knowledge sidebar types ──────────────────────────────────────────────────

interface KnowledgeNode {
  id: string;
  node_type: string;
  slug: string;
  title: string;
  summary: string | null;
  tags: string[] | null;
  metadata: Record<string, any> | null;
  link_target?: string | null;
  validated?: boolean;
  validation_status?: string;
  graph_distance?: number | null;
  path?: Array<{ node_id: string; slug: string | null; title: string | null; node_type: string | null; relation_type: string | null; direction: string | null }>;
  path_slugs?: string[];
  path_relations?: string[];
}

interface SimilarNode {
  node_id: string;
  node_type: string;
  slug: string;
  title: string;
  graph_distance: number | null;
  path: KnowledgeNode["path"];
  path_slugs: string[];
  path_relations: string[];
  validated: boolean;
  link_target: string | null;
}

interface KnowledgeEdge {
  id?: string;
  source_node_id?: string;
  target_node_id?: string;
  relation_type?: string;
  weight?: number | null;
}

interface KnowledgeAsset {
  id: string;
  title: string;
  asset_type: string | null;
  asset_function: string | null;
  file_path: string | null;
  url: string | null;
  tags: string[] | null;
  link_target?: string | null;
  validated?: boolean;
  validation_status?: string;
}

interface KnowledgeKbEntry {
  id?: string;
  kb_id?: string;
  source_table?: string;
  source_id?: string;
  titulo?: string;
  conteudo?: string;
  tipo?: string;
  tags?: string[] | null;
  node_type?: string;
  link_target?: string | null;
  validated?: boolean;
  validation_status?: string;
}

interface ChatContext {
  query_terms: string[];
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
  kb_entries: KnowledgeKbEntry[];
  assets: KnowledgeAsset[];
  similar?: SimilarNode[];
  validated?: { nodes?: KnowledgeNode[]; kb_entries?: KnowledgeKbEntry[]; assets?: KnowledgeAsset[] };
  unvalidated?: { nodes?: KnowledgeNode[]; kb_entries?: KnowledgeKbEntry[]; assets?: KnowledgeAsset[] };
  summary: string;
  mode?: "exact" | "reconstructed";
  persona_slug?: string;
  graph_version?: number;
  graph_checksum?: string;
  current_graph_version?: number;
  current_graph_checksum?: string;
  response?: { id?: number | string; message_id: string; created_at?: string; text?: string } | null;
  used_cards?: ContextCard[];
  related_cards?: ContextCard[];
  current_cards?: Record<string, ContextCard>;
  decisive_node_ids?: string[];
  operator_context?: {
    primary: Array<{
      id: string;
      node_type: string;
      title: string;
      markdown: string;
      validated: boolean;
      used_in_last_decision: boolean;
      path: NonNullable<KnowledgeNode["path"]>;
    }>;
    faq_rules: Array<{
      id: string;
      node_type: string;
      title: string;
      markdown: string;
      validated?: boolean;
      used_in_last_decision?: boolean;
      path?: KnowledgeNode["path"];
    }>;
    graph_path: NonNullable<KnowledgeNode["path"]>;
  };
}

interface ContextCard {
  id: string;
  projection_node_id?: string | null;
  node_type: string;
  slug: string;
  title: string;
  rendered_content: string;
  editable_content: string;
  content_checksum: string;
  revision: number;
  graph_version: number;
  graph_checksum: string;
  context_role: string;
  position: number;
  selection_reason: Record<string, any>;
  path: string[];
  chunk_refs: string[];
  source: string;
  status: string;
  relations: Array<Record<string, any>>;
  technical_metadata: Record<string, any>;
}

interface Message {
  id: number;
  lead_ref: number;
  message_id: string;
  sender_type: string;
  sender_id?: string | null;
  canal: string;
  texto: string;
  status: string;
  direction: string;
  metadata: any;
  created_at: string;
  Lead_Stage: string | null;
  nome: string | null;
}

function attentionFor(
  conv: ConversationSummary | undefined,
  now: number,
): AttentionState {
  if (!conv) return "ok";
  const sender = (conv.last_sender_type || "").toLowerCase();
  if (sender === "human") return "human_replying";
  // Última msg é do cliente (sender_type vazio, "user", ou similar) e não veio
  // resposta do bot/humano há mais que o threshold → aguardando atenção.
  const isClient = sender === "" || sender === "user" || sender === "client" || sender === "lead";
  if (!isClient) return "ok";
  const ts = conv.last_at ? new Date(conv.last_at).getTime() : 0;
  if (!ts) return "ok";
  return now - ts > AWAITING_BOT_THRESHOLD_MS ? "awaiting_bot" : "ok";
}

function attentionRowStyle(state: AttentionState, active: boolean): React.CSSProperties {
  // Selection reads as ink/weight, never an accent colour — an accent here
  // would collide with the meaning already reserved for evidence (teal) and
  // attention (amber/red) elsewhere in this screen.
  if (active) return { background: "rgb(var(--obs-text) / 0.06)", borderLeft: "2px solid rgb(var(--obs-text))" };
  if (state === "human_replying") return { background: "rgba(245,158,11,0.06)", borderLeft: "2px solid rgba(245,158,11,0.55)" };
  if (state === "awaiting_bot")   return { background: "rgba(239,68,68,0.05)",  borderLeft: "2px solid rgba(239,68,68,0.55)" };
  return { background: "transparent", borderLeft: "2px solid transparent" };
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function sortMessages(msgs: Message[]): Message[] {
  const byMessageId = new Map<string, Message>();
  for (const msg of msgs) {
    if (msg.message_id && !msg.message_id.startsWith("ai_reply.")) {
      byMessageId.set(msg.message_id, msg);
    }
  }

  return [...msgs].sort((a, b) => {
    const key = (msg: Message) => {
      const ts = new Date(msg.created_at).getTime() || 0;
      if (msg.message_id?.startsWith("ai_reply.")) {
        const base = byMessageId.get(msg.message_id.slice("ai_reply.".length));
        if (base) {
          return [
            new Date(base.created_at).getTime() || 0,
            base.id || 0,
            1,
            ts,
            msg.id || 0,
          ];
        }
      }
      return [ts, msg.id || 0, 0, ts, msg.id || 0];
    };
    const ka = key(a);
    const kb = key(b);
    for (let i = 0; i < ka.length; i++) {
      if (ka[i] !== kb[i]) return ka[i] - kb[i];
    }
    return 0;
  });
}

function isOutbound(msg: Message): boolean {
  const dir = (msg.direction || "").toLowerCase();
  const type = (msg.sender_type || "").toLowerCase();
  return (
    dir === "outbounding" ||
    dir === "outbound" ||
    type === "agent" ||
    type === "assistant" ||
    type === "ai"
  );
}
// Estágio "positivo do funil" — qualificado, oportunidade ou fechado — lê
// como o mesmo verde de --obs-live (canal conectado / IA ativa): as duas
// leituras da mesma ideia, "estado bom". Estágios anteriores ficam neutros.
const POSITIVE_STAGES = new Set(["qualificado", "interested", "oportunidade", "fechado", "won"]);

function stageColor(stage: string | null): string {
  const s = (stage || "").toLowerCase();
  if (POSITIVE_STAGES.has(s)) return "text-obs-live border-obs-live/30";
  if (s === "perdido" || s === "lost") return "text-red-400 border-red-400/30";
  return "text-obs-subtle border-obs-line";
}

function extractMediaUrl(metadata: any): string | null {
  if (!metadata) return null;
  if (typeof metadata === "string") {
    try { metadata = JSON.parse(metadata); } catch { return null; }
  }
  return metadata.media_url || metadata.image_url || metadata.file_url || metadata.url || null;
}

function relativeTs(ts: string | null): string {
  if (!ts) return "";
  try { return formatDistanceToNow(new Date(ts), { addSuffix: true, locale: ptBR }); }
  catch { return ""; }
}

function formatTs(ts: string): string {
  if (!ts) return "";
  try { return format(new Date(ts), "HH:mm · dd/MM", { locale: ptBR }); }
  catch { return ""; }
}

function truncateHash(hash: string, head = 14, tail = 6): string {
  if (!hash || hash.length <= head + tail + 1) return hash;
  return `${hash.slice(0, head)}…${hash.slice(-tail)}`;
}

const COMMERCIAL_NOTE_META_KEYS = new Set(["updated_at", "source"]);

function commercialNoteEntries(note: Record<string, string> | null | undefined): [string, string][] {
  if (!note) return [];
  return Object.entries(note).filter(
    ([key, value]) => !COMMERCIAL_NOTE_META_KEYS.has(key) && value,
  );
}

// The header badge is a small inline pill, not a form — show a couple of
// fields inline and count the rest, instead of only ever showing
// modelo_veiculo (confirmed live 2026-08-07: a lead with 6+ known fields
// still only ever displayed the vehicle, silently dropping everything else
// the v3 fact ledger had already captured).
function commercialNoteSummary(note: Record<string, string> | null | undefined): string {
  const entries = commercialNoteEntries(note);
  if (entries.length === 0) return "";
  const shown = entries.slice(0, 2).map(([key, value]) => `${key.replace(/_/g, " ")}: ${value}`);
  const rest = entries.length - shown.length;
  return rest > 0 ? `${shown.join(" · ")} · +${rest}` : shown.join(" · ");
}

function commercialNoteTitle(note: Record<string, string> | null | undefined): string {
  return commercialNoteEntries(note)
    .map(([key, value]) => `${key.replace(/_/g, " ")}: ${value}`)
    .join("\n");
}

function displayName(lead: Lead | null, msg?: Message): string {
  return (
    (lead?.nome?.trim()) ||
    (msg?.nome?.trim()) ||
    (lead?.telefone ? `+${lead.telefone}` : null) ||
    (lead ? `Lead #${lead.id}` : "Lead")
  );
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StageBadge({ stage }: { stage: string | null }) {
  return (
    <span
      className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full border ${stageColor(stage)}`}
      style={{ background: "rgb(var(--glass-solid-bg) / 0.7)" }}
    >
      {stage || "novo"}
    </span>
  );
}

function messageTurnId(msg: Message): string {
  return String(msg.message_id || msg.sender_id || msg.id || "");
}

function hasKnowledgeEvidence(msg: Message): boolean {
  const sender = String(msg.sender_type || "").toLowerCase();
  if (!isOutbound(msg) || sender === "human" || sender === "operator") return false;
  const metadata = msg.metadata || {};
  const envelope = metadata.knowledge_context || {};
  return Boolean(
    (Array.isArray(envelope.cards) && envelope.cards.length > 0)
    || (Array.isArray(envelope.decisive_node_ids) && envelope.decisive_node_ids.length > 0)
    || (Array.isArray(metadata.evidence_node_ids) && metadata.evidence_node_ids.length > 0)
    || metadata.graph_version,
  );
}

function MessageBubble({
  msg,
  lead,
  selected = false,
  onSelectEvidence,
}: {
  msg: Message;
  lead: Lead | null;
  selected?: boolean;
  onSelectEvidence?: (messageId: string) => void;
}) {
  const out = isOutbound(msg);
  const mediaUrl = extractMediaUrl(msg.metadata);
  const hasText = (msg.texto || "").trim().length > 0;
  // Outbound message written by a person on the team, not the model — same
  // sender_type the runtime writes for a manual reply. The evidence tint on
  // the bubble is reserved for the IA's own answers, so a human's outbound
  // text must not carry it (previously both rendered identically violet).
  const isHumanOperator = ["human", "operator"].includes(String(msg.sender_type || "").toLowerCase());
  const isAiSender = out && !isHumanOperator;
  const senderName = out
    ? isHumanOperator
      ? "Operador"
      : (msg.sender_type === "assistant" ? "Assistente IA" : msg.sender_type || "IA")
    : displayName(lead, msg);
  const deliveryLabel = (() => {
    const status = String(msg.status || "").toLowerCase();
    if (status === "pending" || status === "pending_send" || status === "processing" || status === "retry") return "enfileirada";
    if (status === "sent") return "enviada";
    if (status === "delivered") return "entregue";
    if (status === "read") return "lida";
    if (status === "failed" || status === "waiting_human" || status === "dead_letter") return "falha no envio";
    return null;
  })();
  const deliveryError = out && deliveryLabel === "falha no envio"
    ? String(msg.metadata?.outbox_error || "")
    : "";

  return (
    <div
      className={`flex flex-col gap-0.5 rounded-xl p-1 transition ${out ? "items-end" : "items-start"} ${selected ? "ring-2 ring-obs-teal/60 bg-obs-teal/5" : ""}`}
      role={hasKnowledgeEvidence(msg) ? "button" : undefined}
      tabIndex={hasKnowledgeEvidence(msg) ? 0 : undefined}
      aria-label={hasKnowledgeEvidence(msg) ? "Mostrar conhecimentos usados nesta resposta" : undefined}
      aria-pressed={hasKnowledgeEvidence(msg) ? selected : undefined}
      onClick={() => hasKnowledgeEvidence(msg) && onSelectEvidence?.(messageTurnId(msg))}
      onKeyDown={(event) => {
        if (!hasKnowledgeEvidence(msg) || !onSelectEvidence) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelectEvidence(messageTurnId(msg));
        }
      }}
    >
      <span className="text-[10px] px-1 text-obs-faint">{senderName}</span>

      <div
        className={`max-w-[72%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${out ? "rounded-tr-sm" : "rounded-tl-sm"}`}
        style={
          out
            ? isAiSender
              ? { background: "rgb(var(--obs-teal) / 0.14)", border: "1px solid rgb(var(--obs-teal) / 0.22)", color: "rgb(var(--obs-text))" }
              : { background: "rgb(var(--glass-solid-bg) / 0.85)", border: "1px solid var(--border-glass-strong)", color: "rgb(var(--obs-text))" }
            : { background: "rgb(var(--glass-solid-bg) / 0.74)", border: "1px solid var(--border-glass)", color: "rgb(var(--obs-text))" }
        }
      >
        {hasText && <p className="whitespace-pre-wrap break-words">{msg.texto}</p>}
        {!hasText && mediaUrl && (
          <a href={mediaUrl} target="_blank" rel="noopener noreferrer" className="text-xs underline text-obs-teal">
            Ver mídia anexada
          </a>
        )}
        {!hasText && !mediaUrl && (
          <span className="text-xs italic text-obs-faint">
            [{out ? "resposta automática" : "mensagem sem texto"}]
          </span>
        )}
      </div>

      <span className={`text-[10px] px-1 ${deliveryLabel === "falha no envio" ? "text-red-400" : "text-obs-faint"}`}>
        {formatTs(msg.created_at)}{out && deliveryLabel ? ` · ${deliveryLabel}` : ""}{deliveryError ? `: ${deliveryError}` : ""}
      </span>
    </div>
  );
}

// ── Knowledge sidebar ────────────────────────────────────────────────────────

const ASSET_IMAGE_EXT = /\.(png|jpe?g|svg|gif|webp)$/i;
const ASSET_VIDEO_EXT = /\.(mp4|mov|webm|avi)$/i;

function nodesByType(ctx: ChatContext | null, type: string): KnowledgeNode[] {
  return (ctx?.nodes || []).filter((n) => n.node_type === type);
}

function uniqueBy<T>(items: T[], identity: (item: T) => string): T[] {
  const seen = new Set<string>();
  const out: T[] = [];
  for (const item of items) {
    const key = identity(item);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(item);
  }
  return out;
}

function nodeIdentity(node: KnowledgeNode): string {
  return node.id || `${node.node_type}:${node.slug}:${node.title}`;
}

function kbEntryIdentity(entry: KnowledgeKbEntry): string {
  return (
    entry.id ||
    entry.source_id ||
    entry.kb_id ||
    `${entry.node_type || entry.tipo || "kb"}:${entry.titulo || ""}:${(entry.conteudo || "").slice(0, 80)}`
  );
}

function assetIdentity(asset: KnowledgeAsset): string {
  return asset.id || asset.url || asset.file_path || asset.title;
}

function scopedKey(scope: string, id: string): string {
  return `${scope}:${id}`;
}

function similarIdentity(node: SimilarNode): string {
  return node.node_id || `${node.node_type}:${node.slug}:${node.title}`;
}

function relationIdentity(edge: KnowledgeEdge): string {
  return edge.id || `${edge.source_node_id || ""}:${edge.relation_type || ""}:${edge.target_node_id || ""}`;
}

function nodeFocus(node: { node_type?: string | null; slug?: string | null; id?: string | null }): string | null {
  const type = node.node_type || "node";
  const slug = node.slug || node.id;
  return slug ? `${type}:${slug}` : null;
}

function graphTarget(focus?: string | null): string {
  return focus ? `/knowledge/graph?focus=${focus}` : "/knowledge/graph";
}

function normalizeKnowledgeText(value?: string | null): string {
  return (value || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function compactKnowledgeText(value?: string | null): string {
  return normalizeKnowledgeText(value).replace(/\s+/g, "");
}

function knowledgeSearchText(node: KnowledgeNode): string {
  const meta = node.metadata || {};
  const aliases = Array.isArray(meta.aliases) ? meta.aliases.join(" ") : "";
  const price = meta.price?.display || "";
  return [node.title, node.slug, node.summary, aliases, price, ...(node.tags || [])].join(" ");
}

function typePriority(nodeType: string): number {
  switch (nodeType) {
    case "product": return 140;
    case "brand": return 80;
    case "faq": return 70;
    case "copy": return 50;
    case "campaign": return 45;
    case "briefing": return 35;
    case "rule":
    case "tone": return 25;
    case "asset": return 20;
    case "mention": return -80;
    case "tag":
    case "persona": return -140;
    default: return 10;
  }
}

function nodeRelevanceScore(node: KnowledgeNode, queryTerms: string[]): number {
  const rawText = knowledgeSearchText(node);
  const text = normalizeKnowledgeText(rawText);
  const compactText = compactKnowledgeText(rawText);
  const title = normalizeKnowledgeText(node.title);
  const slug = normalizeKnowledgeText(node.slug);
  const terms = queryTerms.map(normalizeKnowledgeText).filter(Boolean);
  let score = typePriority(node.node_type);

  if (typeof node.graph_distance === "number") {
    score += Math.max(0, 50 - node.graph_distance * 18);
  }
  if (node.validated || node.validation_status === "validated") score += 10;
  if (node.node_type === "product" && productFacts(node.metadata).length > 0) score += 20;

  for (const term of terms) {
    const compactTerm = term.replace(/\s+/g, "");
    if (!term) continue;
    if (title === term || slug === term) score += 160;
    else if (title.includes(term) || slug.includes(term)) score += 110;
    else if (text.includes(term)) score += 75;
    if (compactTerm.length >= 5 && compactText.includes(compactTerm)) score += 75;

    for (const word of term.split(" ").filter((w) => w.length >= 4)) {
      if (title.includes(word) || slug.includes(word)) score += 12;
      else if (text.includes(word)) score += 5;
    }
  }

  return score;
}

function rankKnowledgeNodes(nodes: KnowledgeNode[], queryTerms: string[]): KnowledgeNode[] {
  return [...nodes]
    .map((node) => ({ node, score: nodeRelevanceScore(node, queryTerms) }))
    .sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      const da = typeof a.node.graph_distance === "number" ? a.node.graph_distance : 999;
      const db = typeof b.node.graph_distance === "number" ? b.node.graph_distance : 999;
      if (da !== db) return da - db;
      return a.node.title.localeCompare(b.node.title);
    })
    .map((item) => item.node);
}

function pickPrimaryKnowledge(nodes: KnowledgeNode[], queryTerms: string[]): KnowledgeNode | null {
  const ranked = rankKnowledgeNodes(nodes, queryTerms).filter((node) =>
    !["tag", "mention", "persona"].includes(node.node_type)
  );
  return ranked[0] || null;
}

// ── Knowledge expand state ───────────────────────────────────────────────────

type ExpandedKind = "node" | "kb" | "similar";
type ExpandedKnowledge = { kind: ExpandedKind; id: string } | null;

function productFacts(metadata: Record<string, any> | null): string[] {
  const meta = metadata || {};
  const price = meta.price || {};
  const facts: string[] = [];
  if (price.display) facts.push(String(price.display));
  else if (price.amount && price.currency) facts.push(`${price.currency} ${price.amount}`);
  if (meta.colors_count !== undefined && meta.colors_count !== null) facts.push(`${meta.colors_count} cores`);
  if (meta.size) facts.push(`Tam. ${meta.size}`);
  return facts;
}

function catalogUrl(metadata: Record<string, any> | null): string | null {
  const meta = metadata || {};
  return meta.catalog_url || meta.url || null;
}

function pathLabel(pathRelations?: string[], pathSlugs?: string[]): string {
  if (pathRelations && pathRelations.length > 0) return pathRelations.join(" -> ");
  if (pathSlugs && pathSlugs.length > 1) return pathSlugs.join(" -> ");
  return "";
}

function pendingLabel(item: { validated?: boolean; validation_status?: string }) {
  if (item.validated || item.validation_status === "validated") return null;
  return (
    <span className="ml-1 shrink-0 rounded border border-amber-400/40 bg-amber-500/10 px-1 py-0.5 text-[9px] uppercase text-amber-200">
      Pendente
    </span>
  );
}

// Evidence markdown is authored as "# title\n\n## Pergunta\n\n{question}\n\n## Resposta\n\n{answer}".
// The card already shows the title separately, so strip the repeated
// heading/question/label lines and keep only the actual answer content.
function extractEvidenceSummary(title: string, markdown: string): string {
  if (!markdown) return "";
  const normalizedTitle = normalizeKnowledgeText(title);
  const lines = markdown
    .split(/\r?\n/)
    .map((line) => line.replace(/^#+\s*/, "").trim())
    .filter(Boolean)
    .filter((line) => {
      const norm = normalizeKnowledgeText(line);
      if (!norm || norm === normalizedTitle) return false;
      if (norm === "pergunta" || norm === "resposta") return false;
      // Confirmed live 2026-08-07: the backend's canonical markdown embeds
      // a raw {"content_checksum": ..., "graph_id": ...} metadata line
      // inline. This card summary is meant for humans — skip any line
      // that's a JSON object/array rather than prose, instead of joining
      // it straight into the visible text.
      if (/^[[{].*[\]}]$/.test(line)) return false;
      return true;
    });
  return lines.join(" ").trim();
}

const EvidenceCard = memo(function EvidenceCard({
  item,
}: {
  item: { id: string; node_type: string; title: string; markdown: string; used_in_last_decision?: boolean };
}) {
  const summary = extractEvidenceSummary(item.title, item.markdown);
  return (
    <article className="relative z-10 flex items-start gap-2.5 py-1.5">
      {/* Ponto da linha de evidência — cheio quando usado na última
          decisão, vazado quando só relacionado. Fio conector vive no
          container pai (EvidenceLine). */}
      <span className="flex w-3.5 shrink-0 justify-center pt-1">
        <span
          className={`h-2 w-2 shrink-0 rounded-full ${item.used_in_last_decision ? "bg-obs-teal" : "border border-obs-teal/55 bg-obs-surface"}`}
        />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium leading-snug text-obs-text">{item.title}</p>
        <p className="mt-0.5 text-[9px] font-semibold uppercase tracking-wide text-obs-faint">{item.node_type}</p>
        {summary && summary !== item.title && (
          <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-obs-subtle">{summary}</p>
        )}
      </div>
    </article>
  );
});

function sortEvidenceByRelevance<T extends { used_in_last_decision?: boolean }>(
  items: T[],
  limit: number,
): T[] {
  return [...items]
    .sort((a, b) => Number(!!b.used_in_last_decision) - Number(!!a.used_in_last_decision))
    .slice(0, limit);
}

function KnowledgeSection({
  icon,
  title,
  count,
  children,
  showEmpty = false,
}: {
  icon: React.ReactNode;
  title: string;
  count: number;
  children: React.ReactNode;
  showEmpty?: boolean;
}) {
  if (count === 0 && !showEmpty) return null;
  return (
    <section className="space-y-1.5">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-obs-faint">
        {icon}
        <span>{title}</span>
        <span className="text-obs-faint/70">· {count}</span>
      </div>
      <div className="space-y-1.5">{children}</div>
    </section>
  );
}

function NodePill({
  node,
  active,
  onSelect,
}: {
  node: KnowledgeNode;
  active: boolean;
  onSelect: (id: string) => void;
}) {
  const facts = productFacts(node.metadata);
  const url = catalogUrl(node.metadata);
  const graphPath = pathLabel(node.path_relations, node.path_slugs);
  const id = nodeIdentity(node);
  return (
    <button
      type="button"
      onClick={() => onSelect(id)}
      className="w-full text-left block rounded-md px-2.5 py-1.5 text-xs hover:opacity-90 transition"
      style={{
        background: active ? "rgb(var(--obs-teal) / 0.22)" : "rgb(var(--obs-teal) / 0.10)",
        border: `1px solid ${active ? "rgb(var(--obs-teal) / 0.65)" : "rgb(var(--obs-teal) / 0.30)"}`,
        color: "rgb(var(--obs-text))",
      }}
    >
      <div className="flex items-center gap-1 min-w-0">
        <p className="font-medium truncate">{node.title}</p>
        <span className="shrink-0 rounded border border-obs-line px-1 py-0.5 text-[9px] uppercase text-obs-faint">
          {node.node_type}
        </span>
        {pendingLabel(node)}
        <ChevronRight size={10} className="ml-auto shrink-0 opacity-60" />
      </div>
      {node.summary && <p className="text-[11px] text-obs-subtle line-clamp-2 mt-0.5">{node.summary}</p>}
      {facts.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {facts.map((fact) => (
            <span key={fact} className="rounded border border-obs-line bg-obs-surface/70 px-1.5 py-0.5 text-[10px] text-obs-subtle">
              {fact}
            </span>
          ))}
        </div>
      )}
      {url && <p className="mt-1 truncate text-[10px] text-obs-teal">{url}</p>}
      {typeof node.graph_distance === "number" && (
        <p className="mt-1 text-[10px] text-obs-faint">
          dist. {node.graph_distance}{graphPath ? ` · ${graphPath}` : ""}
        </p>
      )}
    </button>
  );
}

function SimilarCard({
  node,
  active,
  onSelect,
}: {
  node: SimilarNode;
  active: boolean;
  onSelect: (id: string) => void;
}) {
  const graphPath = pathLabel(node.path_relations, node.path_slugs);
  const id = similarIdentity(node);
  return (
    <button
      type="button"
      onClick={() => onSelect(id)}
      className="w-full text-left block rounded-md px-2.5 py-1.5 text-xs hover:opacity-90 transition"
      style={{
        background: active ? "rgba(34,211,238,0.18)" : "rgba(34,211,238,0.08)",
        border: `1px solid ${active ? "rgba(34,211,238,0.55)" : "rgba(34,211,238,0.22)"}`,
        color: "rgb(var(--obs-text))",
      }}
    >
      <div className="flex items-center gap-1 min-w-0">
        <p className="font-medium truncate">{node.title}</p>
        <span className="shrink-0 rounded border border-obs-line px-1 py-0.5 text-[9px] uppercase text-obs-faint">
          {node.node_type}
        </span>
        <span className="ml-auto shrink-0 text-[10px] text-obs-faint">d{node.graph_distance ?? "-"}</span>
      </div>
      {graphPath && <p className="mt-0.5 truncate text-[10px] text-obs-faint">{graphPath}</p>}
    </button>
  );
}

function KbCard({
  entry,
  active,
  onSelect,
}: {
  entry: KnowledgeKbEntry;
  active: boolean;
  onSelect: (id: string) => void;
}) {
  const title = entry.titulo || "(sem título)";
  const rawBody = entry.conteudo || "";
  const isFaq = String(entry.node_type || entry.tipo || "").toLowerCase() === "faq";
  let body = rawBody;
  if (isFaq) {
    try {
      const parsed = JSON.parse(rawBody);
      body = parsed.resposta || parsed.answer || parsed.content || rawBody;
    } catch {
      const lines = rawBody.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
      if (lines.length > 1 && normalizeKnowledgeText(lines[0]) === normalizeKnowledgeText(title)) {
        lines.shift();
      }
      body = lines.join(" ").replace(/^resposta\s*:\s*/i, "");
    }
  }
  body = body.slice(0, 320);
  const id = kbEntryIdentity(entry);
  if (isFaq) {
    return (
      <button
        type="button"
        onClick={() => onSelect(id)}
        className="block w-full rounded-lg border border-obs-teal/25 bg-obs-teal/5 px-3 py-2.5 text-left text-xs transition hover:border-obs-teal/45"
      >
        <div className="flex items-start gap-2">
          <span className="mt-0.5 rounded bg-obs-teal px-1.5 py-0.5 text-[9px] font-semibold uppercase text-white">FAQ</span>
          <p className="line-clamp-2 flex-1 font-semibold leading-snug text-obs-text">{title}</p>
          {pendingLabel(entry)}
          <ChevronRight size={11} className="mt-0.5 shrink-0 text-obs-teal" />
        </div>
        {body && (
          <p className="mt-2 line-clamp-4 border-t border-obs-teal/20 pt-2 text-[11px] leading-relaxed text-obs-subtle">
            {body}
          </p>
        )}
      </button>
    );
  }
  return (
    <button
      type="button"
      onClick={() => onSelect(id)}
      className="w-full text-left block rounded-md px-2.5 py-1.5 text-xs hover:opacity-90 transition"
      style={{
        background: active ? "rgb(var(--obs-text) / 0.05)" : "rgb(var(--glass-solid-bg) / 0.72)",
        border: `1px solid ${active ? "rgb(var(--obs-text) / 0.18)" : "var(--border-glass)"}`,
      }}
    >
      <div className="flex items-center gap-1 min-w-0">
        <p className="text-obs-text font-medium truncate">{title}</p>
        {pendingLabel(entry)}
        <ChevronRight size={10} className="ml-auto shrink-0 opacity-60" />
      </div>
      {body && <p className="text-[11px] text-obs-subtle line-clamp-3 mt-0.5">{body}</p>}
    </button>
  );
}

function AssetCard({ asset }: { asset: KnowledgeAsset }) {
  const path = asset.file_path || "";
  const url = asset.url;
  const isImage = url && ASSET_IMAGE_EXT.test(path);
  const isVideo = url && ASSET_VIDEO_EXT.test(path);
  const Icon = isImage ? ImageIcon : isVideo ? FileVideo : FileType;
  const ext = path.split(".").pop()?.toUpperCase() || "FILE";
  const target = asset.link_target || url || "#";

  return (
    <a
      href={target}
      target="_blank"
      rel="noopener noreferrer"
      className="block rounded-md overflow-hidden text-xs hover:opacity-90 transition"
      style={{ background: "rgb(var(--glass-solid-bg) / 0.78)", border: "1px solid var(--border-glass)" }}
    >
      {isImage ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={url!} alt={asset.title} className="w-full h-24 object-cover" />
      ) : (
        <div className="flex items-center justify-center h-16" style={{ background: "rgb(var(--obs-teal) / 0.10)" }}>
          <Icon size={20} className="text-obs-teal" />
        </div>
      )}
      <div className="px-2 py-1.5 space-y-0.5">
        <p className="font-medium text-obs-text truncate">{asset.title}</p>
        <div className="flex items-center justify-between text-[10px] text-obs-faint">
          <span>{asset.asset_function || asset.asset_type || ext}</span>
          {url && <ExternalLink size={9} />}
        </div>
      </div>
    </a>
  );
}

function RelationCard({
  edge,
  nodeById,
  onSelect,
}: {
  edge: KnowledgeEdge;
  nodeById: Map<string, KnowledgeNode>;
  onSelect: (id: string) => void;
}) {
  const source = edge.source_node_id ? nodeById.get(edge.source_node_id) : undefined;
  const targetNode = edge.target_node_id ? nodeById.get(edge.target_node_id) : undefined;
  const handleClick = () => {
    const pick = source || targetNode;
    if (pick) onSelect(nodeIdentity(pick));
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className="w-full text-left block rounded-md px-2.5 py-1.5 text-xs hover:opacity-90 transition"
      style={{ background: "rgb(var(--glass-solid-bg) / 0.72)", border: "1px solid var(--border-glass)" }}
    >
      <div className="flex items-center gap-1 min-w-0">
        <p className="font-medium text-obs-text truncate">{source?.title || edge.source_node_id || "origem"}</p>
        <span className="shrink-0 text-[10px] text-obs-faint">→</span>
        <p className="font-medium text-obs-text truncate">{targetNode?.title || edge.target_node_id || "destino"}</p>
        <ChevronRight size={10} className="ml-auto shrink-0 opacity-60" />
      </div>
      <p className="mt-0.5 truncate text-[10px] text-obs-faint">
        {edge.relation_type || "related"}
        {typeof edge.weight === "number" ? ` · peso ${edge.weight}` : ""}
      </p>
    </button>
  );
}

function KnowledgeDetail({
  expanded,
  ctx,
  onBack,
}: {
  expanded: { kind: ExpandedKind; id: string };
  ctx: ChatContext;
  onBack: () => void;
}) {
  // Resolve the entity by kind+id
  const node =
    expanded.kind === "node"
      ? (ctx.nodes || []).find((n) => nodeIdentity(n) === expanded.id) || null
      : null;
  const similar =
    expanded.kind === "similar"
      ? (ctx.similar || []).find((n) => similarIdentity(n) === expanded.id) || null
      : null;
  const kb =
    expanded.kind === "kb"
      ? (ctx.kb_entries || []).find((e) => kbEntryIdentity(e) === expanded.id) || null
      : null;

  const title = node?.title || similar?.title || kb?.titulo || "(sem detalhes)";
  const nodeType = node?.node_type || similar?.node_type || kb?.node_type || kb?.tipo || null;
  const slug = node?.slug || similar?.slug || null;
  const summary = node?.summary || null;
  const tags = node?.tags || (kb?.tags as string[] | null) || null;
  const meta = node?.metadata || null;
  const facts = productFacts(meta);
  const url = catalogUrl(meta);
  const isPending = node
    ? !(node.validated || node.validation_status === "validated")
    : kb
    ? !(kb.validated || kb.validation_status === "validated")
    : false;

  // Resolve graph focus + connected edges
  const targetId = node?.id || similar?.node_id || null;
  const nodeById = new Map((ctx.nodes || []).map((n) => [n.id, n]));
  const incoming = targetId
    ? (ctx.edges || []).filter((e) => e.target_node_id === targetId)
    : [];
  const outgoing = targetId
    ? (ctx.edges || []).filter((e) => e.source_node_id === targetId)
    : [];

  const focus = (() => {
    if (node) return nodeFocus(node);
    if (similar) return nodeFocus({ node_type: similar.node_type, slug: similar.slug, id: similar.node_id });
    return null;
  })();

  return (
    <div className="p-3 space-y-3 overflow-y-auto h-full">
      {/* Header w/ back */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onBack}
          className="flex items-center gap-1 text-[11px] text-obs-subtle hover:text-obs-text transition"
        >
          <ArrowLeft size={11} />
          <span>Voltar</span>
        </button>
        {nodeType && (
          <span className="ml-auto rounded border border-obs-line px-1.5 py-0.5 text-[9px] uppercase text-obs-faint">
            {nodeType}
          </span>
        )}
        {isPending && (
          <span className="rounded border border-amber-400/40 bg-amber-500/10 px-1.5 py-0.5 text-[9px] uppercase text-amber-200">
            Pendente
          </span>
        )}
      </div>

      <div className="space-y-1">
        <h3 className="text-sm font-semibold text-obs-text leading-tight">{title}</h3>
        {slug && <p className="text-[11px] font-mono text-obs-subtle truncate">{slug}</p>}
        {typeof similar?.graph_distance === "number" && (
          <p className="text-[10px] text-obs-faint">distância no grafo: {similar.graph_distance}</p>
        )}
      </div>

      {summary && (
        <div>
          <p className="text-[10px] uppercase tracking-wide text-obs-faint mb-1">Resumo</p>
          <p className="text-[12px] text-obs-subtle leading-snug">{summary}</p>
        </div>
      )}

      {kb && (kb.conteudo || "").trim() && (
        <div>
          <p className="text-[10px] uppercase tracking-wide text-obs-faint mb-1">Conteúdo</p>
          <pre
            className="text-[11px] text-obs-subtle whitespace-pre-wrap break-words rounded-md p-2 leading-relaxed font-mono max-h-56 overflow-y-auto"
            style={{ background: "rgb(var(--glass-solid-bg) / 0.72)", border: "1px solid var(--border-glass)" }}
          >
            {kb.conteudo}
          </pre>
        </div>
      )}

      {facts.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wide text-obs-faint mb-1">Fatos</p>
          <div className="flex flex-wrap gap-1">
            {facts.map((f) => (
              <span
                key={f}
                className="rounded border border-obs-line bg-obs-surface/70 px-1.5 py-0.5 text-[10px] text-obs-subtle"
              >
                {f}
              </span>
            ))}
          </div>
        </div>
      )}

      {tags && tags.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wide text-obs-faint mb-1 flex items-center gap-1">
            <Tag size={9} /> Tags
          </p>
          <div className="flex flex-wrap gap-1">
            {tags.map((t) => (
              <span
                key={t}
                className="rounded-full bg-obs-slate/10 border border-obs-slate/20 text-obs-slate font-mono px-2 py-0.5 text-[10px]"
              >
                {t}
              </span>
            ))}
          </div>
        </div>
      )}

      {url && (
        <div>
          <p className="text-[10px] uppercase tracking-wide text-obs-faint mb-1">Link</p>
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[11px] text-obs-teal underline break-all"
          >
            {url}
          </a>
        </div>
      )}

      {(incoming.length > 0 || outgoing.length > 0) && (
        <div className="space-y-1.5">
          <p className="text-[10px] uppercase tracking-wide text-obs-faint">
            Conexões · {incoming.length + outgoing.length}
          </p>
          {outgoing.map((e) => {
            const dest = e.target_node_id ? nodeById.get(e.target_node_id) : undefined;
            return (
              <div
                key={`out-${relationIdentity(e)}`}
                className="rounded-md px-2 py-1.5"
                style={{ background: "rgb(var(--obs-surface) / 0.72)", border: "1px solid var(--border-glass)" }}
              >
                <div className="flex items-center gap-1 text-[11px] text-obs-text min-w-0">
                  <span className="text-[10px] text-obs-faint">→</span>
                  <span className="truncate">{dest?.title || e.target_node_id || "destino"}</span>
                  {dest?.node_type && (
                    <span className="ml-auto shrink-0 rounded border border-obs-line px-1 py-0.5 text-[9px] uppercase text-obs-faint">
                      {dest.node_type}
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-[10px] text-obs-faint truncate">
                  {e.relation_type || "related"}
                  {typeof e.weight === "number" ? ` · peso ${e.weight}` : ""}
                </p>
              </div>
            );
          })}
          {incoming.map((e) => {
            const src = e.source_node_id ? nodeById.get(e.source_node_id) : undefined;
            return (
              <div
                key={`in-${relationIdentity(e)}`}
                className="rounded-md px-2 py-1.5"
                style={{ background: "rgb(var(--obs-surface) / 0.72)", border: "1px solid var(--border-glass)" }}
              >
                <div className="flex items-center gap-1 text-[11px] text-obs-text min-w-0">
                  <span className="text-[10px] text-obs-faint">←</span>
                  <span className="truncate">{src?.title || e.source_node_id || "origem"}</span>
                  {src?.node_type && (
                    <span className="ml-auto shrink-0 rounded border border-obs-line px-1 py-0.5 text-[9px] uppercase text-obs-faint">
                      {src.node_type}
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-[10px] text-obs-faint truncate">
                  {e.relation_type || "related"}
                  {typeof e.weight === "number" ? ` · peso ${e.weight}` : ""}
                </p>
              </div>
            );
          })}
        </div>
      )}

      <div className="pt-2">
        <a
          href={graphTarget(focus)}
          className="block w-full text-center text-[11px] py-1.5 rounded-md border border-obs-teal/40 bg-obs-teal/10 text-obs-teal hover:bg-obs-teal/20 transition"
        >
          Ver no grafo →
        </a>
      </div>
    </div>
  );
}

const NODE_TYPE_LABELS: Record<string, string> = {
  persona: "Persona",
  brand: "Marca",
  tone: "Tom de voz",
  rule: "Regra",
  product: "Produto",
  offer: "Oferta",
  faq: "Pergunta frequente",
  copy: "Texto",
  campaign: "Campanha",
  product_group: "Grupo de produtos",
  audience: "Público",
  asset: "Arquivo",
  briefing: "Briefing",
};

function humanizeNodeType(nodeType: string): string {
  return NODE_TYPE_LABELS[nodeType] || nodeType.replace(/_/g, " ");
}

// Mirrors the relevance ordering context_cards.py uses server-side
// (rule/tone weighted above brand/persona) so the default "essential" set
// shown before "mostrar mais" isn't an arbitrary cutoff.
const RELATED_TYPE_ORDER = ["rule", "tone", "brand", "persona"];
const ESSENTIAL_RELATED_LIMIT = 4;

function sortRelatedByEssentiality(cards: ContextCard[]): ContextCard[] {
  return [...cards].sort((a, b) => {
    const ai = RELATED_TYPE_ORDER.indexOf(a.node_type);
    const bi = RELATED_TYPE_ORDER.indexOf(b.node_type);
    return (ai === -1 ? RELATED_TYPE_ORDER.length : ai) - (bi === -1 ? RELATED_TYPE_ORDER.length : bi);
  });
}

// O fio vertical que costura os pontos de ContextCardButton — a assinatura
// visual da direção "Evidência". Fica atrás dos botões (z-0 vs. z-10 deles)
// e corre do centro do primeiro ao centro do último ponto.
function EvidenceLine({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative">
      <div className="pointer-events-none absolute left-[1.1rem] top-2.5 bottom-2.5 w-px bg-obs-teal/25" />
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function ContextCardButton({
  card,
  decisive,
  changed,
  onClick,
}: {
  card: ContextCard;
  decisive: boolean;
  changed: boolean;
  onClick: () => void;
}) {
  const summary = extractEvidenceSummary(card.title, card.rendered_content);
  return (
    <button
      type="button"
      onClick={onClick}
      className="group relative z-10 flex w-full items-start gap-2.5 rounded-lg py-1.5 pr-1.5 text-left transition hover:bg-obs-teal/5 focus:outline-none focus:ring-2 focus:ring-obs-teal/30"
    >
      {/* Ponto da linha de evidência — cheio quando decisivo, vazado
          quando só relacionado. O fio conector vive no container pai
          (ver EvidenceLine), não aqui, pra atravessar vários cards. */}
      <span className="flex w-3.5 shrink-0 justify-center pt-1">
        <span
          className={`h-2 w-2 shrink-0 rounded-full ${decisive ? "bg-obs-teal" : "border border-obs-teal/55 bg-obs-surface"}`}
        />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-1.5">
          <span className="min-w-0 flex-1 text-xs font-medium leading-snug text-obs-text">{card.title}</span>
          <ChevronRight size={11} className="mt-0.5 shrink-0 text-obs-faint" />
        </div>
        <p className="mt-0.5 text-[9px] font-semibold uppercase tracking-wide text-obs-faint">
          {humanizeNodeType(card.node_type)}
        </p>
        {summary && <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-obs-subtle">{summary}</p>}
        {(decisive || changed) && (
          <div className="mt-1 flex flex-wrap gap-1">
            {decisive && <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[9px] text-emerald-400">decisivo</span>}
            {changed && <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[9px] text-amber-400">alterado depois</span>}
          </div>
        )}
      </div>
    </button>
  );
}

function ContextCardModal({
  card,
  current,
  canEdit,
  personaSlug,
  currentGraphVersion,
  onClose,
  onPublished,
}: {
  card: ContextCard;
  current?: ContextCard;
  canEdit: boolean;
  personaSlug?: string;
  currentGraphVersion?: number;
  onClose: () => void;
  onPublished: () => void;
}) {
  const live = current || card;
  const changed = Boolean(current && current.content_checksum !== card.content_checksum);
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState(live.editable_content || "");
  const [reason, setReason] = useState("Atualização pelo card de conhecimento da conversa");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    if (!personaSlug || !currentGraphVersion || !content.trim() || !reason.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await api.publishContextCard(card.id, {
        persona_slug: personaSlug,
        content: content.trim(),
        expected_version: currentGraphVersion,
        reason: reason.trim(),
        idempotency_key: crypto.randomUUID(),
      });
      setEditing(false);
      onPublished();
    } catch (err) {
      setError(getErrorMessage(err, "Falha ao salvar e publicar."));
      onPublished();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4" role="dialog" aria-modal="true" aria-labelledby="context-card-title" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="modal-content max-h-[90vh] w-full max-w-3xl overflow-y-auto">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-obs-teal">{card.node_type} · revisão {card.revision}</p>
            <h2 id="context-card-title" className="mt-1 text-lg font-semibold text-obs-text">{card.title}</h2>
          </div>
          <button type="button" onClick={onClose} className="rounded-md border border-obs-line px-2 py-1 text-xs text-obs-subtle">Fechar</button>
        </div>

        <section className="mt-5">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-obs-faint">Conteúdo exato usado na resposta</p>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-obs-line bg-obs-base/60 p-3 text-[11px] leading-relaxed text-obs-subtle">{card.rendered_content}</pre>
        </section>

        {changed && current && (
          <section className="mt-4">
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-amber-600">Versão atual · v{current.graph_version}</p>
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-obs-amber/30 bg-obs-amber-soft p-3 text-[11px] leading-relaxed text-obs-subtle">{current.rendered_content}</pre>
          </section>
        )}

        {canEdit && personaSlug && currentGraphVersion && (
          <section className="mt-4 rounded-lg border border-obs-line p-3">
            {!editing ? (
              <button type="button" onClick={() => setEditing(true)} className="rounded-md bg-obs-teal px-3 py-1.5 text-xs font-medium text-white">Editar versão atual</button>
            ) : (
              <div className="space-y-2">
                <label className="block text-[10px] font-semibold uppercase text-obs-faint">Conteúdo editável</label>
                <textarea value={content} onChange={(event) => setContent(event.target.value)} rows={8} className="lg-input w-full text-xs" />
                <label className="block text-[10px] font-semibold uppercase text-obs-faint">Motivo da publicação</label>
                <input value={reason} onChange={(event) => setReason(event.target.value)} className="lg-input w-full text-xs" />
                {error && <p className="text-xs text-red-500">{error}</p>}
                <div className="flex gap-2">
                  <button type="button" onClick={save} disabled={saving || !content.trim() || !reason.trim()} className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50">{saving ? "Publicando…" : "Salvar e publicar"}</button>
                  <button type="button" onClick={() => setEditing(false)} disabled={saving} className="lg-btn lg-btn-secondary text-xs">Cancelar</button>
                </div>
              </div>
            )}
          </section>
        )}

        <section className="mt-4 grid gap-2 text-[11px] text-obs-subtle sm:grid-cols-2">
          <p><span className="text-obs-faint">Fonte:</span> {card.source}</p>
          <p><span className="text-obs-faint">Estado:</span> {card.status}</p>
          <p><span className="text-obs-faint">Grafo:</span> v{card.graph_version}</p>
          <p
            className="cursor-pointer break-all font-mono text-[10px]"
            title="Clique para copiar o checksum completo"
            onClick={() => navigator.clipboard?.writeText(card.content_checksum)}
          >
            <span className="text-obs-faint font-sans">Checksum:</span> {truncateHash(card.content_checksum)}
          </p>
        </section>

        {card.relations.length > 0 && (
          <section className="mt-4 rounded-lg border border-obs-line p-3">
            <p className="text-xs font-medium text-obs-text">Relações · {card.relations.length}</p>
            <div className="mt-2 space-y-1 text-[11px] text-obs-subtle">
              {card.relations.map((rel, i) => (
                <div key={i} className="flex flex-wrap items-baseline gap-x-1.5">
                  <span className="font-medium text-obs-text">
                    {String(rel.relation_type || rel.type || rel.relation || "relação")}
                  </span>
                  <span className="text-obs-faint">→</span>
                  <span>{String(rel.title || rel.target_title || rel.name || rel.target_id || rel.id || "—")}</span>
                  {rel.node_type && <span className="text-obs-faint">({String(rel.node_type)})</span>}
                </div>
              ))}
            </div>
          </section>
        )}
        <details className="mt-2 rounded-lg border border-obs-line p-3">
          <summary className="cursor-pointer text-xs font-medium text-obs-text">Detalhes técnicos</summary>
          <div className="mt-2 space-y-1 text-[11px] text-obs-subtle">
            <p className="break-all font-mono text-[10px]"><span className="text-obs-faint font-sans">ID:</span> {card.id}</p>
            {card.projection_node_id && (
              <p className="break-all font-mono text-[10px]"><span className="text-obs-faint font-sans">Node de projeção:</span> {card.projection_node_id}</p>
            )}
            {card.path.length > 0 && <p><span className="text-obs-faint">Caminho:</span> {card.path.join(" → ")}</p>}
            {card.chunk_refs.length > 0 && (
              <p><span className="text-obs-faint">Trechos usados:</span> {card.chunk_refs.length}</p>
            )}
            {card.selection_reason && Object.keys(card.selection_reason).length > 0 &&
              Object.entries(card.selection_reason).map(([key, value]) => (
                <p key={key}><span className="text-obs-faint">{key}:</span> {typeof value === "object" ? JSON.stringify(value) : String(value)}</p>
              ))}
            {card.technical_metadata && Object.entries(card.technical_metadata).map(([key, value]) => (
              <p key={key}><span className="text-obs-faint">{key}:</span> {typeof value === "object" ? JSON.stringify(value) : String(value)}</p>
            ))}
          </div>
        </details>
      </div>
    </div>
  );
}

export function KnowledgeSidebar({
  ctx,
  loading,
  leadSelected,
  canEdit = false,
  onPublished = () => undefined,
}: {
  ctx: ChatContext | null;
  loading: boolean;
  leadSelected: boolean;
  canEdit?: boolean;
  onPublished?: () => void;
}) {
  const [expanded, setExpanded] = useState<ExpandedKnowledge>(null);
  const [selectedCard, setSelectedCard] = useState<ContextCard | null>(null);

  // Clear expand state when ctx changes (e.g., switching leads)
  useEffect(() => { setExpanded(null); setSelectedCard(null); }, [ctx?.response?.message_id]);

  if (!leadSelected) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-4 text-center">
        <Boxes size={22} className="text-obs-faint/40 mb-2" />
        <p className="text-xs text-obs-faint">Selecione um lead para ver o conhecimento relacionado.</p>
      </div>
    );
  }
  if (loading && !ctx) {
    return <div className="p-4 text-xs text-obs-faint">Carregando conhecimento…</div>;
  }
  if (!ctx) return null;
  if (ctx.used_cards !== undefined) {
    const used = [...(ctx.used_cards || [])].sort((a, b) => a.position - b.position);
    const decisive = new Set(ctx.decisive_node_ids || []);
    const related = sortRelatedByEssentiality(ctx.related_cards || []);
    const essentialRelated = related.slice(0, ESSENTIAL_RELATED_LIMIT);
    const extraRelated = related.slice(ESSENTIAL_RELATED_LIMIT);
    return (
      <div className="h-full overflow-y-auto p-3">
        <div className="mb-3 px-0.5">
          <div className="flex items-center justify-between gap-2">
            <span className={`rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase ${ctx.mode === "exact" ? "bg-emerald-500/15 text-emerald-400" : "bg-amber-500/15 text-amber-400"}`}>
              {ctx.mode === "exact" ? "espelho exato" : "evidência reconstruída"}
            </span>
            <span className="text-[10px] text-obs-faint">grafo v{ctx.graph_version || "?"}</span>
          </div>
          {ctx.response?.created_at && <p className="mt-1 text-[10px] text-obs-faint">Resposta de {formatTs(ctx.response.created_at)}</p>}
        </div>

        <KnowledgeSection icon={<Boxes size={11} />} title="Usado nesta resposta" count={used.length} showEmpty>
          {used.length > 0 ? (
            <EvidenceLine>
              {used.map((card) => {
                const current = ctx.current_cards?.[card.id];
                return (
                  <ContextCardButton
                    key={`${card.id}:${card.content_checksum}`}
                    card={card}
                    decisive={decisive.has(card.id)}
                    changed={Boolean(current && current.content_checksum !== card.content_checksum)}
                    onClick={() => setSelectedCard(card)}
                  />
                );
              })}
            </EvidenceLine>
          ) : <p className="text-[11px] text-obs-faint">Nenhum card confirmado para esta resposta.</p>}
        </KnowledgeSection>

        {related.length > 0 && (
          <div className="mt-4 rounded-lg border border-obs-line bg-obs-surface/50 p-2.5">
            <p className="text-[11px] font-medium text-obs-text">Relacionados · {related.length}</p>
            <p className="mt-1 text-[10px] text-obs-faint">Não usados nesta resposta.</p>
            <div className="mt-2">
              <EvidenceLine>
                {essentialRelated.map((card) => (
                  <ContextCardButton key={`related:${card.id}`} card={card} decisive={false} changed={false} onClick={() => setSelectedCard(card)} />
                ))}
              </EvidenceLine>
            </div>
            {extraRelated.length > 0 && (
              <details className="mt-2">
                <summary className="cursor-pointer text-[10px] font-medium text-obs-faint hover:text-obs-subtle">
                  Mostrar mais {extraRelated.length}
                </summary>
                <div className="mt-2">
                  <EvidenceLine>
                    {extraRelated.map((card) => (
                      <ContextCardButton key={`related:${card.id}`} card={card} decisive={false} changed={false} onClick={() => setSelectedCard(card)} />
                    ))}
                  </EvidenceLine>
                </div>
              </details>
            )}
          </div>
        )}

        {selectedCard && (
          <ContextCardModal
            key={`${selectedCard.id}:${selectedCard.content_checksum}`}
            card={selectedCard}
            current={ctx.current_cards?.[selectedCard.id]}
            canEdit={canEdit}
            personaSlug={ctx.persona_slug}
            currentGraphVersion={ctx.current_graph_version}
            onClose={() => setSelectedCard(null)}
            onPublished={onPublished}
          />
        )}
      </div>
    );
  }
  if (ctx.operator_context) {
    const operator = ctx.operator_context;
    // Cap and rank by "used in the last decision" so the cards most useful
    // for the current decision surface first, without overwhelming the panel.
    const primaryRanked = sortEvidenceByRelevance(operator.primary, 4);
    const faqRulesRanked = sortEvidenceByRelevance(operator.faq_rules, 4);
    return (
      <div className="h-full space-y-4 overflow-y-auto p-3">
        <KnowledgeSection
          icon={<Boxes size={11} />}
          title="Usado nesta resposta"
          count={operator.primary.length}
          showEmpty
        >
          {primaryRanked.length > 0 ? (
            <EvidenceLine>
              {primaryRanked.map((item) => <EvidenceCard key={item.id} item={item} />)}
            </EvidenceLine>
          ) : (
            <p className="text-[11px] text-obs-faint">
              Nenhuma evidência registrada na última decisão.
            </p>
          )}
        </KnowledgeSection>
        <KnowledgeSection
          icon={<FileQuestion size={11} />}
          title="FAQ e regras relacionadas"
          count={operator.faq_rules.length}
          showEmpty
        >
          {faqRulesRanked.length > 0 ? (
            <EvidenceLine>
              {faqRulesRanked.map((item) => <EvidenceCard key={item.id} item={item} />)}
            </EvidenceLine>
          ) : (
            <p className="text-[11px] text-obs-faint">
              Nenhuma FAQ ou regra relacionada neste contexto.
            </p>
          )}
        </KnowledgeSection>
        <KnowledgeSection
          icon={<Radio size={11} />}
          title="Caminho no grafo"
          count={operator.graph_path.length}
          showEmpty
        >
          {operator.graph_path.length > 0 ? (
            <ol className="space-y-1">
              {operator.graph_path.map((step, index) => (
                <li key={`${step.node_id || step.slug}-${index}`} className="flex items-center gap-2 text-[11px] text-obs-subtle">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-obs-teal/10 text-[9px] text-obs-teal">
                    {index + 1}
                  </span>
                  <span>{step.title || step.slug}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-[11px] text-obs-faint">
              Caminho indisponível para esta evidência.
            </p>
          )}
        </KnowledgeSection>
      </div>
    );
  }

  const graphNodes = uniqueBy(ctx.nodes || [], nodeIdentity);
  const dedupedCtx = { ...ctx, nodes: graphNodes };
  const nodeById = new Map(graphNodes.map((n) => [n.id, n]));
  const relations = uniqueBy(ctx.edges || [], relationIdentity).slice(0, 8);
  const primaryNode = pickPrimaryKnowledge(graphNodes, ctx.query_terms || []);
  const primaryId = primaryNode ? nodeIdentity(primaryNode) : null;
  const rankedGraphNodes = rankKnowledgeNodes(graphNodes, ctx.query_terms || []);
  const graphHighlights = rankedGraphNodes
    .filter((n) => nodeIdentity(n) !== primaryId)
    .filter((n) => !["tag", "mention", "persona"].includes(n.node_type))
    .slice(0, 6);
  const products  = rankKnowledgeNodes(uniqueBy(nodesByType(dedupedCtx, "product"), nodeIdentity), ctx.query_terms || [])
    .filter((n) => nodeIdentity(n) !== primaryId)
    .slice(0, 5);
  const campaigns = rankKnowledgeNodes(uniqueBy(nodesByType(dedupedCtx, "campaign"), nodeIdentity), ctx.query_terms || []).slice(0, 4);
  const briefings = rankKnowledgeNodes(uniqueBy(nodesByType(dedupedCtx, "briefing"), nodeIdentity), ctx.query_terms || []).slice(0, 3);
  const rules     = rankKnowledgeNodes(uniqueBy([...nodesByType(dedupedCtx, "rule"), ...nodesByType(dedupedCtx, "tone")], nodeIdentity), ctx.query_terms || []).slice(0, 4);
  const kbEntries = uniqueBy(ctx.kb_entries || [], kbEntryIdentity);
  const faqs      = kbEntries.filter((e) => (e.node_type || e.tipo || "").toLowerCase() === "faq").slice(0, 5);
  const copies    = kbEntries.filter((e) => (e.node_type || e.tipo || "").toLowerCase() === "copy").slice(0, 3);
  const activeKb  = kbEntries.filter((e) => !["faq", "copy"].includes((e.node_type || e.tipo || "").toLowerCase())).slice(0, 5);
  const related   = graphNodes.filter((n) =>
    !["persona", "product", "campaign", "briefing", "faq", "copy", "asset", "tag", "mention", "rule", "tone"].includes(n.node_type)
  ).slice(0, 5);
  const similar = uniqueBy(ctx.similar || [], similarIdentity).slice(0, 5);
  const assets = uniqueBy(ctx.assets || [], assetIdentity).slice(0, 6);
  const pendingNodes = uniqueBy(ctx.unvalidated?.nodes || [], nodeIdentity).filter((n) =>
    !["persona", "tag"].includes(n.node_type)
  ).slice(0, 5);
  const pendingEntries = uniqueBy(ctx.unvalidated?.kb_entries || [], kbEntryIdentity).slice(0, 5);
  const pendingAssets = uniqueBy(ctx.unvalidated?.assets || [], assetIdentity).slice(0, 4);
  const total =
    (primaryNode ? 1 : 0) + graphHighlights.length + products.length + campaigns.length + briefings.length + rules.length +
    activeKb.length + faqs.length + copies.length + related.length + relations.length + similar.length + assets.length +
    pendingNodes.length + pendingEntries.length + pendingAssets.length;

  if (total === 0) {
    return (
      <div className="p-4 text-xs text-obs-faint space-y-2">
        <div className="flex items-center gap-1.5">
          <Boxes size={14} className="text-obs-faint/60" />
          <span>Nenhum conhecimento detectado nessa conversa ainda.</span>
        </div>
        {ctx.query_terms.length > 0 && (
          <p className="text-[11px]">Termos: {ctx.query_terms.join(", ")}</p>
        )}
      </div>
    );
  }

  // If a knowledge is expanded, replace the list with the detail view
  if (expanded) {
    return (
      <KnowledgeDetail
        expanded={expanded}
        ctx={ctx}
        onBack={() => setExpanded(null)}
      />
    );
  }

  // After the early return above, `expanded` is null in this branch, so cards
  // render in their non-active state. Active styling kicks in only after a
  // future click before detail view is rendered (single render cycle).
  const selectNode = (id: string) => setExpanded({ kind: "node", id });
  const selectKb = (id: string) => setExpanded({ kind: "kb", id });
  const selectSimilar = (id: string) => setExpanded({ kind: "similar", id });
  const isActiveNode = (_n: KnowledgeNode) => false;
  const isActiveKb = (_e: KnowledgeKbEntry) => false;
  const isActiveSimilar = (_n: SimilarNode) => false;

  return (
    <div className="p-3 space-y-3 overflow-y-auto h-full">
      {ctx.summary && (
        <p className="text-[11px] text-obs-subtle leading-snug">{ctx.summary}</p>
      )}

      <KnowledgeSection icon={<Boxes size={11} />} title="Conhecimento principal" count={primaryNode ? 1 : 0}>
        {primaryNode && (
          <NodePill
            key={scopedKey("primary", nodeIdentity(primaryNode))}
            node={primaryNode}
            active={isActiveNode(primaryNode)}
            onSelect={selectNode}
          />
        )}
      </KnowledgeSection>

      <KnowledgeSection icon={<Boxes size={11} />} title="Mais proximos" count={graphHighlights.length}>
        {graphHighlights.map((n) => <NodePill key={scopedKey("graph", nodeIdentity(n))} node={n} active={isActiveNode(n)} onSelect={selectNode} />)}
      </KnowledgeSection>

      <KnowledgeSection icon={<Radio size={11} />} title="Relações do grafo" count={relations.length}>
        {relations.map((e) => <RelationCard key={scopedKey("edge", relationIdentity(e))} edge={e} nodeById={nodeById} onSelect={selectNode} />)}
      </KnowledgeSection>

      <KnowledgeSection icon={<Boxes size={11} />} title="Produtos" count={products.length}>
        {products.map((n) => <NodePill key={scopedKey("product", nodeIdentity(n))} node={n} active={isActiveNode(n)} onSelect={selectNode} />)}
      </KnowledgeSection>

      <KnowledgeSection icon={<Megaphone size={11} />} title="Campanhas" count={campaigns.length}>
        {campaigns.map((n) => <NodePill key={scopedKey("campaign", nodeIdentity(n))} node={n} active={isActiveNode(n)} onSelect={selectNode} />)}
      </KnowledgeSection>

      <KnowledgeSection icon={<Database size={11} />} title="Golden Dataset ativo" count={activeKb.length}>
        {activeKb.map((e) => <KbCard key={scopedKey("active-kb", kbEntryIdentity(e))} entry={e} active={isActiveKb(e)} onSelect={selectKb} />)}
      </KnowledgeSection>

      <KnowledgeSection icon={<FileQuestion size={11} />} title="FAQs" count={faqs.length}>
        {faqs.map((e) => <KbCard key={scopedKey("faq", kbEntryIdentity(e))} entry={e} active={isActiveKb(e)} onSelect={selectKb} />)}
      </KnowledgeSection>

      <KnowledgeSection icon={<FileText size={11} />} title="Briefings" count={briefings.length}>
        {briefings.map((n) => <NodePill key={scopedKey("briefing", nodeIdentity(n))} node={n} active={isActiveNode(n)} onSelect={selectNode} />)}
      </KnowledgeSection>

      <KnowledgeSection icon={<FileText size={11} />} title="Copies" count={copies.length}>
        {copies.map((e) => <KbCard key={scopedKey("copy", kbEntryIdentity(e))} entry={e} active={isActiveKb(e)} onSelect={selectKb} />)}
      </KnowledgeSection>

      <KnowledgeSection icon={<Palette size={11} />} title="Regras / Tom" count={rules.length}>
        {rules.map((n) => <NodePill key={scopedKey("rule", nodeIdentity(n))} node={n} active={isActiveNode(n)} onSelect={selectNode} />)}
      </KnowledgeSection>

      <KnowledgeSection icon={<Boxes size={11} />} title="Conhecimentos relacionados" count={related.length}>
        {related.map((n) => <NodePill key={scopedKey("related", nodeIdentity(n))} node={n} active={isActiveNode(n)} onSelect={selectNode} />)}
      </KnowledgeSection>

      <KnowledgeSection icon={<Radio size={11} />} title="Busca por similaridade" count={similar.length}>
        {similar.map((n) => <SimilarCard key={scopedKey("similar", similarIdentity(n))} node={n} active={isActiveSimilar(n)} onSelect={selectSimilar} />)}
      </KnowledgeSection>

      <KnowledgeSection icon={<ImageIcon size={11} />} title="Assets" count={assets.length}>
        <div className="grid grid-cols-2 gap-1.5">
          {assets.map((a) => <AssetCard key={scopedKey("asset", assetIdentity(a))} asset={a} />)}
        </div>
      </KnowledgeSection>

      <KnowledgeSection
        icon={<AlertCircle size={11} className="text-amber-300" />}
        title="Pendentes de validação"
        count={pendingNodes.length + pendingEntries.length + pendingAssets.length}
      >
        {pendingNodes.map((n) => <NodePill key={scopedKey("pending-node", nodeIdentity(n))} node={n} active={isActiveNode(n)} onSelect={selectNode} />)}
        {pendingEntries.map((e) => <KbCard key={scopedKey("pending-kb", kbEntryIdentity(e))} entry={e} active={isActiveKb(e)} onSelect={selectKb} />)}
        {pendingAssets.length > 0 && (
          <div className="grid grid-cols-2 gap-1.5">
            {pendingAssets.map((a) => <AssetCard key={scopedKey("pending-asset", assetIdentity(a))} asset={a} />)}
          </div>
        )}
      </KnowledgeSection>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function MessagesLayout({
  initialLeadId,
  focused = false,
  portalSlug,
  canEdit = true,
  validationMode = false,
  heightClassName,
  refreshSignal,
}: {
  initialLeadId?: number | null;
  focused?: boolean;
  portalSlug?: string;
  canEdit?: boolean;
  validationMode?: boolean;
  /** Overrides the outer container's height. Defaults to the admin shell's
   * chrome budget (header 3rem + main padding 3rem = 6rem); the portal
   * shell's chrome is different (header 4rem + main padding, no per-page
   * header now that titles live in the persistent portal header) and gets
   * its own default when portalSlug is set. */
  heightClassName?: string;
  /** Bump this (e.g. a counter) to force a lead/conversation refetch from a
   * parent that knows about state this component can't observe on its own
   * -- e.g. the WA Validator's "Validações" tab, where a script run
   * finishes in a sibling component with no other link between the two.
   * Undefined (the default, every other caller) never refetches on its
   * account, so this is a no-op everywhere else. */
  refreshSignal?: number;
}) {
  const pathname = usePathname();
  const portalMatch = portalSlug ? [pathname, portalSlug] : pathname.match(/^\/clientes\/([^/]+)/);
  const isPortal = Boolean(portalSlug);
  // O portal não tem mais header nem padding de `main` nesta rota (ver
  // PortalContext) — só a bottom nav mobile (~5rem com safe-area) segue
  // reservada. `heightClassName` continua sendo o escape hatch para quem
  // ainda precisa do orçamento antigo (ex.: banner de canal não conectado).
  // dvh, não vh: no iOS a barra de URL colapsando dentro de vh empurra o
  // composer pra baixo do chrome do navegador.
  const resolvedHeightClassName =
    heightClassName || (isPortal ? "h-[calc(100dvh-5rem)] lg:h-dvh" : "h-[calc(100dvh-6rem)]");
  const [leads, setLeads] = useState<Lead[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [search, setSearch] = useState("");
  const validationScope = validationMode ? "only" as const : "exclude" as const;
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [isConversationSidebarOpen, setIsConversationSidebarOpen] = useState(!focused);
  const [showLeadInfo, setShowLeadInfo] = useState(false);
  const [isKnowledgeSidebarOpen, setIsKnowledgeSidebarOpen] = useState(false);

  // Três modos derivados do viewport: single (<1024px) mostra um painel por
  // vez (lista | thread), dual (1024-1279px) mostra lista+thread com o rail
  // direito virando overlay, triple (≥1280px) é o comportamento de sempre.
  // Nunca escreve em isConversationSidebarOpen/isKnowledgeSidebarOpen — esses
  // continuam sendo intenção pura do usuário; o breakpoint só afeta como
  // essa intenção é derivada e renderizada.
  const [layoutMode, setLayoutMode] = useState<"single" | "dual" | "triple">("triple");
  const [mobilePane, setMobilePane] = useState<"list" | "thread">(focused ? "thread" : "list");

  useEffect(() => {
    const mqSingle = window.matchMedia("(max-width: 1023px)");
    const mqDual = window.matchMedia("(min-width: 1024px) and (max-width: 1279px)");
    const compute = () => {
      setLayoutMode(mqSingle.matches ? "single" : mqDual.matches ? "dual" : "triple");
    };
    compute();
    mqSingle.addEventListener("change", compute);
    mqDual.addEventListener("change", compute);
    return () => {
      mqSingle.removeEventListener("change", compute);
      mqDual.removeEventListener("change", compute);
    };
  }, []);
  const [personaFilterId, setPersonaFilterId] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loadingLeads, setLoadingLeads] = useState(true);
  const [loadingMsgs, setLoadingMsgs] = useState(false);
  const [loadingOlderMessages, setLoadingOlderMessages] = useState(false);
  const [hasOlderMessages, setHasOlderMessages] = useState(false);
  const [liveSync, setLiveSync] = useState(false);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [messagesError, setMessagesError] = useState<string | null>(null);
  const [knowledgeError, setKnowledgeError] = useState<string | null>(null);
  const [pausing, setPausing] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [knowledge, setKnowledge] = useState<ChatContext | null>(null);
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);
  const [selectedResponseMessageId, setSelectedResponseMessageId] = useState<string | null>(null);
  const [knowledgeRefreshKey, setKnowledgeRefreshKey] = useState(0);
  const bottomRef = useRef<HTMLDivElement>(null);
  const messageListRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const previousLastMessageIdRef = useRef<string | null>(null);
  const selectedIdRef = useRef<number | null>(null);
  const draftRef = useRef<HTMLTextAreaElement>(null);
  const pendingSendRef = useRef<{
    leadId: number;
    text: string;
    clientMessageId: string;
  } | null>(null);
  const loadLeadsRequestRef = useRef(0);
  const loadMessagesRequestRef = useRef(0);
  const loadKnowledgeRequestRef = useRef(0);
  const messageAfterCursorRef = useRef<string | null>(null);
  const messageBeforeCursorRef = useRef<string | null>(null);

  useEffect(() => {
    if (isPortal) return;
    setPersonaFilterId(window.localStorage.getItem("ai-brain-persona-id") || "");
    const onPersonaChange = (event: Event) => {
      const detail = (event as CustomEvent<{ id?: string }>).detail;
      setPersonaFilterId(detail?.id || window.localStorage.getItem("ai-brain-persona-id") || "");
      selectedIdRef.current = null;
      setSelectedId((current) => (current !== null ? null : current));
      setMessages((current) => (current.length > 0 ? [] : current));
      messageAfterCursorRef.current = null;
      messageBeforeCursorRef.current = null;
      setHasOlderMessages(false);
      setKnowledge((current) => (current !== null ? null : current));
      setSelectedResponseMessageId(null);
      setMessagesError(null);
      setKnowledgeError(null);
      setSendError(null);
    };
    window.addEventListener("ai-brain-persona-change", onPersonaChange);
    return () => window.removeEventListener("ai-brain-persona-change", onPersonaChange);
  }, [isPortal]);

  const loadLeads = useCallback(async () => {
    const requestId = ++loadLeadsRequestRef.current;
    setLoadingLeads(true);
    setLoadError(null);
    try {
      const [leadRows, convRows] = await Promise.all([
        isPortal ? api.portalLeads(portalSlug!, 200) : api.leads(200, 0, personaFilterId || undefined, validationScope, validationMode ? 12 : undefined),
        isPortal ? api.portalConversations(portalSlug!) : api.conversations(validationMode ? 12 : 168, personaFilterId || undefined, validationScope),
      ]);
      if (loadLeadsRequestRef.current !== requestId) return;

      setLeads(leadRows as Lead[]);
      setConversations(convRows as ConversationSummary[]);
    } catch (error) {
      if (loadLeadsRequestRef.current !== requestId) return;
      setLeads([]);
      setConversations([]);
      setLoadError(getErrorMessage(error, "Falha ao carregar leads e conversas."));
    } finally {
      if (loadLeadsRequestRef.current === requestId) {
        setLoadingLeads(false);
      }
    }
  }, [isPortal, personaFilterId, portalSlug, validationScope]);

  useEffect(() => { loadLeads(); }, [loadLeads]);

  useEffect(() => {
    if (refreshSignal === undefined) return;
    loadLeads();
    // Only refreshSignal itself should retrigger this -- loadLeads already
    // has its own identity-change effect above; including it here too
    // would double-fetch on every filter/persona change as well.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal]);

  // Tick para reavaliar attentionState (timeout do bot) sem refetch
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30 * 1000);
    return () => clearInterval(id);
  }, []);

  // Index conversations por lead_ref para lookup O(1) no sidebar
  const convByRef = useMemo(() => {
    const m = new Map<number, ConversationSummary>();
    for (const c of conversations) {
      if (typeof c.lead_ref === "number") m.set(c.lead_ref, c);
    }
    return m;
  }, [conversations]);

  const onMessageListScroll = useCallback(() => {
    const el = messageListRef.current;
    if (!el) return;
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  }, []);

  // Auto-scroll only when the operator is already at the bottom. Realtime
  // inserts must not pull the viewport away from older messages being read.
  useEffect(() => {
    const lastId = messages.length ? String(messages[messages.length - 1]?.id || "") : null;
    const isFirstLoad = previousLastMessageIdRef.current === null && !!lastId;
    const changed = lastId !== previousLastMessageIdRef.current;
    previousLastMessageIdRef.current = lastId;
    if (!changed || !lastId) return;
    if (isFirstLoad || stickToBottomRef.current) {
      // scrollIntoView on bottomRef bubbles to the nearest scrollable
      // ancestor -- fine on the standalone /messages route (which reserves
      // full viewport height for this container), but when embedded inside
      // a taller page (e.g. the WA Validator's Validações tab) with no
      // scrollable ancestor of its own, it scrolled the whole page instead
      // of just this message list. Scroll the container itself directly so
      // this component's behavior never depends on where it's mounted.
      messageListRef.current?.scrollTo({
        top: messageListRef.current.scrollHeight,
        behavior: isFirstLoad ? "auto" : "smooth",
      });
    }
  }, [messages]);

  // Same-origin polling keeps the browser behind the Brain API authorization
  // boundary. The portal SSE endpoint can later replace this without exposing
  // Supabase credentials to the browser.
  useEffect(() => {
    selectedIdRef.current = selectedId;
    if (!selectedId) {
      setLiveSync(false);
      return;
    }
    setLiveSync(true);
    let pollCount = 0;
    const refresh = async () => {
      const id = selectedIdRef.current;
      if (!id) return;
      try {
        const msgPage = await (
          isPortal
            ? api.portalConversationMessages(portalSlug!, id, { after: messageAfterCursorRef.current })
            : api.messagesByRef(id, 50, validationScope, { after: messageAfterCursorRef.current })
        );
        if (selectedIdRef.current !== id) return;
        const page = msgPage as { items: Message[]; after_cursor: string | null };
        messageAfterCursorRef.current = page.after_cursor || messageAfterCursorRef.current;
        setMessages((current) => sortMessages(Array.from(new Map(
          [...current, ...(page.items || [])].map((item) => [String(item.id), item]),
        ).values())));
        // The selected thread needs a short poll, but the entire seven-day
        // conversation index does not. Refreshing both every five seconds
        // multiplied the expensive list endpoint (and its former lead N+1)
        // without improving the open chat. Keep the index fresh at 30s.
        pollCount += 1;
        if (pollCount % 6 === 0) {
          const convRows = await (
            isPortal
              ? api.portalConversations(portalSlug!)
              : api.conversations(validationMode ? 12 : 168, personaFilterId || undefined, validationScope)
          );
          if (selectedIdRef.current !== id) return;
          setConversations(convRows as ConversationSummary[]);
        }
        setMessagesError(null);
      } catch {
        setLiveSync(false);
      }
    };
    const visibleRefresh = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    const interval = window.setInterval(visibleRefresh, 5000);
    document.addEventListener("visibilitychange", visibleRefresh);
    return () => {
      setLiveSync(false);
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", visibleRefresh);
    };
  }, [isPortal, selectedId, personaFilterId, portalSlug, validationScope]);

  const openLead = useCallback((lead: Lead) => {
    // Ir para a thread é sempre a intenção de tocar um lead, independente
    // do resto abaixo — que fica atrás de `changed`, uma flag lida
    // sincronamente logo após o updater funcional de setSelectedId. Esse
    // updater não roda de forma síncrona aqui, então `changed` já chegava
    // sempre falso antes desta mudança: o bloco de reset (mensagens,
    // conhecimento, rascunho etc.) nunca executava, silenciosamente, desde
    // sempre — mascarado porque o efeito de fetch abaixo, que depende
    // corretamente de selectedId, sempre sobrescreve os dados velhos assim
    // que chega. Não mexo nesse bloco pré-existente agora; só tiro esta
    // troca de aba dele, que precisa ser incondicional.
    setMobilePane("thread");
    let changed = false;
    setSelectedId((current) => {
      if (current === lead.id) return current;
      changed = true;
      return lead.id;
    });
    if (!changed) return;
    selectedIdRef.current = lead.id;
    setMessages((current) => (current.length > 0 ? [] : current));
    setKnowledge((current) => (current !== null ? null : current));
    setSelectedResponseMessageId(null);
    previousLastMessageIdRef.current = null;
    messageAfterCursorRef.current = null;
    messageBeforeCursorRef.current = null;
    setHasOlderMessages(false);
    stickToBottomRef.current = true;
    setDraft("");
    setSendError(null);
    setMessagesError(null);
    setKnowledgeError(null);
    // No mobile, focar o composer sozinho abre o teclado virtual a cada
    // lead aberto — incômodo demais para valer o ganho no desktop.
    if (layoutMode !== "single") setTimeout(() => draftRef.current?.focus(), 80);
  }, [layoutMode]);

  useEffect(() => {
    if (!initialLeadId || loadingLeads || selectedId === initialLeadId) return;
    const lead = leads.find((l) => l.id === initialLeadId);
    if (!lead) return;
    if (personaFilterId && lead.persona_id !== personaFilterId) {
      selectedIdRef.current = null;
      setSelectedId((current) => (current !== null ? null : current));
      setMessages((current) => (current.length > 0 ? [] : current));
      setKnowledge((current) => (current !== null ? null : current));
      setMessagesError("A lead desta rota nao pertence ao filtro de persona atual.");
      setKnowledgeError(null);
      return;
    }
    openLead(lead);
  }, [initialLeadId, loadingLeads, leads, openLead, personaFilterId, selectedId]);

  // Knowledge sidebar: refetch context when lead changes or when the last
  // client message changes (so detected products/campaigns stay in sync).
  const lastClientText = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      const t = (m.sender_type || "").toLowerCase();
      if (t !== "agent" && t !== "human" && t !== "assistant" && t !== "ai") {
        return (m.texto || "").trim();
      }
    }
    return "";
  }, [messages]);
  const latestEvidenceResponseId = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (hasKnowledgeEvidence(messages[index])) return messageTurnId(messages[index]);
    }
    return "";
  }, [messages]);
  const selectedLead = useMemo(
    () => leads.find((l) => l.id === selectedId) ?? null,
    [leads, selectedId],
  );
  const selectedLeadPersonaId = selectedLead?.persona_id || undefined;
  const selectedLeadInterest = selectedLead?.interesse_produto || undefined;

  useEffect(() => {
    if (!selectedLead || !personaFilterId) return;
    if (selectedLead.persona_id !== personaFilterId) {
      selectedIdRef.current = null;
      setSelectedId((current) => (current !== null ? null : current));
      setMessages((current) => (current.length > 0 ? [] : current));
      setKnowledge((current) => (current !== null ? null : current));
      setMessagesError((current) => current || "Selecao limpa porque a lead nao pertence ao filtro de persona atual.");
      setKnowledgeError(null);
      setSendError(null);
    }
  }, [personaFilterId, selectedLead?.id, selectedLead?.persona_id]);

  useEffect(() => {
    if (!selectedId) {
      setLoadingMsgs(false);
      setMessagesError(null);
      setMessages((current) => (current.length > 0 ? [] : current));
      return;
    }

    const requestId = ++loadMessagesRequestRef.current;
    let cancelled = false;

    setLoadingMsgs(true);
    setMessagesError(null);

    (isPortal
      ? api.portalConversationMessages(portalSlug!, selectedId)
      : api.messagesByRef(selectedId, 50, validationScope))
      .then((response) => {
        if (cancelled || loadMessagesRequestRef.current !== requestId || selectedIdRef.current !== selectedId) return;
        const page = response as { items: Message[]; before_cursor: string | null; after_cursor: string | null; has_more: boolean };
        const rows = page.items || [];
        messageAfterCursorRef.current = page.after_cursor;
        messageBeforeCursorRef.current = page.before_cursor;
        setHasOlderMessages(page.has_more);
        setMessages(sortMessages(rows));
      })
      .catch((error) => {
        if (cancelled || loadMessagesRequestRef.current !== requestId || selectedIdRef.current !== selectedId) return;
        setMessages((current) => (current.length > 0 ? [] : current));
        setMessagesError(getErrorMessage(error, "Falha ao carregar a conversa."));
      })
      .finally(() => {
        if (cancelled || loadMessagesRequestRef.current !== requestId || selectedIdRef.current !== selectedId) return;
        setLoadingMsgs(false);
      });

    return () => {
      cancelled = true;
    };
  }, [isPortal, portalSlug, selectedId, validationScope]);

  const loadOlderMessages = useCallback(async () => {
    const id = selectedIdRef.current;
    const before = messageBeforeCursorRef.current;
    if (!id || !before || loadingOlderMessages) return;
    setLoadingOlderMessages(true);
    const el = messageListRef.current;
    const previousHeight = el?.scrollHeight || 0;
    try {
      const page = await (isPortal
        ? api.portalConversationMessages(portalSlug!, id, { before })
        : api.messagesByRef(id, 50, validationScope, { before }));
      if (selectedIdRef.current !== id) return;
      messageBeforeCursorRef.current = page.before_cursor;
      setHasOlderMessages(page.has_more);
      setMessages((current) => sortMessages(Array.from(new Map(
        [...(page.items || []), ...current].map((item) => [String(item.id), item]),
      ).values())));
      requestAnimationFrame(() => {
        if (el) el.scrollTop += el.scrollHeight - previousHeight;
      });
    } catch (error) {
      setMessagesError(getErrorMessage(error, "Falha ao carregar mensagens anteriores."));
    } finally {
      setLoadingOlderMessages(false);
    }
  }, [isPortal, loadingOlderMessages, portalSlug, validationScope]);

  useEffect(() => {
    if (!selectedId || !selectedLead) {
      setKnowledge((current) => (current !== null ? null : current));
      setKnowledgeLoading(false);
      setKnowledgeError(null);
      return;
    }

    const requestId = ++loadKnowledgeRequestRef.current;
    let cancelled = false;

    setKnowledgeLoading(true);
    setKnowledgeError(null);
    (
      isPortal
        ? api.portalKnowledgeChatContext(
            portalSlug!,
            selectedId,
            lastClientText || selectedLeadInterest,
            12,
            selectedResponseMessageId || undefined,
          )
        : api.knowledgeChatContext(
            selectedId,
            lastClientText || selectedLeadInterest,
            selectedLeadPersonaId,
            selectedResponseMessageId || undefined,
          )
    )
      .then((ctx) => {
        if (cancelled || loadKnowledgeRequestRef.current !== requestId || selectedIdRef.current !== selectedId) return;
        setKnowledge(ctx);
      })
      .catch((error) => {
        if (cancelled || loadKnowledgeRequestRef.current !== requestId || selectedIdRef.current !== selectedId) return;
        setKnowledge((current) => (current !== null ? null : current));
        setKnowledgeError(getErrorMessage(error, "Falha ao carregar o contexto de conhecimento."));
      })
      .finally(() => {
        if (cancelled || loadKnowledgeRequestRef.current !== requestId || selectedIdRef.current !== selectedId) return;
        setKnowledgeLoading(false);
      });
    return () => { cancelled = true; };
  }, [isPortal, portalSlug, selectedId, selectedLead?.id, lastClientText, latestEvidenceResponseId, selectedLeadInterest, selectedLeadPersonaId, selectedResponseMessageId, knowledgeRefreshKey]);

  const refreshSelectedLead = useCallback(async (id: number) => {
    try {
      const fresh = isPortal
        ? await api.portalLead(portalSlug!, id)
        : await api.lead(String(id));
      setLeads((prev) => prev.map((l) => (l.id === id ? { ...l, ...fresh } : l)));
    } catch {
      /* lead lookup is best-effort */
    }
  }, [isPortal, portalSlug]);

  const onSend = useCallback(async () => {
    if (!selectedId || !draft.trim() || sending) return;
    const text = draft.trim();
    const pending = pendingSendRef.current;
    const clientMessageId = (
      pending
      && pending.leadId === selectedId
      && pending.text === text
    )
      ? pending.clientMessageId
      : crypto.randomUUID();
    pendingSendRef.current = {
      leadId: selectedId,
      text,
      clientMessageId,
    };
    setSending(true);
    setSendError(null);
    try {
      if (isPortal) {
        await api.portalSendMessage(portalSlug!, {
          lead_id: selectedId,
          client_message_id: clientMessageId,
          text,
        });
      } else {
        await api.sendMessage({
          lead_ref: selectedId,
          client_message_id: clientMessageId,
          texto: text,
          nome: "Operador",
        });
      }
      pendingSendRef.current = null;
      setDraft("");
      // Refresh messages + conversations imediato (não esperar próximo poll)
      const [msgPage, convRows] = await Promise.all([
        isPortal ? api.portalConversationMessages(portalSlug!, selectedId) : api.messagesByRef(selectedId, 50, validationScope),
        isPortal ? api.portalConversations(portalSlug!) : api.conversations(validationMode ? 12 : 168, personaFilterId || undefined, validationScope),
      ]);
      const page = msgPage as { items: Message[]; before_cursor: string | null; after_cursor: string | null; has_more: boolean };
      const msgRows = page.items || [];
      messageAfterCursorRef.current = page.after_cursor;
      messageBeforeCursorRef.current = page.before_cursor;
      setHasOlderMessages(page.has_more);
      setMessages(sortMessages(msgRows));
      setConversations(convRows as ConversationSummary[]);
    } catch (e: any) {
      setSendError(e?.message || "Falha ao enviar.");
    } finally {
      setSending(false);
      setTimeout(() => draftRef.current?.focus(), 50);
    }
  }, [selectedId, draft, sending, personaFilterId, isPortal, portalSlug, validationScope]);

  const onDraftKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
    e.preventDefault();
    onSend();
  };

  const togglePause = useCallback(async () => {
    if (!selectedId || pausing) return;
    setPausing(true);
    try {
      const current = leads.find((l) => l.id === selectedId);
      const level = current?.handoff_level ?? (current?.ai_paused ? "full" : "none");
      if (level === "full") {
        if (isPortal) await api.portalResumeAi(portalSlug!, selectedId);
        else await api.resumeAi(selectedId);
      } else if (level === "partial") {
        if (isPortal) await api.portalAcknowledgeHandoff(portalSlug!, selectedId);
        else await api.acknowledgeHandoff(selectedId);
      } else if (isPortal) await api.portalPauseAi(portalSlug!, selectedId);
      else await api.pauseAi(selectedId);
      await refreshSelectedLead(selectedId);
    } catch (e) {
      console.error(e);
    } finally {
      setPausing(false);
    }
  }, [selectedId, pausing, leads, refreshSelectedLead, isPortal, portalSlug]);

  const selectedHandoffLevel: "none" | "partial" | "full" = useMemo(
    () => selectedLead?.handoff_level ?? (selectedLead?.ai_paused ? "full" : "none"),
    [selectedLead],
  );

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return leads.filter((l) => (
      (
        !q
        || (l.nome || "").toLowerCase().includes(q)
        || (l.telefone || "").includes(q)
        || (l.lead_id || "").includes(q)
        || (l.stage || "").toLowerCase().includes(q)
        || (l.interesse_produto || "").toLowerCase().includes(q)
      )
    ));
  }, [leads, search]);

  const awaitingCount = useMemo(
    () => filtered.filter((l) => attentionFor(convByRef.get(l.id), now) === "awaiting_bot").length,
    [filtered, convByRef, now],
  );

  const chatName = displayName(selectedLead);

  // Derivação por breakpoint — nunca escreve nos toggles manuais acima.
  const showList = layoutMode === "single" ? mobilePane === "list" : isConversationSidebarOpen;
  const showThread = layoutMode !== "single" || mobilePane === "thread";
  const knowledgeAsOverlay = layoutMode !== "triple";

  return (
    <div
      className={`messages-page flex ${resolvedHeightClassName} overflow-hidden rounded-xl p-3`}
      style={{
        background:
          "radial-gradient(circle at 15% 10%, rgba(124,92,255,0.10), transparent 28%), radial-gradient(circle at 85% 20%, rgba(120,180,255,0.10), transparent 26%), rgb(var(--obs-deep))",
      }}
    >
      {/* ── Left: Leads list ───────────────────────────────────────────── */}
      {showList && (
      <aside
        className="conversation-sidebar w-full lg:w-72 shrink-0 flex flex-col overflow-hidden rounded-l-xl"
        style={{
          border: "1px solid var(--border-glass)",
          background: "rgb(var(--glass-solid-bg) / var(--glass-solid-alpha))",
          backdropFilter: "blur(18px) saturate(130%)",
          WebkitBackdropFilter: "blur(18px) saturate(130%)",
          boxShadow: "var(--glass-shadow)",
        }}
      >
        {/* Header — o portal não tem header de página (removido, ver
            PortalContext); o título "Mensagens" vive aqui. O admin mantém
            "Leads (N)", que já tem o resto do chrome da página em volta. */}
        {isPortal ? (
          <div className="flex items-start justify-between gap-2 px-4 pb-3 pt-4" style={{ borderBottom: "1px solid var(--border-glass)" }}>
            <div className="min-w-0">
              <h1 className="text-base font-semibold text-obs-text">Mensagens</h1>
              <p className="mt-0.5 truncate text-[11px] text-obs-faint">
                {filtered.length} conversa{filtered.length === 1 ? "" : "s"}
                {awaitingCount > 0 ? ` · ${awaitingCount} aguardando resposta` : ""}
              </p>
            </div>
            <button
              onClick={loadLeads}
              className="mt-0.5 shrink-0 rounded p-1 text-obs-subtle transition-colors hover:text-obs-text"
              aria-label="Atualizar lista"
              title="Atualizar lista"
            >
              <RefreshCw size={13} />
            </button>
          </div>
        ) : (
          <div
            className="flex items-center justify-between px-4 py-3"
            style={{ borderBottom: "1px solid var(--border-glass)" }}
          >
            <div className="flex items-center gap-2">
              <User size={13} className="text-obs-subtle" />
              <span className="text-xs font-semibold text-obs-text">Leads</span>
              {!loadingLeads && (
                <span className="text-[10px] text-obs-faint">({filtered.length})</span>
              )}
            </div>
            <button
              onClick={loadLeads}
              className="p-1 rounded text-obs-subtle hover:text-obs-text transition-colors"
            >
              <RefreshCw size={11} />
            </button>
          </div>
        )}

        {/* Search */}
        <div className="px-3 py-2" style={{ borderBottom: "1px solid var(--border-glass-soft)" }}>
          <div
            className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg"
            style={{ background: "rgb(var(--glass-solid-bg) / 0.70)", border: "1px solid var(--border-glass)" }}
          >
            <Search size={11} className="text-obs-faint shrink-0" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar lead..."
              className="flex-1 bg-transparent text-xs text-obs-text placeholder-obs-faint focus:outline-none"
            />
          </div>
        </div>

        {/* Lead list */}
        <div className="flex-1 overflow-y-auto">
          {loadError && (
            <div className="px-3 py-2">
              <div className="rounded-md border border-red-300/40 bg-red-500/10 px-3 py-2 text-[11px] text-red-500">
                {loadError}
              </div>
            </div>
          )}
          {loadingLeads && (
            <div className="flex items-center justify-center py-12">
              <span className="text-xs text-obs-faint">Carregando...</span>
            </div>
          )}

          {!loadingLeads && filtered.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 gap-2">
              <User size={20} className="text-obs-faint/40" />
              <p className="text-xs text-obs-faint">Nenhum lead encontrado.</p>
            </div>
          )}

          {filtered.map((lead) => {
            const active = lead.id === selectedId;
            const conv = convByRef.get(lead.id);
            const attention = attentionFor(conv, now);
            const lastTs = conv?.last_at || lead.last_update || lead.updated_at;
            const name = displayName(lead);
            // Not backed by the API yet (roadmap backend #4 — Não lidas):
            // renders nothing until the field exists, never a fabricated
            // count.
            const unread = Number(lead.metadata?.unread_count) || 0;
            return (
              <button
                key={lead.id}
                onClick={() => openLead(lead)}
                className="w-full text-left px-4 py-3 flex flex-col gap-1 transition-colors"
                style={{
                  ...attentionRowStyle(attention, active),
                  borderBottom: "1px solid var(--border-glass-soft)",
                }}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <div
                      className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold shrink-0"
                      style={{ background: "rgb(var(--obs-text) / 0.08)", color: "rgb(var(--obs-subtle))" }}
                    >
                      {name[0].toUpperCase()}
                    </div>
                    <span className={`text-xs truncate ${unread > 0 ? "font-semibold text-obs-text" : "font-medium text-obs-text"}`}>{name}</span>
                  </div>
                  {unread > 0 && (
                    <span
                      className="flex h-[19px] min-w-[19px] shrink-0 items-center justify-center rounded-full px-1 text-[10px] font-semibold text-white"
                      style={{ background: "rgb(var(--obs-text))" }}
                      aria-label={`${unread} não lidas`}
                    >
                      {unread}
                    </span>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 pl-6 text-[10px] text-obs-faint">
                  <StageBadge stage={lead.stage} />
                  <span>{lead.qualification_score || 0}%</span>
                  {lastTs && <span>{relativeTs(lastTs)}</span>}
                  {(lead.qualification_signals?.length || 0) > 0 && (
                    <span className="truncate">
                      {lead.qualification_signals?.slice(0, 2).map((signal) => signal.label || signal.key).join(" · ")}
                    </span>
                  )}
                </div>

                {/* Attention badge: humano respondendo OU bot inativo */}
                {attention === "human_replying" && (
                  <div className="flex items-center gap-1 pl-6 text-[10px] text-amber-300/90">
                    <UserCheck size={10} />
                    <span>humano respondendo</span>
                  </div>
                )}
                {attention === "awaiting_bot" && (
                  <div className="flex items-center gap-1 pl-6 text-[10px] text-red-300">
                    <AlertCircle size={10} />
                    <span>aguardando — bot inativo</span>
                  </div>
                )}

                {lead.ultima_mensagem && (
                  <p className="text-[11px] truncate text-obs-subtle pl-6">{lead.ultima_mensagem}</p>
                )}

                <div className="flex items-center gap-2 pl-6">
                  {lead.telefone && (
                    <div className="flex items-center gap-1 text-obs-faint">
                      <Phone size={9} />
                      <span className="text-[10px]">{lead.telefone}</span>
                    </div>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      </aside>
      )}

      {/* ── Right: Chat view ───────────────────────────────────────────── */}
      {showThread && (
      <div
        className="message-panel relative flex-1 flex flex-col overflow-hidden rounded-xl min-w-0"
        style={{
          background: "rgb(var(--glass-solid-bg) / var(--glass-solid-alpha))",
          border: "1px solid var(--border-glass)",
          backdropFilter: "blur(18px) saturate(130%)",
          WebkitBackdropFilter: "blur(18px) saturate(130%)",
          boxShadow: "var(--glass-shadow)",
        }}
      >
        {/* Chat header — o toggle da lista mora aqui dentro agora (era um
            botão flutuante `absolute`, inconsistente com o estado vazio,
            que já o renderiza inline). Sempre centralizado verticalmente
            na barra, nunca sobreposto ao conteúdo da thread. */}
        <div
          className="flex items-center gap-3 px-3 py-3 shrink-0"
          style={{ borderBottom: "1px solid var(--border-glass)", background: "rgb(var(--glass-solid-bg) / 0.58)" }}
        >
          {/* No modo single vira botão voltar (fecha a thread, volta pra
              lista); em dual/triple continua o toggle de sempre. */}
          <button
            type="button"
            onClick={() => (layoutMode === "single" ? setMobilePane("list") : setIsConversationSidebarOpen((v) => !v))}
            className="flex h-8 w-8 shrink-0 items-center justify-center self-center rounded-full text-obs-text transition hover:opacity-70"
            style={{ background: "rgb(var(--glass-solid-bg) / var(--glass-solid-hover))", border: "1px solid var(--border-glass-strong)" }}
            aria-label={layoutMode === "single" ? "Voltar para a lista" : isConversationSidebarOpen ? "Esconder conversas" : "Mostrar conversas"}
            title={layoutMode === "single" ? "Voltar para a lista" : isConversationSidebarOpen ? "Esconder conversas" : "Mostrar conversas"}
          >
            {layoutMode === "single" ? <ArrowLeft size={15} /> : isConversationSidebarOpen ? <ChevronLeft size={15} /> : <ChevronRight size={15} />}
          </button>
          {selectedLead ? (
            <>
              {/* Avatar/nome/nota comercial não abrem mais o modal aqui —
                  ele vive só no rail direito (ContactPanel) agora. */}
              <div
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold"
                style={{ background: "rgb(var(--obs-text) / 0.08)", color: "rgb(var(--obs-subtle))" }}
              >
                {chatName[0].toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-obs-text truncate">{chatName}</p>
                <div className="flex items-center gap-2 flex-wrap">
                  <StageBadge stage={selectedLead.stage} />
                  {selectedLead.telefone && (
                    <span className="text-[10px] text-obs-faint">{selectedLead.telefone}</span>
                  )}
                  {selectedLead.interesse_produto && (
                    <span className="text-[10px] text-obs-subtle truncate">
                      {selectedLead.interesse_produto}
                    </span>
                  )}
                  <span className="text-[10px] text-obs-faint ml-auto">
                    {messages.length} msgs
                  </span>
                </div>
              </div>

              {/* Live indicator */}
              {liveSync && (
                <div className="flex items-center gap-1 shrink-0" title="Sincronização em tempo real ativa">
                  <Radio size={11} className="text-green-400 animate-pulse" />
                  <span className="text-[10px] text-green-400">live</span>
                </div>
              )}

              <button
                type="button"
                onClick={togglePause}
                disabled={pausing}
                title={
                  selectedHandoffLevel === "full"
                    ? "IA pausada — clique para retomar"
                    : selectedHandoffLevel === "partial"
                    ? `IA ainda respondendo — precisa de atenção${selectedLead.metadata?.handoff_reason ? ` (${selectedLead.metadata.handoff_reason})` : ""}. Clique para confirmar.`
                    : "IA ativa — clique para pausar"
                }
                className={`text-[10px] font-medium px-2.5 py-1 rounded-full shrink-0 border transition disabled:opacity-50 ${
                  selectedHandoffLevel === "full"
                    ? "border-red-400/60 bg-red-500/25 text-red-300 hover:bg-red-500/35"
                    : selectedHandoffLevel === "partial"
                    ? "border-amber-400/60 bg-amber-500/25 text-amber-300 hover:bg-amber-500/35"
                    : "border-emerald-400/50 bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30"
                }`}
              >
                <span
                  className={`inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle ${
                    selectedHandoffLevel === "full"
                      ? "bg-red-400"
                      : selectedHandoffLevel === "partial"
                      ? "bg-amber-400"
                      : "bg-emerald-400"
                  }`}
                />
                {selectedHandoffLevel === "full"
                  ? "IA pausada · humano"
                  : selectedHandoffLevel === "partial"
                  ? "Atenção · IA respondendo"
                  : "IA ativa"}
              </button>

              {/* Toggle the right-hand knowledge sidebar. */}
              <button
                type="button"
                onClick={() => setIsKnowledgeSidebarOpen((v) => !v)}
                title={isKnowledgeSidebarOpen ? "Esconder conhecimento" : "Mostrar conhecimento"}
                className="p-1.5 rounded-md text-obs-subtle hover:text-obs-teal transition shrink-0 hover:[background:rgb(var(--glass-solid-bg)/0.6)]"
              >
                {isKnowledgeSidebarOpen ? <PanelRightClose size={14} /> : <PanelRightOpen size={14} />}
              </button>
            </>
          ) : (
            <div className="flex items-center gap-2">
              <MessageSquare size={13} className="text-obs-faint" />
              <p className="text-sm text-obs-faint">Selecione um lead para ver a conversa</p>
            </div>
          )}
        </div>

        {/* Messages */}
        <div
          ref={messageListRef}
          onScroll={onMessageListScroll}
          className="flex-1 overflow-y-auto overscroll-contain px-4 py-4 space-y-3 lg:px-6"
        >
          {!selectedLead && (
            <div className="flex flex-col items-center justify-center h-full gap-3">
              <MessageSquare size={32} className="text-obs-faint/20" />
              <p className="text-sm text-obs-faint">
                {messagesError || "Escolha um lead na lista ao lado"}
              </p>
            </div>
          )}

          {selectedLead && loadingMsgs && (
            <div className="flex items-center justify-center py-12">
              <span className="text-xs text-obs-faint">Carregando conversa...</span>
            </div>
          )}

          {selectedLead && !loadingMsgs && messagesError && (
            <div className="flex items-center justify-center py-12">
              <div className="max-w-sm rounded-md border border-red-300/40 bg-red-500/10 px-4 py-3 text-center text-xs text-red-500">
                {messagesError}
              </div>
            </div>
          )}

          {selectedLead && !loadingMsgs && !messagesError && messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full gap-2">
              <MessageSquare size={20} className="text-obs-faint/30" />
              <p className="text-xs text-obs-faint">Nenhuma mensagem encontrada para este lead.</p>
            </div>
          )}

          {selectedLead && !loadingMsgs && hasOlderMessages && (
            <div className="flex justify-center pb-1">
              <button
                type="button"
                onClick={loadOlderMessages}
                disabled={loadingOlderMessages}
                className="rounded-full border border-obs-line px-3 py-1 text-[11px] text-obs-subtle transition hover:bg-obs-surface disabled:opacity-50"
              >
                {loadingOlderMessages ? "Carregando..." : "Carregar mensagens anteriores"}
              </button>
            </div>
          )}

          {messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              msg={msg}
              lead={selectedLead}
              selected={Boolean(
                knowledge?.response
                && (
                  knowledge.response.message_id === messageTurnId(msg)
                  || String(knowledge.response.id || "") === String(msg.id)
                )
              )}
              onSelectEvidence={(messageId) => {
                setSelectedResponseMessageId(messageId);
                setIsKnowledgeSidebarOpen(true);
              }}
            />
          ))}

          <div ref={bottomRef} />
        </div>

        {/* Send bar */}
        {selectedLead && canEdit && (
          <div
            className="px-4 pt-3 shrink-0"
            style={{
              borderTop: "1px solid var(--border-glass)",
              background: "rgb(var(--glass-solid-bg) / 0.58)",
              paddingBottom: "max(0.75rem, env(safe-area-inset-bottom))",
            }}
          >
            <div
              className="rounded-xl p-3 space-y-2"
              style={{ background: "rgb(var(--glass-solid-bg) / 0.72)", border: "1px solid var(--border-glass)" }}
            >
              <textarea
                ref={draftRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={onDraftKey}
                placeholder={
                  selectedLead.ai_paused
                    ? "IA pausada — você está respondendo como operador. Enter envia, Shift+Enter quebra linha."
                    : isPortal
                    ? `Escreva para ${chatName}… Enter envia, Shift+Enter quebra linha.`
                    : "Responder como operador (envia ao agente + WhatsApp). Enter envia, Shift+Enter quebra linha."
                }
                rows={2}
                disabled={sending}
                className="w-full bg-transparent text-sm text-obs-text placeholder-obs-faint resize-none focus:outline-none disabled:opacity-50"
              />
              <div className="flex items-center justify-between gap-2">
                <div className="text-[11px] text-obs-faint min-w-0 truncate">
                  {sendError ? (
                    <span className="text-red-400">erro: {sendError}</span>
                  ) : selectedHandoffLevel === "full" ? (
                    <span className="text-amber-300/80">IA pausada — só você responde até retomar.</span>
                  ) : selectedHandoffLevel === "partial" ? (
                    <span className="text-amber-300/80">IA ainda respondendo — sinalizado para atenção humana.</span>
                  ) : isPortal ? (
                    <span>A IA está ativa e pode responder antes de você.</span>
                  ) : (
                    <span>insere no banco · dispara webhook do agente</span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={onSend}
                  disabled={!draft.trim() || sending}
                  className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-xs font-medium bg-amber-500/85 hover:bg-amber-400 text-zinc-900 disabled:opacity-40 disabled:cursor-not-allowed transition"
                >
                  <Send size={12} />
                  {sending ? "enviando…" : "enviar"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
      )}

      {/* ── Right: Knowledge sidebar ────────────────────────────────────── */}
      {/* Em single/dual vira um overlay (a Sheet que o plano previa, sem
          depender de uma lib nova) em vez do aside inline do triple — o
          mesmo isKnowledgeSidebarOpen controla os dois, então o botão do
          ChatHeader não muda de comportamento entre os modos. */}
      {isKnowledgeSidebarOpen && (
      <>
        {knowledgeAsOverlay && (
          <div
            className="fixed inset-0 z-40 bg-black/30"
            onClick={() => setIsKnowledgeSidebarOpen(false)}
            aria-hidden="true"
          />
        )}
        <aside
          className={`knowledge-panel flex flex-col overflow-hidden ${
            knowledgeAsOverlay
              ? "fixed inset-y-0 right-0 z-50 w-full max-w-sm rounded-l-xl"
              : "w-80 shrink-0 rounded-r-xl"
          }`}
          style={{
            border: "1px solid var(--border-glass)",
            background: "rgb(var(--glass-solid-bg) / var(--glass-solid-alpha))",
            backdropFilter: "blur(18px) saturate(130%)",
            WebkitBackdropFilter: "blur(18px) saturate(130%)",
            boxShadow: "var(--glass-shadow)",
          }}
        >
        <>
          {/* Contato — topo do rail direito, altura própria (não cresce).
              Nada aqui é buscado de novo: tudo já está em selectedLead. */}
          {selectedLead && (
            <button
              type="button"
              onClick={() => setShowLeadInfo(true)}
              title="Ver/editar informações do lead"
              className="block max-h-[45%] w-full shrink-0 overflow-y-auto p-4 text-left transition hover:bg-obs-teal/5"
              style={{ borderBottom: "1px solid var(--border-glass)" }}
            >
              <div className="flex items-center gap-3">
                <div
                  className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-base font-semibold"
                  style={{ background: "rgb(var(--obs-text) / 0.08)", color: "rgb(var(--obs-subtle))" }}
                >
                  {chatName[0]?.toUpperCase()}
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-obs-text">{chatName}</p>
                  {selectedLead.telefone && <p className="truncate text-xs text-obs-faint">{selectedLead.telefone}</p>}
                </div>
              </div>
              <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                <StageBadge stage={selectedLead.stage} />
                <span className="rounded-full px-2 py-0.5 text-[10px] text-obs-faint" style={{ background: "rgb(var(--obs-text) / 0.05)" }}>
                  score {selectedLead.qualification_score || 0}%
                </span>
              </div>
              {(selectedLead.interesse_produto || commercialNoteSummary(selectedLead.metadata?.commercial_note)) && (
                <div className="mt-2.5 space-y-1 text-xs">
                  {selectedLead.interesse_produto && (
                    <p className="text-obs-subtle"><span className="text-obs-faint">Interesse · </span>{selectedLead.interesse_produto}</p>
                  )}
                  {commercialNoteSummary(selectedLead.metadata?.commercial_note) && (
                    <p className="text-obs-subtle" title={commercialNoteTitle(selectedLead.metadata?.commercial_note)}>
                      <span className="text-obs-faint">Nota comercial · </span>{commercialNoteSummary(selectedLead.metadata?.commercial_note)}
                    </p>
                  )}
                </div>
              )}
            </button>
          )}

          <div
            className="flex items-center gap-2 px-4 py-3 shrink-0"
            style={{ borderBottom: "1px solid var(--border-glass)" }}
          >
            <Boxes size={13} className="text-obs-teal" />
            <span className="text-xs font-semibold text-obs-text">Conhecimento</span>
            {selectedResponseMessageId && (
              <button
                type="button"
                onClick={() => setSelectedResponseMessageId(null)}
                className="ml-auto rounded border border-obs-teal/30 px-1.5 py-0.5 text-[9px] text-obs-teal"
              >
                Acompanhar mais recente
              </button>
            )}
            {knowledgeError && (
              <span className={`${selectedResponseMessageId ? "" : "ml-auto"} text-[10px] text-red-500 truncate`}>{knowledgeError}</span>
            )}
            {knowledge?.query_terms && knowledge.query_terms.length > 0 && (
              <span className="text-[10px] text-obs-faint truncate">
                · {knowledge.query_terms.slice(0, 3).join(", ")}
              </span>
            )}
          </div>

          {/* KnowledgeSidebar gerencia o próprio scroll interno (h-full
              overflow-y-auto) — precisa continuar sendo o único filho
              flex-1 do rail, senão colapsa a altura 0. Contato e Mídia
              ficam fora dele, com altura própria. */}
          <div className="flex-1 overflow-hidden">
            <KnowledgeSidebar
              ctx={knowledge}
              loading={knowledgeLoading}
              leadSelected={!!selectedLead}
              canEdit={canEdit}
              onPublished={() => setKnowledgeRefreshKey((value) => value + 1)}
            />
          </div>

          {/* Mídia · Arquivos · Links — o webhook do Evolution ainda
              descarta imagem/áudio/documento (roadmap backend #1/#2), então
              isto fica honesto sobre estar pendente em vez de fingir dado. */}
          {selectedLead && (
            <div className="shrink-0 p-4" style={{ borderTop: "1px solid var(--border-glass)" }}>
              <p className="text-[10px] font-semibold uppercase tracking-wide text-obs-faint">Mídia · Arquivos · Links</p>
              <div className="mt-2.5 grid grid-cols-3 gap-2">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="h-16 rounded-lg border border-dashed" style={{ borderColor: "var(--border-glass-strong)", background: "rgb(var(--obs-text) / 0.02)" }} />
                ))}
              </div>
              <div className="mt-2.5 rounded-lg p-2.5" style={{ background: "rgb(var(--obs-text) / 0.03)" }}>
                <p className="text-[11px] font-medium text-obs-subtle">Em breve</p>
                <p className="mt-0.5 text-[10px] leading-relaxed text-obs-faint">
                  Fotos, áudios e arquivos trocados nesta conversa vão aparecer aqui assim que estiverem disponíveis.
                </p>
              </div>
            </div>
          )}
        </>
        </aside>
      </>
      )}

      {showLeadInfo && selectedLead && (
        <LeadInfoModal
          lead={selectedLead}
          onClose={() => setShowLeadInfo(false)}
          onSaved={async () => {
            await refreshSelectedLead(selectedLead.id);
          }}
          onSubmit={
            isPortal
              ? (leadRef, body) => api.updatePortalLead(portalSlug!, leadRef, body)
              : undefined
          }
        />
      )}
    </div>
  );
}
