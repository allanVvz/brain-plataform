export const REPETITION_THRESHOLD = 0.92;
export const QUESTION_PARAPHRASE_THRESHOLD = 0.80;
export const QUESTION_SUFFIX_MIN_RATIO = 0.60;

const EMPTY_BRIDGE_TOKENS = new Set([
  "ah", "beleza", "bom", "certo", "claro", "entao", "entendi", "legal",
  "ok", "otimo", "perfeito", "sim", "ta", "tudo", "vamos",
]);

export function normalizeText(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

export function sequentialSimilarity(left, right) {
  let a = normalizeText(left);
  let b = normalizeText(right);
  if (!a || !b) return a === b ? 1 : 0;
  if (a === b) return 1;
  if (a.length < b.length) [a, b] = [b, a];
  let previous = Array.from({ length: b.length + 1 }, (_, index) => index);
  for (let row = 1; row <= a.length; row += 1) {
    const current = [row];
    for (let column = 1; column <= b.length; column += 1) {
      current.push(Math.min(
        current[column - 1] + 1,
        previous[column] + 1,
        previous[column - 1] + (a[row - 1] === b[column - 1] ? 0 : 1),
      ));
    }
    previous = current;
  }
  return 1 - previous.at(-1) / Math.max(a.length, b.length);
}

export function tokenOverlap(left, right) {
  const a = new Set(normalizeText(left).split(/\s+/).filter(Boolean));
  const b = new Set(normalizeText(right).split(/\s+/).filter(Boolean));
  if (a.size === 0 || b.size === 0) return 0;
  const overlap = [...a].filter((token) => b.has(token)).length;
  return overlap / Math.max(a.size, b.size);
}

export function semanticSimilarity(left, right) {
  return Math.max(sequentialSimilarity(left, right), tokenOverlap(left, right));
}

export function isSemanticRepetition(left, right) {
  const a = normalizeText(left);
  const b = normalizeText(right);
  return Boolean(a && b && (a === b || semanticSimilarity(a, b) >= REPETITION_THRESHOLD));
}

function contextualBridge(reply, questionText) {
  const foldedReply = normalizeText(reply);
  const foldedQuestion = normalizeText(questionText);
  if (!foldedReply || !foldedQuestion) return "";
  const offset = foldedReply.lastIndexOf(foldedQuestion);
  if (offset >= 0) return foldedReply.slice(0, offset).trim();

  // Mirror the backend: a close paraphrase of the graph-owned question can
  // still have an auditable bridge, but a bare paraphrase cannot manufacture
  // one because only the prefix before the best-matching suffix is returned.
  const replyTokens = foldedReply.split(/\s+/).filter(Boolean);
  const questionTokens = foldedQuestion.split(/\s+/).filter(Boolean);
  const minimumSuffix = Math.max(
    3,
    Math.floor(questionTokens.length * QUESTION_SUFFIX_MIN_RATIO),
  );
  let bestOffset = -1;
  let bestScore = 0;
  for (let tokenOffset = 0; tokenOffset < replyTokens.length; tokenOffset += 1) {
    const suffixTokens = replyTokens.slice(tokenOffset);
    if (suffixTokens.length < minimumSuffix) break;
    const score = semanticSimilarity(suffixTokens.join(" "), foldedQuestion);
    if (score > bestScore) {
      bestScore = score;
      bestOffset = tokenOffset;
    }
  }
  if (bestOffset < 0 || bestScore < QUESTION_PARAPHRASE_THRESHOLD) return "";
  return replyTokens.slice(0, bestOffset).join(" ").trim();
}

export function hasSubstantiveContextualBridge(reply, questionText) {
  const substantive = contextualBridge(reply, questionText)
    .split(/\s+/)
    .filter((token) => token.length > 1 && !EMPTY_BRIDGE_TOKENS.has(token));
  return substantive.length >= 2;
}

export function assessRepetition({
  currentReply,
  recentReplies = [],
  questionNodeId = null,
  questionText = null,
  askedQuestionNodeIds = [],
  maxAttempts = 0,
  fieldPending = false,
  terminalIntent = null,
  previousTerminalIntent = null,
}) {
  const normalizedMax = [0, 1].includes(maxAttempts) ? maxAttempts : 0;
  const previous = recentReplies.map((value) => String(value || "")).filter((value) => value.trim());
  const semanticMatchIndexes = previous
    .map((value, index) => (isSemanticRepetition(value, currentReply) ? index : -1))
    .filter((index) => index >= 0);
  const failures = [];
  if (semanticMatchIndexes.length) failures.push("semantic_repetition");

  const previousQuestionEmissions = questionNodeId
    ? askedQuestionNodeIds.map(String).filter((value) => value === String(questionNodeId)).length
    : 0;
  if (questionNodeId && previousQuestionEmissions > 0) {
    if (previousQuestionEmissions >= 1 + normalizedMax) {
      failures.push("question_attempt_budget_exceeded");
    }
    if (!fieldPending) failures.push("question_field_not_pending");
    if (!hasSubstantiveContextualBridge(currentReply, questionText)) {
      failures.push("contextual_bridge_required");
    }
  }
  if (terminalIntent && terminalIntent === previousTerminalIntent) {
    failures.push("terminal_repetition");
  }
  const uniqueFailures = [...new Set(failures)];
  return {
    passed: uniqueFailures.length === 0,
    failures: uniqueFailures,
    normalizedReply: normalizeText(currentReply),
    semanticMatchIndexes,
    similarities: previous.map((value) => semanticSimilarity(value, currentReply)),
    questionNodeId,
    previousQuestionEmissions,
    allowedQuestionEmissions: 1 + normalizedMax,
    contextualBridge: contextualBridge(currentReply, questionText),
    terminalIntent,
  };
}
