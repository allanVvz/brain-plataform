-- Aurora's graph now publishes "service" branch anchors (non-sales intents
-- like talking to a human or filing a complaint), alongside "product".
-- Both knowledge_items.content_type (graph_document_publisher's
-- import_graph_json) and knowledge_rag_entries.content_type
-- (graph_compiler_v3's RAG projection) must accept it.

ALTER TABLE public.knowledge_items
  DROP CONSTRAINT IF EXISTS knowledge_items_content_type_check;

ALTER TABLE public.knowledge_items
  ADD CONSTRAINT knowledge_items_content_type_check
  CHECK (content_type IN (
    'brand','briefing','product_group','product','service','campaign','copy','asset',
    'prompt','faq','maker_material','tone','competitor',
    'audience','rule','entity','offer','other'
  ));

ALTER TABLE public.knowledge_rag_entries
  DROP CONSTRAINT IF EXISTS knowledge_rag_entries_content_type_check;

ALTER TABLE public.knowledge_rag_entries
  ADD CONSTRAINT knowledge_rag_entries_content_type_check
  CHECK (content_type IN (
    'faq',
    'product',
    'service',
    'product_group',
    'offer',
    'brand',
    'campaign',
    'rule',
    'tone',
    'copy',
    'briefing',
    'audience',
    'asset',
    'entity',
    'general_note'
  ));
