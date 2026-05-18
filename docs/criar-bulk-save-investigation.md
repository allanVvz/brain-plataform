# CRIAR/Sofia bulk save investigation

## Current bottleneck

`kb_intake_service.save()` persists each normalizedPlan entry through `knowledge_lifecycle.persist_pending_knowledge_item()`.
That path writes one item at a time, then mirrors each item into `knowledge_nodes`, creates parent/tag edges, and updates item metadata.

For large plans this becomes many REST calls:

- lookup existing `knowledge_items`
- insert/update `knowledge_items`
- upsert `knowledge_nodes`
- upsert persona parent edge
- upsert parent edge
- upsert tag nodes
- upsert tag edges
- patch `knowledge_items.metadata.knowledge_node_id`
- apply plan hierarchy again

The current hierarchy phase is best-effort after items are already persisted, so a graph failure can leave partial visible state.

## Recommended target

Create a Postgres RPC for atomic plan persistence:

`public.persist_knowledge_plan_bulk(payload jsonb) returns jsonb`

The API should validate the normalizedPlan in Python first, then send one RPC payload containing:

- persona id/slug
- session id
- normalized entries
- links
- trace metadata
- precomputed file paths

The function should run in one transaction and:

1. upsert `knowledge_items` by stable key, preferably `persona_id + file_path` or a new canonical key
2. upsert `knowledge_nodes` by `persona_id,node_type,slug`
3. resolve item id to node id mappings in SQL
4. upsert primary tree `knowledge_edges`
5. upsert tag nodes and tag edges
6. patch item metadata with node ids in bulk
7. return counts and ids

On failure, raise and rollback. If rollback is not possible for a future asynchronous worker path, mark newly created rows `active=false`, `visual_hidden=true`, and return `partial=false`.

## FastAPI fallback before RPC

If RPC is deferred, add a batch service below `kb_intake_service.save()`:

- collect all item payloads first
- bulk `upsert` `knowledge_items`
- bulk `upsert` `knowledge_nodes`
- fetch nodes by slug once
- bulk `upsert` `knowledge_edges`
- bulk `upsert` tag nodes/edges
- bulk patch metadata where possible

This still lacks full transactionality through Supabase REST, but it reduces network round trips and makes failures easier to report.

## Expected response contract

Success:

```json
{
  "ok": true,
  "items_created": 20,
  "nodes_created": 20,
  "edges_created": 19,
  "faq_documents_created": 4,
  "rag_ready": true
}
```

Failure:

```json
{
  "ok": false,
  "error": "bulk persistence failed before graph activation",
  "saved_items": 0,
  "partial": false
}
```

## Why RPC is the better final shape

Supabase REST supports bulk insert/upsert, but it does not make a multi-table save atomic from the client perspective. This flow needs all-or-nothing behavior across items, nodes, edges, tags, and item metadata. A Postgres RPC gives one request, one transaction, one failure boundary, and one final report.
