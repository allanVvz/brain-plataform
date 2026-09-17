# Conversation runtime

This application is the only productive source for conversation runtime code.
It owns canonical inbound decisions, ledger, proof, retry, memory and the WA
Validator. Its `n8n` directory is historical audit material, not a runtime.

The persisted dashboard/binding selection is the engine boundary:

- `/internal/v1/conversations/execute` runs only `deterministic`;
- `/internal/v1/conversations/execute-agentic` owns both model calls, resolved
  state/RAG, proof and commit behind one canonical result;
- `/resolve-understanding` and `/decide` remain private compatibility seams
  during the cutover and are not transport entrypoints;
- `/commit` checks `binding.metadata.decision_owner` and fails closed when the
  caller belongs to the other engine.

In the agentic runtime, the model owns the grounded public reply and its natural next
question. Proof validates publication checksum, persona/agent isolation,
commercial evidence, unsafe price/date/time confirmation and exactly-once. It
does not select a FAQ, force the first missing field or compose replacement
copy. The boundary canary in `api/tests/test_engine_boundary.py` is mandatory
for every runtime change.

The published graph selects policy per role. `interpret_then_respond` runs
`TurnUnderstandingV1 -> read-only resolution/RAG -> ConversationReplyV1 ->
proof -> one commit`. `single_pass` is not a productive strategy. A failed model call,
invalid JSON or invalid proof fails safe to an observable handoff. The two-step
path has no semantic repair call and never fabricates public fallback text.

The root `api/services` tree and frozen repositories are compatibility sources,
not implementation donors for this service.
