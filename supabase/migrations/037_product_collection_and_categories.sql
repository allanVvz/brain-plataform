-- 037_product_collection_and_categories.sql
-- Universal product collections on top of knowledge_nodes/knowledge_edges.
-- Additive and idempotent. No products table.

INSERT INTO public.knowledge_node_type_registry
  (node_type, label, description, default_level, default_importance, color, icon, sort_order)
VALUES
  ('product_collection', 'Product Collection', 'Cardapio, catalogo ou colecao de produtos. O tipo concreto fica em metadata.collection_type.', 25, 0.88, '#34d399', 'book-open', 25),
  ('category', 'Category', 'Agrupamento logico de produtos dentro de uma product_collection.', 38, 0.72, '#fbbf24', 'folder', 38),
  ('product', 'Produto', 'Produto comercial conectado a categorias, colecoes, copy, FAQ e assets.', 45, 0.85, '#60a5fa', 'package', 45),
  ('copy', 'Copy', 'Texto reutilizavel para mensagens, posts ou anuncios.', 70, 0.65, '#64748b', 'text', 70),
  ('faq', 'FAQ', 'Pergunta e resposta operacional.', 75, 0.65, '#4ade80', 'circle-help', 75),
  ('asset', 'Asset', 'Arquivo visual, video, logo, template ou material maker.', 80, 0.55, '#f59e0b', 'image', 80),
  ('briefing', 'Briefing', 'Contexto, estrategia, requisitos e instrucoes.', 50, 0.75, '#c084fc', 'file-text', 50)
ON CONFLICT (node_type) DO UPDATE SET
  label = EXCLUDED.label,
  description = EXCLUDED.description,
  default_level = EXCLUDED.default_level,
  default_importance = EXCLUDED.default_importance,
  color = EXCLUDED.color,
  icon = EXCLUDED.icon,
  sort_order = EXCLUDED.sort_order,
  active = TRUE,
  updated_at = now();

INSERT INTO public.knowledge_relation_type_registry
  (relation_type, label, inverse_label, source_node_types, target_node_types, default_weight, directional, sort_order, active)
VALUES
  ('brand_has_collection', 'brand tem colecao', 'colecao de brand', '{"brand"}', '{"product_collection"}', 0.90, TRUE, 51, TRUE),
  ('collection_has_briefing', 'colecao tem briefing', 'briefing de colecao', '{"product_collection"}', '{"briefing"}', 0.85, TRUE, 52, TRUE),
  ('collection_has_category', 'colecao tem categoria', 'categoria da colecao', '{"product_collection"}', '{"category"}', 0.85, TRUE, 53, TRUE),
  ('part_of_collection', 'parte da colecao', 'contem', '{"product","category","copy","faq","briefing"}', '{"product_collection"}', 0.75, TRUE, 54, TRUE),
  ('category_has_product', 'categoria tem produto', 'produto da categoria', '{"category"}', '{"product"}', 0.86, TRUE, 55, TRUE),
  ('in_category', 'na categoria', 'agrupa', '{"product"}', '{"category"}', 0.70, TRUE, 56, TRUE),
  ('product_has_copy', 'produto tem copy', 'copy de produto', '{"product"}', '{"copy"}', 0.75, TRUE, 57, TRUE),
  ('product_has_faq', 'produto tem FAQ', 'FAQ de produto', '{"product"}', '{"faq"}', 0.75, TRUE, 58, TRUE),
  ('product_has_asset', 'produto tem asset', 'asset de produto', '{"product"}', '{"asset"}', 0.75, TRUE, 59, TRUE),
  ('product_image', 'imagem do produto', 'representa produto', '{"asset"}', '{"product"}', 0.85, TRUE, 60, TRUE),
  ('faq_has_embed', 'FAQ publicado em embed', 'embed de FAQ', '{"faq"}', '{"embedded"}', 0.75, TRUE, 61, TRUE)
ON CONFLICT (relation_type) DO UPDATE SET
  label = EXCLUDED.label,
  inverse_label = EXCLUDED.inverse_label,
  source_node_types = EXCLUDED.source_node_types,
  target_node_types = EXCLUDED.target_node_types,
  default_weight = EXCLUDED.default_weight,
  directional = EXCLUDED.directional,
  sort_order = EXCLUDED.sort_order,
  active = TRUE,
  updated_at = now();

CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_metadata_collection
  ON public.knowledge_nodes ((metadata->>'collection_slug'))
  WHERE metadata ? 'collection_slug';

CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_metadata_category
  ON public.knowledge_nodes ((metadata->>'category_slug'))
  WHERE metadata ? 'category_slug';

CREATE INDEX IF NOT EXISTS idx_knowledge_nodes_metadata_collection_type
  ON public.knowledge_nodes ((metadata->>'collection_type'))
  WHERE metadata ? 'collection_type';

CREATE OR REPLACE FUNCTION pg_temp.m037_upsert_node(
  p_persona_id uuid,
  p_node_type text,
  p_slug text,
  p_title text,
  p_summary text,
  p_tags text[],
  p_metadata jsonb,
  p_status text
) RETURNS uuid AS $f$
DECLARE
  v_id uuid;
BEGIN
  SELECT id INTO v_id
  FROM public.knowledge_nodes
  WHERE COALESCE(persona_id::text, '') = COALESCE(p_persona_id::text, '')
    AND node_type = p_node_type
    AND slug = p_slug
  LIMIT 1;

  IF v_id IS NULL THEN
    INSERT INTO public.knowledge_nodes
      (persona_id, node_type, slug, title, summary, tags, metadata, status)
    VALUES
      (p_persona_id, p_node_type, p_slug, p_title, p_summary,
       COALESCE(p_tags, ARRAY[]::text[]), COALESCE(p_metadata, '{}'::jsonb),
       COALESCE(p_status, 'active'))
    RETURNING id INTO v_id;
  ELSE
    UPDATE public.knowledge_nodes
       SET title = COALESCE(p_title, title),
           summary = COALESCE(p_summary, summary),
           tags = (SELECT ARRAY(SELECT DISTINCT unnest(COALESCE(tags, ARRAY[]::text[]) || COALESCE(p_tags, ARRAY[]::text[])))),
           metadata = COALESCE(metadata, '{}'::jsonb) || COALESCE(p_metadata, '{}'::jsonb),
           status = COALESCE(p_status, status),
           updated_at = now()
     WHERE id = v_id;
  END IF;

  RETURN v_id;
END
$f$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION pg_temp.m037_upsert_edge(
  p_persona_id uuid,
  p_source uuid,
  p_target uuid,
  p_relation text,
  p_weight numeric,
  p_metadata jsonb
) RETURNS void AS $f$
BEGIN
  IF p_source IS NULL OR p_target IS NULL OR p_source = p_target THEN
    RETURN;
  END IF;

  INSERT INTO public.knowledge_edges
    (persona_id, source_node_id, target_node_id, relation_type, weight, metadata)
  VALUES
    (p_persona_id, p_source, p_target, p_relation,
     COALESCE(p_weight, 1.0), COALESCE(p_metadata, '{}'::jsonb))
  ON CONFLICT (source_node_id, target_node_id, relation_type) DO UPDATE SET
    persona_id = EXCLUDED.persona_id,
    weight = EXCLUDED.weight,
    metadata = COALESCE(public.knowledge_edges.metadata, '{}'::jsonb) || EXCLUDED.metadata || '{"active":true}'::jsonb,
    updated_at = now();
END
$f$ LANGUAGE plpgsql;

DO $$
DECLARE
  baita_persona_id uuid;
  persona_node_id uuid;
  brand_id uuid;
  collection_id uuid;
  briefing_id uuid;
  cat_cervejas_premium_id uuid;
  cat_cervejas_id uuid;
  cat_destilados_premium_id uuid;
  cat_a_noite_pede_id uuid;
  cat_vinhos_espumantes_id uuid;
  cat_energia_drinks_id uuid;
  cat_bateu_fome_id uuid;
  cat_munchies_id uuid;
  cat_headshop_id uuid;
  prod_jager_id uuid;
  prod_patagonia_id uuid;
  prod_suspeito_id uuid;
  prod_lagunitas_id uuid;
  primary_meta jsonb := jsonb_build_object('seed','037_product_collection','primary_tree',true,'active',true);
  aux_meta jsonb := jsonb_build_object('seed','037_product_collection','primary_tree',false,'active',true);
