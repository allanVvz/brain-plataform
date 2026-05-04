"use client";
import { use, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";

type SenderKind = "ai" | "human" | "client";

function senderKind(msg: any): SenderKind {
  const dir = (msg.direction || "").toLowerCase();
  const type = (msg.sender_type || "").toLowerCase();
  if (type === "human" || type === "operator" || type === "agent_human") return "human";
  if (
    type === "agent" ||
    type === "assistant" ||
    type === "ai" ||
    dir === "outbounding" ||
    dir === "outbound"
  ) {
    return "ai";
  }
  return "client";
}

function isOutbound(kind: SenderKind): boolean {
  return kind === "ai" || kind === "human";
}

function sortMessages(msgs: any[]): any[] {
  const byMessageId = new Map<string, any>();
  for (const msg of msgs) {
    const messageId = String(msg.message_id || "");
    if (messageId && !messageId.startsWith("ai_reply.")) {
      byMessageId.set(messageId, msg);
    }
  }

  return [...msgs].sort((a, b) => {
    const key = (msg: any) => {
      const messageId = String(msg.message_id || "");
      const ts = new Date(msg.created_at || 0).getTime() || 0;
      const id = Number(msg.id || 0);
      if (messageId.startsWith("ai_reply.")) {
        const base = byMessageId.get(messageId.slice("ai_reply.".length));
        if (base) {
          return [
            new Date(base.created_at || 0).getTime() || 0,
            Number(base.id || 0),
            1,
            ts,
            id,
          ];
        }
      }
      return [ts, id, 0, ts, id];
    };
    const ka = key(a);
    const kb = key(b);
    for (let i = 0; i < ka.length; i++) {
      if (ka[i] !== kb[i]) return ka[i] - kb[i];
    }
    return 0;
  });
}

function extractMediaUrl(metadata: any): string | null {
  if (!metadata) return null;
  if (typeof metadata === "string") {
    try { metadata = JSON.parse(metadata); } catch { return null; }
  }
  return metadata.media_url || metadata.image_url || metadata.file_url || metadata.url || null;
}

const BUBBLE_BY_KIND: Record<SenderKind, string> = {
  ai:     "bg-brain-accent/20 border border-brain-accent/30 text-white",
  human:  "bg-amber-500/15 border border-amber-400/40 text-amber-50",
  client: "bg-brain-surface border border-brain-border text-white",
};

export default function MessageTimelinePage({ params }: { params: Promise<{ leadId: string }> }) {
  const { leadId } = use(params);
  const [messages, setMessages] = useState<any[]>([]);
  const [logs, setLogs] = useState<any[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [lastStatus, setLastStatus] = useState<string | null>(null);
  const [lead, setLead] = useState<any>(null);
  const [pausing, setPausing] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const refresh = () => {
    api.messages(leadId).then((rows) => setMessages(sortMessages(rows))).catch(console.error);
    api.agentLogs(leadId, 20).then(setLogs).catch(console.error);
    api.lead(leadId).then(setLead).catch(() => setLead(null));
  };

  useEffect(() => { refresh(); }, [leadId]);

  const logsByTime = Object.fromEntries(
    logs.map((l) => [l.created_at?.slice(0, 19), l])
  );

  // Resolve numeric lead_ref from leadId. Path supports both the ref ("117")
  // and a name fallback. The reply box only enables when we have a numeric ref.
  const numericRef = (() => {
    const digits = (leadId || "").replace(/\D/g, "");
    if (!digits) return null;
    if (digits.length > 10) return null; // looks like a phone number, not a ref
    const n = Number(digits);
    return Number.isFinite(n) && n > 0 ? n : null;
  })();

  const canSend = numericRef !== null && draft.trim().length > 0 && !sending;

  const onSend = async () => {
    if (!canSend) return;
    setSending(true);
    setSendError(null);
    setLastStatus(null);
    try {
      const result = await api.sendMessage({
        lead_ref: numericRef!,
        texto: draft.trim(),
        nome: "Operador",
      });
      setLastStatus(
        result.status === "sent"
          ? "enviada via webhook"
          : result.status === "failed"
          ? `falha no webhook${result.webhook_error ? `: ${result.webhook_error}` : ""}`
          : result.status === "draft"
          ? "salva (sem webhook configurado)"
          : result.status,
      );
      setDraft("");
      refresh();
      setTimeout(() => textareaRef.current?.focus(), 50);
    } catch (e: any) {
      setSendError(e?.message || "erro ao enviar");
    } finally {
      setSending(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      onSend();
    }
  };

  const aiPaused = !!lead?.ai_paused;

  const togglePause = async () => {
    if (numericRef === null) return;
    setPausing(true);
    try {
      if (aiPaused) await api.resumeAi(numericRef);
      else await api.pauseAi(numericRef);
      refresh();
    } catch (e) {
      console.error(e);
    } finally {
      setPausing(false);
    }
  };

  return (
    <div className="max-w-2xl space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Timeline — {leadId}</h1>
        {numericRef !== null && (
          <button
            type="button"
            onClick={togglePause}
            disabled={pausing}
            className={`text-xs px-3 py-1 rounded-md border transition disabled:opacity-50 ${
              aiPaused
                ? "border-amber-400/50 bg-amber-500/15 text-amber-200 hover:bg-amber-500/25"
                : "border-brain-border bg-brain-surface text-brain-muted hover:text-white"
            }`}
            title={aiPaused ? "IA pausada — clique para retomar" : "IA ativa — clique para pausar"}
          >
            <span className={`inline-block w-1.5 h-1.5 rounded-full mr-2 ${aiPaused ? "bg-amber-400" : "bg-emerald-400"}`} />
            {aiPaused ? "IA pausada · humano respondendo" : "IA ativa"}
          </button>
        )}
      </div>

      <div className="space-y-3">
        {messages.map((msg) => {
          const kind = senderKind(msg);
          const out = isOutbound(kind);
          const log = logsByTime[msg.created_at?.slice(0, 19)];
          const mediaUrl = extractMediaUrl(msg.metadata);
          const hasText = (msg.texto || "").trim().length > 0;
          const senderLabel =
            kind === "human"
              ? msg.nome || msg.sender_id || "Operador"
              : kind === "ai"
              ? msg.agent_name || msg.sender_type || "IA"
              : msg.nome || "Cliente";

          return (
            <div key={msg.id || msg.message_id} className={`flex flex-col gap-1 ${out ? "items-end" : "items-start"}`}>
              <div className={`max-w-[80%] rounded-xl px-4 py-2.5 text-sm ${BUBBLE_BY_KIND[kind]}`}>
                <p className="text-xs font-medium mb-1 text-brain-muted flex items-center gap-1.5">
                  {kind === "human" && <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400" />}
                  {senderLabel}
                  {kind === "human" && <span className="text-amber-300/70">· humano</span>}
                </p>

                {hasText && <p className="whitespace-pre-wrap break-words">{msg.texto}</p>}

                {!hasText && mediaUrl && (
                  <a href={mediaUrl} target="_blank" rel="noopener noreferrer"
                    className="text-xs underline text-brain-accent">
                    Ver mídia
                  </a>
                )}

                {!hasText && !mediaUrl && (
                  <span className="text-xs italic text-brain-muted">
                    [sem conteúdo]
                  </span>
                )}
              </div>

              {log && kind === "ai" && (
                <div className="text-xs text-brain-muted space-y-0.5 px-1 text-right">
                  <p>Classificação: <span className="text-white">{log.input?.route_hint}</span></p>
                  <p>Agente: <span className="text-white">{log.agent_name}</span> · {log.latency_ms}ms</p>
                </div>
              )}

              <span className="text-xs text-brain-muted px-1">
                {msg.created_at
                  ? format(new Date(msg.created_at), "HH:mm · dd/MM/yyyy", { locale: ptBR })
                  : ""}
              </span>
            </div>
          );
        })}

        {messages.length === 0 && (
          <p className="text-brain-muted text-sm">Nenhuma mensagem encontrada.</p>
        )}
      </div>

      {/* Reply box */}
      <div className="sticky bottom-0 pt-4 pb-2 bg-gradient-to-t from-brain-bg via-brain-bg to-transparent">
        <div className="rounded-xl border border-brain-border bg-brain-surface p-3 space-y-2">
          {numericRef === null && (
            <p className="text-xs text-amber-300/80">
              Esta conversa não tem lead_ref numérico — abra pela aba Mensagens via lead_ref para responder.
            </p>
          )}
          <textarea
            ref={textareaRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Digite uma resposta como operador… (Ctrl+Enter envia)"
            rows={3}
            disabled={numericRef === null || sending}
            className="w-full bg-transparent text-sm text-white placeholder:text-brain-muted resize-none focus:outline-none disabled:opacity-50"
          />
          <div className="flex items-center justify-between gap-2">
            <div className="text-xs text-brain-muted">
              {sendError && <span className="text-red-400">erro: {sendError}</span>}
              {!sendError && lastStatus && <span>último envio: {lastStatus}</span>}
              {!sendError && !lastStatus && <span>insere no banco + dispara webhook do agente</span>}
            </div>
            <button
              type="button"
              onClick={onSend}
              disabled={!canSend}
              className="px-4 py-1.5 rounded-md text-sm font-medium bg-amber-500/80 hover:bg-amber-400 text-brain-bg disabled:opacity-40 disabled:cursor-not-allowed transition"
            >
              {sending ? "enviando…" : "enviar"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
