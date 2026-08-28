# /validate-brain-agent-e2e

Use `$brain-agent-e2e` to audit or repair a Brain agent through the dashboard, Evolution, the canonical n8n workflow and graph-backed runtime.

This command is diagnostic and optional. Never turn it or WA Validator into a
mandatory deploy, publication or resume gate.

## Arguments

- `target_persona`: target persona (required)
- `transport_persona`: transport persona/channel (required for live tests)
- `target_conversation`: optional lead name/ref hint; prove the binding before sending
- `mode`: `audit`, `repair-local` or `live-e2e` (default `audit`)

## Workflow

1. Record AI state, binding, provider, graph version/checksum and latest correlation IDs without secrets.
2. Keep transport AI paused and abort if pairing or channel health is uncertain.
3. Reproduce defects locally; add regressions for graph migration, service change, direct intent, model/policy reconciliation and resume idempotency.
4. Prefer the generic canonical n8n template. The GraphBundle supplies published knowledge, commercial facts/limits and completion state; backend changes preserve proof, isolation, CAS and exactly-once.
5. Verify `published context/limits -> model interpretation and natural reply -> proof of cited evidence + isolation -> CAS/idempotent commit -> at most one outbound`.
6. Verify `missing_fields` is treated as completeness/eligibility, not a required order. The model owns explanation, recommendation, language and the next natural question; no backend FAQ/question fallback may replace a valid grounded reply.
7. Run focused tests, JSON validation, Python compilation and relevant broader tests.
8. Drive each next customer message from the agent's actual natural question. Stop before sending if a cited commercial fact lacks published evidence, scope crosses persona/agent, a current fact is repeated, or recent replies substantially repeat.
9. For every turn, verify doubt-first response, all-fact extraction, contextual acknowledgement, grounded explanation/recommendation and one natural next question when needed.
10. In `live-e2e`, send once per turn and prove destination delivery plus exactly one response.
11. Report `technical_pass` and `quality_pass` separately, plus evidence, final AI states, qualification fields/stage and root cause/fix.

Before publication, verify top-down FAQ accumulation (active Persona-to-FAQ path,
source/status and persona/agent scope). Product, Offer and Copy are compiled
publication artifacts, never rebuilt per turn. Tock Fatal and Aurora both use
GraphBundle/runtime v3 with isolated publications, checksums, bindings and memory.

Do not deploy, synchronize a remote workflow, repeat ambiguous delivery, delete history, move leads or alter bindings unless separately authorized.