BEGIN
  SELECT id INTO baita_persona_id FROM public.personas WHERE slug IN ('baita-conveniencia', 'baita') ORDER BY CASE slug WHEN 'baita-conveniencia' THEN 0 ELSE 1 END LIMIT 1;
  IF baita_persona_id IS NULL THEN
    RAISE NOTICE 'Persona Baita not found, skipping product collection seed.';
    RETURN;
  END IF;

  persona_node_id := pg_temp.m037_upsert_node(baita_persona_id, 'persona', 'baita-conveniencia', 'Baita Conveniencia', 'Persona raiz da Baita Conveniencia.', ARRAY['baita','persona'], jsonb_build_object('persona_slug','baita-conveniencia','protected',true), 'validated');
  brand_id := pg_temp.m037_upsert_node(baita_persona_id, 'brand', 'baita', 'Baita''', 'Brand Baita'' conectada ao fluxo de produtos.', ARRAY['baita','brand'], jsonb_build_object('persona_slug','baita-conveniencia'), 'pending_validation');
  collection_id := pg_temp.m037_upsert_node(baita_persona_id, 'product_collection', 'cardapio-baita-v14', 'Cardapio Baita'' v14', 'Cardapio oficial da Baita'' Conveniencia, versao v14.', ARRAY['product_collection','cardapio','baita','v14'], jsonb_build_object('collection_type','menu','display_name','Cardapio Baita'' v14','version','v14','source_file','BAITA_MENU_SYSTEM_v14_2.md'), 'pending_validation');
  briefing_id := pg_temp.m037_upsert_node(baita_persona_id, 'briefing', 'editorial-premium-motion', 'Editorial Premium Motion', 'Briefing editorial para a colecao Baita'' v14: premium, movimento, textura noturna e foco em produto.', ARRAY['editorial','premium','motion','baita'], jsonb_build_object('editorial_style','premium_motion','collection_slug','cardapio-baita-v14'), 'pending_validation');

  cat_cervejas_premium_id := pg_temp.m037_upsert_node(baita_persona_id,'category','cervejas-premium','Cervejas Premium','Long necks, IPAs, weisses e premium imports.',ARRAY['cerveja','premium'],jsonb_build_object('collection_slug','cardapio-baita-v14','sort_order',10),'pending_validation');
  cat_cervejas_id := pg_temp.m037_upsert_node(baita_persona_id,'category','cervejas','Cervejas','Cervejas mainstream em lata, long neck e 600ml.',ARRAY['cerveja'],jsonb_build_object('collection_slug','cardapio-baita-v14','sort_order',20),'pending_validation');
  cat_destilados_premium_id := pg_temp.m037_upsert_node(baita_persona_id,'category','destilados-premium','Destilados Premium','Licores, whiskies, gins e destilados premium.',ARRAY['destilado','premium'],jsonb_build_object('collection_slug','cardapio-baita-v14','sort_order',30),'pending_validation');
  cat_a_noite_pede_id := pg_temp.m037_upsert_node(baita_persona_id,'category','a-noite-pede','A Noite Pede','Drinks prontos e bebidas para a noite.',ARRAY['drink','noite'],jsonb_build_object('collection_slug','cardapio-baita-v14','sort_order',40),'pending_validation');
  cat_vinhos_espumantes_id := pg_temp.m037_upsert_node(baita_persona_id,'category','vinhos-e-espumantes','Vinhos e Espumantes','Vinhos, frisantes e espumantes.',ARRAY['vinho','espumante'],jsonb_build_object('collection_slug','cardapio-baita-v14','sort_order',50),'pending_validation');
  cat_energia_drinks_id := pg_temp.m037_upsert_node(baita_persona_id,'category','energia-drinks','Energia & Drinks','Energeticos, isotonicos, refrigerantes e mixers.',ARRAY['energetico','drinks'],jsonb_build_object('collection_slug','cardapio-baita-v14','sort_order',60),'pending_validation');
  cat_bateu_fome_id := pg_temp.m037_upsert_node(baita_persona_id,'category','bateu-a-fome','Bateu a Fome?','Comidas, pasteis, sandubas, porcoes e pizzas.',ARRAY['comida','fome'],jsonb_build_object('collection_slug','cardapio-baita-v14','sort_order',70),'pending_validation');
  cat_munchies_id := pg_temp.m037_upsert_node(baita_persona_id,'category','munchies','Munchies','Bomboniere, salgadinhos, chocolates e snacks.',ARRAY['munchies','snacks'],jsonb_build_object('collection_slug','cardapio-baita-v14','sort_order',80),'pending_validation');
  cat_headshop_id := pg_temp.m037_upsert_node(baita_persona_id,'category','headshop-tabacaria','Headshop & Tabacaria','Cigarros, sedas, filtros, piteiras, tabacos e acessorios.',ARRAY['tabacaria','headshop'],jsonb_build_object('collection_slug','cardapio-baita-v14','sort_order',90),'pending_validation');

  prod_jager_id := pg_temp.m037_upsert_node(baita_persona_id,'product','licor-jagermeister-700ml','Licor Jagermeister 700ml','Licor amargo alemao com 56 ervas, raizes e especiarias. Servido bem gelado, classico de bar.',ARRAY['licor','jagermeister','destilado','premium'],jsonb_build_object('collection_slug','cardapio-baita-v14','category_slug','destilados-premium','volume_ml',700,'source_file','BAITA_MENU_SYSTEM_v14_2.md'),'pending_validation');
  prod_patagonia_id := pg_temp.m037_upsert_node(baita_persona_id,'product','patagonia-weisse-473ml','Patagonia Weisse 473ml','Cerveja de trigo argentina, refrescante e frutada.',ARRAY['cerveja','weisse','trigo','patagonia','premium'],jsonb_build_object('collection_slug','cardapio-baita-v14','category_slug','cervejas-premium','volume_ml',473,'source_file','BAITA_MENU_SYSTEM_v14_2.md'),'pending_validation');
  prod_suspeito_id := pg_temp.m037_upsert_node(baita_persona_id,'product','vinho-suspeito-750ml','Vinho Suspeito 750ml','Vinho natural brasileiro, rotulo Suspeito, em variacoes para o cardapio.',ARRAY['vinho','natural','suspeito'],jsonb_build_object('collection_slug','cardapio-baita-v14','category_slug','vinhos-e-espumantes','volume_ml',750,'source_file','BAITA_MENU_SYSTEM_v14_2.md'),'pending_validation');
  prod_lagunitas_id := pg_temp.m037_upsert_node(baita_persona_id,'product','lagunitas-daytime-355ml','Lagunitas Daytime Session IPA 355ml','Session IPA da Lagunitas California, leve e aromatica.',ARRAY['cerveja','ipa','session','lagunitas','premium'],jsonb_build_object('collection_slug','cardapio-baita-v14','category_slug','cervejas-premium','volume_ml',355,'source_file','BAITA_MENU_SYSTEM_v14_2.md'),'pending_validation');

  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, persona_node_id, brand_id, 'contains', 1.0, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, brand_id, collection_id, 'brand_has_collection', 0.9, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, briefing_id, 'collection_has_briefing', 0.85, primary_meta);

  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, cat_cervejas_premium_id, 'collection_has_category', 0.85, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, cat_cervejas_id, 'collection_has_category', 0.85, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, cat_destilados_premium_id, 'collection_has_category', 0.85, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, cat_a_noite_pede_id, 'collection_has_category', 0.85, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, cat_vinhos_espumantes_id, 'collection_has_category', 0.85, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, cat_energia_drinks_id, 'collection_has_category', 0.85, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, cat_bateu_fome_id, 'collection_has_category', 0.85, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, cat_munchies_id, 'collection_has_category', 0.85, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, collection_id, cat_headshop_id, 'collection_has_category', 0.85, primary_meta);

  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, cat_destilados_premium_id, prod_jager_id, 'category_has_product', 0.86, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, cat_cervejas_premium_id, prod_patagonia_id, 'category_has_product', 0.86, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, cat_vinhos_espumantes_id, prod_suspeito_id, 'category_has_product', 0.86, primary_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, cat_cervejas_premium_id, prod_lagunitas_id, 'category_has_product', 0.86, primary_meta);

  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, prod_jager_id, collection_id, 'part_of_collection', 0.70, aux_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, prod_patagonia_id, collection_id, 'part_of_collection', 0.70, aux_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, prod_suspeito_id, collection_id, 'part_of_collection', 0.70, aux_meta);
  PERFORM pg_temp.m037_upsert_edge(baita_persona_id, prod_lagunitas_id, collection_id, 'part_of_collection', 0.70, aux_meta);
END$$;
