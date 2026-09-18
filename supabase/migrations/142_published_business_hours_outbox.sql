-- A proof-gated AI reply is inserted as awaiting_proof and migration 111
-- releases it by changing status to pending_send.  Preserve the schedule
-- pinned in its published graph metadata at that transition; otherwise the
-- generic proof-release function would overwrite a closed-window slot with
-- now().  No policy, copy or timezone is invented here.
CREATE OR REPLACE FUNCTION public.apply_published_outbound_schedule_v1()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_available_at timestamptz;
  v_checksum text;
BEGIN
  IF NEW.direction <> 'outbound'
     OR OLD.status <> 'awaiting_proof'
     OR NEW.status <> 'pending_send' THEN
    RETURN NEW;
  END IF;
  v_checksum := NULLIF(NEW.payload #>> '{published_business_hours,graph_checksum}', '');
  IF v_checksum IS NULL THEN
    RETURN NEW;
  END IF;
  BEGIN
    v_available_at := NULLIF(NEW.payload #>> '{available_at}', '')::timestamptz;
  EXCEPTION WHEN invalid_text_representation THEN
    RAISE EXCEPTION 'published outbound schedule is invalid' USING ERRCODE='22023';
  END;
  IF v_available_at IS NULL THEN
    RAISE EXCEPTION 'published outbound schedule is incomplete' USING ERRCODE='22023';
  END IF;
  NEW.available_at := v_available_at;
  NEW.status := CASE WHEN v_available_at > now() THEN 'buffered' ELSE 'pending_send' END;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_apply_published_outbound_schedule_v1 ON public.lead_buffer;
CREATE TRIGGER trg_apply_published_outbound_schedule_v1
BEFORE UPDATE OF status ON public.lead_buffer
FOR EACH ROW EXECUTE FUNCTION public.apply_published_outbound_schedule_v1();

REVOKE ALL ON FUNCTION public.apply_published_outbound_schedule_v1() FROM PUBLIC, anon, authenticated;
