# Release backup retention

Production backups are a continuous environment control, independent from
deploy frequency. They include database and volume dumps, manifest state and
checksums; immutable application images remain in the registry.

The scheduled backup and restore proof are summarized by
`ops/vps/collect-environment-evidence.sh`. Normal API and compatible migration
releases consume that evidence and do not create another full backup. A release
creates a new backup only when its plan has `backup_mode=fresh_required`.

The VPS worktree is not the deployed application source: production runs the
immutable GHCR image SHA. Historical `.releases`, `.rollbacks` and staging
copies in that worktree must not be recursively copied into every new release
backup. `backup-release.sh` therefore inventories untracked files but archives
them only when `BACKUP_INCLUDE_UNTRACKED_SOURCE=true` is explicitly requested
for a forensic capture.

Use the read-only inventory before any cleanup:

```bash
bash ops/vps/summarize-release-backups.sh > /tmp/brain-release-backups.tsv
```

Recommended retention is seven recent full backups, four weekly full backups
and six monthly full backups. The inventory labels those rollback points as
`keep` and everything else as `review`, then totals `review_bytes`; it never
deletes anything. A backup containing a `.keep` marker is always protected.
Before removal, verify the newest retained backup's `SHA256SUMS`, record the
candidate paths and estimated reclaimed bytes, obtain explicit approval, then
remove only those exact resolved directories. Database history, graph
publications, message history and Docker volumes are not cleanup targets.

n8n execution pruning and PostgreSQL log retention are separate maintenance
controls; they must use their product-supported settings. Vacuuming may reclaim
space after pruning, but must be scheduled and observed independently of deploy.
