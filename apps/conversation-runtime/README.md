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
