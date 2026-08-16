"use client";
import { useEffect, useState, useCallback, useRef, useMemo, memo } from "react";
import { api, type JourneyEventType } from "@/lib/api";
import {
  isJourneySettled,
  normalizeJourneyOutcome,
  type JourneyOutcome,
} from "@/lib/lead-state";
import { formatDistanceToNow, format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { MessageSquare, User, RefreshCw, Search, Phone, Radio, AlertCircle, UserCheck, Send, Boxes, FileText, Image as ImageIcon, FileVideo, FileType, ExternalLink, PanelRightClose, PanelRightOpen, ArrowLeft, ChevronLeft, ChevronRight, StickyNote } from "lucide-react";
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
  // Desfecho comercial derivado da jornada corrente pelo backend. Eixo
  // independente de `stage`, nunca um substituto dele.
  journey_outcome?: string | null;
  // `sales` | `appointment` — vem de personas.config.portal e decide o par de
  // eventos do pedido: comprado/entregue ou agendado/concluído.
  business_model?: string | null;
  // Permanente: depois do primeiro agendamento ou compra a lead está
  // convertida e não volta a qualificada, nem ao cancelar, nem no pedido
  // seguinte.
  lead_converted?: boolean | null;
  // Há jornada corrente para receber evento? Sem ela o backend devolve 409.
  journey_is_open?: boolean | null;
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
  journey_outcome?: string | null;
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
// O estágio é categórico, não semântico: o peso codifica o avanço em vez de
// gastar um acento reservado. O verde de --obs-live é exclusivo de "canal
// conectado / IA ativa" — usá-lo aqui fazia a mesma cor significar duas coisas
// diferentes na mesma tela. Quem carrega cor agora é o desfecho da jornada.
function stageColor(stage: string | null): string {
  const s = (stage || "").toLowerCase();
  if (s === "perdido" || s === "lost") return "text-obs-subtle border-obs-line line-through";
  if (s === "fechado" || s === "won") return "text-obs-text border-obs-line-strong font-semibold";
  return "text-obs-subtle border-obs-line";
}

// Desfecho comercial: o único eixo da tela que gasta cor por progresso.
// `qualificado` fica deliberadamente cinza — só compromisso, venda e entrega
// merecem acento. Ver a família resultado/* no design system.
const OUTCOME_STYLE: Record<JourneyOutcome, { label: string; color: string; soft: string }> = {
  qualificado: { label: "qualificado", color: "rgb(var(--obs-faint))", soft: "rgb(var(--obs-faint) / 0.12)" },
  convertido: { label: "convertido", color: "rgb(var(--obs-outcome-converted))", soft: "rgb(var(--obs-outcome-converted) / 0.12)" },
  vendido: { label: "vendido", color: "rgb(var(--obs-outcome-sold))", soft: "rgb(var(--obs-outcome-sold) / 0.12)" },
  entregue: { label: "entregue", color: "rgb(var(--obs-outcome-delivered))", soft: "rgb(var(--obs-outcome-delivered) / 0.12)" },
  cancelado: { label: "cancelado", color: "rgb(var(--obs-outcome-cancelled))", soft: "rgb(var(--obs-outcome-cancelled) / 0.12)" },
};

function OutcomeMark({ outcome, size = "sm" }: { outcome: JourneyOutcome; size?: "sm" | "md" }) {
  const style = OUTCOME_STYLE[outcome];
  const dot = size === "md" ? 8 : 7;
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1.5"
      data-outcome={outcome}
      title={`Jornada · ${style.label}`}
    >
      <span
        className="rounded-full"
        style={{ width: dot, height: dot, background: style.color }}
      />
      <span
        className={`text-[10px] font-medium uppercase tracking-wide ${
          outcome === "cancelado" ? "line-through" : ""
        }`}
        style={{ color: style.color }}
      >
        {style.label}
      </span>
    </span>
  );
}

function parseMetadata(metadata: any): any {
  if (!metadata) return null;
  if (typeof metadata === "string") {
    try { return JSON.parse(metadata); } catch { return null; }
  }
  return metadata;
}

function extractMediaUrl(metadata: any): string | null {
  const meta = parseMetadata(metadata);
  if (!meta) return null;
  return meta.media_url || meta.image_url || meta.file_url || meta.url || null;
}

export type MessageAttachment = {
  kind: "image" | "audio" | "video" | "document";
  /** Set once the ingest worker has stored the file; null while it downloads. */
  url: string | null;
  filename: string | null;
  voiceNote: boolean;
  durationSeconds: number | null;
  mime: string | null;
  status: string | null;
};

/**
 * Describe the file attached to a message, if any.
 *
 * The webhook writes `metadata.media` (the descriptor produced by the
 * provider normalizer) and the ingest worker later adds `metadata.asset_id`
 * once the bytes are stored. Until then the bubble shows the attachment as
 * still loading rather than as a broken link.
 */
