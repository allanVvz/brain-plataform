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

    monkeypatch.setattr(qa_contract, "_require_non_production", lambda: None)
    monkeypatch.setattr(
        qa_contract, "_resolve_sofia_persona", lambda request, ref: {"id": "per1", "slug": "allanvvz"}
    )
    monkeypatch.setattr(
        qa_contract.supabase_client,
        "get_knowledge_node",
        lambda nid: {"id": "p1", "node_type": "product", "metadata": {}},
    )

    persisted: list[dict] = []

    def fake_persist(**kwargs):
        persisted.append(kwargs)
        return {"id": f"ki-{len(persisted)}", "status": "pending", "metadata": {"knowledge_node_id": f"gn{len(persisted)}"}}

    edges: list[tuple] = []

    monkeypatch.setattr(qa_contract.knowledge_lifecycle, "persist_pending_knowledge_item", fake_persist)
    monkeypatch.setattr(
        qa_contract.supabase_client,
        "upsert_knowledge_edge",
        lambda s, t, rt, **k: edges.append((s, t, rt)) or {"id": f"ge-{len(edges)}"},
    )
    monkeypatch.setattr(qa_contract.supabase_client, "update_knowledge_node", lambda *a, **k: None)

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
    assert result["created"][0]["status"] == "pending"
    assert persisted[0]["content_type"] == "faq"
    assert persisted[0]["metadata"]["source_tool"] == "adaptar_faqs_universais_ao_grafo"
    assert persisted[0]["metadata"]["faq_generation_count"] == 4
    assert edges == [("p1", "gn1", "product_has_faq")]
