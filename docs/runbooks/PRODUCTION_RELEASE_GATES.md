# Production release gates

Production deploy is manual and requires the GitHub `production` environment
to have required reviewers. Protect `main` with pull requests, the CI workflow
as a required check and at least one approval; these repository settings must
be verified in GitHub because workflow YAML cannot enforce branch protection.

## Code release

1. Keep agents, transport and production WA Validator runs paused.
2. Require CI, secret/dependency/image scans and the checksummed release
   artifact.
3. Create and verify a data-only backup, including an isolated restore proof.
4. Deploy images by immutable SHA/digest and apply migrations.
5. Run `/validate-production-release`; recreate PostgREST after function/grant
   changes and Kong only when stale connections remain.
6. Run the direct validator, then soak for 30–60 minutes.

The official deploy keeps `KEEP_WORKERS_PAUSED=true`. A successful deploy and
healthy API are not authorization or evidence that conversational processing
is active. Resume is a separate production operation documented in
`docs/VPS_PRODUCTION_RUNBOOK.md` and requires:

1. explicit authorization to consume any existing real `buffered` inbound;
2. a read-only inventory of pending/ambiguous buffers and bindings;
3. API and workers on the same immutable SHA;
4. `docker compose ... up -d workers`, followed by `ops/vps/monitor.sh`;
5. per-buffer proof of one decision, one valid proof, one commit and at most
   one outbound, with no automatic replay after a terminal failure.

Record `deploy_validated` and `workers_resumed` as different gates. Do not call
an agent production-ready while the first is true and the second is false.

Host swap and PostgreSQL observability/timeouts are separate maintenance
windows. Use `ops/vps/ensure-swap.sh` for the reviewed 2 GB OOM guard and
review `ops/vps/configure-postgres-observability.sql` before applying it; do
not couple either host change to the release deploy.

Install and monitor `ops/systemd/brain-ai-backup.timer` independently from
deploy frequency. `ops/vps/monitor.sh` fails when the latest data-only backup
is older than 26 hours.

Code release never publishes persona documents, graphs, workflows or backfills.

## Content release

Use the manual `publish-content.yml` workflow with one persona slug, approved
checksum and approved next version. Configure separate required reviewers on
the `production-content` environment.

## Rollback

Rollback immediately for recurring CAS conflict, branch/fact divergence,
outbound without proof, semantic repetition, persistent graph checksum drift,
orphan critical work or resource pressure. Leave all agents paused.
