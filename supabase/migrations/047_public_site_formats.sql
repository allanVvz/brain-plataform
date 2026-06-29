-- 047_public_site_formats.sql
-- Registry of public site output formats consumed by persona.config.public_site.
-- New formats are added here/by DB operations, not from the dashboard UI.

CREATE TABLE IF NOT EXISTS public.public_site_formats (
  key text PRIMARY KEY,
  label text NOT NULL,
  description text,
  default_route_prefix text NOT NULL DEFAULT '',
  default_collection_type text NOT NULL DEFAULT 'menu',
  structure jsonb NOT NULL DEFAULT '{}'::jsonb,
  enabled boolean NOT NULL DEFAULT true,
  sort_order integer NOT NULL DEFAULT 100,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.public_site_formats IS
  'Fixed registry of public site outputs such as cardapio, landing_page and catalogo_roupas.';
COMMENT ON COLUMN public.public_site_formats.structure IS
  'Renderer hints for the external public-sites repository; never stores secrets.';

ALTER TABLE public.public_site_formats ENABLE ROW LEVEL SECURITY;

INSERT INTO public.public_site_formats (
  key,
  label,
  description,
  default_route_prefix,
  default_collection_type,
  structure,
  enabled,
  sort_order
) VALUES
  (
    'cardapio',
    'Cardapio',
    'Menu comercial com categorias, produtos, FAQ, assets e CTA para WhatsApp.',
    'cardapio',
    'menu',
    '{"sections":["hero","categories","products","faq","whatsapp_cta"],"primary_nodes":["brand","product_group","product","faq","asset"]}'::jsonb,
    true,
    10
  ),
  (
    'landing_page',
    'Landing page',
    'Pagina de campanha/oferta com hero, prova, produto, FAQ e CTA para WhatsApp.',
    'landing',
    'campaign',
    '{"sections":["hero","campaign","offer","products","faq","whatsapp_cta"],"primary_nodes":["brand","campaign","offer","product","faq","asset"]}'::jsonb,
    true,
    20
  ),
  (
    'catalogo_roupas',
    'Catalogo de roupas',
    'Catalogo visual de moda com colecoes, grades de produto, assets e CTA para WhatsApp.',
    'catalogo',
    'catalog',
    '{"sections":["hero","collections","product_grid","size_notes","faq","whatsapp_cta"],"primary_nodes":["brand","product_group","product","faq","asset"]}'::jsonb,
    true,
    30
  )
ON CONFLICT (key) DO UPDATE SET
  label = EXCLUDED.label,
  description = EXCLUDED.description,
  default_route_prefix = EXCLUDED.default_route_prefix,
  default_collection_type = EXCLUDED.default_collection_type,
  structure = EXCLUDED.structure,
  enabled = EXCLUDED.enabled,
  sort_order = EXCLUDED.sort_order,
  updated_at = now();
