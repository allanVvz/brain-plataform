# Graph editor control-plane integration — 2026-10-04

Base: `origin/feat/utzig-commercial-v15` at `0549736`. The four editor commits
`6658cb2`, `43cbacf`, `5e13497`, `767de1a` were selected onto this lineage,
preserving the later North release. No runtime, transport, gateway, binding or
conversation tables are changed by this backend delivery.

## Contract and ownership

- Save retains `{persona_slug, base_publication_id, changes, idempotency_key}`.
  Revert additionally requires its observed `base_publication_id` and a stable
  `idempotency_key`, alongside `to_publication_id`.
- Receipts are durable `system_events` records, scoped to persona and key. Actor,
  operation, base and canonical request hash must match on replay. An ambiguous
  response is HTTP 503 with a Portuguese message; retry the same request/key.
- `set_text` accepts `confirmation`. It edits or creates the single
  `rule:journey:confirmation`, with `global_context` and `journey_stage` declared
  in the graph. Compiler v3.6.7 includes its node and chunk context in both common
  and branch contracts; the current runtime already reads those lists.
- `set_knowledge {node_id,text}` edits only supported knowledge text fields.
  FAQ text is first-line question plus subsequent answer; the existing canonical
  nested/top-level field location is retained. Qualification questions retain
  their single question field. Other supported types edit `summary`.
- Knowledge nodes and handoff rules expose `editable`; each branch requirement
  exposes `per_branch[branch].editable`, using declaration exclusivity. Global
  edits remain available for shared questions. Existing IDs, field owners,
  claims and accepted facts are preserved.
- Optional address collection remains an opportunity, not a qualification gate.
  A graph rule is delivered to the model; the compiler test does not prove that
  a live conversation asks before handoff. The release probe must prove that.

## Read integrity and compiler upgrade

PostgREST/JSON encoders can collapse stored numeric spelling `1.0` to `1`.
`read_graph_editor_publication_v1` returns `document_json::text` as a string;
Python decodes it without that loss. Stored checksum verification remains
unchanged. Editor, generators and publisher use this canonical active read.

A compiler upgrade is explicitly reported. Editable requires valid stored
baseline checksum, no node/edge content changes and no plan validation errors.
A divergent checksum with the same compiler version remains blocked. Generators
receive both `same_checksum` and `compiler_upgrade` from round-trip validation,
and retain the reviewed active ID/checksum in bundle metadata. A bundle derived
from A cannot stage after B has become active.

The SQL exports audited offline show Utzig and Tock editable with explicit
compiler upgrades to 3.6.7. Aurora stays read-only because its legacy source has
status/content conflicts; this gate has not been weakened.

## Transaction and schema 163

Migration 163 extends existing tables and functions, with no new table:
reservation/version allocation, fenced build lease, transactional CAS commit,
activation lineage, durable receipt, canonical active read and isolated grants.
Source nodes/edges change only together with activation and receipt in the same
transaction. New FK placeholders have `editor_staging` metadata and are excluded
from graph read paths. Incomplete/expired builds may be resumed with a new token;
old or missing tokens cannot write published projections.

Published source removal is allowed only for the reviewed base inventory with
explicit retirement/tombstone declarations. Unrelated source content remains
protected. The workflow no longer applies or restores source tombstones outside
CAS, and never reactivates a stale base on an ambiguous failure.

Direct activation/legacy rollback primitives and trigger implementations are
owner-only. Only the scoped transactional/read/reservation RPCs are granted to
control-plane. The grant validator checks the explicit denials. Existing old
writer calls fail closed between schema apply and control-plane cutover; active
conversation reads continue. Control-plane readiness has a schema floor of 163.
The CP rollback CLI now uses CAS and caller-supplied actor/base/key; it does not
change runtime bindings. Legacy `api/` direct-writer scripts are not supported
with schema 163 and fail closed at their revoked RPC.

## Responsibility boundaries

`graph_editor.py` plans and publishes; `graph_editor_model.py` reconstructs and
projects the read model; `graph_editor_operations.py` validates the operation
vocabulary and normalizes requirements; `graph_editor_questions.py` owns question
and field edits; `graph_editor_changes.py` dispatches semantic edits and translates
errors. These are implementation boundaries, with direct imports and no wrappers
per operation. Three historical Utzig generators now load the verified active
bundle, preserving its baseline provenance.

## Validation and production gate

Component tests cover owner preservation, required lists, shared branch edits,
confirmation context, knowledge fields, CAS races, lost replies, replay conflicts
and stale generator rejection. Python compilation, SQL parsing, shell syntax,
grant validation and diff whitespace are checked locally. These tests use an
isolated Python 3.12 virtual environment, without a local backend or Docker.

`ops/vps/rehearse-graph-editor-schema.sh` runs only against an explicitly named
`brain_restore_schema163_TIMESTAMP` database on the VPS. It clones a restored
snapshot into a candidate, runs two psql connections as `brain_control_plane`,
and verifies one CAS winner, receipt replay/conflict, actual revert, activation
lineage, expired-lease recovery, missing/stale token rejection and grants. It has
not been executed by the backend author. Its successful execution on the isolated
restore, plus backup verification and the Lead/Astra review, is required before
production schema apply. Bootstrap is supported by the RPC when and only when
`publish` observes no active publication under the persona lock; its NULL-base bootstrap and receipt replay are included in the mandatory isolated
DB rehearsal. Raw published content/topology writes fail with HTTP 409 and must
use the canonical editor. Only metadata.graph_position {x,y} is a visual write;
CAS/revert preserve that value explicitly. Unpublished asset/conversation nodes
and their connections remain ordinary writes. Source fences acquire the persona
lock with try-lock (transaction-held on success), failing closed on contention
to prevent source-row/advisory lock inversion.
