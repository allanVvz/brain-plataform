# Qualification repair playbook

Use this after E2E evidence proves a flow defect. Keep changes generic and prefer the canonical n8n template plus existing backend contracts.

## Failure classes

- Duplicate after resume: correlate `lead_buffer.id`, `correlation_id` and `payload.conversation_commit`. Never automatically requeue a row with a commit.
- Stale graph: preserve customer facts for an unconfirmed appointment request and revalidate graph-bound service/required fields. Keep conservative handoff for transactional state that cannot be safely migrated.
- Historical service contamination: a current-turn service may replace history only when its slug exists in the current graph; then recalculate required fields.
- Stalled qualification: explicit intent to receive a graph service enters collection even without booking/quote keywords.
- Repeated question: reconcile model extraction through `/internal/conversations/decide` before commit and use `appointment_policy.field_questions[missing_fields[0]]`.

## Boundaries

1. Do not add storage when `lead_buffer.payload.conversation_commit` already provides the idempotency ledger.
2. Do not branch on persona, customer, vehicle, service or campaign literals in production code.
3. Model extraction is observation, never authority over policy or confirmation.
4. A published appointment graph must define non-empty `required_fields` and a non-empty `field_questions` entry for every required field, including product-specific fields.
5. Do not invent a backend field-question fallback.

## Verification

Run runtime, graph-validator, workflow-template and resume-idempotency regressions; validate JSON; compile changed Python; inspect changed production files for commercial literals; then run the live Evolution E2E.
