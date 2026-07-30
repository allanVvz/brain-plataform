-- Aurora client portal persona. No new tables: flexible portal/booking fields
-- live in personas.config and the canonical graph is published by seed_aurora.py.

INSERT INTO public.personas (slug, name, tone, products, config, active, updated_at)
VALUES (
  'aurora',
  'Aurora Estética Automotiva',
  'premium, objetivo, cordial',
  '["Avaliação inicial","Lavagem detalhada","Higienização interna","Polimento técnico"]'::jsonb,
  '{
    "portal": {
      "business_model": "appointment",
      "calendar_provider": "manual",
      "conversion_stage": "fechado",
      "stage_labels": {"fechado": "Agendado"},
      "availability_policy": "always_confirm",
      "schedule_notice": "Disponibilidade e horário sempre sujeitos à confirmação.",
      "automation_mode": "ai_with_handoff"
    }
  }'::jsonb,
  true,
  now()
)
ON CONFLICT (slug) DO UPDATE SET
  name = EXCLUDED.name,
  tone = EXCLUDED.tone,
  products = EXCLUDED.products,
  config = COALESCE(public.personas.config, '{}'::jsonb) || EXCLUDED.config,
  active = true,
  updated_at = now();

-- Protected output sinks never receive a legacy Persona primary edge. Graph
-- JSON owns all explicit hierarchy and FAQ -> Embed remains secondary.
CREATE OR REPLACE FUNCTION public.ensure_knowledge_node_primary_edge()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  persona_node_id uuid;
BEGIN
  IF NEW.persona_id IS NULL
     OR NEW.node_type IN ('persona', 'embed', 'embedded', 'gallery', 'tag', 'mention')
     OR COALESCE(NEW.metadata, '{}'::jsonb) ? 'graph_json_id' THEN
    RETURN NEW;
  END IF;

  IF EXISTS (
    SELECT 1
    FROM public.knowledge_edges e
    WHERE (e.source_node_id = NEW.id OR e.target_node_id = NEW.id)
      AND e.relation_type IN (
        'belongs_to_persona', 'contains', 'part_of_campaign', 'about_product',
        'briefed_by', 'answers_question', 'supports_copy', 'uses_asset', 'manual'
      )
  ) THEN
    RETURN NEW;
  END IF;

  INSERT INTO public.knowledge_nodes (
    persona_id, node_type, slug, title, metadata, status
  ) VALUES (
    NEW.persona_id, 'persona', 'self', 'Persona',
    '{"role":"root"}'::jsonb, 'validated'
  )
  ON CONFLICT (COALESCE(persona_id::text, ''), node_type, slug)
  DO UPDATE SET updated_at = now()
  RETURNING id INTO persona_node_id;

  INSERT INTO public.knowledge_edges (
    persona_id, source_node_id, target_node_id, relation_type, weight, metadata
  ) VALUES (
    NEW.persona_id, persona_node_id, NEW.id, 'belongs_to_persona', 1,
    '{"primary_tree":true,"created_from":"db_primary_tree_guard"}'::jsonb
  )
  ON CONFLICT (source_node_id, target_node_id, relation_type) DO NOTHING;

  RETURN NEW;
END;
$$;
