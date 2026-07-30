"""Node Markdown PATCH + FAQ append (Gerar updates the same FAQ, no new node).

Monkeypatched; no live Supabase.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _req():
    return SimpleNamespace(state=SimpleNamespace(user={"id": "u1", "role": "admin"}))


# ── PATCH /knowledge/graph-nodes/{id} ────────────────────────────────────────

def test_update_graph_node_persists_markdown_to_metadata(monkeypatch):
    from routes import graph

    monkeypatch.setattr(graph.auth_service, "assert_persona_access", lambda *a, **k: None)
    monkeypatch.setattr(graph.supabase_client, "get_knowledge_node", lambda nid: {
        "id": "p1", "node_type": "product", "persona_id": "per1", "metadata": {"x": 1},
    })
    captured = {}
    monkeypatch.setattr(graph.supabase_client, "update_knowledge_node", lambda nid, data, **k: captured.update({"node": (nid, data)}) or {"id": nid, **data})
    monkeypatch.setattr(graph, "_knowledge_item_for_graph_node", lambda node: None)
    monkeypatch.setattr(graph, "emit", lambda *a, **k: None)
    monkeypatch.setattr(graph, "current_actor", lambda req: "u1")

    body = graph.GraphNodeUpdateBody(markdown="# Produto\nLente Prizm UV400", title="Plantaris")
    out = graph.update_graph_node("gn:p1", body, _req())

    assert out["ok"] is True
    assert out["reverted_to_draft"] is False
    _, data = captured["node"]
    assert data["metadata"]["markdown"] == "# Produto\nLente Prizm UV400"
    assert data["title"] == "Plantaris"


def test_update_graph_node_faq_reverts_and_rebuilds_embedded(monkeypatch):
    from routes import graph

    monkeypatch.setattr(graph.auth_service, "assert_persona_access", lambda *a, **k: None)
    monkeypatch.setattr(graph.supabase_client, "get_knowledge_node", lambda nid: {
        "id": "f1", "node_type": "faq", "persona_id": "per1", "source_table": "knowledge_items",
        "source_id": "ki1", "metadata": {},
    })
    monkeypatch.setattr(graph.supabase_client, "update_knowledge_node", lambda nid, data, **k: {"id": nid, **data})
    monkeypatch.setattr(graph, "_knowledge_item_for_graph_node", lambda node: {"id": "ki1", "status": "embedded"})
    item_updates = {}
    monkeypatch.setattr(graph.supabase_client, "update_knowledge_item", lambda iid, data: item_updates.update(data))
    withdrawn = {}
    monkeypatch.setattr(graph.supabase_client, "withdraw_faq_from_embedded", lambda iid: withdrawn.update({"id": iid}))
    rebuilt = {}
    monkeypatch.setattr(graph.embedded_markdown, "rebuild_embedded_markdown", lambda pid: rebuilt.update({"pid": pid}))
    monkeypatch.setattr(graph, "emit", lambda *a, **k: None)
    monkeypatch.setattr(graph, "current_actor", lambda req: "u1")

    out = graph.update_graph_node("gn:f1", graph.GraphNodeUpdateBody(markdown="novo corpo"), _req())

    assert out["reverted_to_draft"] is True
    assert item_updates["status"] == "pending"
    assert withdrawn["id"] == "ki1"
    assert rebuilt["pid"] == "per1"


def test_update_graph_node_blocks_protected(monkeypatch):
    from routes import graph
    from fastapi import HTTPException

    monkeypatch.setattr(graph.auth_service, "assert_persona_access", lambda *a, **k: None)
    monkeypatch.setattr(graph.supabase_client, "get_knowledge_node", lambda nid: {"id": "e1", "node_type": "embedded", "persona_id": "per1"})
    try:
        graph.update_graph_node("gn:e1", graph.GraphNodeUpdateBody(markdown="x"), _req())
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 400


# ── /sofia/faq/append ────────────────────────────────────────────────────────

def test_faq_append_updates_same_node_no_new_node(monkeypatch):
    from routes import qa_contract
    from schemas.graph_json_v2 import GraphJson

    monkeypatch.setattr(qa_contract, "_require_non_production", lambda: None)
    monkeypatch.setattr(qa_contract, "_resolve_sofia_persona", lambda request, ref: {"id": "per1", "slug": "allanvvz"})
    graph = GraphJson.model_validate({
        "graph_id": "allanvvz-test",
        "tenant": "qa",
        "persona_slug": "allanvvz",
        "status": "published",
        "nodes": [
            {
                "id": "persona",
                "node_type": "persona",
                "slug": "allanvvz",
                "label": "AllanVvz",
                "data": {"status": "validated", "source": "test"},
            },
            {
                "id": "f1",
                "node_type": "faq",
                "slug": "faq",
                "label": "FAQ",
                "parent_id": "persona",
                "data": {
                    "status": "approved",
                    "source": "test",
                    "markdown": "# FAQ\n\n### Pergunta antiga\n\nResposta: A",
                },
            },
        ],
        "edges": [],
    })
    monkeypatch.setattr(
        qa_contract.graph_json_v2_store,
        "load_current",
        lambda slug: (4, graph),
    )
    captured = {}
    monkeypatch.setattr(
        qa_contract.graph_document_publisher,
        "publish",
        lambda **kwargs: captured.update(kwargs) or {"ok": True, "version": 5},
    )

    body = qa_contract.SofiaFaqAppendBody(
        persona_slug="allanvvz",
        faq_node_id="gn:f1",
        suggestions=[
            qa_contract.SofiaFaqAcceptSuggestion(question="Nova pergunta?", answer="Nova resposta."),
            qa_contract.SofiaFaqAcceptSuggestion(question="  ", answer="ignored"),
        ],
    )
    out = qa_contract.sofia_faq_append(body, _req())

    assert out["created_node"] is False
    assert out["appended_count"] == 1
    assert out["status"] == "pending_validation"
    assert "### Pergunta antiga" in out["markdown"]  # preserved
    assert "### Nova pergunta?" in out["markdown"]   # appended
    assert "Resposta: Nova resposta." in out["markdown"]
    next_graph = captured["graph"]
    assert len(next_graph.nodes) == len(graph.nodes)
    updated = next(node for node in next_graph.nodes if node.id == "f1")
    assert updated.data["status"] == "pending_validation"
    assert captured["expected_version"] == 4
