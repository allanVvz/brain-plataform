"""Sofia FAQ route layer — target resolution, generation handler, accept persist.

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


def _nodes():
    return [
        {"id": "p1", "node_type": "product", "title": "Juliet Carbon Black Iridium", "slug": "juliet-carbon-black", "metadata": {}},
        {"id": "g1", "node_type": "product_group", "title": "Juliet", "slug": "grupo-juliet", "metadata": {}},
    ]


def test_resolve_target_by_selected_node_id():
    from routes import qa_contract

    node = qa_contract._resolve_faq_target_node(
        _nodes(), selected_node_id="gn:p1", command="gere novamente", session_state={}
    )
    assert node["id"] == "p1"


def test_resolve_target_by_title_mention():
    from routes import qa_contract

    node = qa_contract._resolve_faq_target_node(
        _nodes(),
        selected_node_id=None,
        command="gere novo FAQ com o grafo Juliet Carbon Black Iridium",
        session_state={},
    )
    assert node["id"] == "p1"


def test_resolve_target_falls_back_to_last_referenced():
    from routes import qa_contract

    node = qa_contract._resolve_faq_target_node(
        _nodes(),
        selected_node_id=None,
        command="gere 3 perguntas",
        session_state={"last_referenced_node": {"slug": "grupo-juliet"}},
    )
    assert node["id"] == "g1"


def test_handle_generation_returns_suggestions(monkeypatch):
    from routes import qa_contract

    monkeypatch.setattr(qa_contract.supabase_client, "list_all_knowledge_graph", lambda pid: (_nodes(), []))
    monkeypatch.setattr(qa_contract.sofia_orchestrator, "remember_turn", lambda **k: None)

    resp = qa_contract._handle_sofia_faq_generation(
        persona_id="per1",
        persona_slug="allanvvz",
        command="gere 4 perguntas",
        selected_node_id="gn:p1",
        session_state={},
        intent={"intent": "gerar_n_faqs_para_node", "count": 4},
        session_id="",
    )
    assert resp["needs_clarification"] is False
    assert len(resp["faq_suggestions"]) == 4
    assert resp["faq_context"]["parent_node_id"] == "p1"
    assert "Juliet Carbon Black Iridium" in resp["faq_suggestions"][0]["question"]


def test_handle_generation_needs_node_when_unresolved(monkeypatch):
    from routes import qa_contract

    monkeypatch.setattr(qa_contract.supabase_client, "list_all_knowledge_graph", lambda pid: ([], []))
    resp = qa_contract._handle_sofia_faq_generation(
        persona_id="per1",
        persona_slug="allanvvz",
        command="gere 4 perguntas",
        selected_node_id=None,
        session_state={},
        intent={"intent": "gerar_faqs_para_node", "count": None},
        session_id="",
    )
    assert resp["needs_clarification"] is True
    assert resp["faq_suggestions"] == []


def test_faq_accept_persists_as_pending_and_connects_parent(monkeypatch):
    from routes import qa_contract
    from schemas.graph_json_v2 import GraphJson

    monkeypatch.setattr(qa_contract, "_require_non_production", lambda: None)
    monkeypatch.setattr(
        qa_contract, "_resolve_sofia_persona", lambda request, ref: {"id": "per1", "slug": "allanvvz"}
    )
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
                "id": "p1",
                "node_type": "product",
                "slug": "produto",
                "label": "Produto",
                "parent_id": "persona",
                "data": {"status": "validated", "source": "test"},
            },
        ],
        "edges": [
            {
                "id": "persona-product",
                "source": "persona",
                "target": "p1",
                "relation": "contains",
                "primary_tree": True,
            }
        ],
    })
    monkeypatch.setattr(
        qa_contract.graph_json_v2_store,
        "load_current",
        lambda slug: (7, graph),
    )
    captured = {}
    monkeypatch.setattr(
        qa_contract.graph_document_publisher,
        "publish",
        lambda **kwargs: captured.update(kwargs) or {"ok": True, "version": 8},
    )

    body = qa_contract.SofiaFaqAcceptBody(
        persona_slug="allanvvz",
        parent_node_id="gn:p1",
        parent_node_type="product",
        faq_generation_count=4,
        suggestions=[
            qa_contract.SofiaFaqAcceptSuggestion(question="Como comprar?", answer="Fale com a loja."),
            qa_contract.SofiaFaqAcceptSuggestion(question="", answer="ignored"),  # dropped
        ],
    )
    result = qa_contract.sofia_faq_accept(body, _req())

    assert result["ok"] is True
    assert len(result["created"]) == 1
    assert result["created"][0]["status"] == "pending_validation"
    next_graph = captured["graph"]
    faq = next(node for node in next_graph.nodes if node.node_type == "faq")
    assert faq.data["source"] == "adaptar_faqs_universais_ao_grafo"
    assert faq.data["question_count"] == 1
    assert faq.data["source_node_id"] == "p1"
    assert any(
        edge.source == "p1" and edge.target == faq.id and edge.primary_tree
        for edge in next_graph.edges
    )
    assert captured["expected_version"] == 7
