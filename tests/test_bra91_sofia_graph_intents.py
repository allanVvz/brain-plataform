from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from services import sofia_orchestrator


def _ctx(**kwargs):
    return SimpleNamespace(
        client_action=kwargs.get("client_action", "natural_language"),
        selected_node_ids=kwargs.get("selected_node_ids", []),
        graph_patch=None,
    )


def test_sofia_simple_graph_commands_resolve_without_ambiguity():
    commands = {
        "criar node product": "create_product_node",
        "criar produto": "create_product_node",
        "conectar juliet em audience padrão": "connect_product_group_to_audience",
        "colocar product group em audience": "connect_product_group_to_audience",
        "conectar brand vz lupas em persona allanvvz": "reparent_brand",
        "criar copy para juliet": "create_copy_node",
        "adicionar FAQ em produto X": "create_faq_node",
    }

    for command, operation in commands.items():
        result = sofia_orchestrator.resolve_operation(command)
        assert result["operation"] == operation
        assert result["score"] >= sofia_orchestrator._threshold()


def test_sofia_clear_connect_command_persists_graph_patch():
    result = sofia_orchestrator.plan_graph_command(
        command="conectar juliet em audience padrão",
        context=_ctx(),
        persona_slug="allanvvz",
    )

    assert result["persisted"] is True
    assert result["needs_clarification"] is False
    assert result["graph_patch"]["edges_upsert"][0]["relation_type"] == "audience_has_product_group"


def test_sofia_uses_selected_product_group_for_product_creation():
    result = sofia_orchestrator.plan_graph_command(
        command="criar produto",
        context=_ctx(selected_node_ids=["slug:grupo-juliet"]),
        persona_slug="allanvvz",
    )

    assert result["persisted"] is True
    edge = result["graph_patch"]["edges_upsert"][0]
    assert edge["source_ref"] == "slug:grupo-juliet"
    assert edge["relation_type"] == "product_group_has_product"
