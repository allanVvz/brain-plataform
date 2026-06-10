-- 045_allow_product_group_content_type.sql
-- Local Docker fix: CRIAR/save persists product_group nodes as knowledge_items.

ALTER TABLE public.knowledge_items
  DROP CONSTRAINT IF EXISTS knowledge_items_content_type_check;

ALTER TABLE public.knowledge_items
  ADD CONSTRAINT knowledge_items_content_type_check
  CHECK (content_type IN (
    'brand','briefing','product_group','product','campaign','copy','asset',
    'prompt','faq','maker_material','tone','competitor',
    'audience','rule','entity','offer','other'
  ));
