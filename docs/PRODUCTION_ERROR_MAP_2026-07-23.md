# Production error map — 2026-07-23

Scope: `brain-plataform` dashboard on Vercel and the self-hosted API/database/workers on the Hostinger VPS.

## Blocking errors corrected

| ID | Symptom | Root cause | Correction |
|---|---|---|---|
| GJ2-001 | `Nenhum Graph JSON v2 publicado para esta persona.` | Production had zero `graph_document_published` events. The Graph UI intentionally has no v1 fallback. | Added an explicit, idempotent Graph JSON v2 backfill and publication path for existing personas. |
| GJ2-002 | Graph edits could disappear after a container recreation. | `publish` wrote to `system_events`, while patch/import/rollback/reindex used `/data/graph_documents` inside a disposable container. | Unified every Graph JSON v2 version operation on the existing `system_events` table. No new table was created. |
| GJ2-003 | A persona graph with `brand_slug` could be published but remain invisible to the Graph page. | The page requests by persona only, while the store treated an omitted brand as `brand_slug IS NULL`. | An omitted brand now selects the latest document for the persona; an explicit brand remains exact-match. |
| GJ2-004 | The Baita legacy graph could not be published as valid v2. | It contained two persona roots (`self` and `baita-conveniencia`) and primary relationships outside the canonical v2 hierarchy. | The backfill creates one matching persona root, preserves supported nodes and secondary relations, and normalizes primary parents through the canonical chain. Legacy rows are not destructively deleted. |
| MSG-001 | Repeated API errors: `column messages.nome does not exist`. | Conversation/message helpers queried the legacy columns `nome`, `lead_ref`, `texto`, `sender_type`, while the self-hosted schema uses `lead_id`, `content`, `role`, `sender_id`. | Reads and writes now prefer the self-hosted schema and normalize the response to the dashboard compatibility shape. |
| N8N-001 | `N8nMirrorWorker` emitted `KeyError: N8N_BASE_URL` every five minutes. | The worker started under `--all` even though n8n was intentionally deployed without Brain credentials. | The mirror worker now skips cleanly until both n8n runtime credentials are configured. |
| TEST-001 | Serialization guard tests failed before reaching their assertions. | The route gained an authenticated `request` parameter, but the tests still called the old signature. | Tests now provide an authenticated request fixture and isolate session authorization. |

## Data state discovered

| Persona | Legacy derived graph before backfill | Canonical backfill behavior |
|---|---:|---|
| `baita-conveniencia` | 18 nodes / 36 edges | Normalize and publish the supported graph, preserving active semantic relations as secondary edges. |
| `tock-fatal` | 0 nodes / 0 edges | Publish a valid persona-root document. New knowledge can extend it through the canonical write path. |
| `vz-lupas` | 0 nodes / 0 edges | Publish a valid persona-root document. New knowledge can extend it through the canonical write path. |

## Non-blocking operational debt

- The tracked legacy file `data/graph_documents/tock-fatal.v002.json` contains a Baita payload. It is no longer read in production after GJ2-002 and is retained only as a legacy artifact pending a separate cleanup decision.
- n8n remains intentionally isolated from Brain. `N8N_BASE_URL` and `N8N_API_KEY` must stay unset until the integration phase is approved.
- The n8n image is still `n8nio/n8n:latest`; pin a tested version before workflow production use.
- n8n reports configuration deprecation warnings (`WEBHOOK_URL` and `N8N_RUNNERS_ENABLED`). Update these when the isolated instance is hardened.
- The old Vercel account/domain may still serve a stale project. The active production project is the account connected to team `allanulise027-3939s-projects`.

## Validation gates

1. Python syntax check.
2. Graph route/backfill/integration tests.
3. Dashboard production build.
4. Backfill dry-run for every active persona.
5. Backfill publication and materialization.
6. Authenticated `GET /graph-documents/current` through Vercel for every persona.
7. Browser verification of `/knowledge/graph`.
8. Post-deploy API/worker log scan.
