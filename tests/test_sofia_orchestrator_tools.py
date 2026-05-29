from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
for path in (API_DIR, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _context(client_action: str = "natural_language", graph_patch: dict | None = None):
    class Ctx:
        def __init__(self, client_action: str, graph_patch: dict | None):
            self.client_action = client_action
            self.graph_patch = graph_patch

    return Ctx(client_action=client_action, graph_patch=graph_patch)


def test_plan_graph_command_calls_two_tools_and_builds_patch(monkeypatch):
    from services import sofia_orchestrator

    monkeypatch.setenv("SOFIA_GRAPH_COMMAND_MIN_SCORE", "0.65")
    monkeypatch.setattr(
        sofia_orchestrator,
        "resolve_persona",
        lambda command_text, fallback_persona_slug: {"slug": "allanvvz", "score": 0.91},
    )
    monkeypatch.setattr(
        sofia_orchestrator,
        "resolve_operation",
        lambda command_text: {"operation": "reparent_brand", "score": 0.95},
    )

    result = sofia_orchestrator.plan_graph_command(
        command="reencaixe VZ Lupas abaixo de AllanVvz",
        context=_context(),
        persona_slug="vz-lupas",
    )

    assert result["ok"] is True
    assert result["persisted"] is True
    assert result["graph_patch"]["edges_upsert"][0]["relation_type"] == "persona_has_brand"
    assert [c["name"] for c in result["tool_calls"]] == [
        "resolve-persona",
        "resolve-node",
        "resolve-operation",
        "validate-canonical-chain",
        "generate-graph-patch",
    ]


def test_plan_graph_command_low_score_returns_clarification_no_patch(monkeypatch):
    from services import sofia_orchestrator

    monkeypatch.setenv("SOFIA_GRAPH_COMMAND_MIN_SCORE", "0.65")
    monkeypatch.setattr(
        sofia_orchestrator,
        "resolve_persona",
        lambda command_text, fallback_persona_slug: {"slug": "allanvvz", "score": 0.63},
    )
    monkeypatch.setattr(
        sofia_orchestrator,
        "resolve_operation",
        lambda command_text: {"operation": "persona_has_brand_relink", "score": 0.99},
    )

    result = sofia_orchestrator.plan_graph_command(
        command="reencaixe isso ai",
        context=_context(),
        persona_slug="vz-lupas",
    )

    assert result["ok"] is True
    assert result["persisted"] is False
    assert result["graph_patch"] is None
    assert "persona ativa" in result["sofia_message"].lower()
    assert [c["name"] for c in result["tool_calls"]] == [
        "resolve-persona",
        "resolve-node",
        "resolve-operation",
        "validate-canonical-chain",
        "generate-graph-patch",
    ]
