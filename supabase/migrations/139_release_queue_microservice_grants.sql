-- Migration 131 created isolated PostgREST roles before the release queue
-- tables and routines existed.  Later migrations must grant the owning role
-- explicitly; service_role alone is not inherited by brain_control_plane.

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'brain_control_plane') THEN
    GRANT SELECT ON TABLE public.release_batches TO brain_control_plane;
    GRANT SELECT ON TABLE public.release_batch_items TO brain_control_plane;
    GRANT EXECUTE ON FUNCTION public.register_release_batch_v1(
      uuid, text, uuid[], text, text, uuid, text, uuid, integer, time, time, text
    ) TO brain_control_plane;
    GRANT EXECUTE ON FUNCTION public.set_release_item_override_v1(
      uuid, text, text, text, timestamptz, uuid
    ) TO brain_control_plane;
    GRANT EXECUTE ON FUNCTION public.resume_safety_paused_binding_v1(
      uuid, uuid, text, text, text, uuid
    ) TO brain_control_plane;
  END IF;
END
$$;

NOTIFY pgrst, 'reload schema';
