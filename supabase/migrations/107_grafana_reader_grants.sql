-- Read-only observability access for the new Grafana service (profile
-- "observability" in docker-compose.yml). The grafana_reader role itself is
-- always created by db-bootstrap's inline script (unconditionally, same as
-- anon/authenticated/service_role) so these GRANTs never fail on a missing
-- role on a deploy that hasn't set GRAFANA_PG_PASSWORD yet -- it only gains
-- LOGIN/a password there, conditionally, when that env var is set.
--
-- Deliberately SELECT-only, and only on the tables the observability plan
-- actually reads (agent_logs/system_events/n8n_executions for the new
-- trace_id-linked events from migration 106, messages/leads for volume and
-- lead-level rollups). No INSERT/UPDATE/DELETE, ever -- Grafana query
-- panels run arbitrary SQL from whoever can edit a dashboard, and the whole
-- point of this role is that a mistake or a compromised panel can't mutate
-- production data.

GRANT USAGE ON SCHEMA public TO grafana_reader;

GRANT SELECT ON
  public.agent_logs,
  public.system_events,
  public.n8n_executions,
  public.messages,
  public.leads
TO grafana_reader;
