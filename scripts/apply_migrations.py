#!/usr/bin/env python3
"""Apply the legacy bootstrap + all SQL migrations to a Postgres database.

Env-driven generalization of ``apply_schema_to_new_qa.py``: instead of a
hardcoded Supabase host it reads the connection from standard ``PG*`` env vars,
so it can target the ``db`` service of the self-hosted Docker stack (it is the
entrypoint of the one-shot ``migrate`` container) or any other Postgres.

Order of application (each block in its own transaction, stop on first failure):
  1. docs/qa/00_legacy_leads_messages.sql  — leads/messages tables that predate
     formal migrations and are only ALTER'd by the migration set.
  2. supabase/migrations/*.sql              — in filename order, with the same
     forward-port PRE_PATCHES used by the QA bootstrap.

Idempotent: every migration uses ``IF NOT EXISTS`` / ``ON CONFLICT`` guards, so
re-running against an already-migrated database is safe.

Connection env (with defaults matching the compose ``db`` service):
  PGHOST=db  PGPORT=5432  PGUSER=postgres  PGPASSWORD=postgres  PGDATABASE=postgres
  PGSSLMODE=prefer   APPLY_LEGACY_BOOTSTRAP=1   APPLY_SEED=0
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent.parent
LEGACY_FILE = ROOT / "docs" / "qa" / "00_legacy_leads_messages.sql"
MIGRATIONS_DIR = ROOT / "supabase" / "migrations"
MANIFEST_FILE = ROOT / "MIGRATION_MANIFEST.json"

# Known repairs to run BEFORE a given migration filename. Drift between the
# legacy CREATE in migration N and columns used by indexes/queries of later
# migrations: forward-port the ADD COLUMN that normally happens in 024.
PRE_PATCHES: dict[str, str] = {
    "004_error_logging.sql": """
        ALTER TABLE public.agent_logs
          ADD COLUMN IF NOT EXISTS agent_type text,
          ADD COLUMN IF NOT EXISTS action     text,
          ADD COLUMN IF NOT EXISTS decision   text,
          ADD COLUMN IF NOT EXISTS metadata   jsonb DEFAULT '{}'::jsonb;
    """,
}


def _bool_env(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


LEDGER_TABLE = "public._compose_migrations"


def verify_runner_manifest(migrations: list[Path]) -> dict:
    """Prove the immutable runner contains exactly its declared SQL bytes."""
    if not MANIFEST_FILE.is_file():
        if _bool_env("REQUIRE_MIGRATION_MANIFEST", False):
            raise SystemExit(f"migration runner manifest missing: {MANIFEST_FILE}")
        # Direct CI/test invocations are not an immutable runner image. They
        # still exercise the same manifest algorithm without requiring a
        # generated build artifact in the Git worktree.
        from migration_manifest import build_manifest

        manifest = build_manifest(MIGRATIONS_DIR)
        print("migration manifest computed for direct invocation")
        return manifest
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    expected = {
        str(item["filename"]): str(item["sha256"])
        for item in manifest.get("migrations", [])
    }
    actual_names = {path.name for path in migrations}
    if actual_names != set(expected):
        raise SystemExit("migration runner manifest/file set mismatch")
    for path in migrations:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected[path.name]:
            raise SystemExit(f"migration checksum mismatch: {path.name}")
    return manifest


def ensure_platform_bootstrap(conn, password: str) -> None:
    """Create the Supabase-compatible roles and minimal Storage bootstrap.

    Production deliberately does not mount the old local init directory because
    it contains a known development login. This bootstrap is password-driven,
    idempotent, and runs before the versioned application migrations.
    """
    sql = """
        create extension if not exists vector;
        create extension if not exists pgcrypto;
        do $$
        begin
          if not exists (select 1 from pg_roles where rolname = 'anon') then
            create role anon nologin;
          end if;
          if not exists (select 1 from pg_roles where rolname = 'authenticated') then
            create role authenticated nologin;
          end if;
          if not exists (select 1 from pg_roles where rolname = 'service_role') then
            create role service_role nologin bypassrls;
          end if;
          if not exists (select 1 from pg_roles where rolname = 'authenticator') then
            create role authenticator noinherit login;
          end if;
        end
        $$;
        grant anon, authenticated, service_role to authenticator;
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        cur.execute("alter role authenticator password %s", (password,))
    conn.commit()


