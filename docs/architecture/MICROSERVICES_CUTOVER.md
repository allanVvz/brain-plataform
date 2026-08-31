# Microservices cutover architecture

The four deployable processes and `brain-contracts` now live in this monorepo:
`apps/gateway`, `apps/control-plane`, `apps/conversation-runtime`,
`apps/transport`, and `packages/brain-contracts`. `brain-plataform` remains the
dashboard, `/api-brain` gateway, migrations, route map, and release-manifest
orchestrator. The extracted repositories are frozen historical references and
cannot be release sources.

Public routing keeps the existing paths: webhooks, messages and provider
dispatch go to transport; `/process`, agents, leads, decisions and the WA
Validator go to conversation runtime; authoring, GraphBundle, KB, assets and
administration go to control plane. Internal service endpoints stay under
`/internal/v1/*` and are not exposed directly by the gateway.

Before the initial cutover, shared runtime releases retain the global pause gate.
The cutover itself is limited to the approved eight-hour window and must leave
all paused components paused. No file in `infra/microservices` authorizes deploy,
migration, cleanup, traffic switch, or resume.

After production proof, compatible releases use an inactive blue/green slot,
readiness, graceful Caddy reload, and old-slot draining. Graph publication pins
`publication_id`, version, and checksum at turn start; atomic activation affects
new turns only. Shadow or proof failure pauses only the target persona.

Database migrations remain here. Service images declare schema 131 as their
minimum and use only `brain_control_plane`, `brain_runtime`, or `brain_transport`
credentials. Grants and roles require a separately reviewed migration.

Each slot receives a separate, host-managed environment file. The control-plane,
runtime and transport files contain only their own `BRAIN_DB_JWT`; the gateway
file has no database credential. Control-plane calls runtime and transport over
the configured private URLs. The same internal token is delivered through the
service environment files and is never stored in this repository.

Every v3 integrated manifest records four image digests built from one
`source_sha` plus the `packages/brain-contracts` checksum. Generate a candidate
with `ops/microservices/render-monorepo-release-manifest.py`; rendering is a
dry-run artifact and never authorizes deployment, migration, traffic switching
or worker resume.
