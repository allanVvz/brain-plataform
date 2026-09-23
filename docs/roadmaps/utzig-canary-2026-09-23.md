# Utzig canary evidence — 2026-09-23

The Utzig Aurora-content GraphBundle was activated with CAS:

- publication: `4a3c5ee2-8656-45c3-ac36-62d7a259fc7e`
- version: `3`
- runtime checksum: `sha256:24cf681e03ad96af9307f9c806f7446947a4d8f0dc0354368fa86ca07a0add8f`

The conversation-runtime candidate was tested only through the internal WA
Validator. Candidate session `210a0ea9-957a-4a11-8520-6865b1b7ede8` produced
`technical_pass=true` and `quality_pass=false` with
`semantic_turn_failed:all_intended_facts_extracted`. The canary rollback
completed automatically; runtime is back on the previous blue digest.

The failed turn persisted no outbound to WhatsApp. The next action is a
validator/runtime-quality diagnosis, not another production deploy in this
window. Tock Fatal, Aurora and the transport remain isolated and unpaused.
