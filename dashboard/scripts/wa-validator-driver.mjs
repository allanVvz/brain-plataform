import {
  assessRepetition,
  normalizeText,
  tokenOverlap,
} from "./conversation-repetition.mjs";

export const foldText = normalizeText;

export function tokenSimilarity(left, right) {
  return tokenOverlap(left, right);
}

export function matchPublishedQuestion(reply, questions) {
  const foldedReply = foldText(reply);
  const matches = Object.entries(questions || {})
    .map(([questionId, question]) => {
      const text = String(question?.text || "").trim();
      const foldedQuestion = foldText(text);
      const exact = Boolean(foldedQuestion && foldedReply.includes(foldedQuestion));
      return {
        questionId,
        fieldKey: String(question?.field_key || ""),
        text,
        score: exact ? 1 : tokenSimilarity(reply, text),
      };
    })
    .filter((item) => item.fieldKey && item.text)
    .sort((left, right) => right.score - left.score);
  if (!matches[0] || matches[0].score < 0.72) return null;
  if (matches[1] && matches[1].score === matches[0].score) return null;
  return matches[0];
}

export function auditBrowserTurn({
  reply,
  questions,
  knownFactKeys,
  requiredFields,
  recentReplies,
  askedQuestionNodeIds = [],
  maxAttempts = 0,
  unknownFactKeys = new Set(),
  previousTerminalIntent = null,
  step,
}) {
  const matchedQuestion = matchPublishedQuestion(reply, questions);
  const allRequiredKnown = requiredFields.every((field) => knownFactKeys.has(String(field)));
  const allRequiredResolved = requiredFields.every(
    (field) => knownFactKeys.has(String(field)) || unknownFactKeys.has(String(field)),
  );
  const knownFactReasked = Boolean(
    matchedQuestion && knownFactKeys.has(matchedQuestion.fieldKey),
  );
  const terminalIntent = !matchedQuestion && allRequiredResolved
    ? (allRequiredKnown ? "qualification_complete" : "qualification_incomplete")
    : null;
  const repetition = assessRepetition({
    currentReply: reply,
    recentReplies,
    questionNodeId: matchedQuestion?.questionId,
    questionText: matchedQuestion?.text,
    askedQuestionNodeIds,
    maxAttempts,
    fieldPending: Boolean(
      matchedQuestion && !knownFactKeys.has(matchedQuestion.fieldKey)
      && !unknownFactKeys.has(matchedQuestion.fieldKey)
    ),
    terminalIntent,
    previousTerminalIntent,
  });
  const repetitionFailures = new Set(repetition.failures);
  let doubtAnsweredFirst = true;
  if (step?.kind === "doubt") {
    const segments = String(reply || "").match(/[^.!?]+[.!?]?/g) || [];
    const questionSegmentIndex = matchedQuestion
      ? segments.findIndex(
          (segment) => tokenSimilarity(segment, matchedQuestion.text) >= 0.72,
        )
      : -1;
    doubtAnsweredFirst = questionSegmentIndex > 0 && segments
      .slice(0, questionSegmentIndex)
      .some(
        (segment) =>
          !segment.includes("?")
          && segment.trim().split(/\s+/).filter(Boolean).length >= 3,
      );
  }
  const criteria = {
    reply_not_repeated: !repetitionFailures.has("semantic_repetition")
      && !repetitionFailures.has("terminal_repetition"),
    question_repetition_budget: !repetitionFailures.has("question_already_asked"),
    contextual_retry_valid: !repetitionFailures.has("question_already_asked")
      && !repetitionFailures.has("question_field_not_pending"),
    terminal_not_repeated: !repetitionFailures.has("terminal_repetition"),
    question_matches_published_graph: Boolean(matchedQuestion) || allRequiredResolved,
    known_fact_not_reasked: !knownFactReasked,
    doubt_answered_before_question: doubtAnsweredFirst,
  };
  const failures = Object.entries(criteria)
    .filter(([, passed]) => !passed)
    .map(([name]) => name);
  return {
    passed: failures.length === 0,
    failures,
    criteria,
    matchedQuestion,
    repetition,
    qualificationComplete: !matchedQuestion && allRequiredKnown,
    qualificationTerminal: !matchedQuestion && allRequiredResolved,
    terminalIntent,
  };
}
