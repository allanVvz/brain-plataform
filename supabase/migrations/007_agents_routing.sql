-- 007_agents_routing.sql
-- Per-persona agents (bots) and role routing (SDR / Closer / Followup).
-- Each persona has its own agents; each role is assigned to an agent
-- or to NULL (= human handoff). Multiple personas can have agents
-- with the same bot_name (e.g., two clients both naming a bot "Sofia").
-- Safe to run multiple times.

-- ── 1. agents ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.agents (
  id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
  persona_id            UUID         NOT NULL REFERENCES public.personas(id) ON DELETE CASCADE,
  bot_name              TEXT         NOT NULL,
  description           TEXT,
  whatsapp_number       TEXT,                  -- E.164, ex: +5511999998888
  whatsapp_contact_name TEXT,                  -- nome no WhatsApp Web (E2E)
  n8n_webhook_url       TEXT,                  -- destino quando humano/AI envia
  n8n_webhook_secret    TEXT,                  -- HMAC opcional
  config                JSONB        NOT NULL DEFAULT '{}'::jsonb,
  active                BOOLEAN      NOT NULL DEFAULT TRUE,
  created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
  UNIQUE (persona_id, bot_name)
);

CREATE INDEX IF NOT EXISTS idx_agents_persona_id ON public.agents (persona_id);
CREATE INDEX IF NOT EXISTS idx_agents_active     ON public.agents (active);

-- ── 2. persona_role_assignments ──────────────────────────────
-- Quem cuida de cada role nessa persona.
-- agent_id = NULL  →  role atendida por humano.
CREATE TABLE IF NOT EXISTS public.persona_role_assignments (
  persona_id  UUID         NOT NULL REFERENCES public.personas(id) ON DELETE CASCADE,
  role        TEXT         NOT NULL CHECK (role IN ('sdr','closer','followup')),
  agent_id    UUID                  REFERENCES public.agents(id)   ON DELETE SET NULL,
  active      BOOLEAN      NOT NULL DEFAULT TRUE,
  updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  PRIMARY KEY (persona_id, role)
);

CREATE INDEX IF NOT EXISTS idx_role_assignments_agent_id ON public.persona_role_assignments (agent_id);

-- ── 3. leads.ai_paused ───────────────────────────────────────
-- Quando true, /process não roda agente para esse lead.
-- Usado para handoff manual ou automático (humano cuidando).
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS ai_paused BOOLEAN DEFAULT FALSE;

-- ── 4. messages.sender_id ────────────────────────────────────
-- Identifica QUAL humano (ou agent_id) enviou. Texto livre por ora.
ALTER TABLE public.messages ADD COLUMN IF NOT EXISTS sender_id TEXT;

-- ── 5. Seed: Tock Fatal → Sofia (SDR + Closer); followup = humano ──
-- Idempotente via ON CONFLICT.

INSERT INTO public.agents (persona_id, bot_name, description, whatsapp_contact_name)
SELECT id, 'Sofia', 'Agente de vendas principal do Tock Fatal', 'Sofia'
FROM public.personas WHERE slug = 'tock-fatal'
ON CONFLICT (persona_id, bot_name) DO NOTHING;

-- SDR → Sofia
INSERT INTO public.persona_role_assignments (persona_id, role, agent_id)
SELECT p.id, 'sdr', a.id
FROM public.personas p
JOIN public.agents a ON a.persona_id = p.id AND a.bot_name = 'Sofia'
WHERE p.slug = 'tock-fatal'
ON CONFLICT (persona_id, role) DO UPDATE
  SET agent_id = EXCLUDED.agent_id,
      active   = TRUE,
      updated_at = now();

-- Closer → Sofia (mesma)
INSERT INTO public.persona_role_assignments (persona_id, role, agent_id)
SELECT p.id, 'closer', a.id
FROM public.personas p
JOIN public.agents a ON a.persona_id = p.id AND a.bot_name = 'Sofia'
WHERE p.slug = 'tock-fatal'
ON CONFLICT (persona_id, role) DO UPDATE
  SET agent_id = EXCLUDED.agent_id,
      active   = TRUE,
      updated_at = now();

-- Followup → humano (agent_id NULL)
INSERT INTO public.persona_role_assignments (persona_id, role, agent_id)
SELECT id, 'followup', NULL
FROM public.personas WHERE slug = 'tock-fatal'
ON CONFLICT (persona_id, role) DO NOTHING;
