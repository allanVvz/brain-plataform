# Conversation runtime

This application is the only productive source for conversation runtime code.
It owns canonical inbound decisions, ledger, proof, retry, memory and the WA
Validator. Its `n8n` directory contains the one provisionable template.

The persisted dashboard/binding selection is the engine boundary:

- `/internal/v1/conversations/execute` runs only `deterministic`;
- `/internal/v1/conversations/decide` requires `model_observation` and runs only
  `n8n_agents`;
- `/commit` checks `binding.metadata.decision_owner` and fails closed when the
  caller belongs to the other engine.

In `n8n_agents`, the model owns the grounded public reply and its natural next
question. Proof validates publication checksum, persona/agent isolation,
commercial evidence, unsafe price/date/time confirmation and exactly-once. It
does not select a FAQ, force the first missing field or compose replacement
copy. The boundary canary in `api/tests/test_engine_boundary.py` is mandatory
for every runtime change.

The root `api/services` tree and frozen repositories are compatibility sources,
not implementation donors for this service.

## Agent and execution identity

The production conversation workflow currently executes only the `sdr` role.
Every provisioned instance is identified by `persona_id` plus the persisted
`agent_id` when available, otherwise by `persona_id:agent_slug`. The same
canonical template is rendered for every instance; only technical binding,
workflow, model and credential references differ. Raw API keys remain inside
the n8n credential and never enter the graph, event payloads or workflow
configuration returned to the dashboard.

Closer and image-editor roles are catalog/roadmap contracts only. Provisioning
fails closed for those roles until an executor is implemented, so configuration
cannot make an unavailable agent appear operational. A future backend model
orchestrator must consume the same published context and use the same
proof/commit/transport boundary as `n8n_agents`.

`conversation_turn_proofs` is the durable source for turn evidence. The
`conversation.decision_committed` event is only a searchable projection that
references the real proof id and distinguishes retrieved, model-cited and
proof-authorized knowledge. WA Validator origin is accepted only from its
canonical lead metadata; correlation-id prefixes are not trusted as identity.