function messageAttachment(msg: Message): MessageAttachment | null {
  const meta = parseMetadata(msg.metadata);
  const media = meta?.media;
  if (!media) {
    // Older rows only ever carried a bare URL.
    const legacy = extractMediaUrl(msg.metadata);
    return legacy
      ? { kind: "document", url: legacy, filename: null, voiceNote: false, durationSeconds: null, mime: null, status: "ready" }
      : null;
  }
  const assetId = meta.asset_id || media.asset_id || null;
  const assetStatus = meta.media_asset_status || media.asset_status || null;
  const assetReady = assetId && (!assetStatus || assetStatus === "ready");
  return {
    kind: (["image", "audio", "video", "document"].includes(media.kind) ? media.kind : "document") as MessageAttachment["kind"],
    url: assetReady ? api.assetMediaUrl(String(assetId)) : extractMediaUrl(msg.metadata),
    filename: media.filename || null,
    voiceNote: Boolean(media.voice_note),
    durationSeconds: typeof media.duration_seconds === "number" ? media.duration_seconds : null,
    mime: media.mime || null,
    status: assetStatus,
  };
}

function formatDuration(seconds: number | null): string {
  if (!seconds || seconds <= 0) return "";
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

/** Inline renderer for a message attachment: image, audio player or file chip. */
function MessageMedia({ attachment }: { attachment: MessageAttachment }) {
  const { kind, url, filename, voiceNote, durationSeconds, status } = attachment;
  const [imageState, setImageState] = useState<"loading" | "decoded" | "error">("loading");
  const [imageAttempt, setImageAttempt] = useState(0);

  useEffect(() => {
    setImageState("loading");
    setImageAttempt(0);
  }, [url]);

  if (!url) {
    if (status === "failed") {
      return (
        <span className="flex items-center gap-1.5 text-xs italic text-red-300/80">
          Arquivo recebido, mas indisponivel para visualizacao.
        </span>
      );
    }
    return (
      <span className="flex items-center gap-1.5 text-xs italic text-obs-faint">
        <RefreshCw size={12} className="animate-spin" />
        {kind === "audio" ? "baixando áudio…" : "baixando arquivo…"}
      </span>
    );
  }

  if (kind === "image") {
    const imageUrl = imageAttempt > 0
      ? `${url}${url.includes("?") ? "&" : "?"}_media_retry=${imageAttempt}`
      : url;
    const retryImage = () => {
      setImageState("loading");
      setImageAttempt((attempt) => attempt + 1);
    };
    const failImage = () => {
      if (imageAttempt === 0) {
        retryImage();
      } else {
        setImageState("error");
      }
    };
    return (
      <div className="relative min-h-24 min-w-40 overflow-hidden rounded-lg" data-media-state={imageState}>
        {imageState === "loading" && (
          <span
            className="absolute inset-0 animate-pulse rounded-lg bg-white/10"
            aria-label="Carregando imagem"
          />
        )}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={imageUrl}
          alt={filename || "Imagem recebida"}
          loading="lazy"
          className={`max-h-64 w-auto max-w-full rounded-lg object-cover transition ${imageState === "decoded" ? "opacity-100" : "opacity-0"}`}
          style={{ border: "1px solid var(--border-glass)" }}
          onLoad={(event) => {
            const image = event.currentTarget;
            if (image.complete && image.naturalWidth > 0) {
              setImageState("decoded");
            } else {
              failImage();
            }
          }}
          onError={failImage}
        />
        {imageState === "decoded" && (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`Abrir ${filename || "imagem recebida"}`}
            className="absolute inset-0 rounded-lg transition hover:bg-black/10"
          />
        )}
        {imageState === "error" && (
          <span className="absolute inset-0 flex flex-col items-center justify-center gap-2 rounded-lg bg-red-950/30 p-3 text-center text-xs text-red-200">
            Nao foi possivel decodificar a imagem.
            <button type="button" onClick={retryImage} className="rounded border border-red-200/30 px-2 py-1 hover:bg-white/10">
              Tentar novamente
            </button>
          </span>
        )}
      </div>
    );
  }

  if (kind === "audio") {
    return (
      <div className="flex flex-col gap-1">
        <audio controls preload="metadata" src={url} className="h-9 w-full min-w-[15rem] max-w-xs" />
        <span className="text-[10px] text-obs-faint">
          {voiceNote ? "Mensagem de voz" : "Áudio"}
          {durationSeconds ? ` · ${formatDuration(durationSeconds)}` : ""}
        </span>
      </div>
    );
  }

  if (kind === "video") {
    return (
      <video controls preload="metadata" src={url} className="max-h-64 w-auto max-w-full rounded-lg" />
    );
  }

  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs transition hover:opacity-80"
      style={{ background: "rgb(var(--obs-text) / 0.05)", border: "1px solid var(--border-glass)" }}
    >
      <FileText size={16} className="shrink-0 text-obs-teal" />
      <span className="truncate">{filename || "Documento"}</span>
      <ExternalLink size={12} className="shrink-0 text-obs-faint" />
    </a>
  );
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

// ── Jornada: pedido e ações ──────────────────────────────────────────────────

// O ciclo do pedido tem dois passos, e o par de eventos de cada um depende do
// modelo de negócio da persona: produto é comprado e entregue, serviço é
// agendado e concluído. Registrar "compra" numa persona de agendamento estava
// rotulando errado o que aconteceu.
type OfferingKind = "sales" | "appointment";

// Quem grava o evento muda com a superficie: o portal tem rota propria porque
// o middleware de auth nao libera `/agents/*` para contas `client`.
type RecordJourneyEvent = (
  leadRef: number,
  body: Parameters<typeof api.recordJourneyEvent>[1],
) => Promise<unknown>;

