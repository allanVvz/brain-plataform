---
name: sofia-graph-publication-plan
description: Prepare and review a Brain GraphBundle compilation and PublicationPlan for Sofia graph authoring. Use for draft-to-plan automation; do not use it to publish, activate, deploy, or send WhatsApp messages.
---

# Sofia Graph Publication Plan

Prepare a deterministic, reviewable graph change without mutating production.

## Workflow

1. Read `docs/roadmaps/AGENT_ROADMAP.md` and preserve its gates.
2. Build or edit a declarative GraphBundle. Every fact needs persona, type,
   source and validation status; unresolved facts remain `pending_source` or
   `pending_validation`.
3. Run `api/scripts/compile_graph_bundle.py <bundle.json>` from the repository
   root. This is a dry-run and must not call a publisher.
4. Review both checksums, node/branch diff, chunk reuse, breaking changes and
   validation errors.
5. Stop with `blocked` when validation errors exist. Return `dry_run_complete`
   when `publication_allowed=false`; only a source-approved bundle may return
   `awaiting_approval`. Identify the tests required by affected branches.

Use `--against <compiled-document.json>` only when a trusted current compiled
document was supplied through an approved read-only source. Never substitute a
stale fixture for the active publication.

## Guardrails

- Do not invent products, prices, stock, logistics, minimum quantities, URLs,
  offers or policies.
- Do not create tables. A GraphBundle is an authoring payload over existing
  graph/publication storage.
- Do not call `compile_persona_publication`, `graph.publish_patch` or
  `activate_graph_publication_v3` during planning.
- Human approval of a plan does not authorize deploy, migration, activation,
  transport resume, retention cleanup or WhatsApp traffic.
- A GraphBundle plan and publication are scoped to one persona. Do not pause or
  mutate unrelated personas. A new persona without binding/workflow/transport
  is already inert; an existing target persona may require only its own binding
  to remain paused during a separately authorized publication/validation.
- Validate conversation changes with `brain-agent-e2e` through the internal WA
  Validator; never use real WhatsApp for this repository.

The local example at
`data/graph_bundles/examples/basic-commercial-sdr.json` demonstrates two
audience branches without real commercial claims and is not publishable data.