def finalize_platform_grants(conn) -> None:
    """Keep PostgREST grants aligned without reopening internal graph tables."""
    with conn.cursor() as cur:
        cur.execute(
            """
            grant usage on schema public, storage to anon, authenticated, service_role;
            revoke all on all tables in schema public from public, anon, authenticated;
            grant select on all tables in schema storage to anon, authenticated;
            grant all on all tables in schema public to service_role;
            grant select, insert, update, delete on all tables in schema storage to service_role;
            revoke all on all sequences in schema public from public, anon, authenticated;
            grant all on all sequences in schema public to service_role;
            grant usage, select on all sequences in schema storage to anon, authenticated, service_role;
            alter default privileges in schema public revoke all on tables from public, anon, authenticated;
            alter default privileges in schema public grant all on tables to service_role;
            alter default privileges in schema public revoke all on sequences from public, anon, authenticated;
            alter default privileges in schema public grant all on sequences to service_role;
            alter default privileges in schema public revoke execute on functions from public, anon, authenticated;
            alter default privileges in schema public grant execute on functions to service_role;
            alter default privileges in schema storage grant select on tables to anon, authenticated;
            alter default privileges in schema storage grant select, insert, update, delete on tables to service_role;

            -- Graph/event/RAG tables are API-internal.  The blanket grants
            -- above preserve compatibility for other legacy Data API tables;
            -- these explicit revokes are the security boundary introduced by
            -- migrations 082/083 and must run *after* blanket grants.
            revoke all on table public.system_events from public, anon, authenticated;
            revoke all on table public.knowledge_items from public, anon, authenticated;
            revoke all on table public.knowledge_nodes from public, anon, authenticated;
            revoke all on table public.knowledge_edges from public, anon, authenticated;
            revoke all on table public.knowledge_rag_entries from public, anon, authenticated;
            revoke all on table public.knowledge_rag_chunks from public, anon, authenticated;
            revoke all on table public.knowledge_rag_links from public, anon, authenticated;
            revoke all on table public.assets from public, anon, authenticated;
            revoke all on table public.knowledge_graph_primary_tree from public, anon, authenticated;
            revoke all on table public.knowledge_nodes_canonical from public, anon, authenticated;
            revoke all on table public.v_knowledge_curation_backlog from public, anon, authenticated;
            revoke all on table public.v_knowledge_lineage from public, anon, authenticated;
            revoke all on table public.v_knowledge_products_missing_price from public, anon, authenticated;
            revoke all on table public.v_knowledge_validation_failures from public, anon, authenticated;
            -- Campaign delivery tables contain consent, targeting and audit
            -- state. They are only reachable through the authenticated API
            -- and the narrowly granted service-role RPCs.
            revoke all on table public.lead_import_batches from public, anon, authenticated;
            revoke all on table public.lead_import_rows from public, anon, authenticated;
            revoke all on table public.contact_consents from public, anon, authenticated;
            revoke all on table public.campaign_revisions from public, anon, authenticated;
            revoke all on table public.campaign_revision_imports from public, anon, authenticated;
            revoke all on table public.campaign_recipients from public, anon, authenticated;
            revoke all on table public.agent_sessions from public, anon, authenticated;
            revoke all on table public.agent_runs from public, anon, authenticated;
            revoke all on table public.agent_run_steps from public, anon, authenticated;
            -- GraphRAG v3 compiled publications and conversational proofs are
            -- internal audit/decision state, never public Data API surface.
            revoke all on table public.graph_publications from public, anon, authenticated;
            revoke all on table public.graph_node_coordinates from public, anon, authenticated;
            revoke all on table public.graph_branch_memberships from public, anon, authenticated;
            revoke all on table public.graph_branch_contracts from public, anon, authenticated;
            revoke all on table public.conversation_ledgers from public, anon, authenticated;
            revoke all on table public.conversation_facts from public, anon, authenticated;
            revoke all on table public.conversation_turn_proofs from public, anon, authenticated;
            """
        )
    conn.commit()


def ensure_ledger(conn) -> set[str]:
    """Create the applied-migrations ledger and return the set of applied names.

    Several migrations are not idempotent (e.g. 039 inserts knowledge_nodes
    without ON CONFLICT), so re-running them fails. The ledger lets the one-shot
    `migrate` service run on every `compose up` and skip what is already applied.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"create table if not exists {LEDGER_TABLE} "
            "(filename text primary key, applied_at timestamptz not null default now())"
        )
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(f"select filename from {LEDGER_TABLE}")
        return {row[0] for row in cur.fetchall()}


def run_block(conn, name: str, sql: str, *, record: bool = False) -> bool:
    """Apply a SQL block (and optionally record it in the ledger) atomically."""
    print(f"--> {name}: {len(sql):,} chars ", end="", flush=True)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            if record:
                cur.execute(f"insert into {LEDGER_TABLE}(filename) values (%s)", (name,))
        conn.commit()
        print("OK")
        return True
    except Exception as exc:  # noqa: BLE001 — report and stop
        conn.rollback()
        print("FAIL")
        msg = str(exc).strip().splitlines()[0]
        print(f"    error: {msg}")
        return False


def connect_with_retry(dsn: dict, *, retries: int = 30, delay: float = 2.0):
    """Wait for the db service to accept connections (compose start ordering)."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            conn = psycopg2.connect(**dsn)
            conn.autocommit = False
            return conn
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"db not ready (attempt {attempt + 1}/{retries}): {str(exc).splitlines()[0]}")
            time.sleep(delay)
    raise SystemExit(f"could not connect to Postgres after {retries} attempts: {last}")


