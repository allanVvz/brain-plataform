---
name: validate-production-release
description: Run a read-only Brain AI production readiness audit for a release, including source SHA, image digests, migrations, Data API privileges, CAS conflicts, queues/proofs, graph checksums, host resources, backup age and controlled-restore evidence. Use before production cutover, after rollback, during a soak, or when deciding whether paused agents may resume.
---

# Validate Production Release

Keep the audit read-only. Never deploy, restart, resume agents, send messages,
delete backups or repair state while using this skill.

## Establish the audit window

1. Confirm all agents and transport are paused.
2. Record the intended full Git SHA and approved API/migration image digests.
3. Require a 15-minute quiet window before the final verdict.
4. Stop if the environment or release identity is ambiguous.

## Run the validator

On the production host, run:

```bash
bash ops/vps/validate-production-release.sh
```

The script checks the installed release artifact, migrations 112–127,
privileges/RLS, recent CAS conflicts, orphan processing/proof rows, graph
checksums, Docker resource snapshots, disk use, conditional backup age and last
isolated restore proof. A fresh backup is a hard gate for migrations. For a
durable non-migration release it is reported as operational evidence and does
not block resume; a standalone audit without lifecycle context stays fail
closed.

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
- incomplete migrations;
- orphan `processing`/`awaiting_proof` work;
- ledger/publication checksum divergence;
- missing or stale backup evidence when the release includes migration, or
  missing/stale restore evidence;
- source SHA, digest or release checksum mismatch;
- resource pressure above the approved cutover limits.

Leave agents and transport paused after both pass and failure. Resumption is a
separate authorized operation.
