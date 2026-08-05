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

## Establish the test contract

1. Identify target persona/agent, transport persona, both conversations, fixed answers and expected terminal handoff.
2. Confirm the pair with channel/binding, masked phone or technical IDs, recent messages and timestamps. Do not rely on equal display names; one channel can show different local lead names.
3. Record initial AI state, lead reference, last message, binding/provider and graph version/checksum when available.
4. Keep the transport-side agent paused for the whole run. Activate the target agent only after the transport side is confirmed paused.
5. Preserve history, bindings, providers and nodes. Do not delete messages, move leads or reconnect channels.

## Drive the browser

Use the repository Playwright installation or another Playwright-compatible browser controller. Prefer an isolated persistent session and manual login. Keep the visible authenticated browser attached to automation.

Before the first mutation:

1. Clear or timestamp console, page-error and network capture.
2. Capture the initial screenshot.
3. Read the UI and the same authenticated APIs already used by the page when the UI hides required technical details.
4. Mask phone numbers and never record cookies, tokens, auth headers or response bodies containing secrets.

For every turn:

1. Read the latest target-agent question.
2. Answer only the requested field. Do not volunteer price, date or time.
3. Send exactly once from the paused transport-side conversation.
4. Record the send timestamp and HTTP status.
5. Prove exactly one transport outbound and one target inbound with IDs, directions and timestamps.
6. Confirm the target AI state. If paused by a legitimate handoff, inspect logs before resuming.
7. Wait up to 120 seconds for exactly one target outbound.
8. Prove exactly one corresponding inbound on the transport side.
9. Continue until required fields are persisted and the expected human handoff occurs.

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

1. Reproduce locally with Docker Compose before the remote run.
2. Validate the canonical n8n template and anti-hardcoded contract.
3. Add regression coverage for canonical inbound idempotency, pause/resume, graph-version migration, field extraction and service changes.
4. Run proportional backend tests and dashboard build/type checks.
5. Repeat the live E2E only after local evidence passes.

For n8n qualification, preserve this order:

`context -> initial policy -> structured model extraction -> policy reconciliation -> aligned reply -> exactly-once commit`

Model output may extract customer facts and identify a graph-valid service, but it never owns routing, required fields, the next question, handoff or confirmation policy.

## Use the project command

Run `/validate-brain-agent-e2e` from `.agents/commands/validate-brain-agent-e2e.md` to apply this skill as a repeatable project procedure.

## Finish safely

Capture final screenshots for both sides and logs. Report success, failure or safety stop; never call an incomplete qualification successful. Include final AI states and whether they differ from the requested final state.
