---
name: brain-agent-e2e
description: Validate Brain AI conversational agents end to end through the dashboard, Playwright-compatible browser automation, Evolution transport, n8n workflows, backend runtime, graph context, qualification, pause/resume and human handoff. Use for remote or local tests of `/messages`, WhatsApp/Evolution delivery, agent qualification loops, n8n conversation templates, duplicate responses, stale graph state, incorrect context, or changes affecting messages, workers, bindings, agent decisions and conversation logs.
---

# Brain Agent E2E

Validate the real path `operator -> Evolution -> target persona -> agent -> Evolution -> operator`. Treat persisted destination messages and runtime decisions as evidence; never treat a provider `sent` flag alone as delivery proof.

## Load task references

- Read [references/n8n-template-contract.md](references/n8n-template-contract.md) whenever n8n, backend behavior, provisioning or cross-persona reuse is in scope.
- Read [references/evidence-report.md](references/evidence-report.md) before executing a live E2E or writing its report.
- Read [references/qualification-repair.md](references/qualification-repair.md) when the E2E exposes stale graph state, a service switch, a stalled field or duplicate processing after resume.
- Read [references/browser-mechanics.md](references/browser-mechanics.md) before driving the dashboard through claude-in-chrome or Playwright — it covers the shared-tenant-selector gotcha, the reliable JS-based persona switch, fact polling via `/api-brain/leads/{id}`, and the send-button-over-Ctrl+Enter workaround. Read it first; it prevents re-deriving these mechanics turn by turn.

## Establish the test contract

1. Identify target persona/agent, transport persona, both conversations, a graph-keyed customer fact profile and the expected terminal handoff. The profile is a pool of values, not an ordered list of messages.
2. Confirm the pair with channel/binding, masked phone or technical IDs, recent messages and timestamps. Do not rely on equal display names; one channel can show different local lead names.
3. Record initial AI state, lead reference, last message, binding/provider and graph version/checksum when available.
4. Keep the transport-side agent paused for the whole run. Activate the target agent only after the transport side is confirmed paused.
5. Preserve history, bindings, providers and nodes. Do not delete messages, move leads or reconnect channels.

## Drive the browser

Use the repository Playwright installation or another Playwright-compatible browser controller. Prefer an isolated persistent session and manual login. Keep the visible authenticated browser attached to automation.

The dashboard's `CLIENTE` persona selector is shared state across every tab in the same profile, not scoped per tab — a second tab does not stay pinned to a second persona. Re-assert the correct persona on the active tab immediately before every read or send; see [references/browser-mechanics.md](references/browser-mechanics.md) for the reliable JS-based switch (coordinate clicks on the native dropdown are unreliable).

Before the first mutation:

1. Clear or timestamp console, page-error and network capture.
2. Capture the initial screenshot.
3. Read the UI and the same authenticated APIs already used by the page when the UI hides required technical details.
4. Mask phone numbers and never record cookies, tokens, auth headers or response bodies containing secrets.

For every turn:

1. Read the latest target-agent question and identify the real requested field or customer intent from the published graph.
2. If the customer message contains a doubt or interruption, require the agent to answer it before resuming qualification.
3. Extract and verify every fact present in the customer message, not only the field the previous turn expected.
4. Require a natural acknowledgement of the received content before the next graph question.
5. Require a natural next question that respects published facts, limits and unresolved qualification needs. `missing_fields` is a completion signal, not a forced dialogue order; do not require `missing_fields[0]` or an exact FAQ script.
6. Stop before sending when the response cites a commercial fact/limit that cannot be mapped to published evidence, or crosses persona/agent scope.
7. Stop when a persisted fact is asked again or the reply substantially repeats any recent agent reply.
8. Send exactly once from the paused transport-side conversation. Do not volunteer price, date or time.
9. Record the send timestamp and HTTP status.
10. Prove exactly one transport outbound and one target inbound with IDs, directions and timestamps.
11. Confirm the target AI state. If paused by a legitimate handoff, inspect logs before resuming.
12. Wait up to 120 seconds for exactly one target outbound.
13. Prove exactly one corresponding inbound on the transport side.
14. Continue until required fields are persisted and the expected human handoff occurs.

