from types import SimpleNamespace

from services.conversation_runtime import _published_business_hours


def test_runtime_pins_business_hours_to_turn_publication():
    context = SimpleNamespace(
        rag_nodes=[{
            "node_type": "persona",
            "data": {"conversation_policy": {"business_hours": {
                "timezone": "America/Sao_Paulo", "start": "08:00", "end": "20:00",
            }}},
        }],
        graph_version=12,
        graph_checksum="sha256:published",
        publication_id="publication-1",
    )
    assert _published_business_hours(context) == {
        "timezone": "America/Sao_Paulo", "start": "08:00", "end": "20:00",
        "graph_version": 12, "graph_checksum": "sha256:published",
        "publication_id": "publication-1",
    }


def test_runtime_does_not_invent_a_schedule_when_graph_has_none():
    context = SimpleNamespace(rag_nodes=[], graph_version=1, graph_checksum="sha", publication_id=None)
    assert _published_business_hours(context) is None
