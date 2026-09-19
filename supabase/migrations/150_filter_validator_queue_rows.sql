-- Validator traffic is persisted like real WhatsApp traffic so the internal
-- canary exercises the complete path. It must never appear in the operator's
-- real-message queue. Keep the 149 projection intact and filter by the
-- persisted transport markers at the final read boundary.
ALTER FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer)
  RENAME TO list_actionable_message_queue_v149;

CREATE OR REPLACE FUNCTION public.list_actionable_message_queue_v1(
  p_persona_ids uuid[] DEFAULT NULL, p_origin text DEFAULT NULL, p_status text DEFAULT NULL,
  p_offset integer DEFAULT 0, p_limit integer DEFAULT 50
) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
  WITH raw AS (
    SELECT public.list_actionable_message_queue_v149(
      p_persona_ids,p_origin,p_status,p_offset,p_limit
    ) AS data
  ), kept AS (
    SELECT item
    FROM raw, jsonb_array_elements(
      CASE WHEN jsonb_typeof(data->'items')='array' THEN data->'items' ELSE '[]'::jsonb END
    ) AS expanded(item)
    WHERE NOT EXISTS (
      SELECT 1
      FROM public.lead_buffer b
      WHERE b.id=(item->>'id')::uuid
        AND (
          coalesce(b.correlation_id,'') ILIKE '%validator%'
          OR coalesce(b.payload->>'sender','')='wa-validator'
          OR coalesce(b.payload->>'validation_transport','')='true'
          OR coalesce(b.payload->>'provider','')='internal_validator'
        )
    )
  )
  SELECT jsonb_build_object(
    'items',coalesce((SELECT jsonb_agg(item) FROM kept),'[]'::jsonb),
    'next_offset',(SELECT data->'next_offset' FROM raw)
  );
$$;

REVOKE ALL ON FUNCTION public.list_actionable_message_queue_v149(uuid[],text,text,integer,integer) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.list_actionable_message_queue_v1(uuid[],text,text,integer,integer) TO service_role,brain_control_plane;
NOTIFY pgrst, 'reload schema';
