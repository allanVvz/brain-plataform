-- An autonomous notice is never an inbound replay.  Create its queue row,
-- message projection and proof in one transaction, leaving it inert on any
-- error.  The transport service owns invocation; the runtime only supplies
-- published policy/copy evidence.
CREATE OR REPLACE FUNCTION public.enqueue_proactive_with_proof_v1(
  p_buffer jsonb, p_message jsonb, p_publication_id uuid,
  p_evidence_node_ids jsonb, p_proof_result jsonb, p_model_proposal jsonb DEFAULT '{}'::jsonb
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_envelope jsonb; v_buffer_id uuid; v_proof jsonb; v_available timestamptz;
BEGIN
  IF coalesce(p_buffer->>'message_origin','') <> 'proactive'
     OR coalesce(p_buffer->>'status','') <> 'awaiting_proof' THEN
    RAISE EXCEPTION 'proactive queue must start awaiting proof' USING ERRCODE='23514';
  END IF;
  v_envelope := public.enqueue_whatsapp_envelope(p_buffer,p_message);
  v_buffer_id := (v_envelope->>'buffer_id')::uuid;
  v_proof := public.commit_proactive_queue_proof_v1(
    v_buffer_id,p_publication_id,p_evidence_node_ids,p_proof_result,p_model_proposal
  );
  v_available := nullif(p_buffer->>'available_at','')::timestamptz;
  UPDATE public.lead_buffer SET status=CASE WHEN coalesce(v_available,now()) > now() THEN 'buffered' ELSE 'pending_send' END,
    available_at=coalesce(v_available,now()), updated_at=now()
    WHERE id=v_buffer_id AND status='awaiting_proof';
  RETURN v_envelope || jsonb_build_object('proof',v_proof);
END; $$;

REVOKE ALL ON FUNCTION public.enqueue_proactive_with_proof_v1(jsonb,jsonb,uuid,jsonb,jsonb,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.enqueue_proactive_with_proof_v1(jsonb,jsonb,uuid,jsonb,jsonb,jsonb) TO brain_transport;
NOTIFY pgrst, 'reload schema';
