# Qualification repair playbook

Use this after E2E evidence proves a flow defect. Keep changes generic and prefer the canonical n8n template plus existing backend contracts.

## Failure classes

- Duplicate after resume: correlate `lead_buffer.id`, `correlation_id` and `payload.conversation_commit`. Never automatically requeue a row with a commit.
- Stale graph: preserve customer facts for an unconfirmed appointment request and revalidate graph-bound service/required fields. Keep conservative handoff for transactional state that cannot be safely migrated.
- Historical service contamination: a current-turn service may replace history only when its slug exists in the current graph; then recalculate required fields.
- Stalled qualification: explicit intent to receive a graph service enters collection even without booking/quote keywords.
- Repeated question: reconcile through one additional model call before commit. The model must choose another useful unresolved topic or no question; a contextual bridge never permits reusing an id from `asked_question_node_ids`. If repair repeats it, hand off observably without publishing the question. Never force `appointment_policy.field_questions[missing_fields[0]]`.

## Boundaries

1. Do not add storage when `lead_buffer.payload.conversation_commit` already provides the idempotency ledger.
2. Do not branch on persona, customer, vehicle, service or campaign literals in production code.
3. The graph remains authority for published facts, commercial limits and completion policy. The model owns explanation, recommendation, language and the next natural question; proof validates cited evidence and persona/agent isolation, not a scripted FAQ choice.
4. A published appointment graph must define non-empty `required_fields` and a non-empty `field_questions` entry for every required field, including product-specific fields.
5. Do not invent a backend field-question fallback, deterministically select a FAQ, replace a valid model reply, or rebuild Product/Offer/Copy per turn.
6. Preserve CAS and the canonical one inbound -> one decision -> one commit -> at most one outbound invariant; exactly-once prevents duplicates and must not turn the dialogue into a fixed sequence.

## Verification

Run runtime, graph-validator (including top-down FAQ accumulation), workflow-template and resume-idempotency regressions; validate JSON; compile changed Python; inspect changed production files for commercial literals; then run the live Evolution E2E.
