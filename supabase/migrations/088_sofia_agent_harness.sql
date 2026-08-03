-- Durable Sofia coordinator state. All three tables are backend-only: browser
-- clients authenticate through FastAPI and never query these rows directly.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.agent_sessions (
  id text PRIMARY KEY,
  coordinator_key text NOT NULL DEFAULT 'sofia',
  user_id uuid REFERENCES public.app_users(id) ON DELETE SET NULL,
  persona_id uuid REFERENCES public.personas(id) ON DELETE CASCADE,
  selected_context jsonb NOT NULL DEFAULT '{}'::jsonb,
  graph_version bigint,
  graph_hash text,
  selected_node_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  memory_summary text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'completed', 'cancelled', 'expired')),
  revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
  expires_at timestamptz NOT NULL DEFAULT (now() + interval '30 days'),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.agent_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id text NOT NULL REFERENCES public.agent_sessions(id) ON DELETE CASCADE,
  parent_run_id uuid REFERENCES public.agent_runs(id) ON DELETE SET NULL,
  intent text NOT NULL,
  assigned_agent_key text NOT NULL,
  input_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  response_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  plan jsonb NOT NULL DEFAULT '{}'::jsonb,
  artifacts jsonb NOT NULL DEFAULT '[]'::jsonb,
  status text NOT NULL DEFAULT 'planned'
    CHECK (status IN ('planned', 'awaiting_approval', 'running', 'completed', 'failed', 'cancelled')),
  revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
  idempotency_key text NOT NULL,
  lease_owner text,
  lease_expires_at timestamptz,
  error_code text,
  error_message text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (session_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS public.agent_run_steps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES public.agent_runs(id) ON DELETE CASCADE,
  parent_step_id uuid REFERENCES public.agent_run_steps(id) ON DELETE SET NULL,
  step_order integer NOT NULL CHECK (step_order > 0),
  agent_key text NOT NULL,
  tool_name text NOT NULL,
  tool_version text NOT NULL,
  effect text NOT NULL CHECK (effect IN ('read', 'draft', 'write', 'destructive', 'external')),
  risk text NOT NULL CHECK (risk IN ('low', 'medium', 'high', 'critical')),
  schema_checksum text NOT NULL,
  input_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  output_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status text NOT NULL DEFAULT 'planned'
    CHECK (status IN ('planned', 'awaiting_approval', 'running', 'completed', 'failed', 'cancelled')),
  duration_ms integer CHECK (duration_ms IS NULL OR duration_ms >= 0),
  idempotency_key text NOT NULL,
  contains_sensitive_data boolean NOT NULL DEFAULT false,
  error_code text,
  error_message text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, step_order),
  UNIQUE (run_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_user_persona
  ON public.agent_sessions(user_id, persona_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_status_expiry
  ON public.agent_sessions(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_agent_runs_session_created
  ON public.agent_runs(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_persona_status
  ON public.agent_runs(status, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_agent_run_steps_run_order
  ON public.agent_run_steps(run_id, step_order);
CREATE INDEX IF NOT EXISTS idx_agent_run_steps_status
  ON public.agent_run_steps(status, updated_at);

ALTER TABLE public.user_persona_access
  ADD COLUMN IF NOT EXISTS agent_tool_grants jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS agent_tool_grants_revision integer NOT NULL DEFAULT 1;

-- Conservative compatibility backfill. Legacy rows with an unknown persona are
-- intentionally skipped; the old table remains available to the adapter.
INSERT INTO public.agent_sessions (
  id, coordinator_key, persona_id, selected_context, selected_node_ids,
  memory_summary, status, revision, created_at, updated_at
)
SELECT
  legacy.session_id,
  'sofia',
  persona.id,
  jsonb_build_object(
    'legacy_source', 'sofia_plan_sessions',
    'persona_slug', legacy.persona_slug,
    'active_persona_slug', legacy.active_persona_slug,
    'plan_json', legacy.plan_json,
    'recent_turns', legacy.recent_turns
  ),
  CASE
    WHEN jsonb_typeof(legacy.last_referenced_node) = 'object'
         AND legacy.last_referenced_node <> '{}'::jsonb
      THEN jsonb_build_array(legacy.last_referenced_node)
    ELSE '[]'::jsonb
  END,
  'Backfill conservador da sessao Sofia legada.',
  'active', 1, legacy.created_at, legacy.updated_at
FROM public.sofia_plan_sessions AS legacy
JOIN public.personas AS persona ON persona.slug = legacy.persona_slug
ON CONFLICT (id) DO NOTHING;

INSERT INTO public.agent_prompt_profiles
  (agent_role, name, version, system_prompt, tools, skills, config)
VALUES
  ('coordinator', 'sofia-coordinator', 'v1',
   'Coordene especialistas com menor capacidade necessaria. Nunca amplie persona, permissao ou consentimento. Exija QA antes de writes.',
   '{}', '{planning,delegation,approval}', '{"max_delegation_depth":2,"max_steps":12}'::jsonb),
  ('specialist', 'graph_card_specialist', 'v1',
   'Crie, edite, conecte e valide cards Graph JSON 2.1 por patches versionados. Preserve nodes protegidos.',
   '{}', '{graph,card,patch}', '{"qa_required":true}'::jsonb),
  ('specialist', 'campaign_operator', 'v1',
   'Opere imports, grupos semanticos, consentimentos, previews e drafts sem expor PII no Graph ou em eventos.',
   '{}', '{contacts,consent,campaign}', '{"real_send_allowed":false,"qa_required":true}'::jsonb),
  ('validator', 'qa_validator', 'v1',
   'Valide contratos, Graph, permissoes, consentimento e resultados. Nao escreva dados de negocio.',
   '{}', '{qa,security,contracts}', '{"read_only":true}'::jsonb)
ON CONFLICT (agent_role, name, version) DO UPDATE SET
  system_prompt = EXCLUDED.system_prompt,
  skills = EXCLUDED.skills,
  config = EXCLUDED.config,
  active = true,
  updated_at = now();

ALTER TABLE public.agent_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_run_steps ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.agent_sessions FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.agent_runs FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.agent_run_steps FROM PUBLIC, anon, authenticated;
GRANT ALL ON TABLE public.agent_sessions TO service_role;
GRANT ALL ON TABLE public.agent_runs TO service_role;
GRANT ALL ON TABLE public.agent_run_steps TO service_role;

DROP POLICY IF EXISTS agent_sessions_service_only ON public.agent_sessions;
CREATE POLICY agent_sessions_service_only ON public.agent_sessions
  FOR ALL USING (false) WITH CHECK (false);
DROP POLICY IF EXISTS agent_runs_service_only ON public.agent_runs;
CREATE POLICY agent_runs_service_only ON public.agent_runs
  FOR ALL USING (false) WITH CHECK (false);
DROP POLICY IF EXISTS agent_run_steps_service_only ON public.agent_run_steps;
CREATE POLICY agent_run_steps_service_only ON public.agent_run_steps
  FOR ALL USING (false) WITH CHECK (false);

NOTIFY pgrst, 'reload schema';
