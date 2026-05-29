from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _req():
    return SimpleNamespace(state=SimpleNamespace(user={"id": "u1", "role": "admin"}))


@pytest.mark.parametrize(
    "operation,command",
    [
        ("validate_canonical_chain", "selecione a persona allanvvz"),
        ("validate_canonical_chain", "selecione a brand vz lupas"),
        ("reparent_brand", "reencaixe a brand vz lupas abaixo da persona allanvvz"),
        ("reorganize_campaign_briefing", "reorganize o campaign briefing da persona allanvvz"),
        ("create_default_audience", "crie audiencia padrao para a campanha atual"),
    ],
)
def test_sofia_v2_patch_loop_tool_sequence_for_five_commands(monkeypatch, operation: str, command: str):
    from routes import qa_contract

    monkeypatch.setattr(qa_contract, "_require_non_production", lambda: None)
    monkeypatch.setattr(qa_contract.supabase_client, "get_persona", lambda _slug: {"id": "p2", "slug": "allanvvz"})
    monkeypatch.setattr(qa_contract.auth_service, "assert_persona_access", lambda request, persona_id=None, persona_slug=None: True)
    monkeypatch.setattr(qa_contract.supabase_client, "ensure_persona_knowledge_node", lambda _persona_id: {"id": "persona-2", "node_type": "persona", "slug": "self"})

    # Minimal graph inventory so refs can be resolved during persist.
    monkeypatch.setattr(
        qa_contract.supabase_client,
        "list_knowledge_nodes_by_type",
        lambda *args, **kwargs: [
            {"id": "brand-2", "node_type": "brand", "slug": "vz-lupas", "status": "active"},
            {"id": "briefing-2", "node_type": "briefing", "slug": "briefing-default", "status": "active"},
            {"id": "campaign-2", "node_type": "campaign", "slug": "campaign-default", "status": "active"},
            {"id": "aud-2", "node_type": "audience", "slug": "audiencia-padrao", "status": "active"},
        ],
    )

    monkeypatch.setattr(qa_contract.supabase_client, "insert_event", lambda payload, source=None: {"ok": True})
    monkeypatch.setattr(
        qa_contract.supabase_client,
        "upsert_knowledge_node",
        lambda payload: {
            "id": f"{payload['node_type']}-new",
            "node_type": payload["node_type"],
            "slug": payload["slug"],
            "status": payload.get("status", "active"),
            "persona_id": "p2",
        },
    )
    monkeypatch.setattr(qa_contract.supabase_client, "upsert_knowledge_edge", lambda **kwargs: {"id": "e2"})

    monkeypatch.setattr(
        qa_contract,
        "_resolve_operation_tool",
        lambda body: {
            "ok": True,
            "operation": operation,
            "score": 0.96,
            "target_nodes": {},
            "required_validation": ["canonical_chain"],
            "risk_level": "low",
            "needs_confirmation": False,
            "candidates": [{"operation": operation, "score": 0.96}],
        },
    )

    graph_patch = {
        "nodes_upsert": [
            {
                "node_type": "brand",
                "slug": "vz-lupas",
                "title": "VZ Lupas",
                "summary": "Brand em cadeia canonica.",
            }
        ],
        "nodes_delete": [],
        "edges_upsert": [
            {
                "source_ref": "persona:self",
                "target_ref": "slug:vz-lupas",
                "relation_type": "persona_has_brand",
                "metadata": {"primary_tree": True, "active": True},
            }
        ],
        "edges_delete": [],
    }

    body = qa_contract.SofiaGraphCommandBody(
        persona_slug="allanvvz",
        command=command,
        context=qa_contract.SofiaGraphCommandContext(
            client_action="structured_intent",
            graph_patch=graph_patch,
            session_id=f"test-v2-{operation}",
        ),
    )
    response = qa_contract.sofia_graph_command(body, _req())

    assert response["ok"] is True
    assert response["persisted"] is True

    tools = [call["tool"] for call in response["tool_calls"]]
    assert tools == [
        "resolve-persona",
        "resolve-node",
        "resolve-operation",
        "validate-canonical-chain",
        "generate-graph-patch",
        "persist-graph-patch",
        "refetch-graph",
    ]
