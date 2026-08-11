-- Read-path and validator hardening using existing tables only.

CREATE INDEX IF NOT EXISTS idx_messages_lead_created_id_desc
  ON public.messages(lead_id,created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS idx_lead_buffer_claim_batch_created
  ON public.lead_buffer(batch_key,created_at,id)
  WHERE direction='inbound' AND status IN ('buffered','retry');

CREATE OR REPLACE FUNCTION public.messages_page(
  p_lead_id bigint,p_limit integer DEFAULT 50,
  p_after_created_at timestamptz DEFAULT NULL,p_after_id bigint DEFAULT NULL,
  p_before_created_at timestamptz DEFAULT NULL,p_before_id bigint DEFAULT NULL
)
RETURNS SETOF public.messages
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp
AS $$
  SELECT m.* FROM public.messages m
   WHERE m.lead_id=p_lead_id
     AND (p_after_created_at IS NULL OR (m.created_at,m.id)>(p_after_created_at,coalesce(p_after_id,0)))
     AND (p_before_created_at IS NULL OR (m.created_at,m.id)<(p_before_created_at,coalesce(p_before_id,9223372036854775807)))
     AND NOT (p_after_created_at IS NOT NULL AND p_before_created_at IS NOT NULL)
   ORDER BY
     CASE WHEN p_after_created_at IS NULL THEN m.created_at END DESC,
     CASE WHEN p_after_created_at IS NULL THEN m.id END DESC,
     CASE WHEN p_after_created_at IS NOT NULL THEN m.created_at END ASC,
     CASE WHEN p_after_created_at IS NOT NULL THEN m.id END ASC
   LIMIT greatest(1,least(coalesce(p_limit,50),101));
$$;

CREATE OR REPLACE FUNCTION public.graph_turn_context_batch_v3(
  p_persona_id uuid,p_lead_ref bigint,p_message_limit integer DEFAULT 8
)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp
AS $$
  WITH publication AS (
    SELECT * FROM public.graph_publications
     WHERE persona_id=p_persona_id AND status='active' LIMIT 1
  ), ledger AS (
    SELECT * FROM public.conversation_ledgers
     WHERE persona_id=p_persona_id AND lead_ref=p_lead_ref LIMIT 1
  ), facts AS (
    SELECT coalesce(jsonb_agg(to_jsonb(f) ORDER BY f.field_key,f.revision),'[]'::jsonb) value
      FROM public.conversation_facts f JOIN ledger l ON l.id=f.ledger_id WHERE f.is_current
  ), branches AS (
    SELECT coalesce(jsonb_agg(to_jsonb(b) ORDER BY b.added_at),'[]'::jsonb) value
      FROM public.conversation_ledger_branches b JOIN ledger l ON l.id=b.ledger_id WHERE b.state='active'
  ), messages AS (
    SELECT coalesce(jsonb_agg(to_jsonb(m) ORDER BY m.created_at,m.id),'[]'::jsonb) value FROM (
      SELECT id,lead_id,role,content,direction,external_message_id,created_at
        FROM public.messages WHERE lead_id=p_lead_ref
       ORDER BY created_at DESC,id DESC LIMIT greatest(1,least(coalesce(p_message_limit,8),20))
    ) m
  ) SELECT jsonb_build_object(
    'publication',(SELECT to_jsonb(publication) FROM publication),
    'ledger',(SELECT to_jsonb(ledger) FROM ledger),
    'facts',(SELECT value FROM facts),'branches',(SELECT value FROM branches),
    'messages',(SELECT value FROM messages));
$$;

CREATE OR REPLACE FUNCTION public.graph_branch_package_v3(
  p_publication_id uuid,p_branch_node_id text,p_chunk_ids uuid[] DEFAULT '{}',
  p_node_ids text[] DEFAULT '{}',p_limit integer DEFAULT 12
)
RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp
AS $$
  WITH contract AS (
    SELECT * FROM public.graph_branch_contracts
     WHERE publication_id=p_publication_id AND branch_node_id=p_branch_node_id LIMIT 1
  ), chunks AS (
    SELECT coalesce(jsonb_agg(to_jsonb(c) ORDER BY c.chunk_index,c.id),'[]'::jsonb) value FROM (
      SELECT id,rag_entry_id,source_graph_node_id,branch_anchor_node_id,chunk_text,
             chunk_summary,chunk_kind,chunk_checksum,path_checksum,metadata,chunk_index
        FROM public.knowledge_rag_chunks
       WHERE publication_id=p_publication_id AND branch_anchor_node_id=p_branch_node_id
         AND (coalesce(array_length(p_chunk_ids,1),0)=0 AND coalesce(array_length(p_node_ids,1),0)=0
              OR id=ANY(p_chunk_ids) OR source_graph_node_id=ANY(p_node_ids))
       ORDER BY CASE WHEN source_graph_node_id=ANY(p_node_ids) THEN 0
                     WHEN id=ANY(p_chunk_ids) THEN 1 ELSE 2 END,chunk_index,id
       LIMIT greatest(1,least(coalesce(p_limit,12),12))
    ) c
  ) SELECT jsonb_build_object('contract',(SELECT to_jsonb(contract) FROM contract),
                              'chunks',(SELECT value FROM chunks));
$$;

CREATE OR REPLACE FUNCTION public.claim_wa_validator_session(p_session_id text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE v_row public.wa_validator_sessions%ROWTYPE; v_status text; v_count integer;
BEGIN
  SELECT * INTO v_row FROM public.wa_validator_sessions WHERE id=p_session_id FOR UPDATE;
  IF v_row.id IS NULL THEN RAISE EXCEPTION 'validator session not found' USING ERRCODE='P0002'; END IF;
  v_status:=coalesce(v_row.data->>'status','ready');
  IF v_status<>'ready' THEN
    RETURN jsonb_build_object('claimed',false,'state',v_status,'session',v_row.data);
  END IF;
  SELECT count(*) INTO v_count FROM public.wa_validator_sessions s
   WHERE s.persona_slug=v_row.persona_slug AND s.id<>v_row.id
     AND s.data->>'status' IN ('starting','running')
     AND s.updated_at>now()-interval '10 minutes';
  IF v_count>=2 THEN
    RETURN jsonb_build_object('claimed',false,'state','rate_limited','session',v_row.data);
  END IF;
  SELECT count(*) INTO v_count FROM public.wa_validator_sessions s
   WHERE s.persona_slug=v_row.persona_slug AND s.data->>'status' IN ('error','failed')
     AND s.updated_at>now()-interval '10 minutes';
  IF v_count>=3 THEN
    RETURN jsonb_build_object('claimed',false,'state','circuit_open','session',v_row.data);
  END IF;
  UPDATE public.wa_validator_sessions SET
    data=jsonb_set(jsonb_set(data,'{status}','"running"'::jsonb,true),
      '{claimed_at}',to_jsonb(now()),true),updated_at=now()
   WHERE id=p_session_id RETURNING * INTO v_row;
  RETURN jsonb_build_object('claimed',true,'state','running','session',v_row.data);
END; $$;

REVOKE ALL ON FUNCTION public.graph_turn_context_batch_v3(uuid,bigint,integer) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.graph_branch_package_v3(uuid,text,uuid[],text[],integer) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.claim_wa_validator_session(text) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.messages_page(bigint,integer,timestamptz,bigint,timestamptz,bigint) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.graph_turn_context_batch_v3(uuid,bigint,integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.graph_branch_package_v3(uuid,text,uuid[],text[],integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_wa_validator_session(text) TO service_role;
GRANT EXECUTE ON FUNCTION public.messages_page(bigint,integer,timestamptz,bigint,timestamptz,bigint) TO service_role;