def main() -> int:
    dsn = {
        "host": os.environ.get("PGHOST", "db"),
        "port": int(os.environ.get("PGPORT", "5432")),
        "user": os.environ.get("PGUSER", "postgres"),
        "password": os.environ.get("PGPASSWORD", "postgres"),
        "dbname": os.environ.get("PGDATABASE", "postgres"),
        "sslmode": os.environ.get("PGSSLMODE", "prefer"),
        "connect_timeout": 30,
    }
    migrations = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migrations:
        raise SystemExit(f"no migrations found in {MIGRATIONS_DIR}")
    manifest = verify_runner_manifest(migrations)
    print(
        "migration runner manifest: "
        f"version={manifest.get('runner_version')} "
        f"sha256={manifest.get('manifest_sha256')} "
        f"count={manifest.get('count')} latest={manifest.get('latest')}"
    )

    conn = connect_with_retry(dsn)
    bootstrap_password = os.environ.get("POSTGRES_PASSWORD") or dsn["password"]
    if not bootstrap_password:
        raise SystemExit("POSTGRES_PASSWORD is required for the authenticator role")
    ensure_platform_bootstrap(conn, bootstrap_password)
    applied = ensure_ledger(conn)
    print(f"connected to {dsn['host']}:{dsn['port']}/{dsn['dbname']}, "
          f"{len(migrations)} migrations on disk, {len(applied)} already applied")

    if _bool_env("APPLY_LEGACY_BOOTSTRAP", True):
        # Legacy bootstrap is idempotent (CREATE ... IF NOT EXISTS); gate it on
        # the ledger anyway so re-runs stay quiet.
        if LEGACY_FILE.name not in applied:
            if not LEGACY_FILE.exists():
                raise SystemExit(f"legacy bootstrap missing: {LEGACY_FILE}")
            if not run_block(conn, LEGACY_FILE.name, LEGACY_FILE.read_text(encoding="utf-8"), record=True):
                return 1

    skipped = 0
    for path in migrations:
        if path.name in applied:
            skipped += 1
            continue
        if path.name in PRE_PATCHES:
            if not run_block(conn, f"PRE-PATCH for {path.name}", PRE_PATCHES[path.name]):
                return 1
        if not run_block(conn, path.name, path.read_text(encoding="utf-8"), record=True):
            return 1
    if skipped:
        print(f"(skipped {skipped} already-applied migrations)")

    # Optional seed (e.g. minimal Baita catalog) — off by default.
    seed_file = os.environ.get("SEED_FILE", "").strip()
    if _bool_env("APPLY_SEED", False) and seed_file:
        seed_path = Path(seed_file)
        if not seed_path.is_absolute():
            seed_path = ROOT / seed_path
        if seed_path.exists():
            if not run_block(conn, seed_path.name, seed_path.read_text(encoding="utf-8")):
                return 1
        else:
            print(f"warning: SEED_FILE {seed_path} not found, skipping seed")

    finalize_platform_grants(conn)
    # PostgREST can remain running across an idempotent Compose migration run.
    # Ensure newly added portal/channel columns become visible immediately.
    with conn.cursor() as cur:
        cur.execute("NOTIFY pgrst, 'reload schema'")
    conn.commit()

    with conn.cursor() as cur:
        cur.execute(
            """
            select
              (select count(*) from information_schema.tables where table_schema='public') as tables,
              (select count(*) from information_schema.views  where table_schema='public') as views,
              (select count(*) from pg_policies   where schemaname='public') as policies,
              (select count(*) from pg_extension) as extensions
            """
        )
        tables, views, policies, extensions = cur.fetchone()
    print("\npublic schema summary:")
    print(f"      tables: {tables}\n       views: {views}\n    policies: {policies}\n  extensions: {extensions}")
    conn.close()
    print("\nMIGRATIONS APPLIED OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
