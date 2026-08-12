"""Shared fixtures and opt-in external test profiles.

Every test that has ever caught a bug in these functions (record_whatsapp_
safety_violation's text=uuid cast, activate_persona_whatsapp_binding's
stale decision_owner check) was found live, in production, because nothing
in this repo ran the actual SQL against a real database — every existing
test either mocks the Postgres layer or greps migration text. These
fixtures close that gap.

The default suite is hermetic and reports no conditional skips. SQL tests are
collected only when an explicit non-production Postgres DSN is supplied; live
tests are collected only through explicit safety flags. Nothing here starts
Docker or applies migrations.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

TEST_POSTGRES_DSN = (os.environ.get("AI_BRAIN_TEST_POSTGRES_DSN") or "").strip()

# Optional external tests are not part of the hermetic default suite. This
# avoids conditional skips and, importantly, prevents any implicit local
# Docker startup. Each profile must be enabled explicitly.
collect_ignore: list[str] = []
if not TEST_POSTGRES_DSN:
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
    if not TEST_POSTGRES_DSN:
        raise RuntimeError(
            "AI_BRAIN_TEST_POSTGRES_DSN must point to an explicitly provisioned "
            "non-production database"
        )
    return TEST_POSTGRES_DSN


@pytest.fixture()
def pg_conn(real_pg_dsn):
    """One connection per test, rolled back afterwards.

    None of the functions under test issue their own COMMIT, so wrapping
    each test in an outer transaction gives full isolation without any
    per-test cleanup logic.
    """
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(real_pg_dsn)
    conn.autocommit = False
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
