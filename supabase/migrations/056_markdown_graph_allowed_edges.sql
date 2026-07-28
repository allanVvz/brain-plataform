-- Align the existing edge registry with the Markdown compiler's optional
-- commercial branches. No schema/table is introduced.

INSERT INTO public.knowledge_allowed_edges
  (source_type, target_type, edge_type, requires_source_status, rationale)
VALUES
  ('brand', 'campaign', 'main', NULL, 'Campaign may omit a briefing layer'),
  ('brand', 'briefing', 'main', NULL, 'Persona briefing branch'),
  ('brand', 'tone', 'main', NULL, 'Persona tone branch'),
  ('brand', 'rule', 'main', NULL, 'Persona rule branch'),
  ('product_group', 'copy', 'main', NULL, 'Copy may anchor at product group'),
  ('product', 'copy', 'main', NULL, 'Copy may anchor directly at product'),
  ('brand', 'faq', 'main', NULL, 'General brand FAQ'),
  ('campaign', 'faq', 'main', NULL, 'General campaign FAQ'),
  ('product_group', 'faq', 'main', NULL, 'General product-group FAQ'),
  ('product', 'faq', 'main', NULL, 'Product FAQ without copy'),
  ('product_group', 'campaign', 'reference', NULL, 'Campaign membership'),
  ('product', 'campaign', 'reference', NULL, 'Campaign membership'),
  ('faq', 'embed', 'reference', 'approved', 'Approved FAQ publication')
ON CONFLICT (source_type, target_type, edge_type) DO UPDATE SET
  requires_source_status = EXCLUDED.requires_source_status,
  rationale = EXCLUDED.rationale,
  active = true,
  updated_at = now();
