-- Candidate only: no copy/alter of any North business table.
BEGIN;
CREATE SCHEMA IF NOT EXISTS operations;
CREATE TABLE IF NOT EXISTS operations.platform_admins (
  app_user_id uuid PRIMARY KEY REFERENCES public.app_users(id)
);
CREATE TABLE operations.north_identity_links (
  app_user_id uuid PRIMARY KEY REFERENCES public.app_users(id),
  north_profile_id uuid UNIQUE NOT NULL,
  enabled boolean NOT NULL DEFAULT true
);
CREATE TABLE operations.north_client_registry (
  north_client_id uuid PRIMARY KEY,
  agency_slug text NOT NULL CHECK (agency_slug IN ('north','south'))
);
CREATE TABLE operations.north_client_grants (
  app_user_id uuid NOT NULL REFERENCES operations.north_identity_links(app_user_id),
  north_client_id uuid NOT NULL REFERENCES operations.north_client_registry(north_client_id),
  can_view_internal boolean NOT NULL DEFAULT false,
  PRIMARY KEY (app_user_id,north_client_id)
);
CREATE TABLE operations.north_persona_links (
  north_client_id uuid NOT NULL REFERENCES operations.north_client_registry(north_client_id),
  persona_id uuid NOT NULL REFERENCES public.personas(id),
  PRIMARY KEY(north_client_id,persona_id)
);
REVOKE ALL ON SCHEMA operations FROM PUBLIC;
REVOKE ALL ON operations.north_identity_links,operations.north_client_registry,operations.north_client_grants,operations.north_persona_links,operations.platform_admins FROM PUBLIC;
CREATE OR REPLACE FUNCTION public.akia_portal_grants(p_user_id uuid)
RETURNS text[] LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT coalesce(array_agg(DISTINCT grants.portal ORDER BY grants.portal),ARRAY[]::text[])
  FROM public.app_users u CROSS JOIN LATERAL (
    SELECT unnest(ARRAY['akia','north','south']::text[]) AS portal
    WHERE EXISTS (SELECT 1 FROM operations.platform_admins p WHERE p.app_user_id=u.id)
    UNION
    SELECT registry.agency_slug AS portal FROM operations.north_identity_links identity
    JOIN operations.north_client_grants grant_row ON grant_row.app_user_id=identity.app_user_id
    JOIN operations.north_client_registry registry ON registry.north_client_id=grant_row.north_client_id
    WHERE identity.app_user_id=u.id AND identity.enabled
  ) grants WHERE u.id=p_user_id AND u.is_active
$$;
REVOKE ALL ON FUNCTION public.akia_portal_grants(uuid) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.akia_portal_grants(uuid) TO brain_control_plane;
COMMIT;
