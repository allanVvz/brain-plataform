/** Pure helpers for the Sofia FAQ generation panel (kept out of the component for testing). */

export const DEFAULT_FAQ_COUNT = 5;
export const MAX_FAQ_COUNT = 20;

export type FaqSuggestion = { question: string; answer: string; accepted: boolean };

export function clampFaqCount(value: unknown): number {
  const n = Number(value);
  if (!Number.isFinite(n) || n < 1) return DEFAULT_FAQ_COUNT;
  return Math.min(Math.floor(n), MAX_FAQ_COUNT);
}

/** Default quantity for a node: its saved faq_generation_count, else DEFAULT. */
export function defaultFaqCount(node: any): number {
  const meta = node?.data?.metadata ?? node?.metadata ?? {};
  const saved = meta?.faq_generation_count;
  return saved ? clampFaqCount(saved) : DEFAULT_FAQ_COUNT;
}

/** Turn raw {question,answer} suggestions into editable rows, accepted by default. */
export function toEditableSuggestions(raw: Array<{ question?: string; answer?: string }> | null | undefined): FaqSuggestion[] {
  return (raw || []).map((s) => ({
    question: String(s?.question || ""),
    answer: String(s?.answer || ""),
    accepted: true,
  }));
}

/** Only accepted, non-empty suggestions are persisted. */
export function acceptedPayload(list: FaqSuggestion[]): Array<{ question: string; answer: string }> {
  return (list || [])
    .filter((s) => s.accepted && s.question.trim())
    .map((s) => ({ question: s.question.trim(), answer: s.answer.trim() }));
}
