import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

import { auditBrowserTurn, matchPublishedQuestion } from "./wa-validator-driver.mjs";
import { assessRepetition } from "./conversation-repetition.mjs";


const questions = {
  "q:name": { field_key: "name", text: "Qual é o seu nome?" },
  "q:goal": { field_key: "goal", text: "Qual é o seu objetivo?" },
};


test("maps the actual published question instead of advancing a fixed list", () => {
  const match = matchPublishedQuestion(
    "Entendi. Qual é o seu objetivo?",
    questions,
  );
  assert.equal(match?.fieldKey, "goal");
});


test("stops when the reply does not map to a published question", () => {
  const audit = auditBrowserTurn({
    reply: "Conte um pouco mais.",
    questions,
    knownFactKeys: new Set(),
    requiredFields: ["name", "goal"],
    recentReplies: [],
    step: {},
  });
  assert.equal(audit.passed, false);
  assert.ok(audit.failures.includes("question_matches_published_graph"));
});


test("rejects a question for a fact already sent", () => {
  const audit = auditBrowserTurn({
    reply: "Qual é o seu nome?",
    questions,
    knownFactKeys: new Set(["name"]),
    requiredFields: ["name", "goal"],
    recentReplies: [],
    step: {},
  });
  assert.equal(audit.passed, false);
  assert.ok(audit.failures.includes("known_fact_not_reasked"));
});


test("rejects substantial reply repetition", () => {
  const reply = "Entendi. Qual é o seu objetivo?";
  const audit = auditBrowserTurn({
    reply,
    questions,
    knownFactKeys: new Set(),
    requiredFields: ["name", "goal"],
    recentReplies: [reply],
    step: {},
  });
  assert.equal(audit.passed, false);
  assert.ok(audit.failures.includes("reply_not_repeated"));
});


test("requires a doubt answer before the next qualification question", () => {
  const audit = auditBrowserTurn({
    reply: "Qual é o seu nome? Respondemos sua dúvida depois.",
    questions,
    knownFactKeys: new Set(),
    requiredFields: ["name", "goal"],
    recentReplies: [],
    step: { kind: "doubt" },
  });
  assert.equal(audit.passed, false);
  assert.ok(audit.failures.includes("doubt_answered_before_question"));
});


test("completion requires every graph field to have been sent", () => {
  const audit = auditBrowserTurn({
    reply: "Certo, vou encaminhar para a equipe.",
    questions,
    knownFactKeys: new Set(["name", "goal"]),
    requiredFields: ["name", "goal"],
    recentReplies: [],
    step: {},
  });
  assert.equal(audit.passed, true);
  assert.equal(audit.qualificationComplete, true);
});


test("shared anti-repetition corpus matches the backend verdicts", () => {
  const corpusUrl = new URL("../../tests/fixtures/conversation_repetition_cases.json", import.meta.url);
  const cases = JSON.parse(fs.readFileSync(corpusUrl, "utf8"));
  for (const item of cases) {
    const result = assessRepetition({
      currentReply: item.current_reply,
      recentReplies: item.previous_replies || [],
      questionNodeId: item.question_node_id,
      questionText: item.question_text,
      askedQuestionNodeIds: item.asked_question_node_ids || [],
      maxAttempts: item.max_attempts || 0,
      fieldPending: Boolean(item.field_pending),
      terminalIntent: item.terminal_intent,
      previousTerminalIntent: item.previous_terminal_intent,
    });
    assert.deepEqual(result.failures, item.expected_failures, item.name);
  }
});
