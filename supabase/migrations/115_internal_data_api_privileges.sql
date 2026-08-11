-- Keep the public schema available to the backend service role without making
-- internal CRM/RAG/conversation data a browser-facing Data API. No new storage
-- is introduced by this migration.

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO service_role;

DO $block$
DECLARE
  item record;
BEGIN
  FOR item IN
    SELECT n.nspname AS schema_name, c.relname AS object_name, c.relkind
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relkind IN ('r', 'p', 'v', 'm', 'S')
  LOOP
    IF item.relkind = 'S' THEN
      EXECUTE format('REVOKE ALL ON SEQUENCE %I.%I FROM PUBLIC, anon, authenticated',
                     item.schema_name, item.object_name);
      EXECUTE format('GRANT ALL ON SEQUENCE %I.%I TO service_role',
                     item.schema_name, item.object_name);
    ELSE
      EXECUTE format('REVOKE ALL ON TABLE %I.%I FROM PUBLIC, anon, authenticated',
                     item.schema_name, item.object_name);
      EXECUTE format('GRANT ALL ON TABLE %I.%I TO service_role',
                     item.schema_name, item.object_name);
    END IF;
    IF item.relkind IN ('r', 'p') THEN
      EXECUTE format('ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',
                     item.schema_name, item.object_name);
    END IF;
  END LOOP;

  FOR item IN
    SELECT n.nspname AS schema_name, p.proname AS object_name,
           pg_get_function_identity_arguments(p.oid) AS identity_arguments
      FROM pg_proc p
      JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = 'public'
  LOOP
    EXECUTE format('REVOKE ALL ON FUNCTION %I.%I(%s) FROM PUBLIC, anon, authenticated',
                   item.schema_name, item.object_name, item.identity_arguments);
    EXECUTE format('GRANT EXECUTE ON FUNCTION %I.%I(%s) TO service_role',
                   item.schema_name, item.object_name, item.identity_arguments);
  END LOOP;
END
$block$;

-- Fail closed for objects introduced by later migrations. Migration owners and
-- superusers retain ownership; application access is explicitly service-role.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT ALL ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT EXECUTE ON FUNCTIONS TO service_role;

NOTIFY pgrst, 'reload schema';