Keep two independent verdicts:

- `technical_pass`: canonical inbound, one decision, one valid proof, at most one proof-gated outbound, atomic commit and token budget.
- `quality_pass`: every semantic turn criterion above passed; the model's explanation, recommendation and natural next question remained grounded in the published graph without becoming a fixed script.

A run may have `technical_pass=true` and `quality_pass=false`. A fixed-sequence or browser-only run without ledger/fact/proof evidence is `technical_only` or `browser_dynamic_dialogue`; it is never conversational-quality evidence by itself.

Do not automatically repeat a message with ambiguous delivery. A user-authorized resend is still forbidden once the destination copy or an agent response appears.

## Diagnose before recovery

Open `/logs`, select `Chat e agentes`, scope the target persona and correlate by `lead_ref`, message ID, external message ID and correlation ID.

Inspect:

- `decision.intent`, `route`, `handoff_reason` and `evidence_node_ids`;
- graph version/checksum versus the conversation's previous version/checksum;
- `response.extracted_fields`, `identified_service_slug`, `missing_fields` and `conversation_state`;
- qualification stage/score/signals;
- inbound and outbound correlation IDs;
- duplicate commits or multiple decisions for one canonical inbound.

Allow one safe resume only when the transport agent remains paused and logs explain the handoff. After resume, verify that the pending inbound is claimed once.

## Stop conditions

Stop all new sends immediately when any condition occurs:

- channel disconnected or pair uncertain;
- more than one destination inbound for one send;
- more than one agent decision or outbound for one inbound;
- transport-side agent responds automatically;
- target response uses the wrong persona/service/history;
- the reply cites unpublished commercial knowledge or crosses persona/agent scope;
- the agent repeats a recent response or asks a field whose fact is already current;
- the agent ignores a doubt/interruption or asks the next field before answering it;
- price, date or time is confirmed without the required human confirmation;
- resume reprocesses an already handled message;
- delivery remains ambiguous after the timeout.

Stopping on duplication or cascade overrides a request to keep looping. Preserve evidence and leave the transport agent paused. Leave the target AI active only if no unclaimed inbound can be reprocessed; otherwise keep it paused and report the safety exception.

## Validate qualification

Do not infer completion from friendly copy. Require persisted evidence that:

- every required field is present;
- the current service superseded incompatible historical service state;
- the qualification stage/score advanced coherently;
- exactly one final handoff was committed;
- the final message promises human confirmation rather than confirming final price, date or time.

If the conversation contains incompatible old history, use a clean or explicitly reset validation lead. Never compensate by hardcoding persona or service behavior.

## Validate implementation changes

When code or workflow changes are part of the task:

1. Reproduce in the approved controlled environment before the remote run. If the task explicitly forbids local Docker, use automated tests and a safe remote QA/direct-validator path instead.
2. Validate the canonical n8n template and anti-hardcoded contract.
3. Add regression coverage for canonical inbound idempotency, pause/resume, graph-version migration, field extraction and service changes.
4. Run proportional backend tests and dashboard build/type checks.
5. Repeat the live E2E only after local evidence passes.

For n8n qualification, preserve this order:

`published context/limits -> model interpretation and natural reply -> proof of cited evidence + isolation -> CAS/idempotent commit -> at most one outbound`

The graph owns published knowledge, commercial facts/limits and qualification completion policy. The model owns explanation, recommendation, language, conversational flow and the next natural question. Proof checks cited published evidence plus persona/agent isolation; it must not deterministically select a FAQ, force `missing_fields[0]`, rebuild Product/Offer/Copy per turn or replace a valid model reply. Exactly-once only guards the one inbound/decision/commit/max-one-outbound invariant.

## Use the project command

Run `/validate-brain-agent-e2e` from `.agents/commands/validate-brain-agent-e2e.md` to apply this skill as a repeatable project procedure.

## Finish safely

Capture final screenshots for both sides and logs. Report success, failure or safety stop; never call an incomplete qualification successful. Include final AI states and whether they differ from the requested final state.
