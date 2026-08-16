export type ConversationSummaryLike = {
  lead_ref?: number | null;
  lead_id?: string | null;
};

function normalizeStageValue(stage: string | null | undefined) {
  return (stage || "novo").toLowerCase().trim() || "novo";
}

function normalizePhoneValue(value: string | null | undefined) {
  return String(value || "").replace(/\D/g, "");
}

export function buildConversationLeadIndex(conversations: ConversationSummaryLike[]) {
  const ids = new Set<number>();
  const phones = new Set<string>();
  for (const conversation of conversations || []) {
    if (typeof conversation.lead_ref === "number") {
      ids.add(conversation.lead_ref);
    }
    const phone = normalizePhoneValue(conversation.lead_id);
    if (phone) {
      phones.add(phone);
    }
  }
  return { ids, phones };
}

export function leadHasStartedConversation(
  lead: any,
  conversationIndex?: { ids: Set<number>; phones: Set<string> },
) {
  const stage = normalizeStageValue(lead?.stage);
  const phone = normalizePhoneValue(lead?.lead_id || lead?.telefone);
  if (conversationIndex?.ids?.has(Number(lead?.id))) return true;
  if (phone && conversationIndex?.phones?.has(phone)) return true;
  if (stage !== "novo") return true;
  if ((lead?.ultima_mensagem || "").trim()) return true;
  return false;
}

export function summarizeLeadLifecycle(
  leads: any[],
  conversations: ConversationSummaryLike[] = [],
) {
  const conversationIndex = buildConversationLeadIndex(conversations);
  let mapped = 0;
  let started = 0;

  for (const lead of leads || []) {
    if (leadHasStartedConversation(lead, conversationIndex)) {
      started += 1;
    } else {
      mapped += 1;
    }
  }

  return {
    total: (leads || []).length,
    started,
    mapped,
    conversationIndex,
  };
}

export function normalizeLeadStage(stage: string | null | undefined) {
  return normalizeStageValue(stage);
}

// ── Desfecho comercial da jornada ────────────────────────────────────────────
// Eixo independente do `stage`: o estágio é o funil manual (novo → contatado →
// … → fechado/perdido) e continua sendo editado por humano no pipeline. O
// desfecho vem de conversation_journeys e é derivado no backend por
// api/services/journey_outcome.py — o frontend só normaliza e pinta, nunca
// recalcula. Um lead pode estar `qualificado` no funil e `convertido` na
// jornada ao mesmo tempo; os dois valores são verdadeiros.

export const JOURNEY_OUTCOMES = [
  "qualificado",
  "convertido",
  "vendido",
  "entregue",
  "cancelado",
] as const;

export type JourneyOutcome = (typeof JOURNEY_OUTCOMES)[number];

const OUTCOME_SET = new Set<string>(JOURNEY_OUTCOMES);

export function normalizeJourneyOutcome(value: unknown): JourneyOutcome | null {
  const normalized = String(value ?? "").toLowerCase().trim();
  return OUTCOME_SET.has(normalized) ? (normalized as JourneyOutcome) : null;
}

// Uma jornada fechada não aceita evento novo: o pedido acabou e o próximo
// inbound abre a jornada seguinte.
export function isJourneySettled(outcome: JourneyOutcome | null) {
  return outcome === "entregue" || outcome === "cancelado";
}
