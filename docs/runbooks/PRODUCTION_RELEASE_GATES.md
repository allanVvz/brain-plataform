# Production release gates

Production deploy is manual and requires the GitHub `production` environment
to have required reviewers. Protect `main` with pull requests, the CI workflow
as a required check and at least one approval; these repository settings must
be verified in GitHub because workflow YAML cannot enforce branch protection.

## Code release

1. Because code/infra changes affect the shared runtime, keep all agents,
   transport and production WA Validator runs paused.
2. Require CI, secret/dependency/image scans and the checksummed release
   artifact.
3. Create and verify a data-only backup, including an isolated restore proof.
4. Deploy images by immutable SHA/digest and apply migrations.
5. Run `/validate-production-release`; recreate PostgREST after function/grant
   changes and Kong only when stale connections remain.
6. Run the direct validator, then soak for 30–60 minutes.

Host swap and PostgreSQL observability/timeouts are separate maintenance
windows. Use `ops/vps/ensure-swap.sh` for the reviewed 2 GB OOM guard and
review `ops/vps/configure-postgres-observability.sql` before applying it; do
not couple either host change to the release deploy.

Install and monitor `ops/systemd/brain-ai-backup.timer` independently from
deploy frequency. `ops/vps/monitor.sh` fails when the latest data-only backup
is older than 26 hours.

Code release never publishes persona documents, graphs, workflows or backfills.

## Content release

Content releases are isolated by `persona_id`/`persona_slug`. Audit and mutate
only the target persona. Unrelated bindings and agents remain operational and
must not be paused or changed.

There are two distinct publishers:

- Canonical Markdown / Graph JSON v2: use the manual `publish-content.yml`
  workflow with one persona slug, approved document checksum and approved next
  version. The workflow calls `publish_persona_documents.py`; it does not
  publish a GraphBundle.
- GraphBundle / `graph_publications` v3: compile locally with
  `compile_graph_bundle.py`, approve both `draft_checksum` and
  `runtime_checksum`, then run `publish_graph_bundle.py` in the approved
  production API runtime with `--apply` and, only when separately authorized,
  `--activate`. The publisher rejects a persona UUID/slug mismatch and checksum
  drift.

For an existing target persona with an operational binding, pause that target
binding before staging/activation and keep it paused through direct WA Validator
validation. A new persona without binding, workflow or transport is already
inert and does not require pausing any other persona. Configure required
reviewers on `production-content` for the Markdown workflow; until a dedicated
GraphBundle workflow exists, record the explicit approval and both checksums in
the operation report.

## Rollback

Rollback immediately for recurring CAS conflict, branch/fact divergence,
outbound without proof, semantic repetition, persistent graph checksum drift,
orphan critical work or resource pressure. For a code/infra release, leave all
agents paused. For a persona-scoped content release, leave only the affected
persona paused/inert and do not mutate unrelated personas.
