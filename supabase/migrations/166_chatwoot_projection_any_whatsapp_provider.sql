-- Chatwoot is a projection of the canonical ledger, whatever phone carries it:
-- an Evolution (linked phone) binding projects exactly like a Meta Cloud one.
-- Same body as migration 164; only the provider guard is widened.
CREATE OR REPLACE FUNCTION public.enqueue_chatwoot_projection_v1(
  p_channel_binding_id uuid,
  p_limit integer DEFAULT 500
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE
  v_binding public.workflow_bindings%ROWTYPE;
  v_count integer := 0;
BEGIN
  SELECT * INTO v_binding FROM public.workflow_bindings
   WHERE id=p_channel_binding_id AND active=true
     AND provider IN ('meta_cloud','evolution_baileys');
  IF NOT FOUND THEN
    RAISE EXCEPTION 'active WhatsApp binding required' USING ERRCODE='23514';
  END IF;

  INSERT INTO public.chatwoot_bridge_operations(
    source_kind, source_id, operation, channel_binding_id, lead_ref, brain_message_id
  )
  SELECT 'brain_message', m.id::text, 'project_message', p_channel_binding_id,
         l.id, m.id
    FROM public.messages m
    JOIN public.leads l ON l.id=m.lead_id
   WHERE l.channel_binding_id=p_channel_binding_id
     AND (m.direction='inbound'
       OR (m.direction='outbound' AND m.status IN ('sent','delivered','read')))
     AND NOT (m.direction='outbound' AND coalesce(m.metadata,'{}'::jsonb) ? 'chatwoot_message_id')
     AND (m.channel IS NULL OR m.channel='whatsapp')
     AND coalesce(m.metadata->>'validation_transport','false') <> 'true'
     AND NOT EXISTS (
       SELECT 1 FROM public.chatwoot_bridge_operations o
        WHERE o.source_kind='brain_message' AND o.source_id=m.id::text
     )
   ORDER BY m.created_at, m.id
   LIMIT greatest(1,least(coalesce(p_limit,500),2000))
  ON CONFLICT (source_kind,source_id) DO NOTHING;
  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

REVOKE ALL ON FUNCTION public.enqueue_chatwoot_projection_v1(uuid,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.enqueue_chatwoot_projection_v1(uuid,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.enqueue_chatwoot_projection_v1(uuid,integer) TO brain_transport;
NOTIFY pgrst, 'reload schema';
