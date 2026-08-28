-- Expand-only database identities for the microservice cutover.
--
-- This migration deliberately does not remove the legacy service_role grants:
-- legacy processes remain live until the separately authorized cutover.  The
-- new services instead receive independent, NOLOGIN identities with explicit
-- table and function grants.  Each deployment receives a signed PostgREST JWT
-- whose role claim names only its own identity.
--
-- No storage is introduced here.  Apply only in the approved cutover window.

DO $$
DECLARE
  role_name text;
BEGIN
  FOREACH role_name IN ARRAY ARRAY[
    'brain_gateway', 'brain_control_plane', 'brain_runtime', 'brain_transport'
  ]
  LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN NOINHERIT BYPASSRLS', role_name);
    END IF;
    -- Internal tables are RLS-enabled and historically expose no persona
    -- policies to backend roles.  These backend-only roles therefore bypass
    -- RLS, while the exact object grants below remain their hard boundary.
    -- Persona authorization is revalidated by each service before every read.
    EXECUTE format('ALTER ROLE %I NOLOGIN NOINHERIT BYPASSRLS', role_name);
    EXECUTE format('REVOKE service_role FROM %I', role_name);
    EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', role_name);
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticator') THEN
      EXECUTE format('GRANT %I TO authenticator', role_name);
    END IF;
  END LOOP;
END
$$;

-- The gateway obtains the browser session from the control plane over its
-- private interface.  It intentionally has no direct table or routine grant.

-- Grant table privileges only when the table exists.  This keeps disposable
-- migration-test databases usable while remaining an exact allow-list in a
-- production schema.
DO $$
DECLARE
  role_name text;
  table_name text;
  writable_tables text[];
  readable_tables text[];
BEGIN
  FOR role_name, readable_tables, writable_tables IN
    SELECT * FROM (VALUES
      (
        'brain_control_plane',
        ARRAY[
          'agent_logs','agent_sessions','app_users','approved_knowledge_snapshots',
          'asset_readings','assets','audiences','brand_profiles','contact_consents',
          'conversation_facts','conversation_journeys','conversation_ledger_branches',
          'conversation_ledgers','flow_insights','graph_publications','integration_status',
          'kb_entries','knowledge_edges','knowledge_intake_messages','knowledge_items',
          'knowledge_node_type_registry','knowledge_nodes','knowledge_rag_chunks',
          'knowledge_rag_entries','knowledge_rag_links','knowledge_relation_type_registry',
          'knowledge_sources','lead_audience_memberships','lead_buffer','lead_import_batches',
          'lead_import_rows','leads','messages','n8n_executions','personas','pipeline_status',
          'public_site_formats','sofia_plan_sessions','sync_logs','sync_runs','system_events',
          'system_health','user_integration_connections','user_persona_access','workflow_bindings'
        ]::text[],
        ARRAY[
          'agent_logs','agent_sessions','app_users','approved_knowledge_snapshots',
          'asset_readings','assets','audiences','brand_profiles','contact_consents',
          'flow_insights','graph_publications','integration_status','kb_entries',
          'knowledge_edges','knowledge_intake_messages','knowledge_items',
          'knowledge_node_type_registry','knowledge_nodes','knowledge_rag_chunks',
          'knowledge_rag_entries','knowledge_rag_links','knowledge_relation_type_registry',
          'knowledge_sources','lead_audience_memberships','lead_import_batches','lead_import_rows',
          'leads','n8n_executions','personas','pipeline_status','public_site_formats',
          'sofia_plan_sessions','sync_logs','sync_runs','system_events','system_health',
          'user_integration_connections','user_persona_access','workflow_bindings'
        ]::text[]
      ),
      (
        'brain_runtime',
        ARRAY[
          'agent_logs','app_users','approved_knowledge_snapshots','assets','audiences',
          'contact_consents','conversation_facts','conversation_journeys',
          'conversation_ledger_branches','conversation_ledgers','conversation_turn_proofs',
          'flow_insights','graph_publications','integration_status','kb_entries','knowledge_edges',
          'knowledge_intake_messages','knowledge_items','knowledge_nodes','knowledge_rag_chunks',
          'knowledge_rag_entries','knowledge_rag_links','knowledge_sources',
          'lead_audience_memberships','lead_buffer','lead_import_batches','lead_import_rows',
          'leads','messages','n8n_executions','personas','pipeline_status','sofia_plan_sessions',
          'sync_logs','sync_runs','system_events','system_health','user_integration_connections',
          'wa_validator_sessions','workflow_bindings'
        ]::text[],
        ARRAY[
          'agent_logs','contact_consents','conversation_facts','conversation_journeys',
          'conversation_ledger_branches','conversation_ledgers','conversation_turn_proofs',
          'flow_insights','leads','pipeline_status','system_events','system_health',
          'wa_validator_sessions'
        ]::text[]
      ),
      (
        'brain_transport',
        ARRAY[
          'agent_logs','app_users','asset_readings','assets','audiences','conversation_facts',
          'conversation_journeys','conversation_ledger_branches','conversation_ledgers',
          'graph_publications','integration_status','kb_entries','knowledge_edges',
          'knowledge_intake_messages','knowledge_items','knowledge_nodes','knowledge_rag_chunks',
          'knowledge_rag_entries','lead_audience_memberships','lead_buffer','leads','messages',
          'personas','pipeline_status','system_events','system_health',
          'user_integration_connections','workflow_bindings'
        ]::text[],
        ARRAY[
          'agent_logs','asset_readings','assets','integration_status','lead_buffer','leads',
          'messages','pipeline_status','system_events','system_health','workflow_bindings'
        ]::text[]
      )
    ) AS grants(role_name, readable_tables, writable_tables)
  LOOP
    FOREACH table_name IN ARRAY readable_tables LOOP
      IF to_regclass('public.' || table_name) IS NOT NULL THEN
        EXECUTE format('GRANT SELECT ON TABLE public.%I TO %I', table_name, role_name);
      END IF;
    END LOOP;
    FOREACH table_name IN ARRAY writable_tables LOOP
      IF to_regclass('public.' || table_name) IS NOT NULL THEN
        EXECUTE format('GRANT INSERT, UPDATE, DELETE ON TABLE public.%I TO %I', table_name, role_name);
      END IF;
    END LOOP;
  END LOOP;
