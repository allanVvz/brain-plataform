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


def test_sofia_graph_command_keeps_last_referenced_node_in_session(monkeypatch):
    from routes import qa_contract

    monkeypatch.setattr(qa_contract, "_require_non_production", lambda: None)
    monkeypatch.setattr(qa_contract.supabase_client, "get_persona", lambda _slug: {"id": "p2", "slug": "allanvvz"})
    monkeypatch.setattr(qa_contract.auth_service, "assert_persona_access", lambda request, persona_id=None, persona_slug=None: True)
    monkeypatch.setattr(qa_contract.supabase_client, "ensure_persona_knowledge_node", lambda _persona_id: {"id": "persona-2", "node_type": "persona", "slug": "self"})
    monkeypatch.setattr(qa_contract.supabase_client, "list_knowledge_nodes_by_type", lambda *args, **kwargs: [])
    monkeypatch.setattr(qa_contract.supabase_client, "insert_event", lambda payload, source=None: {"ok": True})
    monkeypatch.setattr(
        qa_contract.supabase_client,
        "upsert_knowledge_node",
        lambda payload: {"id": "brand-2", "node_type": payload["node_type"], "slug": payload["slug"], "status": "active"},
    )
    monkeypatch.setattr(qa_contract.supabase_client, "upsert_knowledge_edge", lambda **kwargs: {"id": "e2"})

    turn1 = qa_contract.SofiaGraphCommandBody(
        persona_slug="allanvvz",
        command="selecione brand vz lupas",
        context=qa_contract.SofiaGraphCommandContext(client_action="natural_language", session_id="test-001"),
    )
    r1 = qa_contract.sofia_graph_command(turn1, _req())
    assert r1["conversation_context"]["last_referenced_node"]["slug"] == "vz-lupas"

    turn2 = qa_contract.SofiaGraphCommandBody(
        persona_slug=None,
        command="reencaixe ele abaixo de allanvvz",
        context=qa_contract.SofiaGraphCommandContext(client_action="natural_language", session_id="test-001"),
    )
    r2 = qa_contract.sofia_graph_command(turn2, _req())
    assert r2["ok"] is True
    assert r2["persisted"] is True
    assert r2["conversation_context"]["active_persona_slug"] == "allanvvz"
    assert r2["conversation_context"]["last_referenced_node"]["slug"] == "vz-lupas"
