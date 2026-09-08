-- Migration 135: least-privilege Supabase Storage access for the services
-- that actually own binary media. Expand-only: no table, policy, bucket or
-- legacy service_role privilege is changed here.

GRANT USAGE ON SCHEMA storage TO brain_control_plane, brain_transport;

GRANT SELECT ON TABLE storage.buckets TO brain_control_plane, brain_transport;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE storage.objects TO brain_control_plane;
GRANT SELECT, INSERT, UPDATE ON TABLE storage.objects TO brain_transport;

-- Storage API requests assume the JWT role after opening a database session.
-- Keep the object namespaces explicit for those assumed roles; do not add the
-- Storage schema to the gateway or conversation runtime context.
ALTER ROLE brain_control_plane SET search_path TO public, storage, extensions;
ALTER ROLE brain_transport SET search_path TO public, storage, extensions;

-- One registry row per operator upload request. The object key is derived from
-- the same token, so HTTP retries converge on one row and one object.
CREATE UNIQUE INDEX IF NOT EXISTS uq_assets_operator_upload_idempotency
  ON public.assets (persona_id, (metadata->>'upload_idempotency_key'))
  WHERE source = 'upload'
    AND nullif(metadata->>'upload_idempotency_key', '') IS NOT NULL;

-- Fail the migration if a future edit broadens the grant surface. These checks
-- intentionally inspect effective privileges, including inherited/PUBLIC
-- access, rather than trusting only the GRANT statements above.
DO $$
BEGIN
  IF NOT has_schema_privilege('brain_control_plane', 'storage', 'USAGE')
     OR NOT has_table_privilege('brain_control_plane', 'storage.buckets', 'SELECT')
     OR NOT has_table_privilege('brain_control_plane', 'storage.objects', 'SELECT,INSERT,UPDATE,DELETE')
     OR has_table_privilege('brain_control_plane', 'storage.buckets', 'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
     OR has_table_privilege('brain_control_plane', 'storage.objects', 'TRUNCATE,REFERENCES,TRIGGER') THEN
    RAISE EXCEPTION 'brain_control_plane Storage privileges are missing or excessive';
  END IF;

  IF NOT has_schema_privilege('brain_transport', 'storage', 'USAGE')
     OR NOT has_table_privilege('brain_transport', 'storage.buckets', 'SELECT')
     OR NOT has_table_privilege('brain_transport', 'storage.objects', 'SELECT,INSERT,UPDATE')
     OR has_table_privilege('brain_transport', 'storage.buckets', 'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
     OR has_table_privilege('brain_transport', 'storage.objects', 'DELETE,TRUNCATE,REFERENCES,TRIGGER') THEN
    RAISE EXCEPTION 'brain_transport Storage privileges are missing or excessive';
  END IF;

  IF has_schema_privilege('brain_runtime', 'storage', 'USAGE')
     OR has_schema_privilege('brain_gateway', 'storage', 'USAGE')
     OR has_table_privilege('brain_runtime', 'storage.buckets', 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
     OR has_table_privilege('brain_runtime', 'storage.objects', 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
     OR has_table_privilege('brain_gateway', 'storage.buckets', 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
     OR has_table_privilege('brain_gateway', 'storage.objects', 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') THEN
    RAISE EXCEPTION 'gateway or runtime unexpectedly has Storage access';
  END IF;
END
$$;

NOTIFY pgrst, 'reload schema';