END
$$;

-- Sequence access is derived only from the explicit writable table allow-list;
-- it never grants access to every sequence in public.
DO $$
DECLARE
  role_name text;
  table_name text;
  sequence_name text;
BEGIN
  FOR role_name, table_name IN
    SELECT * FROM (VALUES
      ('brain_control_plane','agent_logs'),('brain_control_plane','agent_sessions'),
      ('brain_control_plane','app_users'),('brain_control_plane','assets'),
      ('brain_control_plane','audiences'),('brain_control_plane','kb_entries'),
      ('brain_control_plane','knowledge_items'),('brain_control_plane','leads'),
      ('brain_runtime','agent_logs'),('brain_runtime','leads'),
      ('brain_transport','agent_logs'),('brain_transport','assets'),
      ('brain_transport','lead_buffer'),('brain_transport','leads'),('brain_transport','messages')
    ) AS writable(role_name, table_name)
  LOOP
    FOR sequence_name IN
      SELECT DISTINCT seq.relname
      FROM pg_class tbl
      JOIN pg_namespace ns ON ns.oid = tbl.relnamespace AND ns.nspname = 'public'
      JOIN pg_depend dep ON dep.refobjid = tbl.oid AND dep.deptype IN ('a', 'i')
      JOIN pg_class seq ON seq.oid = dep.objid AND seq.relkind = 'S'
      WHERE tbl.relname = table_name
    LOOP
      EXECUTE format(
        'GRANT USAGE, SELECT ON SEQUENCE public.%I TO %I', sequence_name, role_name
      );
    END LOOP;
  END LOOP;
END
$$;

-- Routine execution is also allow-listed by name and resolved with its exact
-- identity arguments so overloads are not accidentally granted.
DO $$
DECLARE
  role_name text;
  function_name text;
  identity_arguments text;
