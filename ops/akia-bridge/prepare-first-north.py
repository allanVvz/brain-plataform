#!/usr/bin/env python3
"""Prepare private AKIA VPS env/SQL; apply SQL only with its reviewed digest."""
from __future__ import annotations
import argparse
import json
import hashlib
import os
from pathlib import Path
import re
import secrets
import subprocess
from urllib.parse import quote, urlparse
from uuid import UUID


def parse_env(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text().splitlines():
        if line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def container_env(name: str) -> dict[str, str]:
    # Capture secret-bearing inspect output internally; never print it.
    raw = subprocess.run(["docker", "inspect", "--format", "{{json .Config.Env}}", name],
                         check=True, capture_output=True, text=True).stdout
    return dict(value.split("=", 1) for value in json.loads(raw) if "=" in value)


def sql_uuid(value: str) -> str:
    return "'" + str(UUID(value)) + "'::uuid"


def validate_manifest(manifest: dict) -> None:
    if manifest.get("approved") is not True or not manifest.get("approval_reference"):
        raise ValueError("Manifest must have explicit approval reference")
    clients = {str(UUID(row["north_client_id"])) for row in manifest["clients"]}
    identities = {str(UUID(row["app_user_id"])) for row in manifest["identity_links"]}
    if not clients or not identities:
        raise ValueError("Explicit client and identity manifests required")
    for row in manifest["identity_links"]:
        UUID(row["north_profile_id"])
        if row.get("approved") is not True:
            raise ValueError("Unapproved identity link")
    for row in manifest["clients"]:
        if row["agency_slug"] not in {"north", "south"}:
            raise ValueError("Invalid agency")
    for row in manifest["client_grants"]:
        if str(UUID(row["app_user_id"])) not in identities or str(UUID(row["north_client_id"])) not in clients:
            raise ValueError("Grant outside approved manifest")
    for row in manifest["persona_links"]:
        UUID(row["persona_id"])
        if str(UUID(row["north_client_id"])) not in clients:
            raise ValueError("Persona outside approved client manifest")
    if not set(manifest["platform_admins"]).issubset(identities):
        raise ValueError("Platform administrator outside approved identities")


def bootstrap_sql(manifest: dict, database: str, password: str, reuse_role: bool) -> str:
    validate_manifest(manifest)
    migration = (Path(__file__).parent / "000_north_read_through.sql").read_text()
    migration = "\n".join(line for line in migration.splitlines() if line.strip() not in {"BEGIN;", "COMMIT;"})
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,}", password):
        raise ValueError("Invalid generated role password")
    sql = ["BEGIN;", "SET LOCAL lock_timeout='5s';", "SET LOCAL statement_timeout='30s';"]
    # Check technical IDs against the actual Brain before creating grants.
    for user in manifest["platform_admins"]:
        sql.append("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM public.app_users WHERE id=" + sql_uuid(user)
                   + " AND is_active AND role='admin' AND account_type='internal') THEN RAISE EXCEPTION 'Approved Brain administrator unavailable'; END IF; END $$;")
    for link in manifest["persona_links"]:
        sql.append("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM public.personas WHERE id=" + sql_uuid(link["persona_id"])
                   + ") THEN RAISE EXCEPTION 'Approved persona unavailable'; END IF; END $$;")
    sql.append(migration)
    for row in manifest["clients"]:
        sql.append("INSERT INTO operations.north_client_registry(north_client_id,agency_slug) VALUES ("
                   + sql_uuid(row["north_client_id"]) + ", '" + row["agency_slug"] + "');")
    for row in manifest["identity_links"]:
        sql.append("INSERT INTO operations.north_identity_links(app_user_id,north_profile_id) VALUES ("
                   + sql_uuid(row["app_user_id"]) + "," + sql_uuid(row["north_profile_id"]) + ");")
    for user in manifest["platform_admins"]:
        sql.append("INSERT INTO operations.platform_admins(app_user_id) VALUES (" + sql_uuid(user) + ") ON CONFLICT DO NOTHING;")
    for row in manifest["client_grants"]:
        sql.append("INSERT INTO operations.north_client_grants(app_user_id,north_client_id,can_view_internal) VALUES ("
                   + sql_uuid(row["app_user_id"]) + "," + sql_uuid(row["north_client_id"]) + ","
                   + ("true" if row.get("can_view_internal") is True else "false") + ");")
    for row in manifest["persona_links"]:
        sql.append("INSERT INTO operations.north_persona_links(north_client_id,persona_id) VALUES ("
                   + sql_uuid(row["north_client_id"]) + "," + sql_uuid(row["persona_id"]) + ");")
    collision = "NULL;" if reuse_role else "RAISE EXCEPTION 'akia_operations already exists but no private env is available';"
    sql.append("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='akia_operations') THEN " + collision
               + " ELSE CREATE ROLE akia_operations LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD '"
               + password + "'; END IF; END $$;")
    sql.append("DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='akia_operations' AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolinherit OR rolreplication OR rolbypassrls)) OR EXISTS (SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='akia_operations')) THEN RAISE EXCEPTION 'Existing operations role is not restricted'; END IF; END $$;")
    identifier = '"' + database.replace('"', '""') + '"'
    sql.extend([
        "GRANT CONNECT ON DATABASE " + identifier + " TO akia_operations;",
        "GRANT USAGE ON SCHEMA public,operations TO akia_operations;",
        "GRANT SELECT(id,is_active) ON public.app_users TO akia_operations;",
        "GRANT SELECT(user_id,persona_id,can_view) ON public.user_persona_access TO akia_operations;",
        "GRANT SELECT ON operations.platform_admins,operations.north_identity_links,operations.north_client_registry,operations.north_client_grants,operations.north_persona_links TO akia_operations;",
        "CREATE POLICY akia_operations_active_identity_lookup ON public.app_users FOR SELECT TO akia_operations USING (EXISTS (SELECT 1 FROM operations.north_identity_links identity WHERE identity.app_user_id=app_users.id AND identity.enabled));",
        "CREATE POLICY akia_operations_mapped_persona_lookup ON public.user_persona_access FOR SELECT TO akia_operations USING (EXISTS (SELECT 1 FROM operations.north_identity_links identity WHERE identity.app_user_id=user_persona_access.user_id AND identity.enabled));",
        "SET LOCAL ROLE akia_operations;",
    ])
    for row in manifest["identity_links"]:
        sql.append("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM public.app_users WHERE id=" + sql_uuid(row["app_user_id"])
                   + " AND is_active) THEN RAISE EXCEPTION 'Operations role cannot resolve approved active identity'; END IF; END $$;")
    sql.extend([
        "SELECT user_id,persona_id,can_view FROM public.user_persona_access LIMIT 0;",
        "RESET ROLE;",
        "COMMIT;",
    ])
    return "\n".join(sql) + "\n"


