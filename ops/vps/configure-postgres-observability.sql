-- Apply in a separate authorized database window. shared_preload_libraries
-- requires a controlled PostgreSQL restart before CREATE EXTENSION succeeds.
ALTER SYSTEM SET shared_preload_libraries = 'pg_stat_statements';
ALTER SYSTEM SET statement_timeout = '30s';
ALTER SYSTEM SET idle_in_transaction_session_timeout = '60s';

-- After the controlled restart:
-- CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
-- SELECT pg_reload_conf();
