-- Filter validator rows before the operator-facing page limit. Migration 150
-- filtered one already-paged result, which could leave a page full of tests
-- and hide real messages behind it.
CREATE OR REPLACE FUNCTION public.list_actionable_message_queue_v1(
  p_persona_ids uuid[] DEFAULT NULL, p_origin text DEFAULT NULL, p_status text DEFAULT NULL,
  p_offset integer DEFAULT 0, p_limit integer DEFAULT 50
) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
  WITH RECURSIVE pages AS (
    SELECT 0 AS page_offset,
      public.list_actionable_message_queue_v149(p_persona_ids,p_origin,p_status,p_offset,100) AS data
    UNION ALL
    SELECT pages.page_offset + 100,
      public.list_actionable_message_queue_v149(
        p_persona_ids,p_origin,p_status,p_offset + pages.page_offset + 100,100
      ) AS data
    FROM pages
    WHERE jsonb_array_length(CASE WHEN jsonb_typeof(pages.data->'items')='array' THEN pages.data->'items' ELSE '[]'::jsonb END)=100
      AND pages.page_offset < 10000
  ), expanded AS (
    SELECT pages.page_offset, expanded.ordinality, expanded.item
    FROM pages
    CROSS JOIN LATERAL jsonb_array_elements(
      CASE WHEN jsonb_typeof(pages.data->'items')='array' THEN pages.data->'items' ELSE '[]'::jsonb END
    ) WITH ORDINALITY AS expanded(item, ordinality)
  ), kept AS (
    SELECT expanded.page_offset, expanded.ordinality, expanded.item
    FROM expanded
    WHERE NOT EXISTS (
      SELECT 1
      FROM public.lead_buffer b
      WHERE b.id=(expanded.item->>'id')::uuid
        AND (
          coalesce(b.correlation_id,'') ILIKE '%validator%'
          OR coalesce(b.payload->>'sender','')='wa-validator'
          OR coalesce(b.payload->>'validation_transport','')='true'
          OR coalesce(b.payload->>'provider','')='internal_validator'
        )
    )
  )
  SELECT jsonb_build_object(
    'items',coalesce((SELECT jsonb_agg(item ORDER BY page_offset,ordinality)
      FROM (SELECT item,page_offset,ordinality FROM kept ORDER BY page_offset,ordinality
            LIMIT greatest(least(p_limit,100),1)) visible),'[]'::jsonb),
    'next_offset',NULL
  );
$$;

REVOKE ALL ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) TO service_role,brain_control_plane;
NOTIFY pgrst, 'reload schema';
