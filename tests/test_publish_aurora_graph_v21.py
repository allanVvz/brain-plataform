from __future__ import annotations

import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from scripts.publish_aurora_graph import build_graph
from routes.conversations import ContextRequest
from services import graph_json_v2_validator, graph_markdown


def test_aurora_rollout_builds_isolated_complete_agent_dataset() -> None:
    graph = graph_markdown.canonicalize_graph(build_graph())
    valid, errors = graph_json_v2_validator.validate_graph_json(graph)

    assert valid, errors
    assert graph.schema_version == "2.1"
    assert len(graph.nodes) == 62
    assert len(graph.edges) == 118

    embedded = next(node for node in graph.nodes if node.node_type == "embedded")
    assert embedded.action is not None
    assert embedded.action.destination_id == "dataset:sdr-aurora"
    assert embedded.action.consumer.ref == "sdr:aurora"

    grants = [
        edge for edge in graph.edges
        if edge.target == embedded.id
        and edge.relation_type == "publishes_to"
        and edge.lifecycle.status == "active"
    ]
    assert len(grants) == 59
    assert {edge.source for edge in grants} == {
        node.id
        for node in graph.nodes
        if node.node_class == "knowledge"
        and node.node_type != "persona"
        and node.lifecycle.status == "approved"
    }
    assert len({edge.id for edge in graph.edges}) == len(graph.edges)


def test_shared_qualification_fields_share_one_owner_across_products() -> None:
    """Regression test for the Aurora repeated-question bug (2026-08-08).

    Confirmed live: every product node declared the same qualification
    fields (nome_cliente, objective, can_visit_in_person, modelo_veiculo,
    vehicle_year, condicao, vehicle_color) with owner_node_id == that
    product's own id. graph_proof_checker_v3 requires a fact's
    owner_node_id to match the field's declared owner before counting it
    resolved, so any branch switch reopened all of them even though the
    question and expected answer never change across products. Only
    "servico" legitimately varies per product (it's derived from
    active_branch_node_id server-side regardless of what's declared here).
    A prior direct database fix for this got silently reverted by this
    exact script re-publishing from the fixture on the next deploy, so the
    fix has to live here, in build_graph(), not in the database.
    """
    graph = build_graph()
    persona = next(node for node in graph.nodes if node.node_type == "persona")
    products = [node for node in graph.nodes if node.node_type == "product"]
    assert len(products) >= 2

    owners_by_key: dict[str, set[str]] = {}
    for product in products:
        for field in (product.data or {}).get("qualification", {}).get("fields", []):
            owners_by_key.setdefault(field["key"], set()).add(field["owner_node_id"])

    assert "modelo_veiculo" in owners_by_key  # sanity: fixture still declares it
    # "servico" legitimately stays branch-owned -- every product declares it
    # with its own id, so more than one distinct owner is expected here.
    assert len(owners_by_key["servico"]) > 1
    for key, owners in owners_by_key.items():
        if key == "servico":
            continue
        assert owners == {persona.id}, f"{key} has per-branch owners: {owners}"


def test_aurora_conversation_contract_rejects_blank_message_cleanly() -> None:
    from pydantic import ValidationError

    try:
        ContextRequest(persona_slug="aurora", lead_ref=1, message="   ")
    except ValidationError as exc:
        assert "message must not be blank" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("blank Aurora messages must be rejected before runtime")
