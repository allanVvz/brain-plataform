"use client";
import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { api } from "@/lib/api";
import { formatDistanceToNow, format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { MessageSquare, User, Clock, RefreshCw, Search, Phone, Radio, AlertCircle, UserCheck, Send, Boxes, Megaphone, FileQuestion, FileText, Palette, Image as ImageIcon, FileVideo, FileType, ExternalLink, Database, Maximize2, ArrowLeft, ChevronRight, Tag } from "lucide-react";
import Link from "next/link";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Lead {
  id: number;
  lead_id: string | null;
  nome: string | null;
  telefone: string | null;
  stage: string | null;
  ai_enabled: boolean | null;
  ai_paused: boolean | null;
  ultima_mensagem: string | null;
  last_update: string | null;
  updated_at: string | null;
  persona_id: string | null;
  interesse_produto: string | null;
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
  if (active) return { background: "rgba(124,111,255,0.10)", borderLeft: "2px solid #7c6fff" };
  if (state === "human_replying") return { background: "rgba(245,158,11,0.06)", borderLeft: "2px solid rgba(245,158,11,0.55)" };
  if (state === "awaiting_bot")   return { background: "rgba(239,68,68,0.05)",  borderLeft: "2px solid rgba(239,68,68,0.55)" };
  return { background: "transparent", borderLeft: "2px solid transparent" };
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function sortMessages(msgs: Message[]): Message[] {
  return [...msgs].sort((a, b) => {
    const dt = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
    return dt !== 0 ? dt : a.id - b.id;
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

function stageColor(stage: string | null): string {
  const s = (stage || "").toLowerCase();
  if (s === "novo") return "text-blue-400 border-blue-400/30";
  if (s === "qualificado" || s === "interested") return "text-yellow-400 border-yellow-400/30";
  if (s === "fechado" || s === "won") return "text-green-400 border-green-400/30";
  if (s === "perdido" || s === "lost") return "text-red-400 border-red-400/30";
  return "text-obs-subtle border-white/10";
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

function displayName(lead: Lead | null, msg?: Message): string {
  return (
    (lead?.nome?.trim()) ||
    (msg?.nome?.trim()) ||
    (lead?.telefone ? `+${lead.telefone}` : null) ||
    (lead ? `Lead #${lead.id}` : "Lead")
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StageBadge({ stage }: { stage: string | null }) {
  return (
    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full border bg-white/4 ${stageColor(stage)}`}>
      {stage || "novo"}
    </span>
  );
}

function MessageBubble({ msg, lead }: { msg: Message; lead: Lead | null }) {
  const out = isOutbound(msg);
  const mediaUrl = extractMediaUrl(msg.metadata);
  const hasText = (msg.texto || "").trim().length > 0;
  const senderName = out
    ? (msg.sender_type === "assistant" ? "Assistente IA" : msg.sender_type || "IA")
    : displayName(lead, msg);

  return (
    <div className={`flex flex-col gap-0.5 ${out ? "items-end" : "items-start"}`}>
      <span className="text-[10px] px-1 text-obs-faint">{senderName}</span>

      <div
        className={`max-w-[72%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${out ? "rounded-tr-sm" : "rounded-tl-sm"}`}
        style={
          out
            ? { background: "rgba(124,111,255,0.18)", border: "1px solid rgba(124,111,255,0.35)", color: "#e0ddff" }
            : { background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.09)", color: "#d4d4d8" }
        }
      >
        {hasText && <p className="whitespace-pre-wrap break-words">{msg.texto}</p>}
        {!hasText && mediaUrl && (
          <a href={mediaUrl} target="_blank" rel="noopener noreferrer" className="text-xs underline text-obs-violet">
            Ver mídia anexada
          </a>
        )}
        {!hasText && !mediaUrl && (
          <span className="text-xs italic text-obs-faint">
            [{out ? "resposta automática" : "mensagem sem texto"}]
          </span>
        )}
      </div>

      <span className="text-[10px] px-1 text-obs-faint">{formatTs(msg.created_at)}</span>
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

function KnowledgeSection({
  icon,
  title,
  count,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  if (count === 0) return null;
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
        background: active ? "rgba(124,111,255,0.22)" : "rgba(124,111,255,0.10)",
        border: `1px solid ${active ? "rgba(124,111,255,0.65)" : "rgba(124,111,255,0.30)"}`,
        color: "#dcd9ff",
      }}
    >
      <div className="flex items-center gap-1 min-w-0">
        <p className="font-medium truncate">{node.title}</p>
        <span className="shrink-0 rounded border border-white/10 px-1 py-0.5 text-[9px] uppercase text-obs-faint">
          {node.node_type}
        </span>
        {pendingLabel(node)}
        <ChevronRight size={10} className="ml-auto shrink-0 opacity-60" />
      </div>
      {node.summary && <p className="text-[11px] text-obs-subtle line-clamp-2 mt-0.5">{node.summary}</p>}
      {facts.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {facts.map((fact) => (
            <span key={fact} className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-obs-subtle">
              {fact}
            </span>
          ))}
        </div>
      )}
      {url && <p className="mt-1 truncate text-[10px] text-obs-violet">{url}</p>}
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
        color: "#d8fbff",
      }}
    >
      <div className="flex items-center gap-1 min-w-0">
        <p className="font-medium truncate">{node.title}</p>
        <span className="shrink-0 rounded border border-white/10 px-1 py-0.5 text-[9px] uppercase text-obs-faint">
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
  const body = (entry.conteudo || "").slice(0, 220);
  const id = kbEntryIdentity(entry);
  return (
    <button
      type="button"
      onClick={() => onSelect(id)}
      className="w-full text-left block rounded-md px-2.5 py-1.5 text-xs hover:opacity-90 transition"
      style={{
        background: active ? "rgba(255,255,255,0.10)" : "rgba(255,255,255,0.04)",
        border: `1px solid ${active ? "rgba(255,255,255,0.20)" : "rgba(255,255,255,0.07)"}`,
      }}
    >
      <div className="flex items-center gap-1 min-w-0">
        <p className="text-white font-medium truncate">{title}</p>
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
      style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}
    >
      {isImage ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={url!} alt={asset.title} className="w-full h-24 object-cover" />
      ) : (
        <div className="flex items-center justify-center h-16" style={{ background: "rgba(124,111,255,0.10)" }}>
          <Icon size={20} className="text-obs-violet" />
        </div>
      )}
      <div className="px-2 py-1.5 space-y-0.5">
        <p className="font-medium text-white truncate">{asset.title}</p>
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
      style={{ background: "rgba(255,255,255,0.035)", border: "1px solid rgba(255,255,255,0.08)" }}
    >
      <div className="flex items-center gap-1 min-w-0">
        <p className="font-medium text-white truncate">{source?.title || edge.source_node_id || "origem"}</p>
        <span className="shrink-0 text-[10px] text-obs-faint">→</span>
        <p className="font-medium text-white truncate">{targetNode?.title || edge.target_node_id || "destino"}</p>
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
          className="flex items-center gap-1 text-[11px] text-obs-subtle hover:text-white transition"
        >
          <ArrowLeft size={11} />
          <span>Voltar</span>
        </button>
        {nodeType && (
          <span className="ml-auto rounded border border-white/10 px-1.5 py-0.5 text-[9px] uppercase text-obs-faint">
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
        <h3 className="text-sm font-semibold text-white leading-tight">{title}</h3>
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
          <pre className="text-[11px] text-obs-subtle whitespace-pre-wrap break-words bg-white/4 border border-white/8 rounded-md p-2 leading-relaxed font-mono max-h-56 overflow-y-auto">
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
                className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-obs-subtle"
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
            className="text-[11px] text-obs-violet underline break-all"
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
                className="rounded-md border border-white/8 bg-white/3 px-2 py-1.5"
              >
                <div className="flex items-center gap-1 text-[11px] text-white min-w-0">
                  <span className="text-[10px] text-obs-faint">→</span>
                  <span className="truncate">{dest?.title || e.target_node_id || "destino"}</span>
                  {dest?.node_type && (
                    <span className="ml-auto shrink-0 rounded border border-white/10 px-1 py-0.5 text-[9px] uppercase text-obs-faint">
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
                className="rounded-md border border-white/8 bg-white/3 px-2 py-1.5"
              >
                <div className="flex items-center gap-1 text-[11px] text-white min-w-0">
                  <span className="text-[10px] text-obs-faint">←</span>
                  <span className="truncate">{src?.title || e.source_node_id || "origem"}</span>
                  {src?.node_type && (
                    <span className="ml-auto shrink-0 rounded border border-white/10 px-1 py-0.5 text-[9px] uppercase text-obs-faint">
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
          className="block w-full text-center text-[11px] py-1.5 rounded-md border border-obs-violet/40 bg-obs-violet/10 text-obs-violet hover:bg-obs-violet/20 transition"
        >
          Ver no grafo →
        </a>
      </div>
    </div>
  );
}

function KnowledgeSidebar({
  ctx,
  loading,
  leadSelected,
}: {
  ctx: ChatContext | null;
  loading: boolean;
  leadSelected: boolean;
}) {
  const [expanded, setExpanded] = useState<ExpandedKnowledge>(null);

  // Clear expand state when ctx changes (e.g., switching leads)
  useEffect(() => { setExpanded(null); }, [ctx]);

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

      <KnowledgeSection icon={<Database size={11} />} title="Base ativa" count={activeKb.length}>
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

const POLL_INTERVAL_MS = 4000;

export default function MessagesPage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [personaFilterId, setPersonaFilterId] = useState<string>("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loadingLeads, setLoadingLeads] = useState(true);
  const [loadingMsgs, setLoadingMsgs] = useState(false);
  const [liveSync, setLiveSync] = useState(false);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [pausing, setPausing] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [knowledge, setKnowledge] = useState<ChatContext | null>(null);
  const [knowledgeLoading, setKnowledgeLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const selectedIdRef = useRef<number | null>(null);
  const draftRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setPersonaFilterId(window.localStorage.getItem("ai-brain-persona-id") || "");
    const onPersonaChange = (event: Event) => {
      const detail = (event as CustomEvent<{ id?: string }>).detail;
      setPersonaFilterId(detail?.id || window.localStorage.getItem("ai-brain-persona-id") || "");
      setSelectedId(null);
      setMessages([]);
      setKnowledge(null);
    };
    window.addEventListener("ai-brain-persona-change", onPersonaChange);
    return () => window.removeEventListener("ai-brain-persona-change", onPersonaChange);
  }, []);

  const loadLeads = useCallback(() => {
    setLoadingLeads(true);
    Promise.all([
      api.leads(200, 0, personaFilterId || undefined),
      api.conversations(168, personaFilterId || undefined),
    ])
      .then(([leadRows, convRows]) => {
        setLeads(leadRows as Lead[]);
        setConversations(convRows as ConversationSummary[]);
      })
      .catch(console.error)
      .finally(() => setLoadingLeads(false));
  }, [personaFilterId]);

  useEffect(() => { loadLeads(); }, [loadLeads]);

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

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Polling: refresh messages for the open lead every POLL_INTERVAL_MS
  useEffect(() => {
    selectedIdRef.current = selectedId;

    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }

    if (!selectedId) {
      setLiveSync(false);
      return;
    }

    setLiveSync(true);

    pollRef.current = setInterval(() => {
      const id = selectedIdRef.current;
      if (!id) return;
      Promise.all([api.messagesByRef(id), api.conversations(168, personaFilterId || undefined)])
        .then(([msgRows, convRows]) => {
          if (selectedIdRef.current !== id) return; // lead changed while fetching
          setMessages(sortMessages(msgRows as Message[]));
          setConversations(convRows as ConversationSummary[]);
        })
        .catch(() => {});
    }, POLL_INTERVAL_MS);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      setLiveSync(false);
    };
  }, [selectedId, personaFilterId]);

  const openLead = useCallback((lead: Lead) => {
    setSelectedId(lead.id);
    setMessages([]);
    setKnowledge(null);
    setLoadingMsgs(true);
    setDraft("");
    setSendError(null);
    api.messagesByRef(lead.id)
      .then((rows) => setMessages(sortMessages(rows as Message[])))
      .catch(console.error)
      .finally(() => setLoadingMsgs(false));
    setTimeout(() => draftRef.current?.focus(), 80);
  }, []);

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
  const selectedLead = useMemo(
    () => leads.find((l) => l.id === selectedId) ?? null,
    [leads, selectedId],
  );

  useEffect(() => {
    if (selectedLead && personaFilterId && selectedLead.persona_id !== personaFilterId) {
      setSelectedId(null);
      setMessages([]);
      setKnowledge(null);
    }
  }, [selectedLead, personaFilterId]);

  useEffect(() => {
    if (!selectedId || !selectedLead) {
      setKnowledge(null);
      return;
    }
    let cancelled = false;
    setKnowledgeLoading(true);
    api.knowledgeChatContext(selectedId, lastClientText || selectedLead?.interesse_produto || undefined, selectedLead?.persona_id || undefined)
      .then((ctx) => { if (!cancelled) setKnowledge(ctx); })
      .catch(() => { if (!cancelled) setKnowledge(null); })
      .finally(() => { if (!cancelled) setKnowledgeLoading(false); });
    return () => { cancelled = true; };
  }, [selectedId, selectedLead, lastClientText, selectedLead?.interesse_produto, selectedLead?.persona_id]);

  const refreshSelectedLead = useCallback(async (id: number) => {
    try {
      const fresh = await api.lead(String(id));
      setLeads((prev) => prev.map((l) => (l.id === id ? { ...l, ...fresh } : l)));
    } catch {
      /* lead lookup is best-effort */
    }
  }, []);

  const onSend = useCallback(async () => {
    if (!selectedId || !draft.trim() || sending) return;
    setSending(true);
    setSendError(null);
    try {
      await api.sendMessage({
        lead_ref: selectedId,
        texto: draft.trim(),
        nome: "Operador",
      });
      setDraft("");
      // Refresh messages + conversations imediato (não esperar próximo poll)
      const [msgRows, convRows] = await Promise.all([
        api.messagesByRef(selectedId),
        api.conversations(168, personaFilterId || undefined),
      ]);
      setMessages(sortMessages(msgRows as Message[]));
      setConversations(convRows as ConversationSummary[]);
    } catch (e: any) {
      setSendError(e?.message || "Falha ao enviar.");
    } finally {
      setSending(false);
      setTimeout(() => draftRef.current?.focus(), 50);
    }
  }, [selectedId, draft, sending, personaFilterId]);

  const onDraftKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      onSend();
    }
  };

  const togglePause = useCallback(async () => {
    if (!selectedId || pausing) return;
    setPausing(true);
    try {
      const current = leads.find((l) => l.id === selectedId);
      if (current?.ai_paused) await api.resumeAi(selectedId);
      else await api.pauseAi(selectedId);
      await refreshSelectedLead(selectedId);
    } catch (e) {
      console.error(e);
    } finally {
      setPausing(false);
    }
  }, [selectedId, pausing, leads, refreshSelectedLead]);

  const filtered = leads.filter((l) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      (l.nome || "").toLowerCase().includes(q) ||
      (l.telefone || "").includes(q) ||
      (l.lead_id || "").includes(q) ||
      (l.stage || "").toLowerCase().includes(q) ||
      (l.interesse_produto || "").toLowerCase().includes(q)
    );
  });

  const chatName = displayName(selectedLead);

  return (
    <div
      className="flex h-[calc(100vh-6rem)] overflow-hidden rounded-xl"
      style={{ border: "1px solid rgba(255,255,255,0.07)" }}
    >
      {/* ── Left: Leads list ───────────────────────────────────────────── */}
      <aside
        className="w-72 shrink-0 flex flex-col overflow-hidden"
        style={{ borderRight: "1px solid rgba(255,255,255,0.07)", background: "rgba(14,17,24,0.80)" }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-4 py-3"
          style={{ borderBottom: "1px solid rgba(255,255,255,0.07)" }}
        >
          <div className="flex items-center gap-2">
            <User size={13} className="text-obs-violet" />
            <span className="text-xs font-semibold text-white">Leads</span>
            {!loadingLeads && (
              <span className="text-[10px] text-obs-faint">({filtered.length})</span>
            )}
          </div>
          <button
            onClick={loadLeads}
            className="p-1 rounded text-obs-subtle hover:text-white transition-colors"
          >
            <RefreshCw size={11} />
          </button>
        </div>

        {/* Search */}
        <div className="px-3 py-2" style={{ borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
          <div
            className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg"
            style={{ background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.07)" }}
          >
            <Search size={11} className="text-obs-faint shrink-0" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar lead..."
              className="flex-1 bg-transparent text-xs text-white placeholder-obs-faint focus:outline-none"
            />
          </div>
        </div>

        {/* Lead list */}
        <div className="flex-1 overflow-y-auto">
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
            return (
              <button
                key={lead.id}
                onClick={() => openLead(lead)}
                className="w-full text-left px-4 py-3 flex flex-col gap-1 transition-colors"
                style={{
                  ...attentionRowStyle(attention, active),
                  borderBottom: "1px solid rgba(255,255,255,0.04)",
                }}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <div
                      className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold shrink-0"
                      style={{ background: "rgba(124,111,255,0.20)", color: "#a78bfa" }}
                    >
                      {name[0].toUpperCase()}
                    </div>
                    <span className="text-xs font-medium text-white truncate">{name}</span>
                  </div>
                  <StageBadge stage={lead.stage} />
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
                  {lastTs && (
                    <div className="flex items-center gap-1 text-obs-faint ml-auto">
                      <Clock size={9} />
                      <span className="text-[10px]">{relativeTs(lastTs)}</span>
                    </div>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      </aside>

      {/* ── Right: Chat view ───────────────────────────────────────────── */}
      <div
        className="flex-1 flex flex-col overflow-hidden"
        style={{ background: "rgba(10,12,19,0.70)" }}
      >
        {/* Chat header */}
        <div
          className="flex items-center gap-3 px-5 py-3 shrink-0"
          style={{ borderBottom: "1px solid rgba(255,255,255,0.07)", background: "rgba(14,17,24,0.80)" }}
        >
          {selectedLead ? (
            <>
              <div
                className="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold shrink-0"
                style={{ background: "rgba(124,111,255,0.20)", color: "#a78bfa" }}
              >
                {chatName[0].toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-white truncate">{chatName}</p>
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

              {/* Expand conversation: open dedicated timeline view */}
              <Link
                href={`/messages/${selectedLead.id}`}
                title="Expandir conversa (abrir timeline em página dedicada)"
                className="p-1.5 rounded-md text-obs-subtle hover:text-white hover:bg-white/5 transition shrink-0"
              >
                <Maximize2 size={13} />
              </Link>

              <button
                type="button"
                onClick={togglePause}
                disabled={pausing}
                title={selectedLead.ai_paused ? "IA pausada — clique para retomar" : "IA ativa — clique para pausar"}
                className={`text-[10px] px-2.5 py-1 rounded-full shrink-0 border transition disabled:opacity-50 ${
                  selectedLead.ai_paused
                    ? "border-amber-400/50 bg-amber-500/15 text-amber-200 hover:bg-amber-500/25"
                    : "border-emerald-400/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20"
                }`}
              >
                <span className={`inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle ${selectedLead.ai_paused ? "bg-amber-400" : "bg-emerald-400"}`} />
                {selectedLead.ai_paused ? "IA pausada · humano" : "IA ativa"}
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
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
          {!selectedLead && (
            <div className="flex flex-col items-center justify-center h-full gap-3">
              <MessageSquare size={32} className="text-obs-faint/20" />
              <p className="text-sm text-obs-faint">Escolha um lead na lista ao lado</p>
            </div>
          )}

          {selectedLead && loadingMsgs && (
            <div className="flex items-center justify-center py-12">
              <span className="text-xs text-obs-faint">Carregando conversa...</span>
            </div>
          )}

          {selectedLead && !loadingMsgs && messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full gap-2">
              <MessageSquare size={20} className="text-obs-faint/30" />
              <p className="text-xs text-obs-faint">Nenhuma mensagem encontrada para este lead.</p>
            </div>
          )}

          {messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              msg={msg}
              lead={selectedLead}
            />
          ))}

          <div ref={bottomRef} />
        </div>

        {/* Send bar */}
        {selectedLead && (
          <div
            className="px-4 py-3 shrink-0"
            style={{
              borderTop: "1px solid rgba(255,255,255,0.07)",
              background: "rgba(14,17,24,0.85)",
            }}
          >
            <div
              className="rounded-xl p-3 space-y-2"
              style={{ background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)" }}
            >
              <textarea
                ref={draftRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={onDraftKey}
                placeholder={
                  selectedLead.ai_paused
                    ? "IA pausada — você está respondendo como operador. Ctrl+Enter envia."
                    : "Responder como operador (envia ao agente + WhatsApp). Ctrl+Enter envia."
                }
                rows={2}
                disabled={sending}
                className="w-full bg-transparent text-sm text-white placeholder-obs-faint resize-none focus:outline-none disabled:opacity-50"
              />
              <div className="flex items-center justify-between gap-2">
                <div className="text-[11px] text-obs-faint min-w-0 truncate">
                  {sendError ? (
                    <span className="text-red-400">erro: {sendError}</span>
                  ) : selectedLead.ai_paused ? (
                    <span className="text-amber-300/80">IA pausada — só você responde até retomar.</span>
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

      {/* ── Right: Knowledge sidebar ────────────────────────────────────── */}
      <aside
        className="w-80 shrink-0 flex flex-col overflow-hidden"
        style={{ borderLeft: "1px solid rgba(255,255,255,0.07)", background: "rgba(14,17,24,0.80)" }}
      >
        <div
          className="flex items-center gap-2 px-4 py-3 shrink-0"
          style={{ borderBottom: "1px solid rgba(255,255,255,0.07)" }}
        >
          <Boxes size={13} className="text-obs-violet" />
          <span className="text-xs font-semibold text-white">Conhecimento</span>
          {knowledge?.query_terms && knowledge.query_terms.length > 0 && (
            <span className="text-[10px] text-obs-faint truncate">
              · {knowledge.query_terms.slice(0, 3).join(", ")}
            </span>
          )}
        </div>
        <div className="flex-1 overflow-hidden">
          <KnowledgeSidebar ctx={knowledge} loading={knowledgeLoading} leadSelected={!!selectedLead} />
        </div>
      </aside>
    </div>
  );
}