def write_private(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(content)
    path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brain-root", type=Path, default=Path("/opt/brain-ai"))
    parser.add_argument("--db-container", default="brain-ai-db-1")
    parser.add_argument("--gateway-container", default="brain-ai-gateway-blue-1")
    parser.add_argument("--north-env", type=Path, help="Optional local file; alternatively use NORTH_SUPABASE_URL/KEY env")
    parser.add_argument("--manifest", type=Path, help="Alternatively use approved AKIA_BOOTSTRAP_MANIFEST JSON env")
    parser.add_argument("--portal-origins", required=True, help="Exact JSON map akia/north/south to HTTPS origins")
    parser.add_argument("--write", action="store_true", help="Write private env and SQL; still never execute SQL")
    parser.add_argument("--apply-sql", action="store_true", help="Execute an existing reviewed private SQL file; never regenerate it")
    parser.add_argument("--reviewed-sql-sha256", help="Required exact digest of the reviewed SQL file for --apply-sql")
    args = parser.parse_args()
    if args.write and args.apply_sql:
        raise SystemExit("Prepare env/SQL and apply SQL are separate invocations")
    raw_manifest = args.manifest.read_text() if args.manifest else os.getenv("AKIA_BOOTSTRAP_MANIFEST", "")
    if not raw_manifest:
        raise SystemExit("Approved bootstrap manifest required")
    manifest = json.loads(raw_manifest)
    validate_manifest(manifest)
    origins = json.loads(args.portal_origins)
    if not isinstance(origins, dict) or set(origins) != {"akia", "north", "south"}:
        raise SystemExit("Three exact portal origins required")
    for origin in origins.values():
        parsed = urlparse(origin)
        if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment:
            raise SystemExit("HTTPS origins without paths required")
    compose = parse_env(args.brain_root / ".env.compose")
    db = container_env(args.db_container)
    gateway = container_env(args.gateway_container)
    north = parse_env(args.north_env) if args.north_env else {}
    hmac = gateway.get("BRAIN_INTERNAL_AUTH_SECRET", "")
    if len(hmac.encode()) < 32:
        raise SystemExit("Existing gateway HMAC unavailable")
    if not all(db.get(key) for key in ("POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD")):
        raise SystemExit("Brain database configuration unavailable")
    url = os.getenv("NORTH_SUPABASE_URL") or north.get("NEXT_PUBLIC_SUPABASE_URL") or north.get("SUPABASE_URL")
    key = os.getenv("NORTH_SUPABASE_SERVICE_ROLE_KEY") or north.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not url.startswith("https://") or not key:
        raise SystemExit("Private North HTTPS configuration unavailable")
    host = compose.get("API_DOMAIN")
    if not host:
        raise SystemExit("Existing API_DOMAIN unavailable")
    target = args.brain_root / "secrets"
    if args.apply_sql:
        reviewed = target / "akia-first-north-bootstrap.sql"
        content = reviewed.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if not args.reviewed_sql_sha256 or digest != args.reviewed_sql_sha256:
            raise SystemExit("Reviewed SQL digest required and must match")
        outcome = subprocess.run(["docker", "exec", "-i", args.db_container, "psql", "--no-psqlrc",
                                  "-v", "ON_ERROR_STOP=1", "-U", db["POSTGRES_USER"], "-d", db["POSTGRES_DB"]],
                                 input=content, capture_output=True)
        if outcome.returncode:
            raise SystemExit("Bootstrap SQL failed; transaction rolled back (details withheld to protect private SQL)")
        print(json.dumps({"sql_executed": True, "sql_sha256": digest, "files_written": False}))
        return
    prior = parse_env(target / "akia-operations.env") if (target / "akia-operations.env").is_file() else {}
    existing = urlparse(prior.get("DATABASE_URL", ""))
    reuse_role = existing.username == "akia_operations" and bool(existing.password)
    password = existing.password if reuse_role else secrets.token_urlsafe(48)
    database_url = f"postgresql://akia_operations:{password}@db:5432/{quote(db['POSTGRES_DB'], safe='')}"
    operations = {"DATABASE_URL": database_url, "BRAIN_INTERNAL_AUTH_SECRET": hmac,
                  "OPERATIONS_NORTH_READ_THROUGH_ENABLED": "true", "OPERATIONS_CRON_ENABLED": "false",
                  "NORTH_SUPABASE_URL": url, "NORTH_SUPABASE_SERVICE_ROLE_KEY": key}
    edge = {"BRAIN_INTERNAL_AUTH_SECRET": hmac, "AKIA_OPERATIONS_URL": "http://operations-api:8096",
            "AKIA_PORTAL_PATH_HOST": host, "AKIA_PORTAL_PATH_ORIGINS": json.dumps(origins, separators=(",", ":"))}
    sql = bootstrap_sql(manifest, db["POSTGRES_DB"], password, reuse_role)
    if args.write:
        target.mkdir(mode=0o700, exist_ok=True)
        target.chmod(0o700)
        for name, values in (("akia-operations.env", operations), ("akia-gateway.env", edge)):
            write_private(target / name, "".join(f"{key}={value}\n" for key, value in sorted(values.items())))
        write_private(target / "akia-first-north-bootstrap.sql", sql)
    print(json.dumps({"validated": True, "files_written": args.write, "sql_executed": False,
                      "sql_sha256": hashlib.sha256(sql.encode()).hexdigest(),
                      "clients": len(manifest["clients"]), "identities": len(manifest["identity_links"]),
                      "output_directory": str(target), "role": "akia_operations"}))


if __name__ == "__main__":
    main()
