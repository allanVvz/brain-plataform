export function foldText(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

export function tokenSimilarity(left, right) {
  const a = new Set(foldText(left).split(/\s+/).filter(Boolean));
  const b = new Set(foldText(right).split(/\s+/).filter(Boolean));
  if (a.size === 0 || b.size === 0) return 0;
  const overlap = [...a].filter((token) => b.has(token)).length;
  return overlap / Math.max(a.size, b.size);
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
  step,
}) {
  const repeated = recentReplies.some(
    (previous) =>
      foldText(previous) === foldText(reply)
      || tokenSimilarity(previous, reply) >= 0.92,
  );
  const matchedQuestion = matchPublishedQuestion(reply, questions);
  const allRequiredKnown = requiredFields.every((field) => knownFactKeys.has(String(field)));
  const knownFactReasked = Boolean(
    matchedQuestion && knownFactKeys.has(matchedQuestion.fieldKey),
  );
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
    reply_not_repeated: !repeated,
    question_matches_published_graph: Boolean(matchedQuestion) || allRequiredKnown,
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
    qualificationComplete: !matchedQuestion && allRequiredKnown,
  };
}
