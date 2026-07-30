-- Client portal account classification and mandatory first-login password change.
-- Existing users remain internal and are not forced to change credentials.

ALTER TABLE public.app_users
  ADD COLUMN IF NOT EXISTS account_type text NOT NULL DEFAULT 'internal',
  ADD COLUMN IF NOT EXISTS must_change_password boolean NOT NULL DEFAULT false;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'app_users_account_type_check'
      AND conrelid = 'public.app_users'::regclass
  ) THEN
    ALTER TABLE public.app_users
      ADD CONSTRAINT app_users_account_type_check
      CHECK (account_type IN ('internal', 'agency', 'client'));
  END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_app_users_account_type
  ON public.app_users(account_type);
