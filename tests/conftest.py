"""Shared fixtures and opt-in external test profiles.

Every test that has ever caught a bug in these functions (record_whatsapp_
safety_violation's text=uuid cast, activate_persona_whatsapp_binding's
stale decision_owner check) was found live, in production, because nothing
in this repo ran the actual SQL against a real database — every existing
test either mocks the Postgres layer or greps migration text. These
fixtures close that gap.

The default suite is hermetic and reports no conditional skips. SQL tests are
collected only when an explicit non-production Postgres DSN is supplied; live
tests are collected only through explicit safety flags. Local runs never start
Docker or apply migrations; CI may create its isolated disposable database.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

TEST_POSTGRES_DSN = (os.environ.get("AI_BRAIN_TEST_POSTGRES_DSN") or "").strip()
IS_CI = (os.environ.get("CI") or "").strip().lower() == "true"
CI_DOCKER = shutil.which("docker") if IS_CI else None
POSTGRES_IMAGE = "pgvector/pgvector:pg16"

# Optional external tests are not part of the hermetic default suite. This
# avoids conditional skips and, importantly, prevents any implicit local
# Docker startup. Each profile must be enabled explicitly.
collect_ignore: list[str] = []
if not TEST_POSTGRES_DSN and not IS_CI:
    collect_ignore.extend([
        "test_graph_agent_v3_sql.py",
        "test_production_privileges_sql.py",
        "test_whatsapp_sql_functions.py",
    ])
if (os.environ.get("RUN_MENU_LIVE_E2E") or "").strip().lower() not in {"1", "true", "yes", "on"}:
    collect_ignore.append("e2e_baita_cardapio_menu.py")
if (os.environ.get("QA_REAL_GRAPH_INSERTION_TEST") or "").strip() != "1":
    collect_ignore.append("test_qa_real_graph_insertion.py")
if (os.environ.get("RUN_BRA91_LIVE_E2E") or "").strip().lower() not in {"1", "true", "yes", "on"}:
    collect_ignore.append("test_bra91_allanvvz_safe_crawler_snapshot.py")


_SOFIA_CANONICAL_TEST_FILES = {
    "test_qa_contract_routes.py",
    "test_sofia_primary_tree_publication.py",
    "test_sofia_session_context.py",
    "test_sofia_v2_patch_loop.py",
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _bootstrap_storage_shim(*, port: int, password: str) -> None:
    """Create the storage schema needed by migrations in CI's throwaway DB."""
    import time

    import psycopg2

    conn = None
    last_exc: Exception | None = None
    for _ in range(30):
        try:
            conn = psycopg2.connect(
                host="127.0.0.1", port=port, user="postgres",
                password=password, dbname="brain", sslmode="disable",
                connect_timeout=5,
            )
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(2.0)
    if conn is None:
        raise RuntimeError(f"could not connect to CI throwaway Postgres: {last_exc}")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "create schema if not exists storage;"
                "create table if not exists storage.buckets ("
                "id text primary key, name text not null, public boolean default false)"
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _published_graph_for_sofia_route_tests(request, monkeypatch):
    """Keep legacy route tests on the required canonical publication path.

    These tests predate Graph JSON as the write authority and mock the legacy
    projection repositories. They now receive an explicit published document
    and a validating publisher double instead of making production fall back to
    direct knowledge_nodes writes when no document exists.
    """
    if Path(str(request.fspath)).name not in _SOFIA_CANONICAL_TEST_FILES:
        return
    from routes import qa_contract
    from schemas.graph_json_v2 import GraphJson
    from services import graph_document_publisher, graph_json_v2_validator

    def current(persona_slug: str, *_args):
        graph = GraphJson.model_validate({
            "schema_version": "2.1",
            "graph_id": f"test:{persona_slug}",
            "tenant": "test",
            "persona_slug": persona_slug,
            "graph_version": 1,
            "status": "published",
            "nodes": [{
                "id": f"node:persona:{persona_slug}",
                "node_type": "persona",
                "slug": persona_slug,
                "title": persona_slug,
                "lifecycle": {"status": "active"},
            }],
            "edges": [],
        })
        return 1, graph

    def publish(*, graph, **_kwargs):
        valid, errors = graph_json_v2_validator.validate_graph_json(graph)
        if not valid:
            raise graph_document_publisher.GraphValidationError(errors)
        return {
            "ok": True,
            "version": 2,
            "checksum": graph.content_checksum or "sha256:test-canonical-publication",
            "status": "published",
        }

    monkeypatch.setattr(qa_contract.graph_json_v2_store, "load_current", current)
    monkeypatch.setattr(qa_contract.graph_document_publisher, "publish", publish)


@pytest.fixture(scope="session")
def real_pg_dsn():
    if TEST_POSTGRES_DSN:
        yield TEST_POSTGRES_DSN
        return
    if not IS_CI or not CI_DOCKER:
        raise RuntimeError(
            "AI_BRAIN_TEST_POSTGRES_DSN must point to an explicitly provisioned "
            "non-production database outside CI"
        )

    password = uuid.uuid4().hex
    port = _free_port()
    name = f"brain-ci-pg-{uuid.uuid4().hex[:10]}"
    run = subprocess.run(
        [
            CI_DOCKER, "run", "-d", "--rm", "--name", name,
            "-e", f"POSTGRES_PASSWORD={password}",
            "-e", "POSTGRES_DB=brain",
            "-p", f"127.0.0.1:{port}:5432", POSTGRES_IMAGE,
        ],
        capture_output=True, text=True,
    )
    if run.returncode != 0:
        raise RuntimeError(f"could not start CI {POSTGRES_IMAGE}: {run.stderr.strip()}")
    try:
        _bootstrap_storage_shim(port=port, password=password)
        env = {
            **os.environ,
            "PGHOST": "127.0.0.1", "PGPORT": str(port),
            "PGUSER": "postgres", "PGPASSWORD": password,
            "PGDATABASE": "brain", "PGSSLMODE": "disable",
            "POSTGRES_PASSWORD": password, "APPLY_LEGACY_BOOTSTRAP": "1",
        }
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "apply_migrations.py")],
            env=env, capture_output=True, text=True, cwd=str(ROOT),
        )
        if result.returncode != 0:
            raise RuntimeError(
                "scripts/apply_migrations.py failed against CI throwaway Postgres:\n"
                f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
            )
        yield {
            "host": "127.0.0.1", "port": port, "user": "postgres",
            "password": password, "dbname": "brain",
        }
    finally:
        subprocess.run([CI_DOCKER, "stop", name], capture_output=True, text=True)


@pytest.fixture()
def pg_conn(real_pg_dsn):
    """One connection per test, rolled back afterwards.

    None of the functions under test issue their own COMMIT, so wrapping
    each test in an outer transaction gives full isolation without any
    per-test cleanup logic.
    """
    import psycopg2
    import psycopg2.extras

    conn = (
        psycopg2.connect(real_pg_dsn)
        if isinstance(real_pg_dsn, str)
        else psycopg2.connect(**real_pg_dsn)
    )
    conn.autocommit = False
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
