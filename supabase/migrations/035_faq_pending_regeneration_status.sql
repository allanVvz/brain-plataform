-- Allow FAQ items to be marked stale when related commercial context changes.
ALTER TABLE knowledge_items
  DROP CONSTRAINT IF EXISTS knowledge_items_status_check;

ALTER TABLE knowledge_items
  ADD CONSTRAINT knowledge_items_status_check
  CHECK (status IN ('pending','approved','rejected','embedded','needs_update','pending_regeneration'));
