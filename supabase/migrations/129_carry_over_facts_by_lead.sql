-- Carry-over facts sourced from the lead's full registered history (every
-- journey), not just the immediately preceding one -- confirmed live
-- 2026-08-18: nome_cliente survived one journey-close-then-reopen hop but
-- vanished on a second consecutive closure because the old lookup
-- (conversation_carry_over_facts_v1) is scoped to a single p_journey_id.
-- Jornadas/pedidos ja registrados sao a fonte de verdade da identidade do
-- cliente, entao a busca de carry_over passa a cobrir todo o historico.

CREATE OR REPLACE FUNCTION public.conversation_carry_over_facts_by_lead_v1(
  p_persona_id uuid, p_lead_ref bigint, p_field_keys text[]
)
RETURNS SETOF public.conversation_facts
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public,pg_temp AS $$
  -- conversation_ledgers already carries its own persona_id/lead_ref (one
  -- ledger per journey, denormalized) -- no need to join conversation_journeys.
  SELECT DISTINCT ON (f.field_key) f.*
    FROM public.conversation_facts f
    JOIN public.conversation_ledgers l ON l.id = f.ledger_id
   WHERE l.persona_id = p_persona_id
     AND l.lead_ref = p_lead_ref
     AND f.field_key = ANY(p_field_keys)
     AND f.is_current AND f.status = 'known'
     AND coalesce(f.metadata->'confirmation'->>'transition','confirmed')
         NOT IN ('pending','rejected')
   ORDER BY f.field_key, f.created_at DESC;
$$;

REVOKE ALL ON FUNCTION public.conversation_carry_over_facts_by_lead_v1(uuid,bigint,text[]) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.conversation_carry_over_facts_by_lead_v1(uuid,bigint,text[]) TO service_role;
