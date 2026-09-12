-- message_templates (migration 090) tracks only OUR OWN lifecycle
-- (draft/active/archived) plus a bare reference to a template name the
-- operator claims is already approved on Meta. There is no column for the
-- Meta side of that lifecycle (PENDING/APPROVED/REJECTED), no id Meta assigns
-- on creation, and no optimistic-concurrency column for the edit endpoint
-- this pairs with. Additive only; existing rows default to 'draft' and
-- revision 1, which is correct for every row created before this migration
-- (none of them were ever submitted to Meta through this system).

ALTER TABLE public.message_templates
  ADD COLUMN IF NOT EXISTS meta_template_id text,
  ADD COLUMN IF NOT EXISTS meta_approval_status text NOT NULL DEFAULT 'draft',
  ADD COLUMN IF NOT EXISTS meta_rejection_reason text,
  ADD COLUMN IF NOT EXISTS meta_synced_at timestamptz,
  ADD COLUMN IF NOT EXISTS revision integer NOT NULL DEFAULT 1;

ALTER TABLE public.message_templates DROP CONSTRAINT IF EXISTS message_templates_meta_approval_status_check;
ALTER TABLE public.message_templates
  ADD CONSTRAINT message_templates_meta_approval_status_check
  CHECK (meta_approval_status IN ('draft', 'pending', 'approved', 'rejected', 'paused', 'disabled'));

-- Meta's id for a submitted template is globally unique once assigned; two
-- local rows must never claim the same one.
CREATE UNIQUE INDEX IF NOT EXISTS idx_message_templates_meta_template_id
  ON public.message_templates (meta_template_id)
  WHERE meta_template_id IS NOT NULL;

NOTIFY pgrst, 'reload schema';
