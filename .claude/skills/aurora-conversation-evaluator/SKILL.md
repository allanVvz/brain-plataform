---
name: aurora-conversation-evaluator
description: Evaluate an Aurora WhatsApp conversation transcript (or a batch of conversation_turn_proofs) for naturalness, progression, repetition, context use, flexible field collection, and handoff correctness — without requiring a fixed order of fields. Use when reviewing real or test Aurora transcripts, debugging a reported "feels robotic" complaint, or checking a prompt change actually improved behavior.
---

# Aurora — Conversation Quality Evaluator

Evaluates whether an Aurora conversation *feels* like a real consultative
SDR, not just whether it's technically valid. `graph_proof_checker_v3`
already enforces structural correctness (contract compliance, evidence,
handoff timing) — this skill is for the layer above that: does the
conversation read naturally to a human customer?

Read `references/criterios-de-qualidade.md` for the rubric before evaluating
anything — it's grounded in Aurora's actual published flow rules
(`aurora-flow-management`, `aurora-tone`) and the `SYSTEM_PROMPT` in
`graph_agent_runtime_v3.py`, not generic chatbot QA advice.

Read `references/cenarios-e2e.md` for real production incidents already
diagnosed this session — use them as calibration examples (what a failure
actually looks like in the data) and as regression scenarios when verifying
a fix.

## How to evaluate a transcript

1. Get the turn-by-turn data. For a real lead, query
   `conversation_turn_proofs` (join `conversation_ledgers` on `lead_ref`) —
   `model_proposal`, `proof_result`, and `retrieval_trace` per turn tell you
   far more than the `messages` table alone (which only has the final
   text). For a hypothetical/test transcript, the same fields from a
   `decide()` call work.
2. Score against each criterion in `criterios-de-qualidade.md`
   independently — a conversation can nail repetition avoidance while still
   failing on flexible field collection, or vice versa.
3. **Never require a fixed field order.** Aurora's contract declares
   required fields, but a real customer volunteers them in any order or
   several at once — flag a conversation as broken only if a field the
   customer *already gave* gets re-asked, not if the agent asks fields in a
   different order than some canonical list.
4. When a turn looks wrong, check `proof_result.model_proposal_errors` and
   `proof_result.mode` before guessing why — `mode: "published_fallback"`
   with a non-empty `model_proposal_errors` array means the model's real
   proposal was rejected and the reply is the raw fallback text, not a
   genuine model response. That distinction changes the diagnosis
   completely (compare `exemplos-de-conversas.md` in the sibling
   `aurora-premium-sdr` skill).
