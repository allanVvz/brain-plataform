# /validate-brain-agent-e2e

Use `$brain-agent-e2e` to audit or repair a Brain agent through the dashboard, Evolution, the canonical n8n workflow and graph-backed runtime.

## Arguments

- `target_persona`: target persona (required)
- `transport_persona`: transport persona/channel (required for live tests)
- `target_conversation`: optional lead name/ref hint; prove the binding before sending
- `mode`: `audit`, `repair-local` or `live-e2e` (default `audit`)

## Workflow

1. Record AI state, binding, provider, graph version/checksum and latest correlation IDs without secrets.
2. Keep transport AI paused and abort if pairing or channel health is uncertain.
3. Reproduce defects locally; add regressions for graph migration, service change, direct intent, model/policy reconciliation and resume idempotency.
4. Prefer the generic canonical n8n template. Backend changes are limited to authoritative graph policy/state and exactly-once guarantees.
5. Verify `context -> policy -> extraction -> reconcile -> aligned reply -> commit`.
6. Verify `missing_fields[0]` maps to the published graph's `appointment_policy.field_questions` and no backend question fallback exists.
7. Run focused tests, JSON validation, Python compilation and relevant broader tests.
8. In `live-e2e`, send once per turn and prove destination delivery plus exactly one response.
9. Report evidence, final AI states, qualification fields/stage and root cause/fix.

Do not deploy, synchronize a remote workflow, repeat ambiguous delivery, delete history, move leads or alter bindings unless separately authorized.
