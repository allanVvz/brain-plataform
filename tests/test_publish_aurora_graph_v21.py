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
    assert len(graph.nodes) == 47
    assert len(graph.edges) == 88

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
    assert len(grants) == 44
    assert {edge.source for edge in grants} == {
        node.id
        for node in graph.nodes
        if node.node_class == "knowledge"
        and node.node_type != "persona"
        and node.lifecycle.status == "approved"
    }
    assert len({edge.id for edge in graph.edges}) == len(graph.edges)


def test_aurora_conversation_contract_rejects_blank_message_cleanly() -> None:
    from pydantic import ValidationError

    try:
        ContextRequest(persona_slug="aurora", lead_ref=1, message="   ")
    except ValidationError as exc:
        assert "message must not be blank" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("blank Aurora messages must be rejected before runtime")