const OFFERING: Record<OfferingKind, {
  aberto: { label: string; event: JourneyEventType };
  concluido: { label: string; event: JourneyEventType };
}> = {
  sales: {
    aberto: { label: "Venda", event: "sale_recorded" },
    concluido: { label: "Entregue", event: "delivered" },
  },
  appointment: {
    aberto: { label: "Agendamento", event: "appointment_booked" },
    concluido: { label: "Concluído", event: "service_completed" },
  },
};

function offeringKind(lead: Lead): OfferingKind {
  return lead.business_model === "appointment" ? "appointment" : "sales";
}

// Conversão da LEAD, não do pedido. É reversível apenas enquanto for leitura do
// operador: assim que o primeiro agendamento ou compra acontece, a lead está
// convertida e não volta a qualificada — nem ao cancelar o pedido, nem no
// pedido seguinte. Desfazer aí passaria por estorno em sales_conversions, que
// é outro contrato.
function ToggleConversao({
  lead, outcome, canEdit, onRecorded, recordEvent,
}: {
  lead: Lead;
  outcome: JourneyOutcome | null;
  canEdit: boolean;
  onRecorded: () => void | Promise<void>;
  recordEvent: RecordJourneyEvent;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const leadConverted = Boolean(lead.lead_converted) || outcome === "convertido"
    || outcome === "vendido";
  const journeyOpen = lead.journey_is_open !== false;
  // Depois da primeira venda a conversão é fato; sem jornada corrente não há
  // o que gravar (o backend responderia 409).
  const locked = Boolean(lead.lead_converted) || !journeyOpen;
  const readable: JourneyOutcome = leadConverted ? "convertido" : "qualificado";
  const style = OUTCOME_STYLE[readable];

  const toggle = useCallback(async () => {
    const event: JourneyEventType = leadConverted ? "conversion_reverted" : "converted";
    setPending(true);
    setError(null);
    try {
      await recordEvent(lead.id, {
        event_type: event,
        idempotency_key: `dashboard:${lead.id}:${event}`,
        source: "dashboard",
        occurred_at: new Date().toISOString(),
        metadata: { recorded_from: "messages" },
      });
      await onRecorded();
    } catch (err) {
      setError(getErrorMessage(err, "Não foi possível alterar a conversão."));
    } finally {
      setPending(false);
    }
  }, [leadConverted, lead.id, onRecorded, recordEvent]);

  const content = (
    <span className="inline-flex items-center gap-[7px]">
      <span
        className="h-[7px] w-[7px] shrink-0 rounded-full"
        style={{ background: style.color }}
      />
      <span
        className="text-[11px] font-medium"
        style={{ color: style.color }}
      >
        {pending ? "…" : style.label}
      </span>
    </span>
  );

  if (!canEdit || locked) {
    return (
      <span
        className="shrink-0 rounded-full px-2.5 py-1"
        data-outcome={readable}
        title={
          lead.lead_converted
            ? "A lead converteu no primeiro pedido — isso não volta atrás"
            : !journeyOpen
              ? "Sem pedido aberto: o próximo contato do cliente inicia o próximo ciclo"
              : `Lead · ${style.label}`
        }
        style={{ background: style.soft }}
      >
        {content}
      </span>
    );
  }

  return (
    <span className="shrink-0">
      <button
        type="button"
        onClick={toggle}
        disabled={pending}
        role="switch"
        aria-checked={leadConverted}
        aria-label="Conversão da lead"
        data-outcome={readable}
        title={leadConverted ? "Desfazer a conversão" : "Marcar como convertido"}
        className="rounded-full px-2.5 py-1 transition hover:opacity-80 disabled:opacity-50"
        style={{ background: style.soft, border: `1px solid ${style.color}` }}
      >
        {content}
      </button>
      {error && <p className="mt-1 text-[10px] text-obs-rose">{error}</p>}
    </span>
  );
}

function JourneyActions({
  lead, outcome, canEdit, onRecorded, recordEvent,
}: {
  lead: Lead;
  outcome: JourneyOutcome | null;
  canEdit: boolean;
  onRecorded: () => void | Promise<void>;
  recordEvent: RecordJourneyEvent;
}) {
  const [pending, setPending] = useState<string | null>(null);
  const [fechando, setFechando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const oferta = OFFERING[offeringKind(lead)];

  const vendido = outcome === "vendido";
  const entregue = outcome === "entregue";
  const cancelado = outcome === "cancelado";
  // Sem jornada corrente o backend levanta `current journey not found` e
  // devolve 409. Antes o botao ficava clicavel e o clique falhava em silencio:
  // um pedido concluido deixa `is_current=false` e so o proximo inbound do
  // cliente abre o pedido seguinte.
  const semPedidoAberto = lead.journey_is_open === false;
  const fechado = isJourneySettled(outcome) || semPedidoAberto;

  const registrar = useCallback(async (event: JourneyEventType, key: string) => {
    setPending(key);
    setError(null);
    try {
      await recordEvent(lead.id, {
        event_type: event,
        // Determinística de propósito: dois cliques no mesmo botão da mesma
        // jornada colidem na chave e o backend devolve deduplicated:true em
        // vez de gravar o evento duas vezes.
        idempotency_key: `dashboard:${lead.id}:${event}`,
        source: "dashboard",
        occurred_at: new Date().toISOString(),
        metadata: { recorded_from: "messages" },
      });
      await onRecorded();
    } catch (err) {
      setError(getErrorMessage(err, "Não foi possível registrar o evento."));
    } finally {
      setPending(null);
      setFechando(false);
    }
  }, [lead.id, onRecorded, recordEvent]);

  if (!canEdit) return null;

  // Botão 1 — o pedido nasce aqui: comprado ou agendado.
  const abertoStyle = OUTCOME_STYLE.vendido;
  const abertoLigado = vendido || entregue;
  const abertoBloqueado = fechado || pending !== null;

  // Botão 2 — o terminal. Fecha o pedido, e o próprio botão diz como fechou:
  // entregue/concluído quando deu certo, cancelado quando não. Cancelar estorna
  // o passo 1, então o botão de venda volta a aparecer desligado.
  const terminalStyle = cancelado ? OUTCOME_STYLE.cancelado : OUTCOME_STYLE.entregue;
  const terminalLabel = entregue
    ? oferta.concluido.label
    : cancelado
      ? "Cancelado"
      : "Fechar pedido";
  const terminalLigado = fechado;
  const terminalBloqueado = fechado || pending !== null || !outcome;

  function botaoStyle(ligado: boolean, bloqueado: boolean, style: { color: string; soft: string }) {
    return {
      background: ligado ? style.soft : "rgb(var(--obs-text) / 0.03)",
      borderColor: ligado ? style.color : "var(--border-glass)",
      color: ligado ? style.color : bloqueado ? "rgb(var(--obs-faint))" : "rgb(var(--obs-subtle))",
      opacity: bloqueado && !ligado ? 0.45 : 1,
    };
  }

  return (
    <div className="shrink-0 px-4 pb-4">
      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          disabled={abertoBloqueado || abertoLigado}
          onClick={() => registrar(oferta.aberto.event, "aberto")}
          title={
            abertoLigado
              ? `Já registrado · ${oferta.aberto.label.toLowerCase()}`
              : semPedidoAberto
                ? "Sem pedido aberto: o próximo contato do cliente inicia o próximo ciclo"
                : fechado
                  ? "O pedido já foi fechado"
                  : oferta.aberto.label
          }
          className="flex items-center gap-2 rounded-[10px] border px-3 py-2.5 text-xs font-medium transition disabled:cursor-not-allowed"
          style={botaoStyle(abertoLigado, abertoBloqueado, abertoStyle)}
        >
          <span
            className="h-[9px] w-[9px] shrink-0 rounded-full"
            style={
              abertoLigado
                ? { background: abertoStyle.color }
                : { border: "1.5px solid rgb(var(--obs-faint))" }
            }
          />
          <span className="truncate">
            {pending === "aberto" ? "…" : oferta.aberto.label}
          </span>
        </button>

        <button
          type="button"
          disabled={terminalBloqueado}
          onClick={() => setFechando(true)}
          title={
            semPedidoAberto
              ? "Sem pedido aberto: o próximo contato do cliente inicia o próximo ciclo"
              : fechado
                ? `Pedido fechado · ${terminalLabel.toLowerCase()}`
                : !outcome
                  ? "Ainda não há pedido para fechar"
                  : "Fechar o pedido"
          }
          className="flex items-center gap-2 rounded-[10px] border px-3 py-2.5 text-xs font-medium transition disabled:cursor-not-allowed"
          style={botaoStyle(terminalLigado, terminalBloqueado, terminalStyle)}
        >
          <span
            className="h-[9px] w-[9px] shrink-0 rounded-full"
            style={
              terminalLigado
                ? { background: terminalStyle.color }
                : { border: "1.5px solid rgb(var(--obs-faint))" }
            }
          />
          <span className={`truncate ${cancelado ? "line-through" : ""}`}>
            {pending && pending !== "aberto" ? "…" : terminalLabel}
          </span>
        </button>
      </div>
      {error && <p className="mt-2 text-[11px] text-obs-rose">{error}</p>}

      {/* Sem window.confirm: um diálogo nativo trava a sessão do navegador. */}
      {fechando && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4" role="dialog" aria-modal="true">
          <div className="absolute inset-0" style={{ background: "rgb(0 0 0 / 0.45)" }} onClick={() => setFechando(false)} />
          <div className="modal-content relative w-full max-w-sm p-5">
            <p className="text-sm font-semibold text-obs-text">Fechar pedido</p>
            <p className="mt-2 text-xs leading-relaxed text-obs-subtle">
              Fechar encerra a jornada. A próxima mensagem do cliente abre um pedido
              novo e o agente recomeça o ciclo.
            </p>
            <div className="mt-4 space-y-2">
              <button
                type="button"
                disabled={!vendido || pending !== null}
                onClick={() => registrar(oferta.concluido.event, "concluido")}
                className="flex w-full items-start gap-3 rounded-[10px] border p-3 text-left transition disabled:cursor-not-allowed disabled:opacity-45"
                style={{ borderColor: "var(--border-glass)" }}
              >
                <span
                  className="mt-[3px] h-[9px] w-[9px] shrink-0 rounded-full"
                  style={{ background: OUTCOME_STYLE.entregue.color }}
                />
                <span className="min-w-0">
                  <span className="block text-xs font-medium text-obs-text">
                    {oferta.concluido.label}
                  </span>
                  <span className="block text-[11px] text-obs-faint">
                    {vendido
                      ? "O pedido foi cumprido."
                      : `Registre ${oferta.aberto.label.toLowerCase()} antes de concluir.`}
                  </span>
                </span>
              </button>
              <button
                type="button"
                disabled={pending !== null}
                onClick={() => registrar("cancelled", "cancelado")}
                className="flex w-full items-start gap-3 rounded-[10px] border p-3 text-left transition disabled:cursor-not-allowed disabled:opacity-45"
                style={{ borderColor: "var(--border-glass)" }}
              >
                <span
                  className="mt-[3px] h-[9px] w-[9px] shrink-0 rounded-full"
                  style={{ background: OUTCOME_STYLE.cancelado.color }}
                />
                <span className="min-w-0">
                  <span className="block text-xs font-medium text-obs-text">Cancelado</span>
                  <span className="block text-[11px] text-obs-faint">
                    {vendido
                      ? `Estorna ${oferta.aberto.label.toLowerCase()}. A conversão do lead é preservada.`
                      : "O pedido não seguiu adiante."}
                  </span>
                </span>
              </button>
            </div>
            <div className="mt-4 flex justify-end">
              <button type="button" className="lg-btn lg-btn-secondary" onClick={() => setFechando(false)}>
                Voltar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function PedidoBlock({ lead }: { lead: Lead }) {
  const entries = commercialNoteEntries(lead.metadata?.commercial_note);
  const [expanded, setExpanded] = useState(false);
  if (entries.length === 0) return null;
  // O resumo antigo mostrava duas chaves e escondia o resto num title=
  // invisível. Aqui as notas são o conteúdo, não uma legenda. O nome do
  // produto não se repete: ele já é o título do resumo no topo do rail.
  const shown = expanded ? entries : entries.slice(0, 4);
  return (
    <div className="shrink-0 px-4 pt-4 pb-3">
      <p className="text-[10px] font-medium uppercase tracking-wide text-obs-faint">Pedido</p>
      {shown.length > 0 && (
        <dl className="mt-2.5 space-y-1.5">
          {shown.map(([key, value]) => (
            <div key={key} className="flex items-baseline gap-3">
              <dt className="w-[88px] shrink-0 text-[10px] uppercase tracking-wide text-obs-faint">
                {key.replace(/_/g, " ")}
              </dt>
              <dd className="min-w-0 flex-1 text-xs text-obs-text">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {entries.length > 4 && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 text-[11px] font-medium text-obs-subtle transition hover:text-obs-text"
        >
          {expanded ? "Mostrar menos" : `+${entries.length - 4} campos`}
        </button>
      )}
    </div>
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

/**
 * Files exchanged in the open conversation.
 *
 * Derived from the messages already in state — no extra request — so it stays
 * in step with the thread as it pages and polls.
 */
export function ConversationMediaRail({ messages }: { messages: Message[] }) {
  const items = useMemo(() => {
    const found: { key: string; attachment: MessageAttachment; at: string }[] = [];
    for (const msg of messages) {
      const attachment = messageAttachment(msg);
      if (attachment) found.push({ key: String(msg.id), attachment, at: msg.created_at });
    }
    return found.reverse().slice(0, 12);
  }, [messages]);

  return (
    <div className="shrink-0 p-4" style={{ borderTop: "1px solid var(--border-glass)" }}>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-obs-faint">
        Mídia · Arquivos · Links{items.length > 0 ? ` · ${items.length}` : ""}
      </p>

      {items.length === 0 ? (
        <p className="mt-2 text-[10px] leading-relaxed text-obs-faint">
          Nenhum arquivo trocado nesta conversa ainda.
        </p>
      ) : (
        <div className="mt-2.5 grid grid-cols-3 gap-2">
          {items.map(({ key, attachment, at }) => {
            const label = attachment.filename
              || (attachment.kind === "audio" ? (attachment.voiceNote ? "Voz" : "Áudio") : null)
              || (attachment.kind === "image" ? "Imagem" : "Arquivo");
            const Icon = attachment.kind === "image" ? ImageIcon
              : attachment.kind === "video" ? FileVideo
              : attachment.kind === "audio" ? Radio
              : FileType;
            const body = attachment.kind === "image" && attachment.url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={attachment.url} alt={label} loading="lazy" className="h-full w-full object-cover" />
            ) : (
              <span className="flex h-full w-full flex-col items-center justify-center gap-1 px-1">
                <Icon size={16} className="text-obs-teal" />
                <span className="w-full truncate text-center text-[9px] text-obs-faint">{label}</span>
              </span>
            );
            const className = "h-16 overflow-hidden rounded-lg transition hover:opacity-80";
            const style = {
              border: "1px solid var(--border-glass)",
              background: "rgb(var(--obs-text) / 0.03)",
            } as const;
            return attachment.url ? (
              <a
                key={key}
                href={attachment.url}
                target="_blank"
                rel="noopener noreferrer"
                title={`${label} · ${formatTs(at)}`}
                className={className}
                style={style}
              >
                {body}
              </a>
            ) : (
              <div key={key} className={className} style={style} title="Baixando…">
                {body}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function MessageBubble({
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
  const attachment = messageAttachment(msg);
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
        {/* Media renders alongside the text, never instead of it: a photo sent
            with a caption used to lose the photo entirely. */}
        {attachment && (
          <div className={hasText ? "mb-1.5" : ""}>
            <MessageMedia attachment={attachment} />
          </div>
        )}
        {hasText && <p className="whitespace-pre-wrap break-words">{msg.texto}</p>}
        {!hasText && !attachment && (
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

function normalizeKnowledgeText(value?: string | null): string {
  return (value || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

// ── Knowledge expand state ───────────────────────────────────────────────────

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

// A aba mostra uma coisa só: o que o agente realmente usou para responder.
//
// Antes havia três renderizações — cards, `operator_context` e um despejo do
// grafo em catorze seções. As duas últimas eram inalcançáveis: o endpoint monta
// a resposta como `{...with_operator_context(ctx), ...turn}` e `turn` sempre
// traz `used_cards`, então o primeiro ramo sempre vencia. Catorze seções de
// produtos, campanhas, briefings, similaridade e assets nunca chegaram à tela.
//
// O bloco "Relacionados · não usados nesta resposta" também saiu: conhecimento
// que não entrou na decisão não é evidência, é ruído ao lado dela.
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
  const [selectedCard, setSelectedCard] = useState<ContextCard | null>(null);

  // Troca de lead ou de resposta fecha o detalhe aberto.
  useEffect(() => { setSelectedCard(null); }, [ctx?.response?.message_id]);

  if (!leadSelected) {
    return (
      <div className="flex h-full flex-col items-center justify-center p-4 text-center">
        <Boxes size={22} className="mb-2 text-obs-faint/40" />
        <p className="text-xs text-obs-faint">Selecione um lead para ver o conhecimento usado.</p>
      </div>
    );
  }
  if (loading && !ctx) {
    return <div className="p-4 text-xs text-obs-faint">Carregando conhecimento…</div>;
  }
  if (!ctx) return null;

  const used = [...(ctx.used_cards || [])].sort((a, b) => a.position - b.position);
  const decisive = new Set(ctx.decisive_node_ids || []);

  return (
    <div className="h-full overflow-y-auto p-3">
      {/* "espelho exato" x "evidência reconstruída" fica: é a diferença entre
          ver o que o agente usou e ver uma aproximação do que ele teria usado. */}
      <div className="mb-3 flex items-center justify-between gap-2 px-0.5">
        <span
          className={`rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase ${
            ctx.mode === "exact"
              ? "bg-emerald-500/15 text-emerald-400"
              : "bg-amber-500/15 text-amber-400"
          }`}
        >
          {ctx.mode === "exact" ? "espelho exato" : "evidência reconstruída"}
        </span>
        {ctx.response?.created_at && (
          <span className="text-[10px] text-obs-faint">{formatTs(ctx.response.created_at)}</span>
        )}
      </div>

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
      ) : (
        <p className="text-[11px] text-obs-faint">
          Nenhum card confirmado para esta resposta.
        </p>
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

// ── Page ──────────────────────────────────────────────────────────────────────────

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
  // PortalContext) — só a bottom nav mobile segue reservada, e com a
  // altura EXATA dela (pt-1.5 + min-h-12 + pb safe-area — os mesmos
  // números do <nav> em PortalContext.tsx), não um chute redondo tipo
  // "5rem": um orçamento generoso demais deixava um vão em branco entre o
  // composer e a bottom nav. `max()` dentro do `calc()` é a mesma conta que
  // o padding-bottom da nav já faz — se o valor real da safe-area mudar
  // (ex.: notch de outro aparelho), os dois lados casam sozinhos.
  // `heightClassName` continua sendo o escape hatch para quem ainda precisa
  // do orçamento antigo (ex.: banner de canal não conectado). dvh, não vh:
  // no iOS a barra de URL colapsando dentro de vh empurra o composer pra
  // baixo do chrome do navegador.
  const resolvedHeightClassName =
    heightClassName ||
    (isPortal
      ? "h-[calc(100dvh-3.375rem-max(0.4rem,env(safe-area-inset-bottom)))] lg:h-dvh"
      : "h-[calc(100dvh-6rem)]");
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
  const selectedOutcome = useMemo(
    () => normalizeJourneyOutcome(selectedLead?.journey_outcome),
    [selectedLead?.journey_outcome],
  );
  // O portal nao pode chamar `/agents/*`: o middleware de auth so libera
  // `/portal/*` para contas `client`, e a rota admin responde 403 antes de
  // chegar ao backend. A rota do portal ainda confirma que a lead pertence a
  // persona da URL, checagem que a de `/agents` nao faz.
  const recordJourneyEvent = useCallback<RecordJourneyEvent>(
    (leadRef, body) =>
      isPortal
        ? api.portalRecordJourneyEvent(portalSlug!, leadRef, body)
        : api.recordJourneyEvent(leadRef, body),
    [isPortal, portalSlug],
  );

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
  // No portal em modo single, um único painel ocupa a tela inteira por vez
  // — o "cartão flutuante" com margem/gradiente/cantos arredondados é uma
  // estética de admin (Obsidiana) que não faz sentido de app nativo aqui.
  // Desktop do portal e o admin inteiro continuam com o cartão de sempre.
  const mobileFullBleed = isPortal && layoutMode === "single";

  return (
    <div
      className={`messages-page flex ${resolvedHeightClassName} overflow-hidden ${mobileFullBleed ? "" : "rounded-xl p-3"}`}
      style={
        mobileFullBleed
          ? { background: "rgb(var(--obs-base))" }
          : {
              background:
                "radial-gradient(circle at 15% 10%, rgba(124,92,255,0.10), transparent 28%), radial-gradient(circle at 85% 20%, rgba(120,180,255,0.10), transparent 26%), rgb(var(--obs-deep))",
            }
      }
    >
      {/* ── Left: Leads list ───────────────────────────────────────────── */}
      {showList && (
      <aside
        className={`conversation-sidebar w-full lg:w-72 shrink-0 flex flex-col overflow-hidden ${mobileFullBleed ? "" : "rounded-l-xl"}`}
        style={
          mobileFullBleed
            ? { background: "rgb(var(--obs-base))" }
            : {
                border: "1px solid var(--border-glass)",
                background: "rgb(var(--glass-solid-bg) / var(--glass-solid-alpha))",
                backdropFilter: "blur(18px) saturate(130%)",
                WebkitBackdropFilter: "blur(18px) saturate(130%)",
                boxShadow: "var(--glass-shadow)",
              }
        }
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
            const outcome = normalizeJourneyOutcome(
              lead.journey_outcome ?? conv?.journey_outcome,
            );
            return (
              <button
                key={lead.id}
                onClick={() => openLead(lead)}
                className="w-full text-left px-4 py-3 flex flex-col gap-1 transition-colors"
                style={{
                  ...attentionRowStyle(attention, active),
                  borderBottom: "1px solid var(--border-glass-soft)",
                  // Cancelado sai de cena sem sumir: ainda é buscável e
                  // clicável, só para de competir por atenção.
                  ...(outcome === "cancelado" ? { opacity: 0.55 } : null),
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
                  {/* O desfecho toma o lugar do estágio nesta linha: 300px não
                      comportam os dois eixos. O estágio completo continua no
                      perfil do rail direito, onde há espaço para os dois. */}
                  {outcome ? <OutcomeMark outcome={outcome} /> : <StageBadge stage={lead.stage} />}
                  {lastTs && <span>{relativeTs(lastTs)}</span>}
                  {/* Score e sinais de qualificação saíram desta linha: são
                      vocabulário interno do scoring ("Primeiro contato",
                      "Descoberta ou listagem"), não algo que ajude a escolher
                      uma conversa. O score continua no perfil do rail. */}
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
        className={`message-panel relative flex-1 flex flex-col overflow-hidden min-w-0 ${mobileFullBleed ? "" : "rounded-xl"}`}
        style={
          mobileFullBleed
            ? { background: "rgb(var(--obs-base))" }
            : {
                background: "rgb(var(--glass-solid-bg) / var(--glass-solid-alpha))",
                border: "1px solid var(--border-glass)",
                backdropFilter: "blur(18px) saturate(130%)",
                WebkitBackdropFilter: "blur(18px) saturate(130%)",
                boxShadow: "var(--glass-shadow)",
              }
        }
      >
        {/* Chat header — duas linhas para caber em telas estreitas: a linha
            principal (voltar/avatar/nome/toggle de IA/conhecimento) nunca
            disputa espaço com os metadados secundários (estágio, telefone,
            interesse, contagem), que ficam numa segunda linha menor e podem
            quebrar livremente sem apertar os botões. */}
        <div
          className="flex flex-col gap-1 px-3 py-2 shrink-0"
          style={{ borderBottom: "1px solid var(--border-glass)", background: "rgb(var(--glass-solid-bg) / 0.58)" }}
        >
          <div className="flex items-center gap-2">
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
                <div className="flex flex-1 min-w-0 items-center gap-1.5">
                  <p className="text-sm font-semibold text-obs-text truncate">{chatName}</p>
                  {commercialNoteSummary(selectedLead.metadata?.commercial_note) && (
                    <span
                      className="shrink-0 text-obs-faint hover:text-obs-teal transition"
                      title={`Nota comercial\n${commercialNoteTitle(selectedLead.metadata?.commercial_note)}`}
                    >
                      <StickyNote size={12} />
                    </span>
                  )}
                </div>

                {/* Live indicator — só o ícone; o texto "live" foi removido
                    da leitura de relance e vive no title. */}
                {liveSync && (
                  <span className="shrink-0" title="Sincronização em tempo real ativa">
                    <Radio size={12} className="text-green-400 animate-pulse" />
                  </span>
                )}

                {/* Toggle de IA — rótulo de uma palavra só; o detalhe
                    completo (motivo do handoff etc.) permanece no title. */}
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
                  className={`flex items-center gap-1 text-[10px] font-semibold px-2 py-1 rounded-full shrink-0 border transition disabled:opacity-50 ${
                    selectedHandoffLevel === "full"
                      ? "border-red-400/60 bg-red-500/15 text-red-300 hover:bg-red-500/25"
                      : selectedHandoffLevel === "partial"
                      ? "border-amber-400/60 bg-amber-500/15 text-amber-300 hover:bg-amber-500/25"
                      : "border-emerald-400/50 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25"
                  }`}
                >
                  <span
                    className={`inline-block w-1.5 h-1.5 rounded-full ${
                      selectedHandoffLevel === "full"
                        ? "bg-red-400"
                        : selectedHandoffLevel === "partial"
                        ? "bg-amber-400"
                        : "bg-emerald-400"
                    }`}
                  />
                  {selectedHandoffLevel === "full" ? "Pausada" : selectedHandoffLevel === "partial" ? "Atenção" : "Ativa"}
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

          {selectedLead && (
            <div className="flex items-center gap-2 flex-wrap pl-[2.5rem]">
              {/* Um estado só: o desfecho do pedido quando existe, senão o
                  estágio do funil. Os dois juntos repetiam a mesma palavra —
                  "qualificado" aparecia duas vezes no mesmo header. */}
              {selectedOutcome
                ? <OutcomeMark outcome={selectedOutcome} />
                : <StageBadge stage={selectedLead.stage} />}
              {selectedLead.telefone && (
                <span className="text-[10px] text-obs-faint">{selectedLead.telefone}</span>
              )}
              {selectedLead.interesse_produto && (
                <span className="text-[10px] text-obs-subtle truncate max-w-[10rem]">
                  {selectedLead.interesse_produto}
                </span>
              )}
              <span className="text-[10px] text-obs-faint ml-auto">
                {messages.length} msgs
              </span>
            </div>
          )}

          {/* Notas comerciais em destaque. Antes viviam só num title=, que é
              invisível no toque e não aparece em leitor de tela como conteúdo:
              cada nota vira um chip legível, truncado por chip e não pela
              string inteira. */}
          {selectedLead && commercialNoteEntries(selectedLead.metadata?.commercial_note).length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 pl-[2.5rem]">
              {commercialNoteEntries(selectedLead.metadata?.commercial_note).slice(0, 3).map(([key, value]) => (
                <span
                  key={key}
                  className="inline-flex max-w-[13rem] items-baseline gap-1.5 rounded-full border px-2 py-0.5"
                  style={{ borderColor: "var(--border-glass)", background: "rgb(var(--obs-text) / 0.03)" }}
                >
                  <span className="shrink-0 text-[9px] uppercase tracking-wide text-obs-faint">
                    {key.replace(/_/g, " ")}
                  </span>
                  <span className="truncate text-[11px] font-medium text-obs-text">{value}</span>
                </span>
              ))}
              {commercialNoteEntries(selectedLead.metadata?.commercial_note).length > 3 && (
                <button
                  type="button"
                  onClick={() => setShowLeadInfo(true)}
                  className="text-[11px] font-medium text-obs-subtle transition hover:text-obs-text"
                >
                  +{commercialNoteEntries(selectedLead.metadata?.commercial_note).length - 3} notas
                </button>
              )}
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
          {/* Resumo do pedido — header do rail. Fica acima do perfil de
              propósito: é a única linha que responde "em que pé está este
              pedido?" sem rolar, inclusive com o rail em overlay. */}
          {/* Sempre presente quando há lead: a conversão é fato da lead e não
              depende de existir pedido aberto. */}
          {selectedLead && (
            <div
              className="shrink-0 px-4 py-3"
              style={{ borderBottom: "1px solid var(--border-glass)" }}
            >
              <div className="flex items-center gap-2">
                <p className="min-w-0 flex-1 truncate text-xs font-semibold text-obs-text">
                  {selectedLead.interesse_produto || "Pedido sem produto definido"}
                </p>
                <ToggleConversao
                  lead={selectedLead}
                  outcome={selectedOutcome}
                  canEdit={canEdit}
                  onRecorded={() => refreshSelectedLead(selectedLead.id)}
                  recordEvent={recordJourneyEvent}
                />
              </div>
            </div>
          )}

          {/* Contato — altura própria (não cresce).
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
                {/* O estágio saiu daqui: o toggle no topo do rail já responde
                    "em que pé está esta lead" e os dois diziam a mesma palavra.
                    O funil manual continua na lista e no Pipeline. */}
                <span className="rounded-full px-2 py-0.5 text-[10px] text-obs-faint" style={{ background: "rgb(var(--obs-text) / 0.05)" }}>
                  score {selectedLead.qualification_score || 0}%
                </span>
              </div>
              {/* Interesse e nota comercial saíram daqui: viraram o bloco
                  Pedido abaixo, onde cabem por inteiro em vez de truncados. */}
            </button>
          )}

          {/* Pedido + ações. As ações ficam logo abaixo das notas: o operador
              lê o que foi combinado e decide na mesma leitura. */}
          {selectedLead && (
            <div className="shrink-0" style={{ borderBottom: "1px solid var(--border-glass)" }}>
              <PedidoBlock lead={selectedLead} />
              <JourneyActions
                lead={selectedLead}
                outcome={selectedOutcome}
                canEdit={canEdit}
                onRecorded={() => refreshSelectedLead(selectedLead.id)}
                recordEvent={recordJourneyEvent}
              />
            </div>
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
            {/* Os `query_terms` saíram: são o insumo da busca de contexto, não
                o resultado. O que importa é o card que a resposta usou. */}
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

          {/* Mídia · Arquivos · Links — derivado das mensagens já carregadas,
              sem fetch extra. */}
          {selectedLead && <ConversationMediaRail messages={messages} />}
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
