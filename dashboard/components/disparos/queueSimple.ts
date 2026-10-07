// The queue in four words — pausada, agendada, gerar preview, enviar.
//
// The single place that turns the database projection (queue_state + message
// status) into what an operator sees and can click. Each button calls one of
// the existing /messaging/queue/<endpoint> actions.

export type SimpleState = "pausada" | "agendada" | "preview" | "sem_preview" | "enviada";
export type SimpleActionKey = "pausar" | "retomar" | "gerar_preview" | "enviar";
export type QueueEndpoint =
  | "pause" | "resume" | "reprocess" | "send-preview" | "reactivate" | "regenerate-preview" | "operator-preview";

export type SimpleAction = { key: SimpleActionKey; endpoint: QueueEndpoint; enabled: boolean; reason?: string | null };

export type QueueMessageLike = { status?: string | null; can_send?: boolean; send_reason?: string | null };

const PENDING = new Set(["buffered", "pending_send", "awaiting_proof", "retry", "processing"]);
const SENT = new Set(["sent", "delivered", "read"]);
const PREVIEW_ENDPOINT: Record<string, QueueEndpoint> = {
  technical_failure: "reprocess",
  blocked: "operator-preview",
  awaiting_customer: "reactivate",
  preview_ready: "regenerate-preview",
};

const action = (key: SimpleActionKey, endpoint: QueueEndpoint, enabled = true, reason?: string | null): SimpleAction =>
  ({ key, endpoint, enabled, reason: enabled ? null : reason ?? null });

export function simplifyMessage(queueState: string | null | undefined, message: QueueMessageLike): { state: SimpleState; actions: SimpleAction[] } {
  const demand = queueState || "";
  const status = message.status || "";
  if (demand === "paused" && (PENDING.has(status) || status === "preview_ready")) {
    return { state: "pausada", actions: [action("retomar", "resume")] };
  }
  if (status === "preview_ready") {
    return {
      state: "preview",
      actions: [
        action("enviar", "send-preview", Boolean(message.can_send), message.send_reason || "Mensagem não está pronta para envio"),
        action("gerar_preview", "regenerate-preview"),
        action("pausar", "pause"),
      ],
    };
  }
  if (PENDING.has(status)) return { state: "agendada", actions: [action("pausar", "pause")] };
  if (SENT.has(status)) {
    return { state: "enviada", actions: demand === "awaiting_customer" ? [action("gerar_preview", "reactivate")] : [] };
  }
  const endpoint = PREVIEW_ENDPOINT[demand];
  return { state: "sem_preview", actions: endpoint ? [action("gerar_preview", endpoint)] : [] };
}

export const STATE_LABEL: Record<SimpleState, string> = {
  pausada: "Pausada",
  agendada: "Agendada",
  preview: "Preview pronto",
  sem_preview: "Sem preview",
  enviada: "Enviada",
};

export const ACTION_LABEL: Record<SimpleActionKey, string> = {
  pausar: "Pausar",
  retomar: "Retomar",
  gerar_preview: "Gerar preview",
  enviar: "Enviar",
};
