# Catalog media rollout

This release adds no table and performs no production mutation by itself.

## Order

1. Audit the source SHA, active publication/checksum, service readiness, paused runtime scope and the four declared Tock Fatal object hashes.
2. Build and release `brain-contracts` 3.1.0, then control plane, conversation runtime, transport and gateway with the exact same version.
3. Deploy the dashboard and Card-pio builds. Keep conversation transport and AI paused for the shared runtime release.
4. Run the internal WA Validator with synthetic turns. Require one decision per inbound, zero real outbound, individual attachment journals and a maximum of three image references.
5. Stage the Tock Fatal media GraphBundle using its reviewed draft checksum. Activation is a separate authorization and must preserve the runtime checksum.
6. Verify `/api/menu/{page_slug}/blocks`, desktop/mobile rendering, graph IDs and cache revalidation. Resume only under a later explicit authorization.

## Rollback

Route traffic back to the previous component images and reactivate the previous graph publication. Media relationships and files remain intact. Do not delete assets, graph nodes, edges or attachment journals. Keep the affected runtime paused until the previous publication/checksum and transport state are verified.

## Initial-load dry run

`scripts/audit_catalog_media.py` found four declared asset nodes and four product associations in `sdr-qualification-v16-voice-reachable.json`. The declared local evidence files were absent, so byte hashes and production object availability are still unverified. The dry run uploaded zero files and performed zero database changes.
