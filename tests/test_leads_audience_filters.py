"""Part 1 — the `import` leads bucket must never surface as a semantic audience,
and audiences created in the Graph/Sofia must surface as Leads filters.

Pure-logic tests: every DB touchpoint is monkeypatched, so this runs with no
live Supabase connection.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def test_is_import_audience_matches_slug_or_source_type():
    from services import supabase_client as sc

    assert sc._is_import_audience({"slug": "import"}) is True
    assert sc._is_import_audience({"slug": "Import"}) is True
    assert sc._is_import_audience({"source_type": "import"}) is True
    assert sc._is_import_audience({"slug": "tecnicos", "source_type": "manual"}) is False
    assert sc._is_import_audience({"slug": "audience-padrao-vz-lupas"}) is False
    assert sc._is_import_audience(None) is False
    assert sc._is_import_audience({}) is False


def test_sync_audience_node_skips_import_and_graph(monkeypatch):
    from services import supabase_client as sc

    # Guard returns before any DB call. If it did not, get_persona_by_id would
    # blow up because we never configured a client.
    def _boom(*_a, **_k):
        raise AssertionError("sync_audience_node must short-circuit, not hit DB")

    monkeypatch.setattr(sc, "get_persona_by_id", _boom)

    assert sc.sync_audience_node({"persona_id": "p1", "id": "a1", "slug": "import"}) is None
    assert sc.sync_audience_node({"persona_id": "p1", "id": "a2", "source_type": "import"}) is None
    assert sc.sync_audience_node({"persona_id": "p1", "id": "a3", "source_type": "graph"}) is None


def test_list_persona_audiences_excludes_import(monkeypatch):
    from services import supabase_client as sc

    monkeypatch.setattr(sc, "materialize_graph_audiences_for_persona", lambda pid: [])
    monkeypatch.setattr(
        sc,
        "get_audiences",
        lambda persona_id=None: [
            {"id": "imp", "slug": "import", "name": "Import", "source_type": "import", "is_system": True},
            {"id": "a1", "slug": "audience-padrao-vz-lupas", "name": "Audience Padrao VZ Lupas", "source_type": "manual"},
            {"id": "a2", "slug": "tecnicos", "name": "Tecnicos", "source_type": "graph"},
        ],
    )

    rows = sc.list_persona_audiences("p1")
    slugs = [r["slug"] for r in rows]

    assert "import" not in slugs
    assert slugs == ["audience-padrao-vz-lupas", "tecnicos"]


def test_list_persona_audiences_unions_graph_nodes(monkeypatch):
    """Graph audiences must show as Leads filters even if row materialization
    did not persist — list unions table rows with graph audience nodes."""
    from services import supabase_client as sc

    monkeypatch.setattr(sc, "materialize_graph_audiences_for_persona", lambda pid: [])
    monkeypatch.setattr(
        sc,
        "get_audiences",
        lambda persona_id=None: [
            {"id": "imp", "slug": "import", "name": "Import", "source_type": "import", "is_system": True},
            {"id": "a1", "slug": "audience-padrao-vz-lupas", "name": "Audience Padrao VZ Lupas", "source_type": "manual"},
        ],
    )
    monkeypatch.setattr(
        sc,
        "list_knowledge_nodes_by_type",
        lambda types, persona_id=None, limit=500: [
            {"id": "n-tec", "slug": "tecnicos", "title": "Tecnicos", "node_type": "audience"},
            {"id": "n-dup", "slug": "audience-padrao-vz-lupas", "title": "dup", "node_type": "audience"},
            {"id": "n-imp", "slug": "import", "title": "Import", "node_type": "audience"},
            {"id": "n-arch", "slug": "antiga", "title": "Antiga", "node_type": "audience", "status": "archived"},
        ],
    )

    out = sc.list_persona_audiences("p1")
    slugs = [a["slug"] for a in out]

    assert "import" not in slugs
    assert "antiga" not in slugs  # archived skipped
    assert "audience-padrao-vz-lupas" in slugs
    assert "tecnicos" in slugs
    assert slugs.count("audience-padrao-vz-lupas") == 1  # no dup
    tec = next(a for a in out if a["slug"] == "tecnicos")
    assert tec["from_graph_node"] is True
    assert tec["persona_id"] == "p1"


def test_materialize_graph_audiences_creates_missing_rows(monkeypatch):
    from services import supabase_client as sc

    nodes = [
        {"slug": "tecnicos", "title": "Tecnicos", "summary": "Publico tecnico", "node_type": "audience", "status": "active"},
        {"slug": "import", "title": "Import", "node_type": "audience"},  # skipped
        {"slug": "arquivado", "title": "Arquivado", "node_type": "audience", "status": "archived"},  # skipped
        {"slug": "existente", "title": "Existente", "node_type": "audience"},  # already has a row
    ]
    monkeypatch.setattr(sc, "list_knowledge_nodes_by_type", lambda types, persona_id=None, limit=500: nodes)
    monkeypatch.setattr(sc, "get_audience_by_slug", lambda pid, slug: {"id": "x"} if slug == "existente" else None)

    created: list[dict] = []

    def fake_create(data):
        row = {"id": f"new-{len(created)}", **data}
        created.append(row)
        return row

    monkeypatch.setattr(sc, "create_audience", fake_create)

    out = sc.materialize_graph_audiences_for_persona("p1")

    assert [r["slug"] for r in out] == ["tecnicos"]
    assert created[0]["source_type"] == "graph"
    assert created[0]["name"] == "Tecnicos"


def test_graph_data_hides_import_audience_node():
    from routes import graph

    assert graph._is_import_audience_node({"node_type": "audience", "slug": "import"}) is True
    assert graph._is_import_audience_node(
        {"node_type": "audience", "slug": "x", "metadata": {"source_type": "import"}}
    ) is True
    assert graph._is_import_audience_node({"node_type": "audience", "slug": "tecnicos"}) is False
    assert graph._is_import_audience_node({"node_type": "product", "slug": "import"}) is False
