# QA environment policy

This policy supersedes environment-state notes in dated QA evidence.

- Keep the QA scaffold on the same VPS, in a separate Compose project.
- Keep QA stopped by default.
- Do not route production traffic, bindings, credentials, volumes or databases
  into QA.
- Do not run live WhatsApp/Evolution E2E from QA.
- Use local Docker, disposable Postgres and the direct validator for routine
  verification.
- Starting QA, refreshing its data or opening external traffic requires a
  separate authorized maintenance window.

Dated documents under `docs/qa` are evidence, not current environment
instructions. Do not copy hosts, credentials or bypass instructions from them.
