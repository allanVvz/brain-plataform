-- 020_audiences_lead_memberships.sql
-- Persona-scoped audiences and canonical lead memberships.

CREATE TABLE IF NOT EXISTS public.audiences (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id uuid NOT NULL REFERENCES public.personas(id) ON DELETE CASCADE,
  slug text NOT NULL,
  name text NOT NULL,
  description text,
  source_type text NOT NULL DEFAULT 'manual' CHECK (source_type IN ('manual', 'import', 'crm', 'shared')),
  is_system boolean NOT NULL DEFAULT false,
  created_by_user_id uuid REFERENCES public.app_users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (persona_id, slug)
);

CREATE INDEX IF NOT EXISTS idx_audiences_persona_id ON public.audiences(persona_id);
CREATE INDEX IF NOT EXISTS idx_audiences_source_type ON public.audiences(source_type);

CREATE TABLE IF NOT EXISTS public.lead_audience_memberships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id bigint NOT NULL REFERENCES public.leads(id) ON DELETE CASCADE,
  audience_id uuid NOT NULL REFERENCES public.audiences(id) ON DELETE CASCADE,
  membership_type text NOT NULL DEFAULT 'primary' CHECK (membership_type IN ('primary', 'shared')),
  created_by_user_id uuid REFERENCES public.app_users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (lead_id, audience_id)
);

CREATE INDEX IF NOT EXISTS idx_lead_audience_memberships_lead_id ON public.lead_audience_memberships(lead_id);
CREATE INDEX IF NOT EXISTS idx_lead_audience_memberships_audience_id ON public.lead_audience_memberships(audience_id);
CREATE INDEX IF NOT EXISTS idx_lead_audience_memberships_membership_type ON public.lead_audience_memberships(membership_type);