BEGIN
  FOR role_name, function_name IN
    SELECT * FROM (VALUES
      ('brain_control_plane','activate_persona_whatsapp_binding'),
      ('brain_control_plane','conversation_carry_over_facts_by_lead_v1'),
      ('brain_control_plane','enqueue_whatsapp_envelope'),
      ('brain_control_plane','graph_branch_package_v3'),('brain_control_plane','graph_branch_rank_v3'),
      ('brain_control_plane','graph_faq_search_v3'),('brain_control_plane','graph_hybrid_search_v3'),
      ('brain_control_plane','graph_service_rank_v3'),('brain_control_plane','graph_turn_context_batch_v3'),
      ('brain_control_plane','graph_turn_context_batch_v4'),('brain_control_plane','messages_page'),
      ('brain_control_plane','record_contact_consent_v1'),('brain_control_plane','replace_lead_semantic_group_v1'),
      ('brain_runtime','audit_conversation_turn_v3'),('brain_runtime','backdate_lead_messages'),
      ('brain_runtime','claim_conversation_commit'),('brain_runtime','claim_inactivity_recovery_candidate_v1'),
      ('brain_runtime','claim_next_wa_validator_session'),('brain_runtime','claim_wa_validator_session'),
      ('brain_runtime','cleanup_wa_validator_artifacts'),('brain_runtime','commit_graph_turn_and_outbox_v3'),
      ('brain_runtime','commit_graph_turn_and_outbox_v4'),('brain_runtime','commit_graph_turn_v3'),
      ('brain_runtime','complete_conversation_commit'),('brain_runtime','conversation_carry_over_facts_by_lead_v1'),
      ('brain_runtime','enqueue_wa_validator_session'),('brain_runtime','enqueue_whatsapp_envelope'),
      ('brain_runtime','graph_branch_package_v3'),('brain_runtime','graph_branch_rank_v3'),
      ('brain_runtime','graph_faq_search_v3'),('brain_runtime','graph_hybrid_search_v3'),
      ('brain_runtime','graph_service_rank_v3'),('brain_runtime','graph_turn_context_batch_v3'),
      ('brain_runtime','graph_turn_context_batch_v4'),('brain_runtime','handoff_whatsapp_lead'),
      ('brain_runtime','handoff_whatsapp_lead_state'),('brain_runtime','record_contact_consent_v1'),
      ('brain_runtime','record_conversation_journey_event_v1'),('brain_runtime','record_whatsapp_safety_violation'),
      ('brain_runtime','replace_lead_semantic_group_v1'),('brain_runtime','requeue_waiting_human_whatsapp_buffer'),
      ('brain_runtime','set_conversation_journey_state_v1'),('brain_runtime','transition_sales_conversion_status_v1'),
      ('brain_transport','claim_whatsapp_buffer'),('brain_transport','complete_whatsapp_outbound_result'),
      ('brain_transport','conversation_carry_over_facts_by_lead_v1'),('brain_transport','enqueue_whatsapp_envelope'),
      ('brain_transport','graph_branch_package_v3'),('brain_transport','graph_branch_rank_v3'),
      ('brain_transport','graph_faq_search_v3'),('brain_transport','graph_hybrid_search_v3'),
      ('brain_transport','graph_service_rank_v3'),('brain_transport','graph_turn_context_batch_v3'),
      ('brain_transport','graph_turn_context_batch_v4'),('brain_transport','handoff_whatsapp_lead'),
      ('brain_transport','mark_whatsapp_attempt'),('brain_transport','messages_page'),
      ('brain_transport','reconcile_committed_graph_inbound'),('brain_transport','reconcile_whatsapp_delivery'),
      ('brain_transport','record_whatsapp_safety_violation'),('brain_transport','resolve_media_buffer')
    ) AS allowed(role_name, function_name)
  LOOP
    FOR identity_arguments IN
      SELECT pg_get_function_identity_arguments(p.oid)
      FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
      WHERE n.nspname = 'public' AND p.proname = function_name
    LOOP
      EXECUTE format('GRANT EXECUTE ON FUNCTION public.%I(%s) TO %I',
                     function_name, identity_arguments, role_name);
    END LOOP;
  END LOOP;
END
$$;

NOTIFY pgrst, 'reload schema';
