-- An absent published business-hours policy means immediate operational send.
-- Service/appointment policy remains independent of the WhatsApp send window.
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
     OR OLD.status NOT IN ('awaiting_proof','preview_ready')
     OR NEW.status <> 'pending_send' THEN
    RETURN NEW;
  END IF;

  v_checksum := nullif(NEW.payload->'published_business_hours'->>'graph_checksum','');
  IF v_checksum IS NULL THEN
    NEW.available_at := coalesce(NEW.available_at, now());
    RETURN NEW;
  END IF;

  BEGIN
    v_available_at := nullif(NEW.payload->>'available_at','')::timestamptz;
  EXCEPTION WHEN OTHERS THEN
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
