# Brain service applications

Each directory is independently deployable and may only depend on its own
source plus `packages/brain-contracts` and `packages/brain-shared`.  The
legacy `api/` tree remains a temporary compatibility adapter while the
production cutover is reviewed; it is not a build source for these apps.

- `gateway`: browser-session boundary and public routing.
- `control-plane`: graph, RAG, publications, personas and n8n provisioning.
- `conversation-runtime`: decisions, ledger, proofs, memory and WA Validator.
- `transport`: provider webhooks, media, buffer and outbox.
