---
name: validate-production-release
description: Run a read-only Brain AI production readiness audit for a release, including source SHA, image digests, migrations, Data API privileges, CAS conflicts, queues/proofs, graph checksums, host resources, backup age and controlled-restore evidence. Use before production cutover, after rollback, during a soak, or when deciding whether paused agents may resume.
---

# Validate Production Release

Keep the audit read-only. Never deploy, restart, resume agents, send messages,
delete backups or repair state while using this skill.

## Establish the audit window

1. Confirm the pause required by the release plan; frontend/API-only releases
   require none, shared runtime requires `release_pause`.
2. Record the intended full Git SHA, release class, backup mode and approved
   component image digests.
3. Require a 15-minute quiet window before the final verdict.
4. Stop if the environment or release identity is ambiguous.

## Run the validator

On the production host, run:

```bash
bash ops/vps/validate-production-release.sh
```

The script checks only the gates selected by the release plan. Migration state
is compared against the installed runner's dynamic `MIGRATION_MANIFEST.json`,
never a fixed filename list. Privileges/RLS, disk, scheduled backup and restore
come from continuous environment evidence. A fresh backup is a hard gate only
when `backup_mode=fresh_required`; compatible migrations consume the scheduled
evidence.

Read [references/release-gates.md](references/release-gates.md) when interpreting
the output or writing the release report.

## Decide

Return `PASS` only when every hard gate passes and the intended SHA/digests
match the approved release. Treat missing evidence as failure. Report warnings
separately and include only non-secret technical IDs.

WA Validator and conversational soak are optional diagnostic evidence. Their
absence or failure does not change this release-readiness verdict and never
blocks deploy or resume by itself. Evaluate the underlying technical evidence
directly; exactly-once, isolation, proof and confirmation safety remain hard
gates.

Do not convert provider `sent`/`delivered` into proof. A live E2E requires
separate authorization and the `brain-agent-e2e` skill.

## Stop conditions

- any CAS conflict inside the quiet window;
- unsafe anon/authenticated grants or a public table without RLS;
- migration ledger behind the installed runner manifest;
- orphan `processing`/`awaiting_proof` work;
- ledger/publication checksum divergence;
- missing, stale or unhealthy continuous environment evidence;
- missing fresh backup for a `fresh_required` migration;
- source SHA, digest or release checksum mismatch;
- resource pressure above the approved cutover limits.

Leave the release-scoped pause unchanged after both pass and failure. Resumption
is a separate authorized operation and must not clear binding/persona pauses.
