# Microservices cutover architecture

Target repositories are `brain-contracts`, `brain-control-plane`,
`brain-conversation-runtime`, and `brain-transport`. `brain-plataform` remains
the dashboard, `/api-brain` gateway, migrations, route map, and release-manifest
orchestrator.

Before the initial cutover, shared runtime releases retain the global pause gate.
The cutover itself is limited to the approved eight-hour window and must leave
all paused components paused. No file in `infra/microservices` authorizes deploy,
migration, cleanup, traffic switch, or resume.

After production proof, compatible releases use an inactive blue/green slot,
readiness, graceful Caddy reload, and old-slot draining. Graph publication pins
`publication_id`, version, and checksum at turn start; atomic activation affects
new turns only. Shadow or proof failure pauses only the target persona.

Database migrations remain here. Service images declare schema 130 as their
minimum and use only `brain_control_plane`, `brain_runtime`, or `brain_transport`
credentials. Grants and roles require a separately reviewed migration.
